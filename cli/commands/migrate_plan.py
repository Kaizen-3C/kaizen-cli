# SPDX-License-Identifier: Apache-2.0
"""`kaizen migrate-plan` — generate a framework-migration plan + per-module ADRs.

Scaffolding only in Phase A of the 2026-04-19 reframe (see
[STRATEGIC_ROADMAP.md §5 Phase A](../../STRATEGIC_ROADMAP.md) and
[docs/markets/FRAMEWORK_MODERNIZATION_WEDGE.md](../../docs/markets/FRAMEWORK_MODERNIZATION_WEDGE.md)).

Current behavior: `--help` works, `--dry-run` prints the planned pipeline
steps, everything else exits 2 with a "not yet wired end-to-end" message.

Phase B wiring (planned):
  1. Run decompose_v2.py with --domain framework-migration
  2. Render the migration plan from api_contract + state_management_model +
     routing_model + dependency_upgrade_path
  3. Emit one ADR per prioritized module
  4. Optionally recompose to the target framework when --recompose is set
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import output
from ..output import Style


_SUPPORTED_PAIRS = {
    "angularjs->angular": ("JavaScript", "TypeScript"),
    "angularjs->react": ("JavaScript", "TypeScript"),
    "jquery->react": ("JavaScript", "TypeScript"),
    "dotnet-framework->dotnet8": ("C#", "C#"),
    "dotnet-framework->dotnet9": ("C#", "C#"),
    "python2->python3": ("Python", "Python"),
    "spring4->spring-boot3": ("Java", "Java"),
    "java8->java17": ("Java", "Java"),
    "java8->java21": ("Java", "Java"),
}


def add_migrate_plan_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "migrate-plan",
        help=(
            "Generate a framework-migration plan (+ per-module ADRs) for a "
            "legacy codebase, with optional target-framework recompose."
        ),
        description=(
            "Generate a framework-migration plan for a legacy codebase. Calls "
            "decompose_v2 with --domain framework-migration to extract the "
            "public API contract, state management model, routing model, and "
            "dependency upgrade path; renders a plan markdown; emits per-"
            "module ADRs. With --recompose, follows through to target-"
            "framework code. See docs/markets/FRAMEWORK_MODERNIZATION_WEDGE.md "
            "for context."
        ),
    )
    p.add_argument("repo", metavar="REPO",
                   help="Path to the legacy source repository (directory)")
    p.add_argument("--from", dest="from_fw", metavar="FW", required=True,
                   help="Source framework (e.g. angularjs, dotnet-framework, "
                        "python2, jquery, spring4)")
    p.add_argument("--to", dest="to_fw", metavar="FW", required=True,
                   help="Target framework (e.g. angular, dotnet8, python3, "
                        "react, spring-boot3)")
    p.add_argument("--output", "-o", metavar="PATH", default="plan.md",
                   help="Output path for the migration plan markdown (default: plan.md)")
    p.add_argument("--adr-dir", metavar="PATH", default="adrs/",
                   help="Directory for per-module ADRs (default: adrs/)")
    p.add_argument("--glob", default=None,
                   help="Source-file glob patterns (default: inferred from --from)")
    p.add_argument("--recompose", action="store_true",
                   help="Also produce target-framework code (slower)")
    p.add_argument("--target-output", metavar="PATH", default="migrated/",
                   help="If --recompose, output directory for target code "
                        "(default: migrated/)")
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


def _pair_key(args: argparse.Namespace) -> str:
    return f"{args.from_fw.lower()}->{args.to_fw.lower()}"


def _glob_for_source_fw(fw: str) -> str:
    fw = fw.lower()
    if fw.startswith("angular") or fw in ("jquery",):
        return "*.js *.ts *.html"
    if fw.startswith("dotnet"):
        return "*.cs *.cshtml *.csproj"
    if fw.startswith("python"):
        return "*.py"
    if fw.startswith("java") or fw.startswith("spring"):
        return "*.java"
    return "*"


def migrate_plan_command(args: argparse.Namespace) -> int:
    style: Style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    repo = Path(args.repo).resolve()

    if not repo.exists() or not repo.is_dir():
        output.error(style, f"repo path does not exist or is not a directory: {repo}")
        return 2

    pair = _pair_key(args)
    if pair not in _SUPPORTED_PAIRS:
        supported = ", ".join(sorted(_SUPPORTED_PAIRS.keys()))
        output.error(style, (
            f"unsupported migration pair: {pair}\n"
            f"  supported: {supported}"
        ))
        return 2

    source_lang, target_lang = _SUPPORTED_PAIRS[pair]
    glob_pat = args.glob or _glob_for_source_fw(args.from_fw)

    planned_steps = [
        ("1", "Decompose", (
            f"scripts/pipeline/decompose_v2.py --input {repo} "
            f"--glob '{glob_pat}' --source-language {source_lang} "
            f"--domain framework-migration --provider {args.provider} "
            f"--output {args.adr_dir}/adr-root.md"
        )),
        ("2", "Render migration plan", (
            f"(internal) pull API Contract + State Management Model + "
            f"Routing Model + Dependency Upgrade Path from the ADR, "
            f"render as plan markdown, write to {args.output}"
        )),
        ("3", "Per-module ADRs", (
            f"(internal) split the root ADR into per-module ADRs under {args.adr_dir}"
        )),
    ]
    if args.recompose:
        planned_steps.append(
            ("4", "Recompose (optional)", (
                f"scripts/pipeline/recompose_v2.py --adr {args.adr_dir}/adr-root.md "
                f"--target-language {target_lang} --cross-language "
                f"--domain framework-migration --provider {args.provider} "
                f"--output-dir {args.target_output}"
            ))
        )

    if args.dry_run:
        print(style.bold(f"kaizen migrate-plan --dry-run  {repo}  ({pair})"))
        print()
        print(f"  source language : {source_lang}")
        print(f"  target language : {target_lang}")
        print(f"  glob            : {glob_pat}")
        print()
        for num, name, cmd in planned_steps:
            print(f"  [{num}] {style.bold(name)}")
            print(f"      {cmd}")
            print()
        print(style.dim("no orchestrator invoked; exit 0"))
        return 0

    output.error(style, (
        "`kaizen migrate-plan` is scaffolded (Phase A of 2026-04-19 reframe) "
        "but not yet wired end-to-end. Phase B (Days 30-60) ships the full "
        "pipeline. For now, run with --dry-run to see the planned steps."
    ))
    output.eprint(style.dim("  see docs/markets/FRAMEWORK_MODERNIZATION_WEDGE.md for context"))
    return 2
