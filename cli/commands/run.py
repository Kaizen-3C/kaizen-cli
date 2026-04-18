# SPDX-License-Identifier: Apache-2.0
"""`kaizen run` — wire the CLI to the bootstrap orchestrator.

Two modes:
  - --target-adr ADR-XXXX  (ADR-driven; mirrors bootstrap_runner)
  - --task "free text"     (wraps the task in a synthetic ADR on disk)

Provider handling matches bootstrap_runner for anthropic / openai / ollama /
litellm / mixed. We deliberately only touch the public orchestrator API; the
parallel agent is modifying step records (adding `diff: str`) so we never
reach into orchestrator internals.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from pathlib import Path
from typing import Any, List, Optional

from .. import output
from ..output import Style, confidence_band


# ── Argument wiring ──────────────────────────────────────────────────────────

def add_run_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "run",
        help="Run the Kaizen bootstrap orchestrator on a workspace",
        description=(
            "Run the Kaizen bootstrap orchestrator on a workspace. "
            "Accepts either an ADR id (--target-adr) or free-text (--task)."
        ),
    )

    spec = p.add_mutually_exclusive_group(required=False)
    spec.add_argument("--target-adr", metavar="ID",
                      help="ADR ID to target (e.g. ADR-0008)")
    spec.add_argument("--task", metavar="TEXT",
                      help='Free-text task; wrapped in a synthetic ADR on disk')

    p.add_argument("--workspace", metavar="PATH", default=".",
                   help="Path to the workspace directory (default: .)")
    p.add_argument("--adr-dir", metavar="PATH", default=None,
                   help="ADR directory (default: <workspace>/.architecture/decisions)")

    p.add_argument("--max-steps", metavar="N", type=int, default=5,
                   help="Maximum orchestrator steps (default: 5)")
    p.add_argument("--theta", metavar="F", type=float, default=0.70,
                   help="Convergence confidence threshold (default: 0.70)")
    p.add_argument("--epsilon", metavar="F", type=float, default=0.05,
                   help="Convergence delta threshold (default: 0.05)")

    conv = p.add_mutually_exclusive_group()
    conv.add_argument("--adaptive-convergence", dest="adaptive_convergence",
                      action="store_true", default=True,
                      help="Enable Thompson-sampling adaptive convergence (default)")
    conv.add_argument("--no-adaptive-convergence", dest="adaptive_convergence",
                      action="store_false",
                      help="Disable adaptive convergence (static thresholds)")
    p.add_argument("--priors-file", metavar="PATH", default=None,
                   help="Thompson priors JSON (loaded at start, saved at end)")

    # Provider flags — mirror bootstrap_runner
    p.add_argument("--provider", default="anthropic",
                   choices=["anthropic", "openai", "ollama", "litellm", "mixed"],
                   help="LLM provider (default: anthropic)")
    p.add_argument("--api-key", default=None,
                   help="API key (or set ANTHROPIC_API_KEY / OPENAI_API_KEY)")
    p.add_argument("--ollama-host", default="127.0.0.1",
                   help="Ollama host (default: 127.0.0.1)")
    p.add_argument("--reasoning-model", default=None,
                   help="Override model for the reasoning tier")
    p.add_argument("--litellm-base-url", default="http://localhost:4000",
                   help="LiteLLM proxy base URL")

    p.add_argument("--dry-run", action="store_true",
                   help="Print resolved plan and exit without running the orchestrator")
    p.add_argument("--format", choices=["human", "json"], default="human",
                   help="Output format (default: human)")
    p.add_argument("--interactive", action="store_true", default=False,
                   help=(
                       "Pause after each denoising step and prompt the user to "
                       "continue, accept early convergence, reject and retry, or abort. "
                       "Forces --format human."
                   ))

    return p


# ── Helpers ──────────────────────────────────────────────────────────────────

_SYNTHETIC_ADR_TEMPLATE = """# ADR-9999: {title}

## Status
Proposed (synthetic — generated from `kaizen run --task`)

## Context
The user invoked `kaizen run --task` with a free-text description. This ADR
wraps that description so it can be fed through the standard TAOR pipeline.

## Decision
{task_text}

## Consequences
- Treated as a one-shot task; will be removed from the ADR dir after the run
  unless the user keeps the file manually.
"""


def _synth_adr(workspace: Path, adr_dir: Path, task_text: str) -> str:
    """Write a synthetic ADR to disk and return its id."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    adr_id = "ADR-9999"
    # Title = first 60 chars of task text, cleaned up
    title = task_text.strip().splitlines()[0][:60] or "synthetic task"
    path = adr_dir / f"{adr_id.lower()}-synthetic-task.md"
    path.write_text(
        _SYNTHETIC_ADR_TEMPLATE.format(title=title, task_text=task_text),
        encoding="utf-8",
    )
    return adr_id


def _resolve_api_key(args: argparse.Namespace) -> str:
    return (
        args.api_key
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )


def _validate_credentials(args: argparse.Namespace) -> None:
    """Check credentials BEFORE importing heavy modules. Raises ValueError."""
    api_key = _resolve_api_key(args)
    if args.provider == "anthropic" and not api_key:
        raise ValueError(
            "Anthropic provider requires an API key. "
            "Set ANTHROPIC_API_KEY or pass --api-key."
        )
    if args.provider == "openai" and not api_key:
        raise ValueError(
            "OpenAI provider requires an API key. "
            "Set OPENAI_API_KEY or pass --api-key."
        )
    if args.provider == "mixed" and not api_key:
        raise ValueError(
            "Mixed provider requires an API key for the reasoning tier. "
            "Set ANTHROPIC_API_KEY or pass --api-key."
        )


def _build_endpoints(args: argparse.Namespace, style: Style):
    """Build (speed, balanced, reasoning) for the requested provider.

    Mirrors bootstrap_runner.main's provider switch. Assumes credentials have
    already been validated via `_validate_credentials`.
    """
    # Late import so `--help` and `--dry-run` never pay the cost.
    from agents.src.bootstrap_orchestrator import OllamaEndpoint, ProviderEndpoint

    api_key = _resolve_api_key(args)
    prov = args.provider

    if prov == "ollama":
        speed = OllamaEndpoint(name="speed", host=args.ollama_host, port=11436,
                               model="qwen2.5-coder:7b", timeout=60.0)
        balanced = OllamaEndpoint(name="balanced", host=args.ollama_host, port=11435,
                                  model="qwen2.5-coder:14b", timeout=90.0)
        reasoning = OllamaEndpoint(name="reasoning", host=args.ollama_host, port=11434,
                                   model=args.reasoning_model or "qwen3-coder:30b",
                                   timeout=180.0)
    elif prov == "anthropic":
        if not api_key:
            raise ValueError(
                "Anthropic provider requires an API key. "
                "Set ANTHROPIC_API_KEY or pass --api-key."
            )
        speed = ProviderEndpoint(name="speed", provider="anthropic", api_key=api_key,
                                 model="claude-haiku-4-5-20251001", timeout=60.0)
        balanced = ProviderEndpoint(name="balanced", provider="anthropic", api_key=api_key,
                                    model="claude-sonnet-4-6", timeout=120.0)
        reasoning = ProviderEndpoint(name="reasoning", provider="anthropic", api_key=api_key,
                                     model=args.reasoning_model or "claude-sonnet-4-6",
                                     timeout=180.0)
    elif prov == "openai":
        if not api_key:
            raise ValueError(
                "OpenAI provider requires an API key. "
                "Set OPENAI_API_KEY or pass --api-key."
            )
        speed = ProviderEndpoint(name="speed", provider="openai", api_key=api_key,
                                 model="gpt-4o-mini", timeout=60.0)
        balanced = ProviderEndpoint(name="balanced", provider="openai", api_key=api_key,
                                    model="gpt-4o", timeout=120.0)
        reasoning = ProviderEndpoint(name="reasoning", provider="openai", api_key=api_key,
                                     model=args.reasoning_model or "gpt-4o", timeout=180.0)
    elif prov == "litellm":
        base = args.litellm_base_url
        speed = ProviderEndpoint(name="speed", provider="litellm", base_url=base,
                                 model="claude-haiku-4-5-20251001", timeout=60.0)
        balanced = ProviderEndpoint(name="balanced", provider="litellm", base_url=base,
                                    model="claude-sonnet-4-6", timeout=120.0)
        reasoning = ProviderEndpoint(name="reasoning", provider="litellm", base_url=base,
                                     model=args.reasoning_model or "claude-sonnet-4-6",
                                     timeout=180.0)
    elif prov == "mixed":
        if not api_key:
            raise ValueError(
                "Mixed provider requires an API key for the reasoning tier. "
                "Set ANTHROPIC_API_KEY or pass --api-key."
            )
        speed = OllamaEndpoint(name="speed", host=args.ollama_host, port=11436,
                               model="qwen2.5-coder:7b", timeout=60.0)
        balanced = OllamaEndpoint(name="balanced", host=args.ollama_host, port=11435,
                                  model="qwen2.5-coder:14b", timeout=90.0)
        reasoning = ProviderEndpoint(name="reasoning", provider="anthropic", api_key=api_key,
                                     model=args.reasoning_model or "claude-sonnet-4-6",
                                     timeout=180.0)
    else:
        raise ValueError(f"Unknown provider: {prov}")

    return speed, balanced, reasoning


# ── Dry-run plan printer ─────────────────────────────────────────────────────

def _print_dry_run(style: Style, args: argparse.Namespace,
                   workspace: Path, adr_dir: Path, adr_id: Optional[str]) -> None:
    print(style.bold("kaizen run --dry-run"))
    print(f"  workspace            : {workspace}")
    print(f"  adr-dir              : {adr_dir}")
    if adr_id:
        print(f"  target ADR           : {adr_id}")
    if args.task:
        print(f"  task (free-text)     : {args.task!r}")
        print(f"  would wrap as        : ADR-9999 synthetic ADR")
    print(f"  max-steps            : {args.max_steps}")
    print(f"  theta / epsilon      : {args.theta} / {args.epsilon}")
    print(f"  adaptive-convergence : {args.adaptive_convergence}")
    print(f"  priors-file          : {args.priors_file or '(none)'}")
    print(f"  provider             : {args.provider}")
    if args.provider in ("anthropic", "openai", "mixed"):
        have = bool(_resolve_api_key(args))
        print(f"  api-key resolved     : {'yes' if have else 'no (will error at runtime)'}")
    if args.provider in ("ollama", "mixed"):
        print(f"  ollama-host          : {args.ollama_host}")
    if args.reasoning_model:
        print(f"  reasoning-model      : {args.reasoning_model}")
    print(f"  output format        : {args.format}")
    print(f"  interactive          : {getattr(args, 'interactive', False)}")
    print()
    print(style.dim("no orchestrator invoked; exit 0"))


# ── Interactive step callback ─────────────────────────────────────────────────

def _build_interactive_callback(style: Style, cost_tracker_ref: List[Any]):
    """Build and return an ``on_step_complete`` callback for interactive mode.

    The callback:
    - Prints step number, composite confidence + band, gate decision, diff summary.
    - Prompts the user with a menu and reads from stdin via ``input()``.
    - Re-prompts on invalid input.
    - Returns a ``StepAction``.

    ``cost_tracker_ref`` is a single-element list that will be populated with
    the orchestrator's ``cost_tracker`` after construction; the callback closes
    over the list so it can display up-to-date token cost.
    """
    # Late import — avoids paying cost on --help / --dry-run.
    def callback(step_result: Any) -> Any:
        from agents.src.bootstrap_orchestrator import StepAction

        c = float(getattr(step_result, "composite_confidence", 0.0) or 0.0)
        delta = float(getattr(step_result, "confidence_delta", 0.0) or 0.0)
        step_num = getattr(step_result, "step", "?")
        gate = getattr(step_result, "convergence_recommendation", "UNKNOWN")
        build = getattr(step_result, "build_success", False)
        tests = float(getattr(step_result, "test_pass_rate", 0.0) or 0.0)
        files = list(getattr(step_result, "files_generated", []) or [])
        diff: str = getattr(step_result, "diff", "") or ""
        band = confidence_band(c)

        # Cost info — best-effort
        cost_usd = 0.0
        in_tok = 0
        out_tok = 0
        if cost_tracker_ref and cost_tracker_ref[0] is not None:
            try:
                summary = cost_tracker_ref[0].get_summary()
                cost_usd = float(summary.get("total_cost_usd", 0.0))
                in_tok = int(summary.get("total_input_tokens", 0))
                out_tok = int(summary.get("total_output_tokens", 0))
            except Exception:
                pass

        # Diff summary: count added/removed lines
        added = sum(1 for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))
        diff_summary = f"+{added}/-{removed} lines across {len(files)} file(s)" if diff else "(no file changes)"

        sep = "─" * 60
        print()
        print(sep)
        print(style.bold(f"  Interactive pause — Step {step_num}"))
        print(sep)
        print(f"  Confidence (C)   : {style.bold(f'{c:.3f}')} [{band}]  delta={delta:+.3f}")
        print(f"  Gate decision    : {output.style_decision(style, gate)}")
        print(f"  Build / Tests    : {'PASS' if build else 'FAIL'} / {tests:.0%}")
        print(f"  Diff summary     : {diff_summary}")
        print(f"  Cost so far      : ${cost_usd:.4f}  ({in_tok} in / {out_tok} out tokens)")
        print()
        print("  [c] continue         — follow gate decision, run next step")
        print("  [a] accept early     — treat this step as final, stop now (converged)")
        print("  [r] reject and retry — discard output, re-run this step")
        print("  [q] quit / abort     — stop without converging")
        print()

        _menu = {"c": StepAction.CONTINUE, "a": StepAction.ACCEPT_EARLY,
                 "r": StepAction.REJECT_RETRY, "q": StepAction.ABORT}

        while True:
            try:
                raw = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return StepAction.ABORT
            if raw in _menu:
                chosen = _menu[raw]
                print(style.dim(f"  → {chosen.value}"))
                return chosen
            print(style.yellow(f"  Invalid choice '{raw}'. Enter c, a, r, or q."))

    return callback


# ── Entrypoint ───────────────────────────────────────────────────────────────

def run_command(args: argparse.Namespace) -> int:
    """Execute `kaizen run`. Returns a process exit code."""
    style: Style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)

    # ── 1. Validate workspace ────────────────────────────────────────────────
    workspace = Path(args.workspace).resolve()
    if not workspace.exists() or not workspace.is_dir():
        output.error(style, f"workspace path does not exist: {workspace}")
        return 2

    # ── 2. Resolve ADR directory ─────────────────────────────────────────────
    adr_dir = Path(args.adr_dir).resolve() if args.adr_dir else workspace / ".architecture" / "decisions"

    # ── 3. Resolve task spec (ADR id vs free-text) ───────────────────────────
    if not args.target_adr and not args.task:
        output.error(style, "must provide either --target-adr or --task")
        return 2

    adr_id = args.target_adr
    synthetic_path: Optional[Path] = None

    # ── 4. Dry run short-circuit (no side effects on disk) ──────────────────
    if args.dry_run:
        preview_adr_id = adr_id or ("ADR-9999" if args.task else None)
        _print_dry_run(style, args, workspace, adr_dir, preview_adr_id)
        return 0

    if args.task:
        adr_dir.mkdir(parents=True, exist_ok=True)
        adr_id = _synth_adr(workspace, adr_dir, args.task)
        synthetic_path = adr_dir / f"{adr_id.lower()}-synthetic-task.md"

    # ── 5. Validate credentials BEFORE heavy imports, then build endpoints ─
    try:
        _validate_credentials(args)
    except ValueError as exc:
        output.error(style, str(exc))
        return 2

    try:
        speed, balanced, reasoning = _build_endpoints(args, style)
    except ValueError as exc:
        output.error(style, str(exc))
        return 2
    except ImportError as exc:
        output.error(style, f"failed to import orchestrator: {exc}")
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            output.eprint(style.dim("  (run with --verbose for stack trace)"))
        return 1

    # Late imports so help / dry-run / missing-ws all skip the dependency cost.
    try:
        from agents.src.adr_task_loader import load_target_adr
        from agents.src.bootstrap_orchestrator import BootstrapOrchestrator
    except Exception as exc:  # pragma: no cover — import wiring
        output.error(style, f"failed to import orchestrator: {exc}")
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            output.eprint(style.dim("  (run with --verbose for stack trace)"))
        return 1

    task = load_target_adr(str(adr_dir), adr_id)
    if task is None:
        output.error(style, f"ADR {adr_id} not found in {adr_dir}")
        return 2

    # ── Interactive mode setup ──────────────────────────────────────────────
    interactive = getattr(args, "interactive", False)
    step_callback = None
    _cost_tracker_ref: List[Any] = [None]  # filled after orchestrator is created

    if interactive:
        if args.format == "json":
            output.warn(style, "--interactive is incompatible with --format json; switching to human format")
            args.format = "human"
        step_callback = _build_interactive_callback(style, _cost_tracker_ref)

    orchestrator = BootstrapOrchestrator(
        speed=speed,
        balanced=balanced,
        reasoning=reasoning,
        workspace_path=str(workspace),
        theta=args.theta,
        epsilon=args.epsilon,
        max_steps=args.max_steps,
        adaptive_convergence=args.adaptive_convergence,
        priors_file=args.priors_file,
        on_step_complete=step_callback,
    )

    # Populate the cost tracker reference so the callback can read live cost.
    if interactive:
        _cost_tracker_ref[0] = orchestrator.cost_tracker

    # ── 6. Invoke the orchestrator ──────────────────────────────────────────
    try:
        result = asyncio.run(orchestrator.run(task))
    except KeyboardInterrupt:
        # Orchestrator owns priors persistence via priors_file; we just announce.
        output.eprint(style.yellow("saved priors, exiting"))
        return 130
    except Exception as exc:
        output.error(style, f"orchestrator raised: {exc.__class__.__name__}: {exc}")
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            output.eprint(style.dim("  (run with --verbose for stack trace)"))
        return 1
    finally:
        # Clean up synthetic ADR file so it does not pollute the ADR dir.
        if synthetic_path and synthetic_path.exists():
            try:
                synthetic_path.unlink()
            except OSError:
                pass

    # ── 7. Render output ────────────────────────────────────────────────────
    if args.format == "json":
        print(output.format_final_json(result))
    else:
        # Per-step stream, then final summary.
        for sr in getattr(result, "step_results", []) or []:
            print(output.format_step_human(style, sr))
            print()
        print(output.format_final_human(style, result))

    converged = bool(getattr(result, "converged", False))
    return 0 if converged else 1
