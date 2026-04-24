# SPDX-License-Identifier: Apache-2.0
# VENDORED FROM: Kaizen-3C/benchmarks/commit0/baselines/value_add_fingerprint.py
# Sync manually; kept self-contained so `pip install kaizen-3c-cli` works without
# requiring a separate clone of the benchmarks repo.
"""Value-add architectural fingerprint table.

For each (architecture x model x library) cell:
  value_add_pp     = arch_pass_rate - single_shot_LLM_pass_rate (same model)
  value_add_$_pp   = arch_cost / max(value_add_pp, 0.01)
  llm_lean         = arch_cost / single_shot_LLM_cost (same model, same lib)

Reads from benchmarks/commit0/results/. Outputs to stdout.
Also flags architectural weakness signatures per ADR-0063 §weakness_fingerprints.
"""

from __future__ import annotations

import json
from pathlib import Path

# Default results directory — relative to the original script location in the
# benchmarks repo.  main() accepts an override via results_dir parameter.
R = Path(__file__).resolve().parents[2] / "commit0" / "results"

LIBS = ["wcwidth", "deprecated", "cachetools", "voluptuous", "portalocker",
        "pyjwt", "chardet", "tinydb", "simpy", "imapclient", "parsel",
        "marshmallow", "cookiecutter", "babel", "jinja", "minitorch"]
FLOOR = {"chardet", "marshmallow", "babel", "jinja", "minitorch"}


def loadj(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


def lib_passrate(per_lib: dict, lib: str) -> tuple[int, int, float | None]:
    """Return (passed, attempted, rate or None if not run)."""
    d = (per_lib or {}).get(lib, {}) or {}
    c = d.get("counts") or d.get("final_counts") or {}
    p, f, e = c.get("passed", 0), c.get("failed", 0), c.get("errors", 0)
    a = p + f + e
    if a == 0 and not c:
        return 0, 0, None  # not run
    return p, a, ((100 * p / a) if a else 0)


def lib_cost(per_lib: dict, lib: str, source_provider: str) -> float | None:
    """Cost from per-library JSON. Some baselines store cost differently."""
    d = (per_lib or {}).get(lib, {}) or {}
    if not d:
        return None
    # Prefer pre-computed cost
    if "totals" in d and isinstance(d["totals"], dict):
        c = d["totals"].get("cost_usd")
        if c is not None:
            return c
    # B2: compute from tokens
    fresh_in = d.get("input_tokens", 0)
    out = d.get("output_tokens", 0)
    cached = d.get("cached_input_tokens", 0)
    if source_provider == "anthropic":
        return (fresh_in * 3 + out * 15) / 1_000_000
    return ((fresh_in - cached) * 1.25 + cached * 0.125 + out * 10) / 1_000_000


def oh_status(report: dict, lib: str) -> tuple[str, float | None]:
    """OH instance status: RES / no / FAIL. Cost from report metrics."""
    if not report:
        return "FAIL", None
    if lib in report.get("resolved_ids", []):
        return "RES", None
    if lib in report.get("unresolved_ids", []):
        return "no", None
    if lib in report.get("completed_ids", []):
        return "?", None
    return "FAIL", None


def oh_lib_cost_from_jsonl(jsonl: Path, lib: str) -> float | None:
    if not jsonl.exists():
        return None
    for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        iid = obj.get("instance_id") or ""
        if iid.endswith(lib):
            return (obj.get("metrics") or {}).get("accumulated_cost", 0)
    return None


def merge_oh_dirs(results_root: Path, *dir_names: str) -> dict:
    """Merge multiple OH result dirs into one (lib -> (status, cost))."""
    out = {}
    for name in dir_names:
        d = results_root / name
        rep_p = d / "output.report.json"
        jsonl_p = d / "output.jsonl"
        if not rep_p.exists():
            continue
        rep = json.loads(rep_p.read_text())
        for lib in (rep.get("completed_ids", []) or []):
            status, _ = oh_status(rep, lib)
            cost = oh_lib_cost_from_jsonl(jsonl_p, lib) if jsonl_p.exists() else None
            out[lib] = (status, cost)
    return out


def kd_per_lib(results_root: Path, provider: str) -> dict:
    """Load KD per-lib JSONs (separate files, not aggregated dict)."""
    out = {}
    for lib in LIBS:
        p = results_root / f"{lib}_kaizen_delta_{provider}.json"
        if p.exists():
            d = json.loads(p.read_text())
            if "final_counts" in d:
                d["counts"] = d["final_counts"]
            out[lib] = d
    return out


def compute_cell(arch_per_lib: dict, lib: str, single_shot_per_lib: dict,
                 source_provider: str) -> dict | None:
    """For KD-style architectures with full per-lib pass-rate."""
    p, a, rate = lib_passrate(arch_per_lib, lib)
    sp, sa, srate = lib_passrate(single_shot_per_lib, lib)
    if rate is None or srate is None:
        return None
    cost = lib_cost(arch_per_lib, lib, source_provider) or 0
    s_cost = lib_cost(single_shot_per_lib, lib, source_provider) or 0.001
    value_add_pp = rate - srate
    value_add_dollar_pp = (cost / max(value_add_pp, 0.01)) if value_add_pp > 0 else None
    llm_lean = cost / max(s_cost, 0.001)
    return {
        "passed": p, "attempted": a, "rate": rate,
        "cost": cost, "value_add_pp": value_add_pp,
        "value_add_dollar_pp": value_add_dollar_pp, "llm_lean": llm_lean,
    }


def compute_oh_cell(oh_dict: dict, lib: str, single_shot_per_lib: dict,
                    source_provider: str) -> dict | None:
    """For OH (binary RES/no/FAIL)."""
    if lib not in oh_dict:
        return None
    status, cost = oh_dict[lib]
    cost = cost or 0
    sp, sa, srate = lib_passrate(single_shot_per_lib, lib)
    if srate is None:
        return None
    s_cost = lib_cost(single_shot_per_lib, lib, source_provider) or 0.001
    # OH's pass-rate is binary: RES = 100, anything else = unknown
    if status == "RES":
        rate = 100.0
        value_add_pp = 100 - srate
    elif status == "no":
        rate = None
        value_add_pp = None
    else:
        rate = None
        value_add_pp = None
    value_add_dollar_pp = (
        (cost / max(value_add_pp, 0.01))
        if (value_add_pp and value_add_pp > 0)
        else None
    )
    llm_lean = cost / max(s_cost, 0.001)
    return {
        "status": status, "rate": rate, "cost": cost,
        "value_add_pp": value_add_pp,
        "value_add_dollar_pp": value_add_dollar_pp, "llm_lean": llm_lean,
    }


def fmt_cell(c: dict | None, kind: str = "kd") -> str:
    if c is None:
        return f"{'  --':>16}"
    if kind == "oh":
        if c['status'] == "RES":
            return f"RES +{c['value_add_pp']:>3.0f}pp x{c['llm_lean']:>4.0f}"
        if c['status'] == "no":
            return f" no  ?      x{c['llm_lean']:>4.0f}"
        return "FAIL  --       --"
    # KD-style
    va = c['value_add_pp']
    sign = "+" if va >= 0 else ""
    return f"{c['rate']:>3.0f}% {sign}{va:>+4.0f}pp x{c['llm_lean']:>4.1f}"


def run_fingerprint(results_root: Path) -> None:
    """Compute and print the full value-add fingerprint table."""
    # Load all baselines
    b2s = loadj(results_root / "aggregate_lite_single_shot_sonnet.json").get("per_library", {})
    b2g = loadj(results_root / "aggregate_lite_single_shot_openai.json").get("per_library", {})
    b3s = loadj(results_root / "aggregate_lite_reflexion_sonnet.json").get("per_library", {})
    b3g = loadj(results_root / "aggregate_lite_reflexion_openai.json").get("per_library", {})

    kds = kd_per_lib(results_root, "anthropic")
    kdg = kd_per_lib(results_root, "openai")

    # OH merged across all subset dirs
    oh_s = merge_oh_dirs(results_root, "b6_partial_pass1", "b6_4cheap_sonnet", "b6_t3_sonnet")
    oh_g = merge_oh_dirs(results_root, "b6_partial_gpt54_3libs", "b6_4cheap_gpt54", "b6_10missing_gpt54")

    print("=" * 145)
    print("VALUE-ADD FINGERPRINT — each cell shows: pass-rate, value_add_pp vs same-model B2, llm_lean (cost ratio vs B2)")
    print("=" * 145)
    hdr = f"{'lib':12} {'F?':>2} | {'KD-S':>16} {'KD-G':>16} | {'OH-S':>17} {'OH-G':>17}"
    print(hdr)
    print("-" * len(hdr))

    floor_unlocks = []
    big_wins = []
    big_losses = []
    oh_resolved = []

    for lib in LIBS:
        f = "*" if lib in FLOOR else " "
        kds_cell = compute_cell(kds, lib, b2s, "anthropic")
        kdg_cell = compute_cell(kdg, lib, b2g, "openai")
        ohs_cell = compute_oh_cell(oh_s, lib, b2s, "anthropic")
        ohg_cell = compute_oh_cell(oh_g, lib, b2g, "openai")
        print(
            f"{lib:12} {f:>2} | "
            f"{fmt_cell(kds_cell, 'kd'):>16} {fmt_cell(kdg_cell, 'kd'):>16} | "
            f"{fmt_cell(ohs_cell, 'oh'):>17} {fmt_cell(ohg_cell, 'oh'):>17}"
        )

        # Collect findings
        for cell, label in [(kds_cell, f"KD-S {lib}"), (kdg_cell, f"KD-G {lib}")]:
            if cell and cell['value_add_pp'] is not None:
                if cell['value_add_pp'] >= 10:
                    big_wins.append((label, cell))
                if cell['value_add_pp'] <= -10:
                    big_losses.append((label, cell))
                if lib in FLOOR and cell['rate'] > 0:
                    floor_unlocks.append((label, cell))
        for cell, label in [(ohs_cell, f"OH-S {lib}"), (ohg_cell, f"OH-G {lib}")]:
            if cell and cell.get('status') == 'RES':
                oh_resolved.append((label, cell))
                if lib in FLOOR:
                    floor_unlocks.append((label + " (RES)", cell))

    print()
    print("Legend:")
    print("  KD cells: pass% +pp vs same-model B2 xN llm_lean (cost ratio)")
    print("  OH cells: RES = resolved 100% / no = unresolved / FAIL = didn't complete")
    print("  +/- pp:   value-add over the LLM's single-shot baseline (same model)")
    print("  llm_lean: cost ratio -- 1x means 'spent same as just calling the LLM once'")
    print()

    # Architectural-weakness signatures
    print("=" * 100)
    print("ARCHITECTURAL-WEAKNESS SIGNATURES (per ADR-0063 §weakness_fingerprints)")
    print("=" * 100)

    print()
    print("OH WEAKNESS — high llm_lean for low/negative value-add")
    print("(cells where OH spent much more than the LLM and didn't resolve):")
    for lib in LIBS:
        cell = compute_oh_cell(oh_s, lib, b2s, "anthropic")
        if cell and cell['llm_lean'] > 5 and cell.get('status') in ("no", "FAIL"):
            print(
                f"  OH-S {lib:13} {cell['status']:>4} "
                f"llm_lean={cell['llm_lean']:>5.0f}x cost=${cell['cost']:.2f}"
            )
        cell = compute_oh_cell(oh_g, lib, b2g, "openai")
        if cell and cell['llm_lean'] > 5 and cell.get('status') in ("no", "FAIL"):
            print(
                f"  OH-G {lib:13} {cell['status']:>4} "
                f"llm_lean={cell['llm_lean']:>5.0f}x cost=${cell['cost']:.2f}"
            )

    print()
    print("KD WEAKNESS — negative value-add (per-file regen damaged working code):")
    for label, cell in big_losses:
        print(
            f"  {label:18} rate={cell['rate']:>3.0f}%  "
            f"value_add={cell['value_add_pp']:+.0f}pp  "
            f"cost=${cell['cost']:.2f}  llm_lean={cell['llm_lean']:.1f}x"
        )

    print()
    print("FLOOR-LIB UNLOCKS (only baseline >0% on a floor lib):")
    for label, cell in floor_unlocks:
        rate = cell.get('rate', 100 if cell.get('status') == 'RES' else None)
        print(f"  {label:30} rate={rate}  cost=${cell['cost']:.2f}")

    print()
    print("BIG WINS (KD value-add >= 10pp):")
    for label, cell in big_wins:
        print(
            f"  {label:18} rate={cell['rate']:>3.0f}%  "
            f"value_add=+{cell['value_add_pp']:.0f}pp  "
            f"cost=${cell['cost']:.2f}  llm_lean={cell['llm_lean']:.1f}x"
        )


def main(results_dir: Path | None = None) -> int:
    """Programmatic entry point.  Returns exit code (0 = success).

    Parameters
    ----------
    results_dir:
        Override the default results directory.  When *None* the module falls
        back to the ``R`` global (which points at the benchmarks repo's own
        ``commit0/results/`` tree when run from the monorepo, or wherever
        ``kaizen bench fingerprint --results`` points).
    """
    global R
    if results_dir is not None:
        R = Path(results_dir).resolve()

    results_root = R
    if not results_root.exists():
        print(f"Results directory not found: {results_root}")
        print("Pass --results <dir> pointing at a commit0 results directory.")
        return 1

    run_fingerprint(results_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
