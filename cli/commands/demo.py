# SPDX-License-Identifier: Apache-2.0
"""kaizen demo — offline-first walkthrough of a real kaizen run on wcwidth.

Bundles a pre-recorded successful run (ADR + recomposed code + transcript)
for the `wcwidth` library. Extracts to a temp dir, walks the user through
what kaizen produced, and runs REAL pytest against the recomposed code.

No API key required — the LLM work is pre-recorded. The pytest output is
live and reflects what kaizen actually generated.
"""

from __future__ import annotations

import argparse
import importlib.resources
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Asset location helper
# ---------------------------------------------------------------------------

_ASSET_NAME = "wcwidth_demo.tar.gz"


def _find_bundled_asset() -> Path | None:
    """Return a Path to the bundled tarball, or None if not present.

    Uses importlib.resources so the asset works both from source and from
    an installed wheel (provided pyproject.toml declares the package_data).
    """
    try:
        # importlib.resources.files() is the stable API from Python 3.9+.
        pkg_ref = importlib.resources.files("cli.demo_assets")
        asset_ref = pkg_ref / _ASSET_NAME
        # Materialise to a real path so tarfile can open it.
        # As of Python 3.9, files() returns traversable objects; we need a
        # concrete path for tarfile.  Use as_file() context manager when in a
        # zip archive, but for a regular install a simple str() works too.
        # We detect existence via the traversable interface first.
        if asset_ref.is_file():
            # Return as concrete Path.  For an editable / src install this is
            # already a real filesystem path.
            return Path(str(asset_ref))
    except (FileNotFoundError, TypeError, AttributeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def add_demo_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "demo",
        help="Offline walkthrough of a real kaizen run (no API key required)",
        description=(
            "Runs an offline demo of kaizen using a pre-recorded successful run "
            "on the `wcwidth` library (ADR + recomposed code). "
            "The LLM work is pre-recorded; pytest runs live against the "
            "recomposed code so you see real output. Takes ~5 minutes total."
        ),
    )
    p.add_argument(
        "--no-pytest",
        action="store_true",
        help="Skip the live pytest step (useful if pytest is not installed)",
    )
    p.add_argument(
        "--keep-temp",
        action="store_true",
        help="(Reserved) Temp dir is always kept for inspection; this flag is a no-op",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal output — print only the final pytest result",
    )
    return p


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print(msg: str = "", *, quiet: bool, force: bool = False) -> None:
    """Print *msg* unless quiet mode is on (use force=True for final results)."""
    if not quiet or force:
        print(msg)


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------


def demo_command(args: argparse.Namespace) -> int:
    """Entrypoint for `kaizen demo`; returns an exit code."""
    quiet: bool = getattr(args, "quiet", False)
    no_pytest: bool = getattr(args, "no_pytest", False)

    # ------------------------------------------------------------------
    # Locate bundled asset
    # ------------------------------------------------------------------
    asset_path = _find_bundled_asset()

    if asset_path is None:
        print("Demo asset not bundled in this build of kaizen-cli.")
        print(
            "To generate the demo cache, see scripts/build-demo-cache.py (forthcoming)."
        )
        return 0

    # ------------------------------------------------------------------
    # Intro banner
    # ------------------------------------------------------------------
    _print("=" * 70, quiet=quiet)
    _print("  kaizen demo  —  offline walkthrough of a real kaizen run", quiet=quiet)
    _print("=" * 70, quiet=quiet)
    _print(quiet=quiet)
    _print(
        "  Library:   wcwidth (Unicode character-width helper, 6 files, 28 tests)",
        quiet=quiet,
    )
    _print(
        "  LLM work:  pre-recorded — no API key required, no network calls.",
        quiet=quiet,
    )
    _print(
        "  pytest:    runs LIVE against the recomposed code — output is real.",
        quiet=quiet,
    )
    _print(
        "  Duration:  ~5 minutes end-to-end (pytest is the long pole).",
        quiet=quiet,
    )
    _print(quiet=quiet)

    # ------------------------------------------------------------------
    # Extract tarball to temp dir
    # ------------------------------------------------------------------
    tmp_dir = tempfile.mkdtemp(prefix="kaizen_demo_")
    tmp_path = Path(tmp_dir)

    _print(f"Extracting demo assets to: {tmp_dir}", quiet=quiet)
    _print(quiet=quiet)

    with tarfile.open(asset_path, "r:gz") as tf:
        tf.extractall(tmp_path)  # noqa: S202 — bundled, trusted asset

    # The tarball unpacks to wcwidth_demo/ inside tmp_dir.
    demo_root = tmp_path / "wcwidth_demo"
    if not demo_root.exists():
        # Fallback: asset extracted directly (no subdirectory).
        demo_root = tmp_path

    # ------------------------------------------------------------------
    # Step 1: Decompose (pre-recorded — show ADR)
    # ------------------------------------------------------------------
    _print("Step 1/3: Decomposing wcwidth...", quiet=quiet)
    time.sleep(0.8)  # Dramatic pause — shows UX pacing, not faking work.

    adr_path = demo_root / "adr.md"
    if adr_path.exists() and not quiet:
        lines = adr_path.read_text(encoding="utf-8").splitlines()
        preview = lines[:30]
        print()
        print("-" * 70)
        for line in preview:
            print(line)
        if len(lines) > 30:
            print(f"\n(... see {adr_path} for full ADR ...)")
        print("-" * 70)
        print()

    # ------------------------------------------------------------------
    # Step 2: Recompose (pre-recorded — show file list)
    # ------------------------------------------------------------------
    _print("Step 2/3: Recomposing 6 files based on the ADR...", quiet=quiet)

    after_dir = demo_root / "after"
    summary_path = demo_root / "summary.json"

    if not quiet:
        print()
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                file_list = summary.get("files", [])
                elapsed = summary.get("elapsed_s", "?")
                pass_count = summary.get("pass_count", "?")
                print(f"  Elapsed (original run): {elapsed}s")
                print(f"  Tests passed:           {pass_count}")
                print(f"  Files recomposed:")
                for fname in file_list:
                    print(f"    - {fname}")
            except (json.JSONDecodeError, KeyError):
                _list_after_files(after_dir)
        else:
            _list_after_files(after_dir)
        print()

    # ------------------------------------------------------------------
    # Step 3: pytest (live)
    # ------------------------------------------------------------------
    _print("Step 3/3: Running pytest against recomposed code...", quiet=quiet)

    if no_pytest:
        _print(
            "(skipped — pass without --no-pytest to see live pytest output)",
            quiet=quiet,
            force=True,
        )
        pytest_rc = 0
    elif not after_dir.exists():
        print(
            f"WARNING: after/ directory not found in demo asset ({demo_root}). "
            "Skipping pytest.",
            file=sys.stderr,
        )
        pytest_rc = 0
    else:
        if not quiet:
            print()
            print("-" * 70)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(after_dir), "-v"],
            capture_output=False,
        )
        pytest_rc = result.returncode
        if not quiet:
            print("-" * 70)
            print()

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    _print(quiet=quiet)
    _print("=" * 70, quiet=quiet, force=True)
    _print("  Demo complete.", quiet=quiet, force=True)
    _print(f"  Full output preserved at: {tmp_dir}", quiet=quiet, force=True)
    _print(quiet=quiet, force=True)
    _print(
        "  Run kaizen on your own code:",
        quiet=quiet,
        force=True,
    )
    _print(
        "    kaizen memsafe-roadmap <repo>",
        quiet=quiet,
        force=True,
    )
    _print("=" * 70, quiet=quiet, force=True)

    return pytest_rc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _list_after_files(after_dir: Path) -> None:
    """Print the Python files found in after/, or a warning if absent."""
    if not after_dir.exists():
        print("  (after/ directory not found in demo asset)")
        return
    py_files = sorted(after_dir.rglob("*.py"))
    print(f"  Files recomposed ({len(py_files)} .py files):")
    for f in py_files:
        print(f"    - {f.name}")
