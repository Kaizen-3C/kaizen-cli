# SPDX-License-Identifier: Apache-2.0
"""`kaizen memsafe-roadmap` — generate a CISA-format memory safety roadmap.

Scaffolding only in Phase A of the 2026-04-19 reframe (see
[STRATEGIC_ROADMAP.md §5 Phase A](../../STRATEGIC_ROADMAP.md) and
[docs/markets/MEMORY_SAFETY_WEDGE.md](../../docs/markets/MEMORY_SAFETY_WEDGE.md)).

Current behavior: `--help` works, `--dry-run` prints the planned pipeline
steps, everything else exits 2 with a "not yet wired end-to-end" message.

Phase B wiring (planned):
  1. Run decompose_v2.py with --domain memory-safe on the target repo
  2. Render the CISA-format roadmap from the ownership_decisions + priorities
  3. Emit one ADR per prioritized module
  4. Optionally recompose to Rust crate when --recompose is set
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import output
from ..output import Style


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
            "repository. Calls decompose_v2 with --domain memory-safe to "
            "extract ownership decisions, lifetime bounds, and prioritized "
            "components; renders a roadmap markdown; emits per-module ADRs. "
            "With --recompose, follows through to a Rust crate. See "
            "docs/markets/MEMORY_SAFETY_WEDGE.md for context."
        ),
    )
    p.add_argument("repo", metavar="REPO",
                   help="Path to the C/C++ source repository (directory)")
    p.add_argument("--output", "-o", metavar="PATH", default="roadmap.md",
                   help="Output path for the roadmap markdown (default: roadmap.md)")
    p.add_argument("--adr-dir", metavar="PATH", default="adrs/",
                   help="Directory for per-module ADRs (default: adrs/)")
    p.add_argument("--glob", default="*.c *.cpp *.h *.hpp *.cc",
                   help="Source-file glob patterns (default: common C/C++ extensions)")
    p.add_argument("--recompose", action="store_true",
                   help="Also produce a Rust crate (slower; requires more budget)")
    p.add_argument("--rust-output", metavar="PATH", default="rust-port/",
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


# --- Command entrypoint ------------------------------------------------------


def memsafe_roadmap_command(args: argparse.Namespace) -> int:
    style: Style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    repo = Path(args.repo).resolve()

    if not repo.exists() or not repo.is_dir():
        output.error(style, f"repo path does not exist or is not a directory: {repo}")
        return 2

    planned_steps = [
        ("1", "Decompose", (
            f"scripts/pipeline/decompose_v2.py --input {repo} "
            f"--glob '{args.glob}' --source-language C "
            f"--domain memory-safe --provider {args.provider} "
            f"--output {args.adr_dir}/adr-root.md"
        )),
        ("2", "Render roadmap", (
            f"(internal) pull Ownership Decisions + Key Identifiers from the ADR, "
            f"apply CISA-format template, write to {args.output}"
        )),
        ("3", "Per-module ADRs", (
            f"(internal) split the root ADR into per-module ADRs under {args.adr_dir}"
        )),
    ]
    if args.recompose:
        planned_steps.append(
            ("4", "Recompose (optional)", (
                f"scripts/pipeline/recompose_v2.py --adr {args.adr_dir}/adr-root.md "
                f"--target-language Rust --cross-language --domain memory-safe "
                f"--provider {args.provider} --output-dir {args.rust_output}"
            ))
        )

    if args.dry_run:
        print(style.bold(f"kaizen memsafe-roadmap --dry-run  {repo}"))
        print()
        for num, name, cmd in planned_steps:
            print(f"  [{num}] {style.bold(name)}")
            print(f"      {cmd}")
            print()
        print(style.dim("no orchestrator invoked; exit 0"))
        return 0

    # Phase A: scaffolding only — not yet wired end-to-end.
    output.error(style, (
        "`kaizen memsafe-roadmap` is scaffolded (Phase A of 2026-04-19 reframe) "
        "but not yet wired end-to-end. Phase B (Days 30-60) ships the full "
        "pipeline. For now, run with --dry-run to see the planned steps, or "
        "invoke `scripts/pipeline/decompose_v2.py --domain memory-safe` "
        "directly."
    ))
    output.eprint(style.dim("  see docs/markets/MEMORY_SAFETY_WEDGE.md for context"))
    return 2
