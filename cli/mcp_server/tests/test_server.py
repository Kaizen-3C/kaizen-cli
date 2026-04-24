# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for kaizen_mcp.server.

Tests run the module-level async handler bodies directly rather than through
an MCP client round-trip -- that keeps them fast and avoids pulling in a
transport dependency for CI. The `create_server()` builder is exercised
separately to confirm the tool registry is wired up correctly.

All pipeline commands are invoked in `dry_run=True` mode, same trick
`kaizen_web/tests/test_routes.py` uses -- the CLI command short-circuits
before any LLM call, so the test suite is hermetic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")  # noqa: F841 -- whole module depends on mcp

from cli.mcp_server import server  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


# --- Tool-handler smoke tests (dry-run; no LLM calls) -----------------------


def test_decompose_dry_run(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("def f(): pass\n", encoding="utf-8")
    result = asyncio.run(server.decompose_tool(
        repo=str(tmp_path),
        source_language="Python",
        output=str(tmp_path / "adr.md"),
        dry_run=True,
    ))
    assert "error" not in result, result
    assert result["exit_code"] == 0
    # dry_run short-circuits before writing the ADR, so adr_path may be None.
    assert "events" in result


def test_decompose_rejects_missing_repo() -> None:
    result = asyncio.run(server.decompose_tool(
        repo=str(REPO_ROOT / "definitely" / "missing" / "xyzzy"),
        dry_run=True,
    ))
    assert "error" in result
    assert "exit_code" not in result  # short-circuit before invocation


def test_decompose_rejects_file_as_repo(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "a_file.py"
    not_a_dir.write_text("x=1\n", encoding="utf-8")
    result = asyncio.run(server.decompose_tool(
        repo=str(not_a_dir),
        dry_run=True,
    ))
    assert "error" in result
    assert "not a directory" in result["error"]


def test_recompose_dry_run(tmp_path: Path) -> None:
    adr = tmp_path / "adr.md"
    adr.write_text("# ADR\nstub\n", encoding="utf-8")
    result = asyncio.run(server.recompose_tool(
        adr=str(adr),
        output_dir=str(tmp_path / "out"),
        target_language="Python",
        dry_run=True,
    ))
    assert "error" not in result, result
    assert result["exit_code"] == 0


def test_recompose_rejects_missing_adr() -> None:
    result = asyncio.run(server.recompose_tool(
        adr=str(REPO_ROOT / "definitely" / "missing" / "adr.md"),
        dry_run=True,
    ))
    assert "error" in result


def test_memsafe_roadmap_dry_run(tmp_path: Path) -> None:
    (tmp_path / "src.c").write_text("int main(){return 0;}\n", encoding="utf-8")
    result = asyncio.run(server.memsafe_roadmap_tool(
        repo=str(tmp_path),
        output=str(tmp_path / "roadmap.md"),
        adr_dir=str(tmp_path / "adrs"),
        plain=True,
        dry_run=True,
    ))
    assert "error" not in result, result
    assert result["exit_code"] == 0


def test_memsafe_roadmap_rejects_missing_repo() -> None:
    result = asyncio.run(server.memsafe_roadmap_tool(
        repo=str(REPO_ROOT / "definitely" / "missing" / "xyzzy"),
        dry_run=True,
    ))
    assert "error" in result


def test_migrate_plan_dry_run(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('py2 code')\n", encoding="utf-8")
    result = asyncio.run(server.migrate_plan_tool(
        repo=str(tmp_path),
        from_fw="python2",
        to_fw="python3",
        output=str(tmp_path / "plan.md"),
        adr_dir=str(tmp_path / "adrs"),
        plain=True,
        dry_run=True,
    ))
    assert "error" not in result, result
    assert result["exit_code"] == 0


def test_migrate_plan_rejects_missing_repo() -> None:
    result = asyncio.run(server.migrate_plan_tool(
        repo=str(REPO_ROOT / "definitely" / "missing" / "xyzzy"),
        from_fw="python2",
        to_fw="python3",
        dry_run=True,
    ))
    assert "error" in result


# --- list_runs / read_adr -----------------------------------------------------


def test_list_runs_scans_case_studies() -> None:
    case_dir = REPO_ROOT / "docs" / "case-studies"
    if not case_dir.is_dir():
        pytest.skip("repo layout missing docs/case-studies/")
    result = server.list_runs_tool(path=str(case_dir), limit=3)
    assert "error" not in result, result
    assert result["count"] >= 1
    assert all(entry["name"].endswith(".md") for entry in result["artifacts"])


def test_list_runs_rejects_missing_path() -> None:
    result = server.list_runs_tool(path=str(REPO_ROOT / "nope" / "missing"))
    assert "error" in result


def test_list_runs_rejects_file_path(tmp_path: Path) -> None:
    f = tmp_path / "not-a-dir.md"
    f.write_text("x\n", encoding="utf-8")
    result = server.list_runs_tool(path=str(f))
    assert "error" in result
    assert "not a directory" in result["error"]


def test_read_adr_reads_markdown(tmp_path: Path) -> None:
    fixture = tmp_path / "ADR-test.md"
    fixture.write_text("# ADR-0001\n\nhello world\n", encoding="utf-8")
    result = server.read_adr_tool(path=str(fixture))
    assert "error" not in result, result
    assert result["path"] == str(fixture.resolve())
    assert "hello world" in result["contents"]
    assert result["size_bytes"] == fixture.stat().st_size


def test_read_adr_rejects_missing() -> None:
    result = server.read_adr_tool(path=str(Path("/definitely/missing/adr.md")))
    assert "error" in result


def test_read_adr_rejects_non_markdown(tmp_path: Path) -> None:
    wrong = tmp_path / "script.py"
    wrong.write_text("x=1\n", encoding="utf-8")
    result = server.read_adr_tool(path=str(wrong))
    assert "error" in result


# --- Truncation helper --------------------------------------------------------


def test_truncate_contents_passes_through_small_text(tmp_path: Path) -> None:
    text = "# small adr\n" * 10
    out = server._truncate_contents(text, tmp_path / "adr.md")
    assert out == text


def test_truncate_contents_truncates_large_text(tmp_path: Path) -> None:
    # > 100 KB so the truncation branch activates.
    text = "x" * (120 * 1024)
    path = tmp_path / "big.md"
    out = server._truncate_contents(text, path)
    assert len(out.encode("utf-8")) < len(text.encode("utf-8")) + 500
    assert "truncated" in out
    assert str(path) in out


# --- Server construction ------------------------------------------------------


def test_create_server_registers_all_tools() -> None:
    srv = server.create_server()
    tools = asyncio.run(srv.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "decompose",
        "recompose",
        "memsafe_roadmap",
        "migrate_plan",
        "list_runs",
        "read_adr",
    }


def test_create_server_is_importable_without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_server() must not touch ANTHROPIC_API_KEY / OPENAI_API_KEY at
    registration time -- keys only matter when a real tool call reaches the
    pipeline scripts. Mirrors the kaizen_web startup contract."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    srv = server.create_server()
    assert srv is not None
