# SPDX-License-Identifier: Apache-2.0
"""`kaizen migrate-plan` — generate a framework-migration plan + per-module ADRs.

End-to-end wiring (Phase B, 2026-04-19 reframe):
  1. Run `scripts/pipeline/decompose_v2.py` on the target repo (optionally
     with `--domain framework-migration` for the full API-contract schema).
  2. Parse the emitted ADR markdown to extract Decisions + Key Identifiers
     + framework-migration domain sections (if domain schema was used).
  3. Render a framework-migration plan markdown.
  4. Emit one ADR stub per Key Identifier module for the transition plan.
  5. Optionally recompose to the target framework via `--recompose`.

Per the 2026-04-19 three-arm ablation, the ADR-as-contract alone closes
~83% of the architecture's measured value on decision-dense cross-
language translations. The `--domain framework-migration` schema is
additive polish. Customers can opt out via `--plain` for the minimum-
viable output.
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
from .memsafe_roadmap import (
    _KAIZEN_ROOT,
    _DECOMPOSE_SCRIPT,
    _RECOMPOSE_SCRIPT,
    _build_subprocess_env,
    _extract_decisions,
    _extract_key_identifiers,
    _extract_section,
    _write_per_module_adr_stubs,
)


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
                   help="Source-file glob (default: inferred from --from). Single "
                        "pattern only; decompose_v2 does not accept space-separated "
                        "globs. Use '*' for all files.")
    p.add_argument("--plain", action="store_true",
                   help="Skip --domain framework-migration on decompose. Produces "
                        "the minimum-viable plan per the three-arm inih ablation.")
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
    """Single-pattern glob (decompose_v2 doesn't accept space-separated)."""
    fw = fw.lower()
    if fw.startswith("angular") or fw in ("jquery",):
        return "*.js"
    if fw.startswith("dotnet"):
        return "*.cs"
    if fw.startswith("python"):
        return "*.py"
    if fw.startswith("java") or fw.startswith("spring"):
        return "*.java"
    return "*"


# --- Plan rendering ---------------------------------------------------------


def _extract_state_model(md: str) -> dict:
    """Parse the State Management Model section if present."""
    section = _extract_section(md, "State Management Model")
    if not section:
        return {}
    out = {}
    for line in section.splitlines():
        m = re.match(r"-\s*\*\*(Source|Target|Evidence)\*\*:\s*(.*)", line.strip())
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


def _extract_routing_model(md: str) -> dict:
    section = _extract_section(md, "Routing Model")
    if not section:
        return {}
    out = {}
    for line in section.splitlines():
        m = re.match(r"-\s*\*\*(Source|Target|Evidence)\*\*:\s*(.*)", line.strip())
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out


def _extract_api_contracts(md: str) -> list:
    section = _extract_section(md, "API Contract (framework-migration domain)")
    rows = []
    _ESCAPED_PIPE = "\x00PIPE\x00"
    for line in section.splitlines():
        if "|" not in line:
            continue
        tmp = line.replace(r"\|", _ESCAPED_PIPE)
        parts = [p.strip().strip("`").replace(_ESCAPED_PIPE, "|")
                 for p in tmp.strip().strip("|").split("|")]
        if len(parts) < 3 or parts[0] in ("Contract", "") or parts[0].startswith("-"):
            continue
        rows.append({
            "contract": parts[0],
            "shape": parts[1],
            "evidence": parts[2] if len(parts) > 2 else "",
        })
    return rows


def _extract_dependency_upgrade_path(md: str) -> list:
    section = _extract_section(md, "Dependency Upgrade Path")
    rows = []
    _ESCAPED_PIPE = "\x00PIPE\x00"
    for line in section.splitlines():
        if "|" not in line:
            continue
        tmp = line.replace(r"\|", _ESCAPED_PIPE)
        parts = [p.strip().strip("`").replace(_ESCAPED_PIPE, "|")
                 for p in tmp.strip().strip("|").split("|")]
        if len(parts) < 2 or parts[0] in ("Dependency", "") or parts[0].startswith("-"):
            continue
        rows.append({
            "dependency": parts[0],
            "decision": parts[1] if len(parts) > 1 else "",
            "evidence": parts[2] if len(parts) > 2 else "",
        })
    return rows


def _render_migration_plan(
    repo_path: Path, adr_path: Path, pair: str,
    source_lang: str, target_lang: str,
    decisions: list, key_ids: list,
    api_contracts: list, state_model: dict, routing_model: dict,
    dep_path: list, used_domain: bool,
) -> str:
    lines = []
    lines += ["# Framework Migration Plan", ""]
    lines += [f"**Generated**: `kaizen migrate-plan` from `{repo_path}`"]
    lines += [f"**Source ADR**: [`{adr_path.name}`]({adr_path.as_posix()})"]
    lines += [f"**Transition**: `{pair}`  ({source_lang} → {target_lang})"]
    lines += [""]

    lines += ["## Executive Summary", ""]
    lines += [
        f"- Source: `{repo_path}`",
        f"- Transition: {pair}",
        f"- Key Identifiers (migration candidates): {len(key_ids)}",
        f"- Architectural Decisions documented: {len(decisions)}",
        f"- API contracts captured: "
        f"{len(api_contracts) if used_domain else '(not captured — --plain mode)'}",
        f"- Dependency decisions captured: "
        f"{len(dep_path) if used_domain else '(not captured — --plain mode)'}",
        "",
    ]
    if not used_domain:
        lines += [
            "> `--plain` mode: this plan captures per-module transition "
            "candidates and high-level architectural decisions. Re-run without "
            "`--plain` for the full framework-migration schema output "
            "(API contracts, state-management model, routing model, "
            "dependency upgrade path).",
            "",
        ]

    lines += ["## Migration Order (per-module transition plan)", ""]
    lines += [
        "Suggested order: leaf modules first, working up to the app's "
        "composition root. Ordering reflects the appearance order in the "
        "ADR's Key Identifiers table — human-review this before committing.",
        "",
    ]
    lines += ["| # | Identifier | Kind | Source File | Target Framework |",
              "|---|------------|------|-------------|------------------|"]
    for i, k in enumerate(key_ids, start=1):
        lines += [
            f"| {i} | `{k['name']}` | {k['kind']} | `{k['file']}` | {target_lang} equivalent |"
        ]
    lines += [""]

    if api_contracts:
        lines += ["## API Contract (load-bearing across the transition)", ""]
        lines += [
            "Each row is a public contract that MUST survive the migration "
            "exactly. Customer-facing shape does not change; internal "
            "implementation does.",
            "",
        ]
        lines += ["| # | Contract | Shape | Evidence |",
                  "|---|----------|-------|----------|"]
        for i, c in enumerate(api_contracts, start=1):
            lines += [f"| {i} | `{c['contract']}` | {c['shape']} | `{c['evidence']}` |"]
        lines += [""]

    if state_model:
        lines += ["## State Management Model", ""]
        lines += [f"- **Source**: {state_model.get('source', '(unspecified)')}"]
        lines += [f"- **Target**: {state_model.get('target', '(unspecified)')}"]
        if state_model.get("evidence"):
            lines += [f"- **Evidence**: `{state_model['evidence']}`"]
        lines += [""]

    if routing_model:
        lines += ["## Routing Model", ""]
        lines += [f"- **Source**: {routing_model.get('source', '(unspecified)')}"]
        lines += [f"- **Target**: {routing_model.get('target', '(unspecified)')}"]
        if routing_model.get("evidence"):
            lines += [f"- **Evidence**: `{routing_model['evidence']}`"]
        lines += [""]

    if dep_path:
        lines += ["## Dependency Upgrade Path", ""]
        lines += ["| Dependency | Decision | Evidence |",
                  "|------------|----------|----------|"]
        for d in dep_path:
            lines += [f"| {d['dependency']} | {d['decision']} | `{d['evidence']}` |"]
        lines += [""]

    if decisions:
        lines += ["## Architectural Decisions (verbatim from ADR)", ""]
        for d in decisions:
            lines += [f"- {d}"]
        lines += [""]

    lines += ["## Reviewer Checklist", ""]
    lines += [
        "Before executing this migration plan, a human reviewer must:",
        "",
        "- [ ] Confirm the Migration Order reflects actual dependencies "
        "(compilation / runtime). Leaf-first or topological sort preferred.",
        "- [ ] Review each API Contract (if present) against customer "
        "documentation; any breaking change surfaces here.",
        "- [ ] Sign off on State Management and Routing Model decisions.",
        "- [ ] Verify each dependency decision (upgrade / replace / remove) "
        "with the security + compliance team.",
        "- [ ] Assign effort estimates and target milestones per module.",
        "",
    ]

    lines += ["## Source-of-Truth Links", ""]
    lines += [f"- Full ADR: [`{adr_path.name}`]({adr_path.as_posix()})"]
    lines += [f"- Transition: `{pair}`"]
    lines += [""]

    return "\n".join(lines)


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
    use_domain = not args.plain

    adr_dir = Path(args.adr_dir).resolve()
    root_adr_path = adr_dir / "adr-root.md"
    plan_path = Path(args.output).resolve()

    # --- Dry-run short-circuit ------------------------------------------------
    if args.dry_run:
        print(style.bold(f"kaizen migrate-plan --dry-run  {repo}  ({pair})"))
        print()
        print(f"  source language : {source_lang}")
        print(f"  target language : {target_lang}")
        print(f"  glob            : {glob_pat}")
        print()
        step_num = 1
        dom_flag = "--domain framework-migration" if use_domain else "(--plain; no domain)"
        print(f"  [{step_num}] {style.bold('Decompose')}")
        print(f"      python {_DECOMPOSE_SCRIPT.as_posix()} \\")
        print(f"        --input {repo} --glob '{glob_pat}' \\")
        print(f"        --source-language {source_lang} {dom_flag} \\")
        print(f"        --provider {args.provider} --output {root_adr_path}")
        step_num += 1
        print()
        print(f"  [{step_num}] {style.bold('Render migration plan')}")
        print(f"      (internal) parse ADR, render plan markdown to {plan_path}")
        step_num += 1
        print()
        print(f"  [{step_num}] {style.bold('Per-module ADR stubs')}")
        print(f"      (internal) one ADR stub per Key Identifier file under {adr_dir}/")
        step_num += 1
        if args.recompose:
            print()
            print(f"  [{step_num}] {style.bold('Recompose (optional)')}")
            print(f"      python {_RECOMPOSE_SCRIPT.as_posix()} \\")
            print(f"        --adr {root_adr_path} --target-language {target_lang} \\")
            print(f"        --cross-language --domain framework-migration \\")
            print(f"        --provider {args.provider} --output-dir {args.target_output}")
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
        "--adr-id", f"ADR-{repo.name}-migrate-{pair.replace('->', '-to-')}",
        "--glob", glob_pat,
        "--source-language", source_lang,
        "--provider", args.provider,
    ]
    if use_domain:
        cmd += ["--domain", "framework-migration"]
    if args.model:
        cmd += ["--model", args.model]
    rc = subprocess.run(cmd, env=_build_subprocess_env()).returncode
    if rc != 0:
        output.error(style, f"decompose failed with exit code {rc}")
        return rc
    if not root_adr_path.exists():
        output.error(style, f"decompose did not produce the expected ADR at {root_adr_path}")
        return 3

    # --- Step 2: Parse ADR and render migration plan -------------------------
    print(style.bold("[2/3] Render migration plan"), flush=True)
    adr_md = root_adr_path.read_text(encoding="utf-8")
    decisions = _extract_decisions(adr_md)
    key_ids = _extract_key_identifiers(adr_md)
    api_contracts = _extract_api_contracts(adr_md) if use_domain else []
    state_model = _extract_state_model(adr_md) if use_domain else {}
    routing_model = _extract_routing_model(adr_md) if use_domain else {}
    dep_path = _extract_dependency_upgrade_path(adr_md) if use_domain else []

    plan_md = _render_migration_plan(
        repo_path=repo, adr_path=root_adr_path, pair=pair,
        source_lang=source_lang, target_lang=target_lang,
        decisions=decisions, key_ids=key_ids,
        api_contracts=api_contracts, state_model=state_model,
        routing_model=routing_model, dep_path=dep_path,
        used_domain=use_domain,
    )
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(plan_md, encoding="utf-8")
    print(f"       wrote {plan_path}  "
          f"({len(key_ids)} identifiers, {len(decisions)} decisions, "
          f"{len(api_contracts)} api contracts, {len(dep_path)} dep decisions)")

    # --- Step 3: Per-module ADR stubs ----------------------------------------
    print(style.bold("[3/3] Per-module ADR stubs"), flush=True)
    stub_count = _write_per_module_adr_stubs(adr_dir, key_ids, root_adr_path)
    print(f"       wrote {stub_count} module stub(s) under {adr_dir}/")

    # --- Optional: Recompose --------------------------------------------------
    if args.recompose:
        print(style.bold("[4/4] Recompose"), flush=True)
        target_dir = Path(args.target_output).resolve()
        rcmd = [
            sys.executable, str(_RECOMPOSE_SCRIPT),
            "--adr", str(root_adr_path),
            "--output-dir", str(target_dir),
            "--target-language", target_lang,
            "--cross-language",
            "--provider", args.provider,
            "--max-tokens", "16000",
        ]
        if use_domain:
            rcmd += ["--domain", "framework-migration"]
        if args.model:
            rcmd += ["--model", args.model]
        rc = subprocess.run(rcmd, env=_build_subprocess_env()).returncode
        if rc != 0:
            output.warn(style, f"recompose exited {rc}; plan + ADRs already written")
        else:
            print(f"       wrote target code under {target_dir}/")

    if args.format == "json":
        print(json.dumps({
            "ok": True,
            "repo": str(repo),
            "pair": pair,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "plan": str(plan_path),
            "adr_root": str(root_adr_path),
            "adr_stubs": stub_count,
            "identifiers": len(key_ids),
            "decisions": len(decisions),
            "api_contracts": len(api_contracts),
            "dep_decisions": len(dep_path),
            "used_domain_schema": use_domain,
        }, indent=2))
    else:
        print()
        print(style.bold("Done."))
        print(f"  Plan:      {plan_path}")
        print(f"  Root ADR:  {root_adr_path}")
        print(f"  Stubs:     {adr_dir}/ ({stub_count} file(s))")
        print(style.dim("  Review: see the 'Reviewer Checklist' section in the plan."))

    return 0
