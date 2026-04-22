# SPDX-License-Identifier: Apache-2.0
"""`kaizen recompose` — ADR -> target code.

Thin wrapper over `cli.pipeline.recompose_v2`. Mirrors `kaizen decompose` in
structure: same event emission, same subprocess pattern, same --dry-run
semantics. The web UI's POST /api/recompose route delegates to this command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import config as _cfg
from .. import events, output
from ..output import Style

_SUPPORTED_PROVIDERS = ("anthropic", "openai")
_SUPPORTED_DOMAINS = ("none", "memory-safe", "framework-migration")

_CLI_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_RECOMPOSE_SCRIPT = _CLI_PACKAGE_ROOT / "pipeline" / "recompose_v2.py"


def _build_subprocess_env():
    """Load .env from cwd or dev-checkout root. Same as decompose/wedge commands."""
    import os
    env = dict(os.environ)
    kaizen_root = _CLI_PACKAGE_ROOT.parent
    for candidate in (Path.cwd() / ".env", kaizen_root / ".env"):
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in env:
                        env[k] = v
                break
            except (OSError, UnicodeDecodeError):
                pass
    return env


def add_recompose_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "recompose",
        help="Recompose an ADR into target code (ADR -> source)",
        description=(
            "Run `cli.pipeline.recompose_v2` on an ADR markdown file and emit "
            "target-language source code. The wedges (`memsafe-roadmap`, "
            "`migrate-plan`) invoke this as their optional final step when "
            "--recompose is passed; use `kaizen recompose` directly when you "
            "already have an ADR and just want to regenerate code from it."
        ),
    )
    p.add_argument("adr", metavar="ADR",
                   help="Path to the ADR markdown file to recompose")
    p.add_argument("--output-dir", "-o", metavar="DIR", default="recomposed",
                   help="Output directory for the recomposed source (default: recomposed/)")
    p.add_argument("--target-language", metavar="LANG", default="Python",
                   help="Target implementation language (default: Python). "
                        "Examples: Python, Rust, C#, TypeScript, Java, Go.")
    p.add_argument("--cross-language", action="store_true",
                   help="Enable cross-language translation mode (accept transliterated identifier names)")
    p.add_argument("--emit-tests", action="store_true",
                   help="Hint the model that tests are welcome alongside the implementation")
    p.add_argument("--max-tokens", type=int, default=8000,
                   help="Max output tokens (default: 8000). Bump for larger sources.")
    p.add_argument("--temperature", type=float, default=0.0,
                   help="LLM sampling temperature (default: 0.0)")
    p.add_argument("--no-repair-syntax", action="store_true",
                   help="Skip the one-shot repair retry when recomposed Python has syntax errors")
    p.add_argument("--target-python-version", default="3.9",
                   help="Target Python version for generated code (default: 3.9). "
                        "Set to 3.10+ to allow PEP 604 union syntax.")
    p.add_argument("--domain", choices=_SUPPORTED_DOMAINS, default="none",
                   help="Wedge schema preset. Should match the --domain used at decompose time.")
    p.add_argument("--provider", default="anthropic", choices=_SUPPORTED_PROVIDERS,
                   help="LLM provider (default: anthropic)")
    p.add_argument("--model", default=None,
                   help="Override provider default model")
    p.add_argument("--llm-review", action="store_true",
                   help="Review the ADR before recomposing (ADR-0009 anti-vibe-coding guardrail).")
    p.add_argument("--review-model", default=None, metavar="MODEL",
                   help="Explicit review model override (only used with --llm-review).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the resolved command and exit without invoking the pipeline")
    p.add_argument("--format", choices=["human", "json"], default="human",
                   help="Output format (default: human)")
    return p


def recompose_command(args: argparse.Namespace) -> int:
    _cfg.apply_defaults(args)
    style: Style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    adr_path = Path(args.adr).resolve()

    if not adr_path.exists() or not adr_path.is_file():
        output.error(style, f"ADR not found at {adr_path}")
        return 2

    output_dir = Path(args.output_dir).resolve()

    # --- Dry run ---
    if args.dry_run:
        cmd = [
            sys.executable, str(_RECOMPOSE_SCRIPT),
            "--adr", str(adr_path),
            "--output-dir", str(output_dir),
            "--target-language", args.target_language,
            "--provider", args.provider,
            "--max-tokens", str(args.max_tokens),
            "--temperature", str(args.temperature),
            "--target-python-version", args.target_python_version,
            "--domain", args.domain,
        ]
        if args.cross_language:
            cmd += ["--cross-language"]
        if args.emit_tests:
            cmd += ["--emit-tests"]
        if args.no_repair_syntax:
            cmd += ["--no-repair-syntax"]
        if args.model:
            cmd += ["--model", args.model]
        print(style.bold("kaizen recompose --dry-run"))
        print()
        print("  " + " \\\n    ".join(cmd))
        print()
        print(style.dim("no pipeline invoked; exit 0"))
        return 0

    # --- Real run ---
    events.run_start(
        command="recompose",
        adr=str(adr_path),
        output_dir=str(output_dir),
        target_language=args.target_language,
        domain=args.domain,
        provider=args.provider,
        model=args.model,
        cross_language=args.cross_language,
        emit_tests=args.emit_tests,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    total_stages = 2 if args.llm_review else 1

    # --- Optional: LLM Review BEFORE recompose (ADR-0009) --------------------
    review_result: dict | None = None
    if args.llm_review:
        from .. import review as _review
        events.stage("llm_review", index=1, total=total_stages,
                     model=_review._pick_review_model(args.model, args.provider,
                                                      getattr(args, "review_model", None)))
        review_result = _review.run_llm_review(
            adr_path,
            provider=args.provider,
            model=args.model,
            review_model=getattr(args, "review_model", None),
        )
        events.stage_done(
            "llm_review",
            review_path=review_result.get("review_path"),
            findings_count=review_result.get("findings_count"),
            critical_findings=review_result.get("critical_findings"),
        )
        if review_result["exit_code"] != 0:
            events.warn(f"llm-review exited {review_result['exit_code']}; continuing to recompose")

    events.stage("recompose", index=total_stages, total=total_stages,
                 target=args.target_language, domain=args.domain)

    cmd = [
        sys.executable, str(_RECOMPOSE_SCRIPT),
        "--adr", str(adr_path),
        "--output-dir", str(output_dir),
        "--target-language", args.target_language,
        "--provider", args.provider,
        "--max-tokens", str(args.max_tokens),
        "--temperature", str(args.temperature),
        "--target-python-version", args.target_python_version,
        "--domain", args.domain,
    ]
    if args.cross_language:
        cmd += ["--cross-language"]
    if args.emit_tests:
        cmd += ["--emit-tests"]
    if args.no_repair_syntax:
        cmd += ["--no-repair-syntax"]
    if args.model:
        cmd += ["--model", args.model]

    rc = events.run_subprocess_with_logs(cmd, env=_build_subprocess_env(), source="recompose")
    if rc != 0:
        events.error(f"recompose failed with exit code {rc}")
        output.error(style, f"recompose failed with exit code {rc}")
        events.result(rc)
        return rc

    # Enumerate produced files for structured event payload.
    produced_files = sorted(str(p) for p in output_dir.rglob("*") if p.is_file())
    events.stage_done("recompose", output_dir=str(output_dir), file_count=len(produced_files))

    events.result(
        0,
        output_dir=str(output_dir),
        target_language=args.target_language,
        domain=args.domain,
        file_count=len(produced_files),
        files=produced_files[:50],  # cap at 50 in the event payload
        review_findings=review_result if review_result else None,
    )

    if events.get_mode() != "ndjson":
        if args.format == "json":
            import json
            print(json.dumps({
                "ok": True,
                "output_dir": str(output_dir),
                "target_language": args.target_language,
                "file_count": len(produced_files),
            }, indent=2))
        else:
            print()
            print(style.bold("Done."))
            print(f"  Target:    {args.target_language}")
            print(f"  Output:    {output_dir}/")
            print(f"  Files:     {len(produced_files)}")

    return 0
