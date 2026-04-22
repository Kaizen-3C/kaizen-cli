# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cli.review.run_llm_review.

Strategy
--------
- `events.run_subprocess_with_logs` is monkeypatched to avoid invoking any
  real subprocess (and therefore any LLM or API key).
- The monkeypatch simulates success (exit code 0) by writing a minimal review
  JSON to the output path before returning 0.  Failure cases return non-zero
  without writing output.
- Tests verify the returned dict structure, the model-selection heuristic, and
  the missing-ADR guard without touching any real pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli import events
from cli.review import run_llm_review, _pick_review_model


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_adr(tmp_path: Path) -> Path:
    """Write a minimal ADR markdown file and return its path."""
    adr = tmp_path / "adr-root.md"
    adr.write_text(
        "# ADR: Test\n\n## Decision\n\n- Use Python.\n\n## Key Identifiers\n\n"
        "| Name | Kind | File |\n|------|------|------|\n| foo | function | foo.py |\n",
        encoding="utf-8",
    )
    return adr


def _fake_review_json(output_path: Path) -> None:
    """Write a minimal specialist_review.py-style JSON to *output_path*."""
    payload = {
        "triggered": True,
        "review": {
            "findings": [
                {
                    "severity": "low",
                    "category": "prose_drift",
                    "adr_claim": "Use Python.",
                    "source_reality": "Python used.",
                    "impact": "minimal",
                },
                {
                    "severity": "critical",
                    "category": "invented_feature",
                    "adr_claim": "Uses asyncio.",
                    "source_reality": "No asyncio found.",
                    "impact": "high",
                },
            ],
            "overall_assessment": "ADR has one critical invented feature.",
            "recommended_action": "revise_major",
        },
        "specialist_score": 0.45,
        "n_findings": 2,
        "severity_counts": {"critical": 1, "high": 0, "medium": 0, "low": 1},
        "meta": {"model": "claude-sonnet-4-6", "input_tokens": 500, "output_tokens": 200,
                 "wall_seconds": 1.2},
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helper: build a monkeypatch that simulates a successful review run
# ---------------------------------------------------------------------------


def _make_mock_run(exit_code: int = 0, write_output: bool = True):
    """Return a mock for events.run_subprocess_with_logs.

    When *write_output* is True and *exit_code* is 0, the mock writes a
    synthetic review JSON to the path found in the cmd list (``--output``
    argument).
    """
    def _mock(cmd, env=None, source="subprocess"):
        if write_output and exit_code == 0:
            # Locate the --output argument in cmd and write fake JSON there.
            try:
                out_idx = cmd.index("--output")
                out_path = Path(cmd[out_idx + 1])
                _fake_review_json(out_path)
            except (ValueError, IndexError):
                pass
        return exit_code
    return _mock


# ---------------------------------------------------------------------------
# Tests: successful run
# ---------------------------------------------------------------------------


def test_run_llm_review_success_returns_expected_dict(
    tmp_adr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: subprocess exits 0, review JSON is written, dict is correct."""
    monkeypatch.setattr(events, "run_subprocess_with_logs", _make_mock_run(0))

    result = run_llm_review(tmp_adr, provider="anthropic")

    assert result["exit_code"] == 0
    assert result["review_path"] is not None
    assert Path(result["review_path"]).exists()
    assert result["findings_count"] == 2
    assert result["critical_findings"] == 1
    assert result["triggered"] is True
    assert isinstance(result["model"], str) and result["model"]


def test_run_llm_review_review_file_named_correctly(
    tmp_adr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default output path is <adr_stem>.review.json next to the ADR."""
    monkeypatch.setattr(events, "run_subprocess_with_logs", _make_mock_run(0))

    result = run_llm_review(tmp_adr)

    expected = tmp_adr.parent / "adr-root.review.json"
    assert result["review_path"] == str(expected)


def test_run_llm_review_explicit_output_path(
    tmp_adr: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When output_path is supplied, the review is written there."""
    custom_out = tmp_path / "custom" / "review.json"
    custom_out.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(events, "run_subprocess_with_logs", _make_mock_run(0))

    result = run_llm_review(tmp_adr, output_path=custom_out)

    assert result["review_path"] == str(custom_out.resolve())


# ---------------------------------------------------------------------------
# Tests: missing ADR
# ---------------------------------------------------------------------------


def test_run_llm_review_missing_adr_returns_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing ADR path returns exit_code=2 without raising and without calling subprocess."""
    called = []
    monkeypatch.setattr(
        events, "run_subprocess_with_logs",
        lambda *a, **kw: called.append(True) or 0,
    )

    result = run_llm_review(tmp_path / "nonexistent.md", provider="anthropic")

    assert result["exit_code"] == 2
    assert result["review_path"] is None
    assert called == [], "subprocess should not be invoked for missing ADR"


def test_run_llm_review_missing_adr_does_not_raise(tmp_path: Path) -> None:
    """run_llm_review is safe to call when the ADR is absent -- never raises."""
    result = run_llm_review(tmp_path / "does_not_exist.md")
    assert result["exit_code"] == 2


# ---------------------------------------------------------------------------
# Tests: subprocess failure
# ---------------------------------------------------------------------------


def test_run_llm_review_subprocess_failure(
    tmp_adr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When subprocess exits non-zero, exit_code is non-zero; review_path is None."""
    monkeypatch.setattr(
        events, "run_subprocess_with_logs",
        _make_mock_run(exit_code=1, write_output=False),
    )

    result = run_llm_review(tmp_adr)

    assert result["exit_code"] == 1
    assert result["review_path"] is None
    assert result["findings_count"] == -1


# ---------------------------------------------------------------------------
# Tests: model selection heuristic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("write_model,provider,expected_review", [
    ("claude-sonnet-4-5", "anthropic", "claude-sonnet-4-6"),
    ("claude-sonnet-4-6", "anthropic", "claude-sonnet-4-5"),
    ("claude-opus-4-5",  "anthropic", "claude-sonnet-4-6"),
    ("gpt-4o",           "openai",    "gpt-4.1"),
    ("gpt-4.1",          "openai",    "gpt-4o"),
    (None,               "anthropic", "claude-sonnet-4-6"),  # no write model -> provider default
    (None,               "openai",    "gpt-4.1"),
    ("unknown-model",    "anthropic", "claude-sonnet-4-6"),  # unknown -> provider default
])
def test_pick_review_model(
    write_model: str | None,
    provider: str,
    expected_review: str,
) -> None:
    assert _pick_review_model(write_model, provider, None) == expected_review


def test_explicit_review_model_overrides_heuristic() -> None:
    """An explicit review_model wins over every heuristic."""
    assert _pick_review_model("claude-sonnet-4-5", "anthropic", "claude-opus-4-7") == "claude-opus-4-7"


def test_run_llm_review_uses_heuristic_model(
    tmp_adr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_llm_review applies the model-flip heuristic to the returned 'model' field."""
    monkeypatch.setattr(events, "run_subprocess_with_logs", _make_mock_run(0))

    result = run_llm_review(tmp_adr, provider="anthropic", model="claude-sonnet-4-5")

    assert result["model"] == "claude-sonnet-4-6"


def test_run_llm_review_explicit_review_model(
    tmp_adr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit review_model argument is honored and returned in the dict."""
    monkeypatch.setattr(events, "run_subprocess_with_logs", _make_mock_run(0))

    result = run_llm_review(
        tmp_adr, provider="anthropic",
        model="claude-sonnet-4-5",
        review_model="claude-opus-4-7",
    )

    assert result["model"] == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Tests: event emission
# ---------------------------------------------------------------------------


def test_run_llm_review_emits_detail_events(
    tmp_adr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail events from the subprocess are captured via the events sink."""
    monkeypatch.setattr(events, "run_subprocess_with_logs", _make_mock_run(0))

    with events.capture() as captured:
        run_llm_review(tmp_adr)

    # The mock doesn't emit detail events (it skips the real subprocess), but
    # run_llm_review itself emits an error event only on ADR-not-found.
    # For a valid ADR this should produce zero events from run_llm_review itself.
    kinds = [e["kind"] for e in captured]
    assert "error" not in kinds


def test_run_llm_review_emits_error_event_for_missing_adr(
    tmp_path: Path,
) -> None:
    """An error event is emitted when the ADR is missing."""
    with events.capture() as captured:
        run_llm_review(tmp_path / "ghost.md")

    kinds = [e["kind"] for e in captured]
    assert "error" in kinds


# ---------------------------------------------------------------------------
# Tests: source_dir handling
# ---------------------------------------------------------------------------


def test_run_llm_review_with_valid_source_dir(
    tmp_adr: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When source_dir is provided and exists, it is used directly."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("def foo(): pass\n", encoding="utf-8")

    calls: list[list] = []

    def _capturing_mock(cmd, env=None, source="subprocess"):
        calls.append(list(cmd))
        _make_mock_run(0)(cmd, env=env, source=source)
        return 0

    monkeypatch.setattr(events, "run_subprocess_with_logs", _capturing_mock)

    result = run_llm_review(tmp_adr, source_dir=src)

    assert result["exit_code"] == 0
    assert "--source-dir" in calls[0]
    src_idx = calls[0].index("--source-dir")
    assert calls[0][src_idx + 1] == str(src.resolve())


def test_run_llm_review_without_source_dir_uses_tempdir(
    tmp_adr: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without source_dir, a temp dir is silently used; --source-dir is still in cmd."""
    calls: list[list] = []

    def _capturing_mock(cmd, env=None, source="subprocess"):
        calls.append(list(cmd))
        _make_mock_run(0)(cmd, env=env, source=source)
        return 0

    monkeypatch.setattr(events, "run_subprocess_with_logs", _capturing_mock)

    result = run_llm_review(tmp_adr)

    assert result["exit_code"] == 0
    assert "--source-dir" in calls[0]
    # The temp dir path will NOT match the ADR's parent
    src_idx = calls[0].index("--source-dir")
    assert calls[0][src_idx + 1] != str(tmp_adr.parent)
