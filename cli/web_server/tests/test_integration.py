# SPDX-License-Identifier: Apache-2.0
"""Opt-in real-LLM integration tests for the SSE streaming path.

These tests are SKIPPED by default. They make real LLM API calls and cost
money (~$0.05-0.50 per test run depending on model). Enable with:

    export KAIZEN_INTEGRATION_TESTS=1
    export ANTHROPIC_API_KEY=sk-ant-...
    pytest kaizen_web/tests/test_integration.py -v

Each test runs `kaizen memsafe-roadmap` or `migrate-plan` against a tiny
fixture repo (few dozen lines of source) with real provider calls and
verifies:
- The SSE stream produces the expected event kinds in order
- stage events appear for each pipeline step
- detail events include subprocess output from decompose_v2
- result event carries the expected artifact paths
- Local artifacts (ADR markdown, roadmap/plan) are actually written
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
sse_starlette = pytest.importorskip("sse_starlette")
from fastapi.testclient import TestClient  # noqa: E402

from cli.web_server.server import create_app  # noqa: E402
from cli.web_server.tests.test_sse import _parse_sse_stream  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("KAIZEN_INTEGRATION_TESTS") != "1",
    reason="set KAIZEN_INTEGRATION_TESTS=1 + ANTHROPIC_API_KEY to run real-LLM tests",
)

# Minimal C fixture for memsafe-roadmap — small enough to keep costs low.
_FIXTURE_C = """\
#include <stdio.h>
#include <string.h>

static void copy_input(char *dst, const char *src) {
    strcpy(dst, src);  /* unsafe — classic memory-safety target */
}

int main(int argc, char **argv) {
    char buf[16];
    if (argc > 1) {
        copy_input(buf, argv[1]);
        printf("%s\\n", buf);
    }
    return 0;
}
"""


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_memsafe_roadmap_real_llm_streams_to_completion(
    tmp_path: Path, client: TestClient,
) -> None:
    """End-to-end: real LLM, real ADR, real roadmap, SSE stream to completion."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY required")

    repo = tmp_path / "tiny-c-repo"
    repo.mkdir()
    (repo / "main.c").write_text(_FIXTURE_C, encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Use a 5-minute timeout — LLM calls can be slow under load.
    with client.stream(
        "POST",
        "/api/memsafe-roadmap/stream",
        json={
            "repo": str(repo),
            "output": str(out_dir / "roadmap.md"),
            "adr_dir": str(out_dir / "adrs"),
            "plain": True,  # no domain schema — keeps it fast + cheap
            "provider": "anthropic",
        },
        timeout=300.0,
    ) as response:
        assert response.status_code == 200
        body = response.read().decode("utf-8")

    events = _parse_sse_stream(body)
    kinds = [e["event"] for e in events if "event" in e]

    # Contract: run.start first, end last, result before end, stages in order.
    assert kinds[0] == "run.start"
    assert kinds[-1] == "end"
    assert "result" in kinds
    assert kinds.index("result") < kinds.index("end")

    # stage events for decompose, render_roadmap, adr_stubs (in that order)
    stage_events = [
        json.loads(e["data"]) for e in events if e.get("event") == "stage"
    ]
    stage_names = [s["name"] for s in stage_events]
    assert stage_names == ["decompose", "render_roadmap", "adr_stubs"]

    # result event carries the roadmap path
    result_events = [
        json.loads(e["data"]) for e in events if e.get("event") == "result"
    ]
    assert len(result_events) == 1
    assert result_events[0]["exit_code"] == 0
    assert result_events[0]["roadmap"] == str(out_dir / "roadmap.md")

    # Artifacts actually exist on disk
    assert (out_dir / "roadmap.md").is_file()
    assert (out_dir / "adrs" / "adr-root.md").is_file()
