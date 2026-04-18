# SPDX-License-Identifier: Apache-2.0
"""`kaizen status` — scan the cwd for recent Kaizen artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .. import output
from ..output import Style


# Directories we never want to recurse into — speeds up `find` on big repos
# and avoids false positives from dependency trees.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__",
    "node_modules", "venv", ".venv", "env",
    "target", "build", "dist", ".mypy_cache", ".pytest_cache",
}


def add_status_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "status",
        help="Summarize recent Kaizen runs in the current directory",
        description=(
            "Scan the current directory for `taor_observations.jsonl` and "
            "`priors.json` artifacts and print a summary of the most recent run."
        ),
    )
    p.add_argument("--path", default=".", metavar="DIR",
                   help="Directory to scan (default: current directory)")
    return p


def _scan(root: Path, filename: str) -> List[Path]:
    """Find files named `filename` anywhere under root, skipping noisy dirs."""
    hits: List[Path] = []
    for p in root.rglob(filename):
        # Exclude anything under a skipped directory.
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        hits.append(p)
    return hits


def _latest(files: List[Path]) -> Optional[Path]:
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _last_trajectory(observations_path: Path, n: int = 10) -> List[float]:
    """Read the last n `composite_confidence` values from an observations jsonl."""
    traj: List[float] = []
    try:
        with observations_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Observations log may use different keys; try a few.
                c = rec.get("composite_confidence")
                if c is None:
                    c = rec.get("confidence")
                if isinstance(c, (int, float)):
                    traj.append(float(c))
    except OSError:
        return []
    return traj[-n:]


def status_command(args: argparse.Namespace) -> int:
    style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    root = Path(args.path).resolve()

    if not root.exists() or not root.is_dir():
        output.error(style, f"path does not exist: {root}")
        return 2

    obs_files = _scan(root, "taor_observations.jsonl")
    priors_files = _scan(root, "priors.json")

    if not obs_files and not priors_files:
        print("No prior Kaizen runs detected in this directory")
        return 0

    print(style.bold("kaizen status"))
    print(f"  scanned  : {root}")
    print()

    latest_obs = _latest(obs_files)
    if latest_obs:
        mtime = datetime.fromtimestamp(latest_obs.stat().st_mtime).isoformat(timespec="seconds")
        print(style.bold("most recent observations log"))
        print(f"  path     : {latest_obs}")
        print(f"  modified : {mtime}")
        traj = _last_trajectory(latest_obs)
        if traj:
            arrow = " -> ".join(f"{c:.3f}" for c in traj)
            print(f"  trajectory (last {len(traj)}): {arrow}")
        else:
            print(f"  trajectory: {style.dim('(no confidence values found)')}")
        print()

    latest_priors = _latest(priors_files)
    if latest_priors:
        mtime = datetime.fromtimestamp(latest_priors.stat().st_mtime).isoformat(timespec="seconds")
        print(style.bold("most recent priors file"))
        print(f"  path     : {latest_priors}")
        print(f"  modified : {mtime}")
        print()

    # Summaries
    extra = []
    if len(obs_files) > 1:
        extra.append(f"{len(obs_files)} observation logs total")
    if len(priors_files) > 1:
        extra.append(f"{len(priors_files)} priors files total")
    if extra:
        print(style.dim("  " + ", ".join(extra)))

    return 0
