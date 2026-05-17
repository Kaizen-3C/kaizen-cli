# SPDX-License-Identifier: Apache-2.0
"""`kaizen history` — render the CD-AOR denoising trajectory from git.

ADR-0006 Phase 3 analysis tooling. The Rust orchestrator writes one git
commit per denoising step whose subject is ``cd-aor: step {N} — {desc}`` and
whose body is a JSON metadata object (schema versioned). This command parses
those commits in a workspace and prints the trajectory as a table — with
regression detection (a step whose composite confidence dropped vs. the
previous step) — or as raw JSON.

Stdlib only; reads git via subprocess.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import output
from ..output import Style

# git log field/record separators: ASCII Unit/Record separators never appear
# in JSON or normal commit text, so the split is reliable across the
# multi-line JSON bodies.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"
_SUBJECT_PREFIX = "cd-aor: step "
# Highest checkpoint metadata schema MAJOR this CLI understands. Minor bumps
# are additive (e.g. 1.1.0 added the optional rl_signals block) and remain
# parseable; a different MAJOR may have moved/removed fields, so such commits
# are surfaced rather than silently mis-rendered.
_SUPPORTED_SCHEMA_MAJOR = 1


def add_history_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "history",
        help="Show the CD-AOR denoising trajectory from git checkpoints",
        description=(
            "Parse `cd-aor: step N` checkpoint commits in a workspace and "
            "print the denoising trajectory (confidence, delta, tests, files) "
            "with regression detection."
        ),
    )
    p.add_argument("--path", default=".", metavar="DIR",
                   help="Workspace git repository to inspect (default: cwd)")
    p.add_argument("--json", action="store_true", dest="json",
                   help="Emit the parsed step records as a JSON array")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Show only the most recent N steps")
    p.add_argument("--task", default=None, metavar="ID",
                   help="Only show steps for this task id (a shared workspace "
                        "may interleave multiple tasks' checkpoints)")
    return p


def _git(path: str, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _schema_major(version: Any) -> Any:
    """Leading integer of a dotted ``schema_version``; None if unparseable."""
    try:
        return int(str(version).split(".", 1)[0])
    except (ValueError, AttributeError):
        return None


def _parse_commits(
    raw: str,
) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    """Return (step_records, skipped_count, unsupported_versions).

    A commit is a step iff its subject starts with the cd-aor step prefix and
    its body is valid JSON carrying a ``schema_version``. Commits that look
    like cd-aor steps but whose body is unparseable/legacy are counted as
    *skipped* (an actionable signal). A step whose schema MAJOR differs from
    what this CLI understands is not rendered (fields may have moved) and its
    version is collected in ``unsupported_versions``. Non-step commits
    (workspace baseline, human commits) are silently ignored — counting them
    would be noise in a repo with ordinary history.
    """
    records: List[Dict[str, Any]] = []
    skipped = 0
    unsupported: List[str] = []
    for chunk in raw.split(_RECORD_SEP):
        chunk = chunk.strip("\n")
        if not chunk or _FIELD_SEP not in chunk:
            continue
        commit_hash, _, body = chunk.partition(_FIELD_SEP)
        subject = body.split("\n", 1)[0].strip()
        if not subject.startswith(_SUBJECT_PREFIX):
            continue
        # Body after the blank line that follows the subject.
        payload = body.split("\n\n", 1)[1] if "\n\n" in body else ""
        try:
            rec = json.loads(payload)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(rec, dict) or "schema_version" not in rec:
            skipped += 1
            continue
        major = _schema_major(rec.get("schema_version"))
        if major != _SUPPORTED_SCHEMA_MAJOR:
            ver = str(rec.get("schema_version"))
            if ver not in unsupported:
                unsupported.append(ver)
            continue
        rec["_commit"] = commit_hash.strip()[:7]
        records.append(rec)
    return records, skipped, unsupported


def _flag_regressions(records: List[Dict[str, Any]]) -> List[int]:
    """Indices of records whose confidence dropped vs. the previous step."""
    regressed: List[int] = []
    prev: Optional[float] = None
    for i, rec in enumerate(records):
        c = float(rec.get("confidence_score", 0.0) or 0.0)
        if prev is not None and c < prev:
            regressed.append(i)
        prev = c
    return regressed


def _render_table(style: Style, records: List[Dict[str, Any]],
                  regressed: List[int], skipped: int) -> None:
    regressed_set = set(regressed)
    print(style.bold(
        f"{'':1}{'step':>4}  {'C':>6}  {'delta':>7}  "
        f"{'tests':>9}  {'files':>5}  {'commit':<7}  timestamp"
    ))

    confidences: List[float] = []
    for i, rec in enumerate(records):
        step = rec.get("step_number", "?")
        c = float(rec.get("confidence_score", 0.0) or 0.0)
        confidences.append(c)
        delta = float(rec.get("convergence_delta", 0.0) or 0.0)
        tr = rec.get("test_results", {}) or {}
        passed = tr.get("passed", 0)
        total = tr.get("total", 0)
        files = len(rec.get("files_modified", []) or [])
        commit = rec.get("_commit", "")
        ts = rec.get("timestamp_utc", "")
        is_reg = i in regressed_set
        mark = "!" if is_reg else " "
        row = (
            f"{mark}{step:>4}  {c:>6.3f}  {delta:>+7.3f}  "
            f"{f'{passed}/{total}':>9}  {files:>5}  {commit:<7}  {ts}"
        )
        print(style.red(row) if is_reg else row)

    if confidences:
        traj = " -> ".join(f"{c:.3f}" for c in confidences)
        print()
        print(f"trajectory: {traj}")

    if regressed:
        steps = ", ".join(str(records[i].get("step_number", "?")) for i in regressed)
        print(f"regressions: steps {steps}")
    else:
        print("regressions: none")

    if skipped:
        print(style.dim(f"  (skipped {skipped} unparseable cd-aor checkpoint(s))"))


def history_command(args: argparse.Namespace) -> int:
    style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    root = Path(args.path).resolve()

    if not root.exists() or not root.is_dir():
        output.error(style, f"path does not exist: {root}")
        return 2

    try:
        inside = _git(str(root), ["rev-parse", "--is-inside-work-tree"])
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            output.error(style, f"not a git repository: {root}")
            return 2

        log = _git(str(root), ["log", "--reverse",
                               f"--format=%H{_FIELD_SEP}%B{_RECORD_SEP}"])
        # A repo with no commits exits non-zero here — that is simply an
        # empty trajectory, not an error.
        raw = log.stdout if log.returncode == 0 else ""

        records, skipped, unsupported = _parse_commits(raw)
    except FileNotFoundError:
        output.error(style, "git executable not found on PATH")
        return 1
    except Exception as exc:  # pragma: no cover - defensive
        output.error(style, f"{exc.__class__.__name__}: {exc}")
        return 1

    task = getattr(args, "task", None)
    if task:
        records = [r for r in records if r.get("task_id") == task]

    if args.limit is not None and args.limit >= 0:
        records = records[-args.limit:] if args.limit else []

    if args.json:
        print(json.dumps(records, indent=2))
        return 0

    def _note_unsupported() -> None:
        if unsupported:
            vers = ", ".join(unsupported)
            output.warn(
                style,
                f"{len(unsupported)} unsupported schema version(s) skipped "
                f"({vers}); upgrade kaizen to read these checkpoints",
            )

    if not records:
        print(f"No cd-aor checkpoints found in {root}")
        if skipped:
            print(style.dim(f"  (skipped {skipped} unparseable cd-aor checkpoint(s))"))
        _note_unsupported()
        return 0

    regressed = _flag_regressions(records)
    _render_table(style, records, regressed, skipped)
    _note_unsupported()
    return 0
