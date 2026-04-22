# SPDX-License-Identifier: Apache-2.0
"""`kaizen decompose` — Source → ADR.

Thin wrapper over `cli.pipeline.decompose_v2`. Exposes the same pipeline the
wedge commands (`memsafe-roadmap`, `migrate-plan`) use internally, so a CLI
user can run the decompose step in isolation — useful for iterating on ADR
schema choices before layering a wedge on top.

The web UI's POST /api/decompose route calls into this same command (not the
decompose_v2 script directly), so CLI and web behavior stay in lockstep.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import config as _cfg
from .. import events, output
from ..output import Style

# Keep these in sync with cli/pipeline/decompose_v2.py argparse choices.
_SUPPORTED_PROVIDERS = ("anthropic", "openai")
_SUPPORTED_DOMAINS = ("none", "memory-safe", "framework-migration")

_CLI_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_DECOMPOSE_SCRIPT = _CLI_PACKAGE_ROOT / "pipeline" / "decompose_v2.py"


def _build_subprocess_env():
    """Load .env from cwd (preferred) or the dev-checkout root. Same shape as
    the wedge commands — keeps ANTHROPIC_API_KEY etc. available without
    requiring the caller to pre-export them."""
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


def add_decompose_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "decompose",
        help="Run the symmetric decompose step directly (Source -> ADR)",
        description=(
            "Run `cli.pipeline.decompose_v2` directly on a repo and emit an ADR "
            "markdown file. The wedge commands (`memsafe-roadmap`, `migrate-plan`) "
            "invoke this same pipeline as their first step; use `kaizen decompose` "
            "when you want the raw ADR without wedge-specific post-processing."
        ),
    )
    p.add_argument("repo", metavar="REPO",
                   help="Path to the source repo to decompose")
    p.add_argument("--output", "-o", metavar="PATH", default="adr-root.md",
                   help="Output path for the ADR markdown (default: adr-root.md)")
    p.add_argument("--adr-id", metavar="ID", default=None,
                   help="ADR identifier string (default: derived from repo dir name)")
    p.add_argument("--glob", default="*",
                   help="Source file glob (default: '*' — all files)")
    p.add_argument("--source-language", metavar="LANG", default="Python",
                   help="Source language label (informs the prompt). Examples: "
                        "Python, C, C++, JavaScript, TypeScript, Java, C#, Go, Rust.")
    p.add_argument("--domain", choices=_SUPPORTED_DOMAINS, default="none",
                   help="Wedge schema preset. 'memory-safe' for C/C++ to Rust, "
                        "'framework-migration' for framework transitions, 'none' "
                        "for generic decompose (default).")
    p.add_argument("--provider", default="anthropic", choices=_SUPPORTED_PROVIDERS,
                   help="LLM provider (default: anthropic)")
    p.add_argument("--model", default=None,
                   help="Override provider default model")
    p.add_argument("--llm-review", action="store_true",
                   help="Run adversarial LLM review of the ADR after decompose (ADR-0009).")
    p.add_argument("--review-model", default=None, metavar="MODEL",
                   help="Explicit review model override (only used with --llm-review).")
    p.add_argument("--temperature", type=float, default=0.0,
                   help="LLM sampling temperature (default: 0.0)")
    p.add_argument("--no-signatures", action="store_true",
                   help="Strip 'signature' and 'attributes' fields from Key Identifiers")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the resolved command and exit without invoking the pipeline")
    p.add_argument("--format", choices=["human", "json"], default="human",
                   help="Output format (default: human)")
    return p


def decompose_command(args: argparse.Namespace) -> int:
    _cfg.apply_defaults(args)
    style: Style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    repo = Path(args.repo).resolve()

    if not repo.exists() or not repo.is_dir():
        output.error(style, f"repo path does not exist or is not a directory: {repo}")
        return 2

    adr_id = args.adr_id or f"ADR-{repo.name}-decomposed"
    output_path = Path(args.output).resolve()

    # --- Dry run ---
    if args.dry_run:
        cmd = [
            sys.executable, str(_DECOMPOSE_SCRIPT),
            "--input", str(repo),
            "--output", str(output_path),
            "--adr-id", adr_id,
            "--glob", args.glob,
            "--source-language", args.source_language,
            "--provider", args.provider,
            "--temperature", str(args.temperature),
            "--domain", args.domain,
        ]
        if args.model:
            cmd += ["--model", args.model]
        if args.no_signatures:
            cmd += ["--no-signatures"]
        print(style.bold("kaizen decompose --dry-run"))
        print()
        print("  " + " \\\n    ".join(cmd))
        print()
        print(style.dim("no pipeline invoked; exit 0"))
        return 0

    # --- Real run ---
    events.run_start(
        command="decompose",
        repo=str(repo),
        output=str(output_path),
        adr_id=adr_id,
        source_language=args.source_language,
        domain=args.domain,
        provider=args.provider,
        model=args.model,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_stages = 2 if args.llm_review else 1
    events.stage("decompose", index=1, total=total_stages, domain=args.domain)

    cmd = [
        sys.executable, str(_DECOMPOSE_SCRIPT),
        "--input", str(repo),
        "--output", str(output_path),
        "--adr-id", adr_id,
        "--glob", args.glob,
        "--source-language", args.source_language,
        "--provider", args.provider,
        "--temperature", str(args.temperature),
        "--domain", args.domain,
    ]
    if args.model:
        cmd += ["--model", args.model]
    if args.no_signatures:
        cmd += ["--no-signatures"]

    rc = events.run_subprocess_with_logs(cmd, env=_build_subprocess_env(), source="decompose")
    if rc != 0:
        events.error(f"decompose failed with exit code {rc}")
        output.error(style, f"decompose failed with exit code {rc}")
        events.result(rc)
        return rc
    if not output_path.exists():
        events.error(f"decompose did not produce the expected ADR at {output_path}")
        output.error(style, f"decompose did not produce the expected ADR at {output_path}")
        events.result(3)
        return 3

    events.stage_done("decompose", adr_path=str(output_path), adr_id=adr_id)

    # --- Optional: LLM Review (ADR-0009 anti-vibe-coding guardrail) ---------
    review_result: dict | None = None
    if args.llm_review:
        from .. import review as _review
        events.stage("llm_review", index=2, total=total_stages,
                     model=_review._pick_review_model(args.model, args.provider,
                                                      getattr(args, "review_model", None)))
        review_result = _review.run_llm_review(
            output_path,
            provider=args.provider,
            model=args.model,
            review_model=getattr(args, "review_model", None),
            source_dir=repo,
        )
        events.stage_done(
            "llm_review",
            review_path=review_result.get("review_path"),
            findings_count=review_result.get("findings_count"),
            critical_findings=review_result.get("critical_findings"),
        )
        if review_result["exit_code"] != 0:
            events.warn(f"llm-review exited {review_result['exit_code']}; ADR already written")

    size_bytes = output_path.stat().st_size
    events.result(
        0,
        adr_path=str(output_path),
        adr_id=adr_id,
        size_bytes=size_bytes,
        source_language=args.source_language,
        domain=args.domain,
        review_findings=review_result if review_result else None,
    )

    if events.get_mode() != "ndjson":
        if args.format == "json":
            import json
            print(json.dumps({
                "ok": True,
                "adr_path": str(output_path),
                "adr_id": adr_id,
                "size_bytes": size_bytes,
                "domain": args.domain,
            }, indent=2))
        else:
            print()
            print(style.bold("Done."))
            print(f"  ADR:       {output_path}")
            print(f"  ADR id:    {adr_id}")
            print(f"  Size:      {size_bytes:,} bytes")

    return 0
