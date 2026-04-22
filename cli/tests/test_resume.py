# SPDX-License-Identifier: Apache-2.0
"""Tests for `cli.commands.resume`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from cli.commands.resume import (
    _scan_adrs,
    _sort_by_mtime,
    add_resume_parser,
    resume_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> argparse.Namespace:
    """Build a minimal Namespace with resume defaults."""
    defaults = dict(
        run_id=None,
        last=False,
        path=".",
        list=False,
        output_dir="recomposed",
        target_language="Python",
        cross_language=False,
        emit_tests=False,
        max_tokens=8000,
        temperature=0.0,
        no_repair_syntax=False,
        target_python_version="3.9",
        domain="none",
        provider="anthropic",
        model=None,
        dry_run=False,
        format="human",
        no_color=True,
        verbose=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _write_adr(directory: Path, name: str, mtime: float) -> Path:
    """Create a dummy ADR file with a specific mtime."""
    p = directory / name
    p.write_text(f"# ADR: {name}\n", encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


# ---------------------------------------------------------------------------
# 1. --list on docs/case-studies returns 3 ADR-CASE-*.md files, newest first
# ---------------------------------------------------------------------------

def test_list_case_studies(capsys: pytest.CaptureFixture) -> None:
    """--list on docs/case-studies/ finds 3 ADR-CASE-*.md files sorted by mtime."""
    case_studies = Path(__file__).resolve().parents[2] / "docs" / "case-studies"
    if not case_studies.exists():
        pytest.skip("docs/case-studies not present in this checkout")

    args = _make_args(**{"list": True, "path": str(case_studies)})
    rc = resume_command(args)

    assert rc == 0
    out = capsys.readouterr().out
    # Should mention 3 files.
    assert "ADR-CASE-A.md" in out or "ADR-CASE-B.md" in out or "ADR-CASE-C.md" in out

    # Verify ordering via _scan_adrs directly.
    candidates = _sort_by_mtime(_scan_adrs(case_studies))
    names = [p.name for p in candidates]
    assert set(names) == {"ADR-CASE-A.md", "ADR-CASE-B.md", "ADR-CASE-C.md"}
    # Sorted newest first -- each subsequent file must have mtime <= previous.
    mtimes = [p.stat().st_mtime for p in candidates]
    assert mtimes == sorted(mtimes, reverse=True)


def test_list_case_studies_json(capsys: pytest.CaptureFixture) -> None:
    """--list --format json produces a valid JSON array."""
    case_studies = Path(__file__).resolve().parents[2] / "docs" / "case-studies"
    if not case_studies.exists():
        pytest.skip("docs/case-studies not present in this checkout")

    args = _make_args(**{"list": True, "path": str(case_studies), "format": "json"})
    rc = resume_command(args)

    assert rc == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert isinstance(rows, list)
    assert len(rows) == 3
    for row in rows:
        assert "path" in row
        assert "size_bytes" in row
        assert "mtime" in row


# ---------------------------------------------------------------------------
# 2. Explicit path + --dry-run resolves correctly
# ---------------------------------------------------------------------------

def test_explicit_path_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Passing a direct .md path with --dry-run prints the resolved ADR."""
    adr = tmp_path / "ADR-0001-test.md"
    adr.write_text("# ADR\n", encoding="utf-8")

    args = _make_args(run_id=str(adr), dry_run=True, path=str(tmp_path))
    rc = resume_command(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert str(adr) in out
    assert "dry-run" in out.lower() or "no pipeline invoked" in out


# ---------------------------------------------------------------------------
# 3. --last picks the newest file in a tmp_path with multiple ADR md files
# ---------------------------------------------------------------------------

def test_last_picks_newest(tmp_path: Path) -> None:
    """--last selects the file with the most recent mtime."""
    older = _write_adr(tmp_path, "adr-old.md", mtime=1_000_000.0)
    newer = _write_adr(tmp_path, "ADR-new.md", mtime=2_000_000.0)

    # We test resolution without triggering recompose by using --dry-run.
    args = _make_args(last=True, dry_run=True, path=str(tmp_path))

    captured_out: list[str] = []
    original_print = print

    def _mock_print(*a, **kw):
        if kw.get("file") is sys.stderr:
            original_print(*a, **kw)
        else:
            captured_out.append(" ".join(str(x) for x in a))
            original_print(*a, **kw)

    with patch("builtins.print", side_effect=_mock_print):
        rc = resume_command(args)

    assert rc == 0
    combined = "\n".join(captured_out)
    assert newer.name in combined, f"Expected {newer.name!r} in output; got:\n{combined}"
    assert older.name not in combined


# ---------------------------------------------------------------------------
# 4. Missing ADR path -> exit code 2
# ---------------------------------------------------------------------------

def test_missing_adr_exit_2(tmp_path: Path) -> None:
    """A run_id that resolves to nothing should return exit code 2."""
    args = _make_args(run_id="nonexistent-adr.md", path=str(tmp_path))
    rc = resume_command(args)
    assert rc == 2


def test_missing_stem_exit_2(tmp_path: Path) -> None:
    """A stem that matches nothing under --path should return exit code 2."""
    args = _make_args(run_id="doesnotexist", path=str(tmp_path))
    rc = resume_command(args)
    assert rc == 2


# ---------------------------------------------------------------------------
# 5. No args, no --list -> exits 0, prints hint to stderr
# ---------------------------------------------------------------------------

def test_no_args_defaults_to_list(capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
    """When neither run_id nor --last are given, defaults to list mode (exit 0)."""
    _write_adr(tmp_path, "ADR-0042.md", mtime=1_500_000.0)

    args = _make_args(path=str(tmp_path))  # run_id=None, last=False, list=False
    rc = resume_command(args)

    assert rc == 0
    captured = capsys.readouterr()
    # Hint must go to stderr
    assert "No run id" in captured.err or "--last" in captured.err


def test_no_args_empty_dir_still_exit_0(capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
    """Even an empty directory should exit 0 in list/default mode."""
    args = _make_args(path=str(tmp_path))
    rc = resume_command(args)
    assert rc == 0


# ---------------------------------------------------------------------------
# 6. --dry-run never calls recompose_command
# ---------------------------------------------------------------------------

def test_dry_run_does_not_call_recompose(tmp_path: Path) -> None:
    """--dry-run must not invoke recompose_command (no recomposed/ dir created)."""
    adr = tmp_path / "ADR-X.md"
    adr.write_text("# ADR\n", encoding="utf-8")

    recomposed_dir = tmp_path / "recomposed"
    assert not recomposed_dir.exists(), "precondition: recomposed/ must not exist"

    with patch("cli.commands.resume.recompose_command") as mock_rc:
        args = _make_args(run_id=str(adr), dry_run=True, path=str(tmp_path),
                          output_dir=str(recomposed_dir))
        rc = resume_command(args)

    assert rc == 0
    mock_rc.assert_not_called()
    assert not recomposed_dir.exists()


def test_dry_run_last_does_not_call_recompose(tmp_path: Path) -> None:
    """--last --dry-run must not invoke recompose_command."""
    _write_adr(tmp_path, "adr-root.md", mtime=1_600_000.0)
    recomposed_dir = tmp_path / "recomposed"

    with patch("cli.commands.resume.recompose_command") as mock_rc:
        args = _make_args(last=True, dry_run=True, path=str(tmp_path),
                          output_dir=str(recomposed_dir))
        rc = resume_command(args)

    assert rc == 0
    mock_rc.assert_not_called()
    assert not recomposed_dir.exists()


# ---------------------------------------------------------------------------
# 7. add_resume_parser registers the subcommand correctly
# ---------------------------------------------------------------------------

def test_add_resume_parser() -> None:
    """add_resume_parser registers the 'resume' subcommand with key arguments."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_resume_parser(subparsers)

    ns = parser.parse_args(["resume", "--last", "--list"])
    assert ns.command == "resume"
    assert ns.last is True
    assert ns.list is True

    ns2 = parser.parse_args(["resume", "some-id", "--dry-run",
                              "--target-language", "Rust",
                              "--provider", "openai"])
    assert ns2.run_id == "some-id"
    assert ns2.dry_run is True
    assert ns2.target_language == "Rust"
    assert ns2.provider == "openai"
