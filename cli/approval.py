# SPDX-License-Identifier: Apache-2.0
"""User approval prompt for interactive CLI checkpoints.

Provides a single interactive approval function for commands that have optional
stages (e.g., recompose after generating a roadmap/plan). Handles non-TTY
environments (CI, piped input) gracefully.
"""

from __future__ import annotations

import sys


def is_tty() -> bool:
    """Return True if stdin is connected to a terminal (interactive session).

    Wrapped in try/except for odd environments (e.g., some test harnesses).
    """
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def approval_prompt(
    message: str,
    *,
    yolo: bool = False,
    default: bool = False,
) -> bool:
    """Prompt the user for approval, with graceful fallbacks for non-TTY.

    Args:
        message: The prompt message to display (e.g. "Continue to recompose?").
        yolo: If True, return True immediately without prompting (opt-out mode).
        default: The return value if stdin is not a TTY or user hits enter.

    Returns:
        True if user approves (or yolo=True), False otherwise.

    Behavior:
        - If yolo=True: return True immediately (no prompt).
        - If stdin is not a TTY: log "(non-interactive; skipping prompt, proceeding=<default>)"
          to stderr and return `default`.
        - Otherwise: print message + prompt to stderr, read a line from stdin.
          - "y" or "yes" (case-insensitive) -> True
          - Empty line -> `default`
          - Anything else -> False
          - Ctrl-C (KeyboardInterrupt) -> print "aborted" and return False.
    """
    if yolo:
        return True

    if not is_tty():
        sys.stderr.write(f"(non-interactive; skipping prompt, proceeding={default})\n")
        return default

    try:
        prompt_suffix = " [Y/n] " if default else " [y/N] "
        sys.stderr.write(message + prompt_suffix)
        sys.stderr.flush()

        line = sys.stdin.readline().strip().lower()

        if not line:
            return default
        if line in ("y", "yes"):
            return True
        return False
    except KeyboardInterrupt:
        sys.stderr.write("\naborted\n")
        return False
