# SPDX-License-Identifier: Apache-2.0
"""`kaizen memsafe-roadmap` — generate a CISA-format memory safety roadmap.

End-to-end wiring (Phase B, 2026-04-19 reframe):
  1. Run `cli.pipeline.decompose_v2` on the target repo (optionally
     with `--domain memory-safe` for the full ownership/lifetime schema).
  2. Parse the emitted ADR markdown to extract Decisions + Key Identifiers
     + Ownership Decisions (if domain schema was used).
  3. Render a CISA-compliant memory safety roadmap markdown.
  4. Emit one ADR stub per Key Identifier module for the transition plan.
  5. Optionally recompose to a Rust crate via `--recompose`.

Per the 2026-04-19 three-arm ablation (see
docs/case-studies/memsafe-01-inih/README.md), the ADR-as-contract alone
closes ~83% of the architecture's measured value vs. one-shot LLM on
C -> Rust. The `--domain memory-safe` schema is additive polish for the
last-mile (17%). Customers can opt out via `--plain` if they want the
minimum-viable output with the smaller schema surface.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .. import output
from ..output import Style


_CLI_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _CLI_PACKAGE_ROOT / "pipeline"
_DECOMPOSE_SCRIPT = _PIPELINE_DIR / "decompose_v2.py"
_RECOMPOSE_SCRIPT = _PIPELINE_DIR / "recompose_v2.py"

# Preserved for any downstream imports; dev-checkout root (three levels up from
# this file) is the repo root, which is where a contributor's `.env` typically
# lives. In an installed-package context this path won't exist — the `.env`
# lookup in _build_subprocess_env falls back to the caller's CWD.
_KAIZEN_ROOT = _CLI_PACKAGE_ROOT.parent


def _build_subprocess_env():
    """Return an environment dict to pass to subprocesses, with .env loaded
    from the caller's CWD (preferred) or the dev-checkout repo root. Users
    can also rely on the caller's already-exported environment; this helper
    is best-effort augmentation."""
    env = dict(os.environ)
    for candidate in (Path.cwd() / ".env", _KAIZEN_ROOT / ".env"):
        if candidate.exists():
            dotenv_path = candidate
            break
    else:
        return env
    try:
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in env:  # don't overwrite caller-exported values
                env[k] = v
    except (OSError, UnicodeDecodeError):
        pass
    return env


# --- Argument wiring --------------------------------------------------------


def add_memsafe_roadmap_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "memsafe-roadmap",
        help=(
            "Generate a CISA-format memory safety roadmap (+ per-module "
            "ADRs) for a C/C++ codebase, with optional Rust recompose."
        ),
        description=(
            "Generate a CISA-compliant memory safety roadmap for a C/C++ "
            "repository. Calls decompose_v2 to extract decisions and (with "
            "--domain memory-safe, default) ownership decisions; renders a "
            "roadmap markdown; emits per-module ADR stubs. With --recompose, "
            "follows through to a Rust crate. See "
            "docs/markets/MEMORY_SAFETY_WEDGE.md for context."
        ),
    )
    p.add_argument("repo", metavar="REPO",
                   help="Path to the C/C++ source repository (directory)")
    p.add_argument("--output", "-o", metavar="PATH", default="roadmap.md",
                   help="Output path for the roadmap markdown (default: roadmap.md)")
    p.add_argument("--adr-dir", metavar="PATH", default="adrs",
                   help="Directory for per-module ADRs (default: adrs/)")
    p.add_argument("--glob", default="*",
                   help="Source-file glob pattern passed to decompose_v2 "
                        "(default: '*' - all files in repo root). Note: "
                        "decompose_v2 does not accept space-separated globs.")
    p.add_argument("--plain", action="store_true",
                   help="Skip --domain memory-safe on decompose. Produces the "
                        "minimum-viable ADR per the three-arm inih ablation "
                        "(plain ADR closes 83%% of the architecture's C->Rust "
                        "win, without the ownership-decisions schema overhead).")
    p.add_argument("--recompose", action="store_true",
                   help="Also produce a Rust crate (slower; requires more budget)")
    p.add_argument("--rust-output", metavar="PATH", default="rust-port",
                   help="If --recompose, output directory for the Rust crate "
                        "(default: rust-port/)")
    p.add_argument("--provider", default="anthropic",
                   choices=["anthropic", "openai"],
                   help="LLM provider (default: anthropic)")
    p.add_argument("--model", default=None,
                   help="Model name override")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the planned pipeline steps without calling any LLM")
    p.add_argument("--format", choices=["human", "json"], default="human",
                   help="Output format (default: human)")
    return p


# --- ADR parsing ------------------------------------------------------------


def _extract_section(md: str, heading: str) -> str:
    """Return the text of the section under `## <heading>` up to the next `##`."""
    # Match "## <heading>" (any markdown heading level >= 2 with this label).
    m = re.search(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s+|\Z)",
        md, flags=re.DOTALL | re.MULTILINE,
    )
    return m.group(1).strip() if m else ""


def _extract_decisions(md: str) -> list:
    """Return the Decision bullets verbatim from the `## Decision` section."""
    section = _extract_section(md, "Decision")
    bullets = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets


def _extract_key_identifiers(md: str) -> list:
    """Parse the Key Identifiers table. Returns list of dicts with name/kind/file."""
    section = _extract_section(md, "Key Identifiers")
    rows = []
    _ESCAPED_PIPE = "\x00PIPE\x00"
    for line in section.splitlines():
        if "|" not in line:
            continue
        tmp = line.replace(r"\|", _ESCAPED_PIPE)
        parts = [p.strip().strip("`").replace(_ESCAPED_PIPE, "|")
                 for p in tmp.strip().strip("|").split("|")]
        if len(parts) < 3 or parts[0] in ("Name", "") or parts[0].startswith("-"):
            continue
        row = {"name": parts[0], "kind": parts[1], "file": parts[2]}
        if len(parts) >= 4 and parts[3]:
            row["signature_or_attrs"] = parts[3]
        rows.append(row)
    return rows


def _extract_ownership_decisions(md: str) -> list:
    """Parse the Ownership Decisions table (only present with --domain memory-safe)."""
    section = _extract_section(md, "Ownership Decisions (memory-safe domain)")
    rows = []
    _ESCAPED_PIPE = "\x00PIPE\x00"
    for line in section.splitlines():
        if "|" not in line:
            continue
        tmp = line.replace(r"\|", _ESCAPED_PIPE)
        parts = [p.strip().strip("`").replace(_ESCAPED_PIPE, "|")
                 for p in tmp.strip().strip("|").split("|")]
        if len(parts) < 3 or parts[0] in ("Resource", "") or parts[0].startswith("-"):
            continue
        rows.append({
            "resource": parts[0],
            "ownership": parts[1] if len(parts) > 1 else "",
            "evidence": parts[2] if len(parts) > 2 else "",
        })
    return rows


# --- Roadmap rendering ------------------------------------------------------


def _render_cisa_roadmap(
    repo_path: Path, adr_path: Path,
    decisions: list, key_ids: list, ownership: list,
    used_domain: bool,
) -> str:
    """Render the CISA-format memory safety roadmap markdown."""
    lines = []
    lines += ["# Memory Safety Roadmap", ""]
    lines += [f"**Generated**: `kaizen memsafe-roadmap` from `{repo_path}`"]
    lines += [f"**Source ADR**: [`{adr_path.name}`]({adr_path.as_posix()})"]
    lines += [f"**Format**: CISA Secure by Design guidance-aligned (2024-12 joint guidance)"]
    lines += [""]

    lines += ["## Executive Summary", ""]
    lines += [
        f"- Source: `{repo_path}`",
        f"- Key Identifiers (transition candidates): {len(key_ids)}",
        f"- Architectural Decisions documented: {len(decisions)}",
        f"- Ownership Decisions captured: "
        f"{len(ownership) if used_domain else '(not captured — see --plain flag note below)'}",
        "",
    ]
    if not used_domain:
        lines += [
            "> `--plain` mode: this roadmap captures public-API transition "
            "candidates and architectural decisions, but not the per-resource "
            "ownership-model decisions that `--domain memory-safe` would add. "
            "Re-run without `--plain` for the full CISA-aligned output.",
            "",
        ]

    lines += ["## Priority Components", ""]
    lines += [
        "Priority order inferred from the order Key Identifiers appear in the ADR. "
        "Ordering by security-criticality (network-facing, cryptography-handling, "
        "privilege boundary) is a manual human-review step — see the '## Reviewer "
        "Checklist' section below.",
        "",
    ]
    lines += ["| # | Identifier | Kind | Source File | Transition Target |",
              "|---|------------|------|-------------|-------------------|"]
    for i, k in enumerate(key_ids, start=1):
        target = "memory-safe equivalent (Rust / safe-C++ / language-of-choice)"
        lines += [
            f"| {i} | `{k['name']}` | {k['kind']} | `{k['file']}` | {target} |"
        ]
    lines += [""]

    if ownership:
        lines += ["## Ownership Decisions (from `--domain memory-safe` schema)", ""]
        lines += [
            "Per-resource ownership model decisions. Each row is **load-bearing**: "
            "the reimplementation MUST honor the decision. A security reviewer "
            "signs off on this table *before* any code is written.",
            "",
        ]
        lines += ["| # | Resource | Target Ownership | Source Evidence |",
                  "|---|----------|------------------|-----------------|"]
        for i, o in enumerate(ownership, start=1):
            lines += [
                f"| {i} | `{o['resource']}` | `{o['ownership']}` | `{o['evidence']}` |"
            ]
        lines += [""]

    if decisions:
        lines += ["## Architectural Decisions (verbatim from ADR)", ""]
        for d in decisions:
            lines += [f"- {d}"]
        lines += [""]

    lines += ["## Reviewer Checklist", ""]
    lines += [
        "Before this roadmap is considered CISA-compliance-ready, a human "
        "reviewer (typically a security architect or compliance officer) must:",
        "",
        "- [ ] Confirm the Priority Components ordering reflects actual "
        "security criticality (network-facing / crypto / privilege-boundary first).",
        "- [ ] Review each Ownership Decision (if present) for correctness.",
        "- [ ] Assign per-component effort estimates and target milestones.",
        "- [ ] Attach this roadmap + ADR to the vendor's published memory "
        "safety plan per CISA's guidance.",
        "- [ ] Schedule re-assessment cadence (quarterly recommended).",
        "",
    ]

    lines += ["## Source-of-Truth Links", ""]
    lines += [f"- Full ADR: [`{adr_path.name}`]({adr_path.as_posix()})"]
    lines += ["- CISA Secure by Design: https://www.cisa.gov/securebydesign"]
    lines += [
        "- NSA Cybersecurity Information sheet on memory safety: "
        "https://media.defense.gov/2025/Jun/23/2003742198/-1/-1/0/"
        "CSI_MEMORY_SAFE_LANGUAGES_REDUCING_VULNERABILITIES_IN_MODERN_SOFTWARE_DEVELOPMENT.PDF",
    ]
    lines += [""]

    return "\n".join(lines)


def _write_per_module_adr_stubs(
    adr_dir: Path, key_ids: list, source_adr_path: Path
) -> int:
    """Emit one stub ADR per Key Identifier module. Returns count emitted."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    seen_files = set()
    for k in key_ids:
        # Group by source file rather than per-identifier.
        file_key = k.get("file", "").strip("`")
        if not file_key or file_key in seen_files:
            continue
        seen_files.add(file_key)
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", file_key).strip("-") or "module"
        stub_path = adr_dir / f"ADR-module-{safe_name}.md"
        stub_path.write_text(
            f"# ADR: Memory-safety transition for `{file_key}`\n\n"
            f"## Status\n\nProposed (auto-generated stub by `kaizen memsafe-roadmap`)\n\n"
            f"## Context\n\n"
            f"This module was identified as a memory-safety transition "
            f"candidate by decompose_v2 against the root repo. See the "
            f"parent ADR at [`{source_adr_path.name}`]({source_adr_path.as_posix()}) "
            f"for full context.\n\n"
            f"## Decision\n\n"
            f"*To be filled by a human reviewer after consulting the root ADR's "
            f"Ownership Decisions (if present) and the Priority Components table "
            f"in the generated roadmap.*\n\n"
            f"## Consequences\n\n*To be filled.*\n",
            encoding="utf-8",
        )
        count += 1
    return count


# --- Command entrypoint ------------------------------------------------------


def memsafe_roadmap_command(args: argparse.Namespace) -> int:
    style: Style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    repo = Path(args.repo).resolve()

    if not repo.exists() or not repo.is_dir():
        output.error(style, f"repo path does not exist or is not a directory: {repo}")
        return 2

    adr_dir = Path(args.adr_dir).resolve()
    root_adr_path = adr_dir / "adr-root.md"
    roadmap_path = Path(args.output).resolve()
    use_domain = not args.plain

    # --- Dry-run short-circuit ------------------------------------------------
    if args.dry_run:
        print(style.bold(f"kaizen memsafe-roadmap --dry-run  {repo}"))
        print()
        step_num = 1
        print(f"  [{step_num}] {style.bold('Decompose')}")
        dom_flag = "--domain memory-safe" if use_domain else "(--plain; no domain)"
        print(f"      python {_DECOMPOSE_SCRIPT.as_posix()} \\")
        print(f"        --input {repo} --glob '{args.glob}' \\")
        print(f"        --source-language C {dom_flag} \\")
        print(f"        --provider {args.provider} --output {root_adr_path}")
        step_num += 1
        print()
        print(f"  [{step_num}] {style.bold('Render CISA roadmap')}")
        print(f"      (internal) parse ADR, render CISA-format markdown to {roadmap_path}")
        step_num += 1
        print()
        print(f"  [{step_num}] {style.bold('Per-module ADR stubs')}")
        print(f"      (internal) one ADR stub per Key Identifier file under {adr_dir}/")
        step_num += 1
        if args.recompose:
            print()
            print(f"  [{step_num}] {style.bold('Recompose (optional)')}")
            print(f"      python {_RECOMPOSE_SCRIPT.as_posix()} \\")
            print(f"        --adr {root_adr_path} --target-language Rust \\")
            print(f"        --cross-language --domain memory-safe \\")
            print(f"        --provider {args.provider} --output-dir {args.rust_output}")
        print()
        print(style.dim("no orchestrator invoked; exit 0"))
        return 0

    # --- Step 1: Decompose ----------------------------------------------------
    adr_dir.mkdir(parents=True, exist_ok=True)
    print(style.bold("[1/3] Decompose"), flush=True)
    cmd = [
        sys.executable, str(_DECOMPOSE_SCRIPT),
        "--input", str(repo),
        "--output", str(root_adr_path),
        "--adr-id", f"ADR-{repo.name}-memsafe",
        "--glob", args.glob,
        "--source-language", "C",
        "--provider", args.provider,
    ]
    if use_domain:
        cmd += ["--domain", "memory-safe"]
    if args.model:
        cmd += ["--model", args.model]
    rc = subprocess.run(cmd, env=_build_subprocess_env()).returncode
    if rc != 0:
        output.error(style, f"decompose failed with exit code {rc}")
        return rc
    if not root_adr_path.exists():
        output.error(style, f"decompose did not produce the expected ADR at {root_adr_path}")
        return 3

    # --- Step 2: Parse ADR and render roadmap --------------------------------
    print(style.bold("[2/3] Render CISA roadmap"), flush=True)
    adr_md = root_adr_path.read_text(encoding="utf-8")
    decisions = _extract_decisions(adr_md)
    key_ids = _extract_key_identifiers(adr_md)
    ownership = _extract_ownership_decisions(adr_md) if use_domain else []
    roadmap_md = _render_cisa_roadmap(
        repo_path=repo, adr_path=root_adr_path,
        decisions=decisions, key_ids=key_ids, ownership=ownership,
        used_domain=use_domain,
    )
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    roadmap_path.write_text(roadmap_md, encoding="utf-8")
    print(f"       wrote {roadmap_path}  "
          f"({len(key_ids)} identifiers, {len(decisions)} decisions, "
          f"{len(ownership)} ownership rows)")

    # --- Step 3: Per-module ADR stubs ----------------------------------------
    print(style.bold("[3/3] Per-module ADR stubs"), flush=True)
    stub_count = _write_per_module_adr_stubs(adr_dir, key_ids, root_adr_path)
    print(f"       wrote {stub_count} module stub(s) under {adr_dir}/")

    # --- Optional: Recompose --------------------------------------------------
    if args.recompose:
        print(style.bold("[4/4] Recompose to Rust"), flush=True)
        rust_dir = Path(args.rust_output).resolve()
        rcmd = [
            sys.executable, str(_RECOMPOSE_SCRIPT),
            "--adr", str(root_adr_path),
            "--output-dir", str(rust_dir),
            "--target-language", "Rust",
            "--cross-language",
            "--provider", args.provider,
            "--max-tokens", "16000",
        ]
        if use_domain:
            rcmd += ["--domain", "memory-safe"]
        if args.model:
            rcmd += ["--model", args.model]
        rc = subprocess.run(rcmd, env=_build_subprocess_env()).returncode
        if rc != 0:
            output.warn(style, f"recompose exited {rc}; roadmap + ADRs already written")
        else:
            print(f"       wrote Rust crate under {rust_dir}/")

    if args.format == "json":
        print(json.dumps({
            "ok": True,
            "repo": str(repo),
            "roadmap": str(roadmap_path),
            "adr_root": str(root_adr_path),
            "adr_stubs": stub_count,
            "identifiers": len(key_ids),
            "decisions": len(decisions),
            "ownership_decisions": len(ownership),
            "used_domain_schema": use_domain,
        }, indent=2))
    else:
        print()
        print(style.bold("Done."))
        print(f"  Roadmap:   {roadmap_path}")
        print(f"  Root ADR:  {root_adr_path}")
        print(f"  Stubs:     {adr_dir}/ ({stub_count} file(s))")
        print(style.dim("  Review: see the 'Reviewer Checklist' section in the roadmap."))

    return 0
