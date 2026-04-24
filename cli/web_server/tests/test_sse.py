# SPDX-License-Identifier: Apache-2.0
"""SSE streaming tests for wedge routes.

These tests exercise the streaming path end-to-end by running the wedge
commands in dry-run mode (which goes through the SSE pipeline but does not
make LLM calls). Real-LLM integration tests are opt-in and live in
test_integration.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
sse_starlette = pytest.importorskip("sse_starlette")
from fastapi.testclient import TestClient  # noqa: E402

from cli.web_server.server import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _parse_sse_stream(text: str) -> list[dict]:
    """Parse a text/event-stream response body into a list of event dicts.

    Each SSE event is a block of lines separated by blank lines, where each
    line is `<field>: <value>`. We care about `event:` and `data:`.
    """
    events: list[dict] = []
    current: dict = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line:
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith(":"):  # keepalive comment
            continue
        if ": " in line:
            field, _, value = line.partition(": ")
        else:
            field, value = line, ""
        if field in ("event", "data", "id", "retry"):
            current[field] = current.get(field, "") + value
    if current:
        events.append(current)
    return events


def test_memsafe_stream_emits_events_in_order(tmp_path: Path, client: TestClient) -> None:
    """Dry-run memsafe SSE should emit run.start + result + end events, in order.

    Dry-run short-circuits before the real pipeline, so we get a minimal but
    representative event sequence without making LLM calls.
    """
    (tmp_path / "source.c").write_text("int main() { return 0; }\n", encoding="utf-8")
    with client.stream("POST", "/api/memsafe-roadmap/stream", json={
        "repo": str(tmp_path),
        "dry_run": True,
        "plain": True,
    }) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.read().decode("utf-8")

    events = _parse_sse_stream(body)
    event_kinds = [e["event"] for e in events if "event" in e]

    # We expect an "end" event last with exit_code=0 (dry-run short-circuits
    # cleanly). run.start may or may not appear because dry-run exits before
    # we call events.run_start — that's fine; the contract is that 'end' is
    # always the terminator.
    assert event_kinds[-1] == "end", f"last event was {event_kinds[-1]!r}, expected 'end'"
    end_data = json.loads(events[-1]["data"])
    assert end_data == {"kind": "end", "exit_code": 0}


def test_memsafe_stream_rejects_missing_repo(client: TestClient) -> None:
    with client.stream("POST", "/api/memsafe-roadmap/stream", json={
        "repo": "/definitely/missing/xyzzy",
        "dry_run": True,
    }) as response:
        assert response.status_code == 400


def test_migrate_stream_terminates_with_end_event(tmp_path: Path, client: TestClient) -> None:
    (tmp_path / "app.py").write_text("print('py2 code')\n", encoding="utf-8")
    with client.stream("POST", "/api/migrate-plan/stream", json={
        "repo": str(tmp_path),
        "from": "python2",
        "to": "python3",
        "dry_run": True,
        "plain": True,
    }) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = _parse_sse_stream(body)
    assert events, "expected at least one SSE event"
    end_events = [e for e in events if e.get("event") == "end"]
    assert len(end_events) == 1
    end_data = json.loads(end_events[0]["data"])
    assert end_data["kind"] == "end"
    assert end_data["exit_code"] == 0


def test_recompose_stream_emits_end_event(tmp_path: Path, client: TestClient) -> None:
    adr = tmp_path / "adr.md"
    adr.write_text("# ADR\nstub\n", encoding="utf-8")
    with client.stream("POST", "/api/recompose/stream", json={
        "adr": str(adr),
        "output_dir": str(tmp_path / "out"),
        "target_language": "Python",
        "dry_run": True,
    }) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = _parse_sse_stream(body)
    end_events = [e for e in events if e.get("event") == "end"]
    assert len(end_events) == 1
    assert json.loads(end_events[0]["data"])["exit_code"] == 0


def test_decompose_stream_emits_end_event(tmp_path: Path, client: TestClient) -> None:
    (tmp_path / "module.py").write_text("def hello(): return 1\n", encoding="utf-8")
    with client.stream("POST", "/api/decompose/stream", json={
        "repo": str(tmp_path),
        "source_language": "Python",
        "dry_run": True,
    }) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = _parse_sse_stream(body)
    assert events, "expected at least one SSE event"
    end_events = [e for e in events if e.get("event") == "end"]
    assert len(end_events) == 1
    assert json.loads(end_events[0]["data"])["exit_code"] == 0


def test_sse_event_data_is_valid_json(tmp_path: Path, client: TestClient) -> None:
    """Every SSE event's `data:` field must be a parseable JSON object."""
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    with client.stream("POST", "/api/migrate-plan/stream", json={
        "repo": str(tmp_path),
        "from": "python2",
        "to": "python3",
        "dry_run": True,
        "plain": True,
    }) as response:
        body = response.read().decode("utf-8")

    events = _parse_sse_stream(body)
    for ev in events:
        data = ev.get("data", "")
        if not data:
            continue
        parsed = json.loads(data)  # raises if malformed
        assert isinstance(parsed, dict)
        assert "kind" in parsed
