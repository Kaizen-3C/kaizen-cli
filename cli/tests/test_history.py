# SPDX-License-Identifier: Apache-2.0
"""Tests for `cli.commands.history` (ADR-0006 Phase 3)."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from cli.commands.history import add_history_parser, history_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(path=".", json=False, limit=None, no_color=True, verbose=False)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "commit.gpgsign", "false")


def _metadata(step: int, confidence: float, delta: float = 0.05) -> dict:
    return {
        "schema_version": "1.0.0",
        "step_number": step,
        "confidence_score": confidence,
        "convergence_delta": delta,
        "test_results": {"total": 10, "passed": 9, "failed": 1, "coverage_pct": 88.0},
        "agent_messages": [
            {"agent": "researcher", "summary": "r", "hash": "sha256:aaa"},
            {"agent": "red_team", "summary": "rt", "hash": "sha256:bbb"},
            {"agent": "draft", "summary": "d", "hash": "sha256:ccc"},
            {"agent": "write", "summary": "w", "hash": "sha256:ddd",
             "taor_turns_used": None, "taor_turns_max": 50},
            {"agent": "evaluator", "composite_score": confidence,
             "signals": {"test_pass_rate": 0.9}},
        ],
        "files_modified": [f"src/step{step}.rs"],
        "timestamp_utc": f"2026-05-15T00:0{step}:00Z",
    }


def _commit(repo: Path, n: int, subject: str, body: str) -> None:
    """Create a commit with `subject\\n\\n{body}` and a real file change."""
    (repo / f"file{n}.txt").write_text(f"content {n}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    msg = f"{subject}\n\n{body}" if body else subject
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Repo with: baseline, step1 (0.60), step2 (0.70), step3 (0.65 regression),
    a human commit, and a legacy non-JSON `cd-aor: step` commit."""
    repo = tmp_path / "ws"
    repo.mkdir()
    _init_repo(repo)
    _commit(repo, 0, "cd-aor: workspace baseline", "")
    _commit(repo, 1, "cd-aor: step 1 — denoising iteration",
            json.dumps(_metadata(1, 0.60), indent=2))
    _commit(repo, 2, "cd-aor: step 2 — denoising iteration",
            json.dumps(_metadata(2, 0.70), indent=2))
    _commit(repo, 3, "cd-aor: step 3 — denoising iteration",
            json.dumps(_metadata(3, 0.65), indent=2))
    _commit(repo, 4, "chore: a human commit", "")
    _commit(repo, 5, "cd-aor: step 9 — old format", "not-json-legacy-body")
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_step_row_count(workspace: Path, capsys: pytest.CaptureFixture) -> None:
    rc = history_command(_make_args(path=str(workspace)))
    assert rc == 0
    out = capsys.readouterr().out
    # 3 valid step rows.
    assert out.count("denoising") == 0  # subjects are not echoed
    for s in ("1", "2", "3"):
        assert s in out
    assert "trajectory:" in out


def test_regression_flagged(workspace: Path, capsys: pytest.CaptureFixture) -> None:
    rc = history_command(_make_args(path=str(workspace)))
    assert rc == 0
    out = capsys.readouterr().out
    # Step 3 (0.65) regressed vs step 2 (0.70); marked with '!'.
    reg_lines = [ln for ln in out.splitlines() if ln.strip().startswith("!")]
    assert len(reg_lines) == 1
    assert " 3 " in reg_lines[0] or reg_lines[0].strip().startswith("!   3")


def test_regression_summary(workspace: Path, capsys: pytest.CaptureFixture) -> None:
    history_command(_make_args(path=str(workspace)))
    out = capsys.readouterr().out
    assert "regressions: steps 3" in out


def test_skipped_note(workspace: Path, capsys: pytest.CaptureFixture) -> None:
    history_command(_make_args(path=str(workspace)))
    out = capsys.readouterr().out
    # Only the legacy `cd-aor: step 9` commit with a non-JSON body is an
    # unparseable checkpoint; the baseline and human commits are not cd-aor
    # steps and are silently ignored (not counted as noise).
    assert "skipped 1 unparseable cd-aor checkpoint(s)" in out


def test_json_mode(workspace: Path, capsys: pytest.CaptureFixture) -> None:
    rc = history_command(_make_args(path=str(workspace), json=True))
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) == 3
    assert [r["step_number"] for r in data] == [1, 2, 3]
    assert all("_commit" in r for r in data)


def test_limit_respected(workspace: Path, capsys: pytest.CaptureFixture) -> None:
    rc = history_command(_make_args(path=str(workspace), json=True, limit=2))
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["step_number"] for r in data] == [2, 3]


def test_trajectory_format(workspace: Path, capsys: pytest.CaptureFixture) -> None:
    history_command(_make_args(path=str(workspace)))
    out = capsys.readouterr().out
    assert "trajectory: 0.600 -> 0.700 -> 0.650" in out


def test_non_git_path_exit_2(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    rc = history_command(_make_args(path=str(plain)))
    assert rc == 2


def test_nonexistent_path_exit_2() -> None:
    rc = history_command(_make_args(path="/no/such/dir/xyz123"))
    assert rc == 2


def test_only_human_commits_exit_0(tmp_path: Path,
                                   capsys: pytest.CaptureFixture) -> None:
    repo = tmp_path / "human"
    repo.mkdir()
    _init_repo(repo)
    _commit(repo, 1, "chore: only human commits here", "")
    rc = history_command(_make_args(path=str(repo)))
    assert rc == 0
    assert "No cd-aor checkpoints found" in capsys.readouterr().out


def test_add_history_parser() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_history_parser(subparsers)

    ns = parser.parse_args(["history", "--path", "X", "--json", "--limit", "5"])
    assert ns.command == "history"
    assert ns.path == "X"
    assert ns.json is True
    assert ns.limit == 5
