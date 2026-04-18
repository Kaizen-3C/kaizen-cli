# SPDX-License-Identifier: Apache-2.0
"""Formatting helpers for the kaizen CLI.

Stdlib-only. ANSI color is emitted ONLY when stdout is a TTY and --no-color
is not set. All error output is routed to stderr.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Iterable, Optional


# ── ANSI escape codes ────────────────────────────────────────────────────────
# Kept as plain constants so we can concatenate conditionally.
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GREY = "\033[90m"


class Style:
    """Tiny style helper that obeys --no-color and TTY detection."""

    def __init__(self, use_color: Optional[bool] = None) -> None:
        if use_color is None:
            use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        self.use_color = bool(use_color)

    def _wrap(self, code: str, text: str) -> str:
        if not self.use_color:
            return text
        return f"{code}{text}{RESET}"

    def bold(self, text: str) -> str:
        return self._wrap(BOLD, text)

    def dim(self, text: str) -> str:
        return self._wrap(DIM, text)

    def red(self, text: str) -> str:
        return self._wrap(RED, text)

    def green(self, text: str) -> str:
        return self._wrap(GREEN, text)

    def yellow(self, text: str) -> str:
        return self._wrap(YELLOW, text)

    def blue(self, text: str) -> str:
        return self._wrap(BLUE, text)

    def cyan(self, text: str) -> str:
        return self._wrap(CYAN, text)

    def magenta(self, text: str) -> str:
        return self._wrap(MAGENTA, text)

    def grey(self, text: str) -> str:
        return self._wrap(GREY, text)


# ── Band / decision coloring ─────────────────────────────────────────────────

def confidence_band(c: float) -> str:
    """Map a composite confidence score to a human-readable band."""
    if c >= 0.90:
        return "VERY HIGH"
    if c >= 0.75:
        return "HIGH"
    if c >= 0.55:
        return "MEDIUM"
    if c >= 0.30:
        return "LOW"
    return "VERY LOW"


def style_decision(style: Style, decision: str) -> str:
    d = (decision or "").upper()
    if d == "CONVERGED":
        return style.green(d)
    if d == "CONTINUE":
        return style.cyan(d)
    if d == "ABORT":
        return style.red(d)
    return style.yellow(d or "UNKNOWN")


def style_band(style: Style, band: str) -> str:
    if band in ("VERY HIGH", "HIGH"):
        return style.green(band)
    if band == "MEDIUM":
        return style.yellow(band)
    return style.red(band)


# ── Stream helpers ───────────────────────────────────────────────────────────

def eprint(msg: str) -> None:
    """Print to stderr."""
    print(msg, file=sys.stderr)


def warn(style: Style, msg: str) -> None:
    eprint(f"{style.yellow('warning:')} {msg}")


def error(style: Style, msg: str) -> None:
    eprint(f"{style.red('error:')} {msg}")


# ── Step / result formatting ─────────────────────────────────────────────────

def format_step_human(style: Style, step: Any) -> str:
    """Format a DenoisingStepResult for human display.

    Uses getattr everywhere so we don't crash if the orchestrator record
    shape changes (e.g. the parallel agent adding a diff: str field).
    """
    step_num = getattr(step, "step", "?")
    c = float(getattr(step, "composite_confidence", 0.0) or 0.0)
    delta = float(getattr(step, "confidence_delta", 0.0) or 0.0)
    decision = getattr(step, "convergence_recommendation", "UNKNOWN")
    build = getattr(step, "build_success", False)
    tests = float(getattr(step, "test_pass_rate", 0.0) or 0.0)
    critical = getattr(step, "has_critical_findings", False)
    files = list(getattr(step, "files_generated", []) or [])
    band = confidence_band(c)

    reason = _one_line_reason(build, tests, critical, delta)

    lines = []
    header = (
        f"{style.bold(f'Step {step_num}')}  "
        f"C={style.bold(f'{c:.3f}')} [{style_band(style, band)}]  "
        f"gate={style_decision(style, decision)}"
    )
    lines.append(header)
    lines.append(f"  {style.dim('reason:')} {reason}")
    if files:
        lines.append(f"  {style.dim('files :')} {', '.join(files)}")

    # Guarded diff rendering — the parallel agent is adding this field.
    diff = getattr(step, "diff", None)
    if isinstance(diff, str) and diff.strip():
        lines.append(f"  {style.dim('diff  :')}")
        for dl in diff.splitlines():
            if dl.startswith("+") and not dl.startswith("+++"):
                lines.append("    " + style.green(dl))
            elif dl.startswith("-") and not dl.startswith("---"):
                lines.append("    " + style.red(dl))
            elif dl.startswith("@@"):
                lines.append("    " + style.cyan(dl))
            else:
                lines.append("    " + dl)
    return "\n".join(lines)


def _one_line_reason(build: bool, tests: float, critical: bool, delta: float) -> str:
    parts = []
    parts.append("build PASS" if build else "build FAIL")
    parts.append(f"tests {tests:.0%}")
    if critical:
        parts.append("critical findings")
    parts.append(f"delta {delta:+.3f}")
    return ", ".join(parts)


def format_final_human(style: Style, result: Any) -> str:
    adr_id = getattr(result, "adr_id", "?")
    converged = bool(getattr(result, "converged", False))
    final_c = float(getattr(result, "final_confidence", 0.0) or 0.0)
    steps = int(getattr(result, "steps_taken", 0) or 0)
    duration = float(getattr(result, "total_duration_secs", 0.0) or 0.0)
    cost = float(getattr(result, "total_cost_usd", 0.0) or 0.0)
    band = confidence_band(final_c)

    files: set = set()
    for sr in getattr(result, "step_results", []) or []:
        for f in getattr(sr, "files_generated", []) or []:
            files.add(f)

    head = style.bold(f"FINAL — {adr_id}")
    status = style.green("CONVERGED") if converged else style.yellow("NOT CONVERGED")
    lines = [
        "=" * 60,
        head,
        "=" * 60,
        f"  status       : {status}",
        f"  total steps  : {steps}",
        f"  final C      : {final_c:.3f}  [{style_band(style, band)}]",
        f"  duration     : {duration:.1f}s",
        f"  cost (USD)   : ${cost:.4f}",
        f"  files        : {len(files)}",
    ]
    for f in sorted(files):
        lines.append(f"    - {f}")
    lines.append("=" * 60)
    return "\n".join(lines)


def format_final_json(result: Any) -> str:
    """Render a BootstrapResult as a JSON string."""
    import json

    step_records = []
    for sr in getattr(result, "step_results", []) or []:
        rec: Dict[str, Any] = {
            "step": getattr(sr, "step", None),
            "composite_confidence": getattr(sr, "composite_confidence", None),
            "confidence_delta": getattr(sr, "confidence_delta", None),
            "convergence_recommendation": getattr(sr, "convergence_recommendation", None),
            "has_critical_findings": getattr(sr, "has_critical_findings", None),
            "build_success": getattr(sr, "build_success", None),
            "test_pass_rate": getattr(sr, "test_pass_rate", None),
            "files_generated": list(getattr(sr, "files_generated", []) or []),
        }
        diff = getattr(sr, "diff", None)
        if isinstance(diff, str):
            rec["diff"] = diff
        step_records.append(rec)

    payload = {
        "adr_id": getattr(result, "adr_id", None),
        "converged": getattr(result, "converged", None),
        "final_confidence": getattr(result, "final_confidence", None),
        "steps_taken": getattr(result, "steps_taken", None),
        "total_duration_secs": getattr(result, "total_duration_secs", None),
        "total_cost_usd": getattr(result, "total_cost_usd", None),
        "total_input_tokens": getattr(result, "total_input_tokens", None),
        "total_output_tokens": getattr(result, "total_output_tokens", None),
        "step_results": step_records,
    }
    return json.dumps(payload, indent=2, default=str)
