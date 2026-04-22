# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cli.events."""

from __future__ import annotations

import io
import json
import sys

import pytest

from cli import events


@pytest.fixture(autouse=True)
def _reset_sink():
    """Each test starts from a clean default-sink + human-mode baseline."""
    events.set_sink(None)
    events.set_mode("human")
    yield
    events.set_sink(None)
    events.set_mode("human")


def test_emit_default_sink_human(capsys: pytest.CaptureFixture) -> None:
    events.stage("decompose", index=1, total=3)
    captured = capsys.readouterr()
    assert "[1/3] decompose" in captured.out


def test_emit_default_sink_ndjson(capsys: pytest.CaptureFixture) -> None:
    events.set_mode("ndjson")
    events.stage("decompose", index=1, total=3, provider="anthropic")
    captured = capsys.readouterr()
    # One JSON line per event -- parse to verify schema
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed == {
        "kind": "stage",
        "name": "decompose",
        "index": 1,
        "total": 3,
        "provider": "anthropic",
    }


def test_capture_context_manager() -> None:
    with events.capture() as collected:
        events.run_start("memsafe-roadmap", repo="/tmp/foo")
        events.stage("decompose", index=1, total=3)
        events.stage_done("decompose", artifacts={"adr": "/tmp/foo/adr.md"})
        events.result(0, roadmap_path="/tmp/roadmap.md")
    assert len(collected) == 4
    assert collected[0]["kind"] == "run.start"
    assert collected[0]["command"] == "memsafe-roadmap"
    assert collected[1]["kind"] == "stage"
    assert collected[2]["kind"] == "stage.done"
    assert collected[3]["kind"] == "result"
    assert collected[3]["exit_code"] == 0


def test_capture_restores_previous_sink() -> None:
    received: list[dict] = []

    def my_sink(event: dict) -> None:
        received.append(event)

    events.set_sink(my_sink)
    with events.capture() as collected:
        events.detail("inside capture")
    assert collected[0]["message"] == "inside capture"
    assert received == []
    events.detail("after capture")
    assert received == [{"kind": "detail", "message": "after capture"}]


def test_set_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        events.set_mode("not-a-mode")


def test_ndjson_mode_context_manager(capsys: pytest.CaptureFixture) -> None:
    events.detail("human line")
    with events.ndjson_mode():
        events.detail("ndjson line", extra="foo")
    events.detail("human again")
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert "human line" in lines[0]
    # Middle line is JSON
    parsed = json.loads(lines[1])
    assert parsed == {"kind": "detail", "message": "ndjson line", "extra": "foo"}
    assert "human again" in lines[2]


def test_warn_and_error_go_to_stderr(capsys: pytest.CaptureFixture) -> None:
    events.warn("suspicious")
    events.error("bad")
    captured = capsys.readouterr()
    assert "suspicious" in captured.err
    assert "bad" in captured.err
    assert captured.out == ""


def test_unknown_kind_human_suppressed(capsys: pytest.CaptureFixture) -> None:
    events.emit("custom.unknown", foo="bar")
    # Human mode suppresses unknown kinds; sink still receives them when captured.
    assert capsys.readouterr().out == ""
    with events.capture() as collected:
        events.emit("custom.unknown", foo="bar")
    assert collected[0] == {"kind": "custom.unknown", "foo": "bar"}


def test_env_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAIZEN_EVENT_STREAM", "ndjson")
    events._init_from_env()
    assert events.get_mode() == "ndjson"
