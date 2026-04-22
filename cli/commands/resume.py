# SPDX-License-Identifier: Apache-2.0
"""`kaizen resume` -- re-run recompose from the most recent ADR.

kaizen is single-shot: decompose writes an ADR to disk, the user edits it,
then recompose regenerates code. `kaizen resume` automates the final step:
find the most-recently modified kaizen-produced ADR under a directory and
invoke `recompose_command` on it -- without the user having to remember the
exact path.

Heuristic for "kaizen-produced ADR":
  - adr-root.md
  - adrs/adr-root.md  (matched transitively)
  - roadmap.md
  - plan.md
  - ADR-*.md  (any file whose name matches this glob)
  - adr-*.md  (any file whose name matches this glob)

Standard noisy directories are skipped during the walk (same list as
`cli.commands.status._SKIP_DIRS`).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .. import events, output
from ..output import Style
from .status import _SKIP_DIRS

# Re-import the recompose command we will delegate to.
from .recompose import recompose_command  # noqa: F401 - re-exported for tests

# Filename patterns that identify kaizen-produced ADR markdown files.
_ADR_NAMES = {"adr-root.md", "roadmap.md", "plan.md"}
_ADR_GLOBS = ("ADR-*.md", "adr-*.md")


# ---------------------------------------------------------------------------
# Scan helpers
# ---------------------------------------------------------------------------

def _is_adr_candidate(path: Path) -> bool:
    """Return True if *path* looks like a kaizen-produced ADR markdown file."""
    name = path.name
    if name.lower() in _ADR_NAMES:
        return True
    for pat in _ADR_GLOBS:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def _scan_adrs(root: Path) -> List[Path]:
    """Walk *root* and return all ADR candidate files, skipping noisy dirs."""
    hits: List[Path] = []
    for p in root.rglob("*.md"):
        # Skip anything under a noisy directory.
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if _is_adr_candidate(p):
            hits.append(p)
    return hits


def _sort_by_mtime(files: List[Path]) -> List[Path]:
    """Return *files* sorted by mtime descending (newest first)."""
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _resolve_adr(
    run_id: Optional[str],
    use_last: bool,
    scan_root: Path,
) -> tuple[Optional[Path], int]:
    """Resolve the ADR path.

    Returns ``(path, exit_code)`` where *path* is None on failure (exit_code
    will be non-zero).
    """
    if use_last:
        candidates = _sort_by_mtime(_scan_adrs(scan_root))
        if not candidates:
            return None, 2
        return candidates[0], 0

    if run_id is not None:
        # Direct path: absolute, or relative-looking ending in .md.
        candidate = Path(run_id)
        if candidate.suffix.lower() == ".md" and candidate.exists() and candidate.is_file():
            return candidate.resolve(), 0
        # Stem search: find adr-<run_id>-*.md or ADR-<run_id>*.md
        all_adrs = _scan_adrs(scan_root)
        stem_lower = run_id.lower()
        matches = [
            p for p in all_adrs
            if stem_lower in p.stem.lower()
        ]
        if len(matches) == 1:
            return matches[0].resolve(), 0
        if len(matches) > 1:
            # Return the newest among the matches.
            return _sort_by_mtime(matches)[0], 0
        # Nothing found.
        return None, 2

    return None, 2


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def add_resume_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "resume",
        help="Re-run recompose from the most recent (or specified) ADR",
        description=(
            "Find the most-recently modified kaizen-produced ADR under --path "
            "and regenerate target code from it via `kaizen recompose`. "
            "Useful after hand-editing an ADR without having to remember the "
            "exact file path. Pass --list to browse recent ADRs without "
            "triggering a re-run."
        ),
    )

    # Positional: optional run_id or path
    p.add_argument(
        "run_id",
        nargs="?",
        metavar="RUN_ID",
        help=(
            "A run identifier or direct path to an ADR markdown file. "
            "If it ends in .md and exists, use it directly. "
            "Otherwise treat as a stem and search for a matching ADR "
            "(e.g. 'inih' matches 'adr-inih-*.md'). "
            "Omit to use --last or --list mode."
        ),
    )

    # Selection
    p.add_argument(
        "--last",
        action="store_true",
        help="Ignore run_id; pick the most recently modified ADR under --path",
    )
    p.add_argument(
        "--path",
        default=".",
        metavar="DIR",
        help="Directory to scan for ADRs (default: current directory)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List the 10 most recent candidate ADRs and exit (no re-run)",
    )

    # Recompose pass-through flags (mirror recompose.py EXACTLY)
    p.add_argument(
        "--output-dir", "-o",
        metavar="DIR",
        default="recomposed",
        help="Output directory for the recomposed source (default: recomposed/)",
    )
    p.add_argument(
        "--target-language",
        metavar="LANG",
        default="Python",
        help="Target implementation language (default: Python)",
    )
    p.add_argument(
        "--cross-language",
        action="store_true",
        help="Enable cross-language translation mode",
    )
    p.add_argument(
        "--emit-tests",
        action="store_true",
        help="Hint the model that tests are welcome alongside the implementation",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=8000,
        help="Max output tokens (default: 8000)",
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="LLM sampling temperature (default: 0.0)",
    )
    p.add_argument(
        "--no-repair-syntax",
        action="store_true",
        help="Skip the one-shot repair retry when recomposed Python has syntax errors",
    )
    p.add_argument(
        "--target-python-version",
        default="3.9",
        help="Target Python version for generated code (default: 3.9)",
    )
    p.add_argument(
        "--domain",
        choices=("none", "memory-safe", "framework-migration"),
        default="none",
        help="Wedge schema preset (default: none)",
    )
    p.add_argument(
        "--provider",
        default="anthropic",
        choices=("anthropic", "openai"),
        help="LLM provider (default: anthropic)",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override provider default model",
    )

    # Resume-specific
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved ADR path and recompose command, then exit without running",
    )
    p.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )

    return p


# ---------------------------------------------------------------------------
# List helper
# ---------------------------------------------------------------------------

def _print_list(
    candidates: List[Path],
    fmt: str,
    style: Style,
    *,
    limit: int = 10,
) -> None:
    """Print up to *limit* ADR candidates."""
    shown = candidates[:limit]

    if fmt == "json":
        rows = []
        for p in shown:
            st = p.stat()
            rows.append({
                "path": str(p),
                "size_bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            })
        print(json.dumps(rows, indent=2))
        return

    # Human table
    print(style.bold(f"Recent ADR candidates  (showing {len(shown)} of {len(candidates)})"))
    print()
    for i, p in enumerate(shown, 1):
        st = p.stat()
        mtime = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        size_kb = st.st_size / 1024
        print(f"  {i:2d}.  {p}")
        print(f"        size: {size_kb:.1f} KB   mtime: {mtime}")
    print()


# ---------------------------------------------------------------------------
# Command entry point
# ---------------------------------------------------------------------------

def resume_command(args: argparse.Namespace) -> int:
    style: Style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    fmt: str = getattr(args, "format", "human")
    scan_root = Path(args.path).resolve()

    if not scan_root.exists() or not scan_root.is_dir():
        output.error(style, f"path does not exist or is not a directory: {scan_root}")
        return 2

    # ------------------------------------------------------------------
    # --list mode (also the default when no run_id / --last given)
    # ------------------------------------------------------------------
    no_selection = not args.last and not getattr(args, "run_id", None)

    if args.list or no_selection:
        candidates = _sort_by_mtime(_scan_adrs(scan_root))
        if no_selection and not args.list:
            print(
                "No run id or --last given; showing recent ADRs. "
                "Use --last to resume the most recent, or pass a path/id.",
                file=sys.stderr,
            )
        _print_list(candidates, fmt, style)
        return 0

    # ------------------------------------------------------------------
    # Resolve the ADR
    # ------------------------------------------------------------------
    adr_path, rc = _resolve_adr(
        run_id=getattr(args, "run_id", None),
        use_last=args.last,
        scan_root=scan_root,
    )

    if adr_path is None:
        run_id = getattr(args, "run_id", None)
        if run_id:
            output.error(style, f"no ADR found for run_id {run_id!r} under {scan_root}")
        else:
            output.error(style, f"no ADR candidates found under {scan_root}")
        # Print candidates as a hint.
        candidates = _sort_by_mtime(_scan_adrs(scan_root))
        if candidates:
            _print_list(candidates, fmt, style)
        return 2

    # ------------------------------------------------------------------
    # --dry-run: show what would run and exit
    # ------------------------------------------------------------------
    if args.dry_run:
        print(style.bold("kaizen resume --dry-run"))
        print()
        print(f"  resolved ADR : {adr_path}")
        print()
        print(style.bold("  would invoke: kaizen recompose"))
        print(f"    --adr          {adr_path}")
        print(f"    --output-dir   {args.output_dir}")
        print(f"    --target-language {args.target_language}")
        print(f"    --provider     {args.provider}")
        print(f"    --max-tokens   {args.max_tokens}")
        print(f"    --temperature  {args.temperature}")
        print(f"    --domain       {args.domain}")
        if args.cross_language:
            print("    --cross-language")
        if args.emit_tests:
            print("    --emit-tests")
        if args.no_repair_syntax:
            print("    --no-repair-syntax")
        if args.model:
            print(f"    --model        {args.model}")
        print()
        print(style.dim("no pipeline invoked; exit 0"))
        return 0

    # ------------------------------------------------------------------
    # Real run: emit start, delegate to recompose_command
    # ------------------------------------------------------------------
    events.run_start(
        command="resume",
        resolved_adr=str(adr_path),
        target_language=args.target_language,
        provider=args.provider,
        model=args.model,
        domain=args.domain,
    )

    # Build a Namespace that satisfies recompose_command's expectations.
    recompose_ns = argparse.Namespace(
        adr=str(adr_path),
        output_dir=args.output_dir,
        target_language=args.target_language,
        cross_language=args.cross_language,
        emit_tests=args.emit_tests,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        no_repair_syntax=args.no_repair_syntax,
        target_python_version=args.target_python_version,
        domain=args.domain,
        provider=args.provider,
        model=args.model,
        dry_run=False,
        format=fmt,
        # Propagate no_color if caller set it.
        no_color=getattr(args, "no_color", False),
        verbose=getattr(args, "verbose", False),
    )

    rc = recompose_command(recompose_ns)

    events.result(rc, resumed_from=str(adr_path), target_language=args.target_language)
    return rc
