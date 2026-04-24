# SPDX-License-Identifier: Apache-2.0
"""kaizen bench — architectural-weakness benchmarking.

Three subcommands:
- fingerprint --results <dir>   Compute the value-add fingerprint table
                                  on a results directory
- compare --a <dir> --b <dir>   Head-to-head comparison of two architectures'
                                  results
- commit0                       Informational: how to run the full sweep
                                  via the Kaizen-3C/benchmarks repo

The fingerprint and compare scripts are vendored from the benchmarks repo
to make `kaizen bench` self-contained. The commit0 sweep stays in the
benchmarks repo for v1.0 because it requires Docker + commit0 + ~$30 of API
spend per run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def add_bench_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `bench` subcommand and its three sub-subcommands."""
    bench_p = subparsers.add_parser(
        "bench",
        help="Architectural-weakness benchmarking (fingerprint / compare / commit0)",
        description=(
            "kaizen bench — tools for analysing commit0 benchmark results.\n\n"
            "Subcommands:\n"
            "  fingerprint   Compute the value-add fingerprint table for a results dir\n"
            "  compare       Side-by-side comparison of two architectures' results\n"
            "  commit0       Instructions for running the full commit0 sweep upstream\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    bench_sub = bench_p.add_subparsers(
        dest="bench_subcommand",
        metavar="SUBCOMMAND",
    )
    bench_sub.required = True

    # --- fingerprint ---
    fp_p = bench_sub.add_parser(
        "fingerprint",
        help="Compute the value-add fingerprint table on a results directory",
        description=(
            "Reads aggregate JSON files from RESULTS_DIR and prints a per-cell\n"
            "pass-rate / value-add / llm_lean matrix, plus architectural-weakness\n"
            "signatures (ADR-0063)."
        ),
    )
    fp_p.add_argument(
        "--results",
        required=True,
        metavar="PATH",
        help="Path to a commit0 results directory (must contain aggregate_lite_*.json files)",
    )
    fp_p.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Suppress ANSI colour codes in output (passthrough, reserved for future use)",
    )

    # --- compare ---
    cmp_p = bench_sub.add_parser(
        "compare",
        help="Head-to-head comparison of two architectures' aggregate results",
        description=(
            "Reads aggregate_lite_*.json files from both directories and prints\n"
            "a side-by-side Markdown table of (architecture, libs covered,\n"
            "total tests passed, total cost)."
        ),
    )
    cmp_p.add_argument(
        "--a",
        required=True,
        metavar="PATH",
        dest="dir_a",
        help="First results directory (baseline)",
    )
    cmp_p.add_argument(
        "--b",
        required=True,
        metavar="PATH",
        dest="dir_b",
        help="Second results directory (comparison)",
    )

    # --- commit0 ---
    bench_sub.add_parser(
        "commit0",
        help="How to run the full commit0 sweep via the upstream benchmarks repo",
        description=(
            "Prints step-by-step instructions for reproducing commit0 benchmark\n"
            "numbers via the Kaizen-3C/benchmarks repository.\n\n"
            "After running the sweep, use `kaizen bench fingerprint` and\n"
            "`kaizen bench compare` to analyse your results."
        ),
    )

    return bench_p


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


def bench_command(args: argparse.Namespace) -> int:
    """Dispatch `kaizen bench <subcommand>`.  Returns an exit code."""
    dispatch = {
        "fingerprint": _bench_fingerprint,
        "compare": _bench_compare,
        "commit0": _bench_commit0,
    }
    handler = dispatch.get(args.bench_subcommand)
    if handler is None:
        print(f"Unknown bench subcommand: {args.bench_subcommand!r}", file=sys.stderr)
        return 2
    return handler(args)


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


def _bench_fingerprint(args: argparse.Namespace) -> int:
    """Invoke the vendored value_add_fingerprint.main()."""
    from cli.bench.value_add_fingerprint import main as fp_main

    results = Path(args.results)
    if not results.exists():
        print(f"Error: results directory not found: {results}", file=sys.stderr)
        return 1

    return fp_main(results_dir=results)


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


def _load_aggregate_jsons(directory: Path) -> list[dict[str, Any]]:
    """Return a list of parsed aggregate_lite_*.json dicts from *directory*."""
    results = []
    for p in sorted(directory.glob("aggregate_lite_*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_source_file"] = p.name
            results.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return results


def _summarise_aggregate(data: dict[str, Any]) -> dict[str, Any]:
    """Distil an aggregate JSON into a summary row for the comparison table."""
    per_lib: dict[str, Any] = data.get("per_library") or {}
    libs_covered = len(per_lib)
    total_passed = 0
    total_attempted = 0
    total_cost = 0.0

    for lib_data in per_lib.values():
        if not isinstance(lib_data, dict):
            continue
        counts = lib_data.get("counts") or lib_data.get("final_counts") or {}
        total_passed += counts.get("passed", 0)
        total_attempted += (
            counts.get("passed", 0)
            + counts.get("failed", 0)
            + counts.get("errors", 0)
        )
        # Cost: prefer pre-computed, otherwise estimate from tokens
        totals = lib_data.get("totals") or {}
        if isinstance(totals, dict) and "cost_usd" in totals:
            total_cost += totals["cost_usd"]
        else:
            inp = lib_data.get("input_tokens", 0)
            out = lib_data.get("output_tokens", 0)
            cached = lib_data.get("cached_input_tokens", 0)
            # Default to anthropic pricing if no provider info available
            model = data.get("model") or data.get("provider") or ""
            if "gpt" in model.lower() or "openai" in model.lower():
                total_cost += ((inp - cached) * 1.25 + cached * 0.125 + out * 10) / 1_000_000
            else:
                total_cost += (inp * 3 + out * 15) / 1_000_000

    pass_rate = (100.0 * total_passed / total_attempted) if total_attempted else 0.0
    # Derive an architecture label from the file name:
    # aggregate_lite_<arch>.json  ->  <arch>
    src = data.get("_source_file", "")
    arch = src.removeprefix("aggregate_lite_").removesuffix(".json") if src else "unknown"

    return {
        "arch": arch,
        "model": data.get("model", ""),
        "libs_covered": libs_covered,
        "total_passed": total_passed,
        "total_attempted": total_attempted,
        "pass_rate_pct": pass_rate,
        "total_cost_usd": total_cost,
    }


def _bench_compare(args: argparse.Namespace) -> int:
    """Side-by-side Markdown comparison of two results directories."""
    dir_a = Path(args.dir_a)
    dir_b = Path(args.dir_b)

    errors = []
    if not dir_a.exists():
        errors.append(f"--a directory not found: {dir_a}")
    if not dir_b.exists():
        errors.append(f"--b directory not found: {dir_b}")
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    aggs_a = _load_aggregate_jsons(dir_a)
    aggs_b = _load_aggregate_jsons(dir_b)

    if not aggs_a and not dir_a.glob("*.json"):
        print(f"Warning: no aggregate_lite_*.json files found in {dir_a}", file=sys.stderr)
    if not aggs_b and not dir_b.glob("*.json"):
        print(f"Warning: no aggregate_lite_*.json files found in {dir_b}", file=sys.stderr)

    rows_a = [_summarise_aggregate(d) for d in aggs_a]
    rows_b = [_summarise_aggregate(d) for d in aggs_b]

    # Build a unified index keyed by arch name so we can align A/B side-by-side
    all_archs: dict[str, dict[str, Any]] = {}
    for row in rows_a:
        all_archs.setdefault(row["arch"], {})["a"] = row
    for row in rows_b:
        all_archs.setdefault(row["arch"], {})["b"] = row

    # Print Markdown table header
    print()
    print(f"## Benchmark comparison")
    print(f"   A: `{dir_a}`")
    print(f"   B: `{dir_b}`")
    print()

    col_hdr = (
        "| Architecture | Src | Model | Libs covered | "
        "Tests passed | Attempted | Pass rate | Est. cost |"
    )
    col_sep = (
        "|---|---|---|---|---|---|---|---|"
    )
    print(col_hdr)
    print(col_sep)

    def _row_line(row: dict[str, Any], src_label: str) -> str:
        return (
            f"| {row['arch']} "
            f"| {src_label} "
            f"| {row['model']} "
            f"| {row['libs_covered']} "
            f"| {row['total_passed']} "
            f"| {row['total_attempted']} "
            f"| {row['pass_rate_pct']:.1f}% "
            f"| ${row['total_cost_usd']:.3f} |"
        )

    if not all_archs:
        print("| _(no data found in either directory)_ | | | | | | | |")
    else:
        for arch, sides in sorted(all_archs.items()):
            if "a" in sides:
                print(_row_line(sides["a"], "A"))
            if "b" in sides:
                print(_row_line(sides["b"], "B"))

    print()
    return 0


# ---------------------------------------------------------------------------
# commit0
# ---------------------------------------------------------------------------


def _bench_commit0(_args: argparse.Namespace) -> int:
    """Print step-by-step instructions for running the full commit0 sweep."""
    print(
        "kaizen bench commit0 -- reproduction via the benchmarks repo\n"
        "\n"
        "Full-sweep reproduction is done via the upstream benchmarks repository\n"
        "directly, not through this CLI. The reason: the benchmark runners have\n"
        "environment conventions (Docker workspace, Python paths, per-architecture\n"
        "model pins) that the CLI would only paper over, risking divergence from\n"
        "the published numbers.\n"
        "\n"
        "Reproduction steps:\n"
        "\n"
        "  git clone https://github.com/Kaizen-3C/benchmarks.git ~/kaizen-commit0\n"
        "  cd ~/kaizen-commit0\n"
        "  # Follow the README for environment setup, then run baseline scripts:\n"
        "  python commit0/baselines/run_lite_kaizen_delta.py --provider anthropic\n"
        "  python commit0/baselines/run_lite_single_shot.py\n"
        "\n"
        "Requirements:\n"
        "  - Docker (commit0 uses containers per library)\n"
        "  - ANTHROPIC_API_KEY (OPENAI_API_KEY for some baselines)\n"
        "  - Small sweep (4 libs x 2 archs): ~$4.52, ~22 min\n"
        "  - Full sweep: ~$30+, hours\n"
        "\n"
        "Once you have a results directory, analyse it with:\n"
        "\n"
        "  kaizen bench fingerprint --results <dir>\n"
        "  kaizen bench compare --a <baseline-dir> --b <your-results-dir>\n"
        "\n"
        "For the current published baselines and methodology:\n"
        "  https://github.com/Kaizen-3C/benchmarks"
    )
    return 0
