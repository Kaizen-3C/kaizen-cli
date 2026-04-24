# SPDX-License-Identifier: Apache-2.0
"""MCP server that exposes kaizen pipeline commands as tools.

Architecturally this is a sibling of `kaizen_web`: a thin transport over the
same CLI command functions. Each MCP tool handler:

  1. Validates its inputs (returns a dict with an `error` field on failure --
     never raises into the client).
  2. Constructs an `argparse.Namespace` that matches the CLI command's
     expected shape (same pattern as `kaizen_web/routes/*.py:_request_to_namespace`).
  3. Invokes the `*_command(ns)` function on a worker thread via
     `asyncio.to_thread` -- the underlying command itself subprocesses the
     pipeline scripts, so no extra process management happens here.
  4. Returns a JSON-serializable dict with artifact paths, a bounded slice
     of contents, and the exit code.

Progress reporting: the mcp SDK's Context.report_progress hook is wired up
where a Context is available; as a pragmatic fallback for SDK versions
where injecting Context changes the schema, each handler also captures
`cli.events` emissions via `events.capture()` and attaches them as an
`events` field in the response. Clients can surface either.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from cli import __version__, events
from cli.commands.decompose import decompose_command
from cli.commands.memsafe_roadmap import memsafe_roadmap_command
from cli.commands.migrate_plan import migrate_plan_command
from cli.commands.recompose import recompose_command

try:  # The mcp extra may be absent in a minimum install.
    from mcp.server.fastmcp import FastMCP
except ImportError as _exc:  # pragma: no cover -- surfaced via mcp-serve entry point
    FastMCP = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR: Exception | None = _exc
else:
    _MCP_IMPORT_ERROR = None


_LOG = logging.getLogger("kaizen_mcp")

# Mirrors kaizen_web routes/runs.py -- keep in sync if those ever change.
_RUNS_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__",
    "node_modules", "venv", ".venv", "env",
    "target", "build", "dist", ".mypy_cache", ".pytest_cache",
}
_RUNS_INTERESTING_STEMS = ("roadmap", "plan", "adr-root", "adr-")

# Cap on how many bytes of file content we embed in a tool response. Clients
# display these inline, so large ADRs would blow out context windows.
_CONTENTS_MAX_BYTES = 100 * 1024  # 100 KB


# --- Helpers ----------------------------------------------------------------


def _truncate_contents(text: str, path: Path) -> str:
    """Return `text` unchanged if small, or a truncated version with a footer
    pointing at the on-disk file so clients can fetch the full content via
    `read_adr` or a shell tool."""
    encoded_size = len(text.encode("utf-8"))
    if encoded_size <= _CONTENTS_MAX_BYTES:
        return text
    # Truncate by character count keyed to the byte cap; this is approximate
    # for multibyte content and that's fine -- the footer explains.
    head = text[:_CONTENTS_MAX_BYTES]
    footer = (
        f"\n\n[truncated -- full file at {path}, size {encoded_size} bytes, "
        f"showing first {_CONTENTS_MAX_BYTES} bytes. Use the read_adr tool "
        "for the complete contents.]\n"
    )
    return head + footer


def _is_run_artifact(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    stem = path.stem.lower()
    return any(stem.startswith(s) or s in stem for s in _RUNS_INTERESTING_STEMS)


async def _run_command(
    command: Any, ns: argparse.Namespace
) -> tuple[int, list[dict]]:
    """Invoke a blocking `*_command(ns)` in a worker thread, capturing events.

    Returns `(exit_code, captured_events)`. Exceptions are converted into an
    error event and an exit_code of 1 -- the MCP tool handler surfaces them
    to the client as a normal response dict, never as a JSON-RPC error.
    """
    captured: list[dict] = []

    def _worker() -> int:
        with events.capture() as collected:
            try:
                rc = command(ns)
            except Exception as exc:  # noqa: BLE001 -- any failure becomes an event
                events.error(f"{exc.__class__.__name__}: {exc}")
                rc = 1
        captured.extend(collected)
        return int(rc) if isinstance(rc, int) else 0

    exit_code = await asyncio.to_thread(_worker)
    return exit_code, captured


def _validate_repo(repo: str) -> Optional[dict]:
    p = Path(repo).resolve()
    if not p.exists():
        return {"error": f"repo path does not exist: {p}"}
    if not p.is_dir():
        return {"error": f"repo path is not a directory: {p}"}
    return None


def _validate_adr(adr: str) -> Optional[dict]:
    p = Path(adr).resolve()
    if not p.exists():
        return {"error": f"ADR file does not exist: {p}"}
    if not p.is_file():
        return {"error": f"ADR path is not a regular file: {p}"}
    if p.suffix.lower() not in {".md", ".markdown", ".txt"}:
        return {"error": f"ADR path is not markdown/text: {p}"}
    return None


# --- Handler bodies (module-level so tests can import them directly) --------


async def decompose_tool(
    repo: str,
    source_language: str = "Python",
    domain: str = "none",
    provider: str = "anthropic",
    model: Optional[str] = None,
    output: str = "adr-root.md",
    glob: str = "*",
    temperature: float = 0.0,
    dry_run: bool = False,
) -> dict:
    """Decompose source -> ADR. Delegates to cli.commands.decompose."""
    err = _validate_repo(repo)
    if err is not None:
        return err

    ns = argparse.Namespace(
        repo=repo,
        output=output,
        adr_id=None,
        glob=glob,
        source_language=source_language,
        domain=domain,
        provider=provider,
        model=model,
        temperature=temperature,
        no_signatures=False,
        dry_run=dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="decompose",
    )
    exit_code, captured = await _run_command(decompose_command, ns)

    adr_path = Path(output).resolve()
    contents: Optional[str] = None
    size_bytes: Optional[int] = None
    if adr_path.is_file():
        try:
            raw = adr_path.read_text(encoding="utf-8")
            size_bytes = adr_path.stat().st_size
            contents = _truncate_contents(raw, adr_path)
        except OSError as exc:
            contents = None
            _LOG.warning("failed to read adr at %s: %s", adr_path, exc)

    return {
        "exit_code": exit_code,
        "adr_path": str(adr_path) if adr_path.exists() else None,
        "adr_contents": contents,
        "size_bytes": size_bytes,
        "events": captured,
    }


async def recompose_tool(
    adr: str,
    output_dir: str = "recomposed",
    target_language: str = "Python",
    domain: str = "none",
    provider: str = "anthropic",
    cross_language: bool = False,
    emit_tests: bool = False,
    dry_run: bool = False,
) -> dict:
    """Recompose ADR -> target code. Delegates to cli.commands.recompose."""
    err = _validate_adr(adr)
    if err is not None:
        return err

    ns = argparse.Namespace(
        adr=adr,
        output_dir=output_dir,
        target_language=target_language,
        cross_language=cross_language,
        emit_tests=emit_tests,
        max_tokens=8000,
        temperature=0.0,
        no_repair_syntax=False,
        target_python_version="3.9",
        domain=domain,
        provider=provider,
        model=None,
        dry_run=dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="recompose",
    )
    exit_code, captured = await _run_command(recompose_command, ns)

    out_dir = Path(output_dir).resolve()
    files: list[str] = []
    if out_dir.is_dir():
        files = sorted(str(p) for p in out_dir.rglob("*") if p.is_file())

    return {
        "exit_code": exit_code,
        "output_dir": str(out_dir) if out_dir.exists() else None,
        "file_count": len(files),
        "files": files[:50],
        "events": captured,
    }


async def memsafe_roadmap_tool(
    repo: str,
    plain: bool = False,
    recompose: bool = False,
    provider: str = "anthropic",
    model: Optional[str] = None,
    output: str = "roadmap.md",
    adr_dir: str = "adrs",
    rust_output: str = "rust-port",
    dry_run: bool = False,
) -> dict:
    """Generate a CISA memory-safety roadmap + per-module ADRs."""
    err = _validate_repo(repo)
    if err is not None:
        return err

    ns = argparse.Namespace(
        repo=repo,
        output=output,
        adr_dir=adr_dir,
        glob="*",
        plain=plain,
        recompose=recompose,
        rust_output=rust_output,
        provider=provider,
        model=model,
        dry_run=dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="memsafe-roadmap",
    )
    exit_code, captured = await _run_command(memsafe_roadmap_command, ns)

    roadmap_path = Path(output).resolve()
    adr_dir_path = Path(adr_dir).resolve()
    rust_path = Path(rust_output).resolve() if recompose else None

    adr_files: list[str] = []
    if adr_dir_path.is_dir():
        adr_files = sorted(str(p) for p in adr_dir_path.rglob("*.md"))

    return {
        "exit_code": exit_code,
        "roadmap_path": str(roadmap_path) if roadmap_path.exists() else None,
        "adr_dir": str(adr_dir_path) if adr_dir_path.exists() else None,
        "adr_files": adr_files,
        "rust_output": str(rust_path) if rust_path and rust_path.exists() else None,
        "events": captured,
    }


async def migrate_plan_tool(
    repo: str,
    from_fw: str,
    to_fw: str,
    plain: bool = False,
    recompose: bool = False,
    provider: str = "anthropic",
    model: Optional[str] = None,
    output: str = "plan.md",
    adr_dir: str = "adrs/",
    target_output: str = "migrated/",
    dry_run: bool = False,
) -> dict:
    """Generate a framework-migration plan + per-module ADRs."""
    err = _validate_repo(repo)
    if err is not None:
        return err

    ns = argparse.Namespace(
        repo=repo,
        from_fw=from_fw,
        to_fw=to_fw,
        output=output,
        adr_dir=adr_dir,
        glob=None,
        plain=plain,
        recompose=recompose,
        target_output=target_output,
        provider=provider,
        model=model,
        dry_run=dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="migrate-plan",
    )
    exit_code, captured = await _run_command(migrate_plan_command, ns)

    plan_path = Path(output).resolve()
    adr_dir_path = Path(adr_dir).resolve()
    target_path = Path(target_output).resolve() if recompose else None

    adr_files: list[str] = []
    if adr_dir_path.is_dir():
        adr_files = sorted(str(p) for p in adr_dir_path.rglob("*.md"))

    return {
        "exit_code": exit_code,
        "plan_path": str(plan_path) if plan_path.exists() else None,
        "adr_dir": str(adr_dir_path) if adr_dir_path.exists() else None,
        "adr_files": adr_files,
        "target_output": str(target_path) if target_path and target_path.exists() else None,
        "events": captured,
    }


def list_runs_tool(path: str = ".", limit: int = 50) -> dict:
    """Enumerate roadmap/plan/ADR markdown artifacts under a working directory.

    Mirrors /api/runs behavior -- same skip-dir set, same 'interesting stems'
    filter. Returned paths are absolute.
    """
    root = Path(path).resolve()
    if not root.exists():
        return {"error": f"path does not exist: {root}"}
    if not root.is_dir():
        return {"error": f"path is not a directory: {root}"}
    if limit < 1:
        return {"error": "limit must be >= 1"}
    limit = min(limit, 500)

    hits: list[Path] = []
    for p in root.rglob("*.md"):
        if any(part in _RUNS_SKIP_DIRS for part in p.parts):
            continue
        if _is_run_artifact(p):
            hits.append(p)
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    hits = hits[:limit]

    entries = [
        {
            "path": str(p),
            "name": p.name,
            "directory": str(p.parent),
            "size_bytes": p.stat().st_size,
            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(
                timespec="seconds"
            ),
        }
        for p in hits
    ]
    return {"scanned": str(root), "count": len(entries), "artifacts": entries}


def read_adr_tool(path: str) -> dict:
    """Return the full contents of an ADR markdown file. No truncation -- the
    client explicitly asked for it, so respect the request. Path must resolve
    to a regular file with a markdown-ish suffix (.md, .markdown, .txt)."""
    err = _validate_adr(path)
    if err is not None:
        return err
    resolved = Path(path).resolve()
    try:
        contents = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"failed to read ADR: {exc}"}
    return {
        "path": str(resolved),
        "contents": contents,
        "size_bytes": resolved.stat().st_size,
    }


# --- Server construction ----------------------------------------------------


def create_server() -> "FastMCP":
    """Build and return the FastMCP server with all tools registered.

    Importable from tests so individual tool registrations can be inspected
    without actually running the server. The command handlers invoked here
    do not require any LLM API key at registration time -- keys only matter
    when a real (non-dry-run) tool call reaches the pipeline scripts. This
    mirrors `kaizen_web.server.create_app`'s startup contract.
    """
    if FastMCP is None:
        raise ImportError(
            "cli.mcp_server.server requires the [mcp] optional dependency group. "
            "Install it with:  pip install 'kaizen-3c-cli[mcp]'"
        ) from _MCP_IMPORT_ERROR

    server = FastMCP(
        name="kaizen",
        instructions=(
            "Kaizen pipeline tools -- decompose source into ADRs, recompose "
            "ADRs into target code, and run the memory-safety and framework-"
            "migration wedges. Tools delegate to the same functions the "
            "`kaizen` CLI invokes; artifacts are written to the caller's "
            "working directory unless output paths are absolute."
        ),
    )

    server.add_tool(
        decompose_tool,
        name="decompose",
        description=(
            "Decompose a source repo into an ADR markdown. Wraps `kaizen "
            "decompose`. Set dry_run=True to validate the invocation without "
            "calling the LLM."
        ),
    )
    server.add_tool(
        recompose_tool,
        name="recompose",
        description=(
            "Recompose an ADR markdown into target-language source code. "
            "Wraps `kaizen recompose`. Set dry_run=True to validate inputs "
            "without invoking the pipeline."
        ),
    )
    server.add_tool(
        memsafe_roadmap_tool,
        name="memsafe_roadmap",
        description=(
            "Generate a CISA-aligned memory-safety roadmap and per-module "
            "ADR stubs for a C/C++ repo. Optionally recompose to Rust with "
            "`recompose=True`. Wraps `kaizen memsafe-roadmap`."
        ),
    )
    server.add_tool(
        migrate_plan_tool,
        name="migrate_plan",
        description=(
            "Generate a framework-migration plan and per-module ADR stubs "
            "for a legacy codebase (e.g. python2->python3, angularjs->react). "
            "Wraps `kaizen migrate-plan`."
        ),
    )
    server.add_tool(
        list_runs_tool,
        name="list_runs",
        description=(
            "List roadmap/plan/ADR markdown artifacts under a working "
            "directory, sorted by modification time descending. Mirrors the "
            "/api/runs route in kaizen_web."
        ),
    )
    server.add_tool(
        read_adr_tool,
        name="read_adr",
        description=(
            "Read the full contents of an ADR or plan/roadmap markdown file. "
            "Use this when a previous tool response was truncated."
        ),
    )

    return server


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point so `py -m kaizen_mcp.server` works standalone.

    The `kaizen mcp-serve` subcommand is the user-facing surface; this main
    function exists so the package can also be invoked via `-m` for
    debugging (e.g. when a client config points directly at the module)."""
    parser = argparse.ArgumentParser(
        prog="cli.mcp_server.server",
        description="Run the kaizen MCP server (stdio by default).",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=7866,
        help="Bind port for SSE transport (default: 7866)",
    )
    parser.add_argument("--version", action="version", version=f"kaizen_mcp {__version__}")
    args = parser.parse_args(argv)

    if FastMCP is None:
        print(
            "error: cli.mcp_server requires the [mcp] optional dependency group.\n"
            "       Install it with:  pip install 'kaizen-3c-cli[mcp]'",
            flush=True,
        )
        return 2

    server = create_server()
    if args.transport == "sse":
        # FastMCP reads host/port off its settings object; override before run.
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="sse")
    else:
        server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover -- exercised by mcp-serve / -m
    raise SystemExit(main())
