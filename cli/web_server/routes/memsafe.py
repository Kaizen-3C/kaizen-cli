# SPDX-License-Identifier: Apache-2.0
"""POST /api/memsafe-roadmap — run `kaizen memsafe-roadmap` via HTTP.

The route constructs an argparse.Namespace mirroring the CLI arguments, runs
the SAME function the CLI invokes (`memsafe_roadmap_command`), and returns
the produced artifact paths and contents.

This is deliberately the same code path as the CLI. If the CLI and this
route produce different ADRs for the same inputs, that is a bug.

Milestone 1: blocking call; stdout is discarded. Streaming (SSE) comes
in a follow-up that captures stdout line-by-line via subprocess PIPE.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from cli.commands.memsafe_roadmap import memsafe_roadmap_command
from cli.web_server.sse import stream_command_events

router = APIRouter(tags=["wedges"])


class MemsafeRoadmapRequest(BaseModel):
    repo: str = Field(..., description="Path to the C/C++ repo to analyze")
    output: str = Field("roadmap.md", description="Output path for the CISA roadmap markdown")
    adr_dir: str = Field("adrs", description="Directory for ADR stubs")
    glob: str = Field("*", description="Source file filter glob")
    plain: bool = Field(False, description="Skip the memory-safe domain schema (baseline arm)")
    recompose: bool = Field(False, description="Recompose to a Rust crate after planning")
    rust_output: str = Field("rust-port", description="Output dir for recomposed Rust crate")
    provider: Literal["anthropic", "openai", "ollama", "litellm", "mixed"] = "anthropic"
    model: Optional[str] = Field(None, description="Override provider default model")
    dry_run: bool = Field(False, description="Print the resolved plan and exit without running")


class MemsafeRoadmapResponse(BaseModel):
    exit_code: int
    roadmap_path: Optional[str] = None
    roadmap_contents: Optional[str] = None
    adr_dir: Optional[str] = None
    adr_files: list[str] = Field(default_factory=list)
    rust_output: Optional[str] = None


def _request_to_namespace(req: MemsafeRoadmapRequest) -> argparse.Namespace:
    return argparse.Namespace(
        repo=req.repo,
        output=req.output,
        adr_dir=req.adr_dir,
        glob=req.glob,
        plain=req.plain,
        recompose=req.recompose,
        rust_output=req.rust_output,
        provider=req.provider,
        model=req.model,
        dry_run=req.dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="memsafe-roadmap",
    )


def _collect_results(req: MemsafeRoadmapRequest, exit_code: int) -> MemsafeRoadmapResponse:
    roadmap_path = Path(req.output).resolve()
    adr_dir = Path(req.adr_dir).resolve()
    rust_out = Path(req.rust_output).resolve() if req.recompose else None

    roadmap_contents: Optional[str] = None
    if roadmap_path.is_file():
        try:
            roadmap_contents = roadmap_path.read_text(encoding="utf-8")
        except OSError:
            roadmap_contents = None

    adr_files: list[str] = []
    if adr_dir.is_dir():
        adr_files = sorted(str(p) for p in adr_dir.rglob("*.md"))

    return MemsafeRoadmapResponse(
        exit_code=exit_code,
        roadmap_path=str(roadmap_path) if roadmap_path.exists() else None,
        roadmap_contents=roadmap_contents,
        adr_dir=str(adr_dir) if adr_dir.exists() else None,
        adr_files=adr_files,
        rust_output=str(rust_out) if rust_out and rust_out.exists() else None,
    )


@router.post("/memsafe-roadmap", response_model=MemsafeRoadmapResponse)
async def run_memsafe_roadmap(req: MemsafeRoadmapRequest) -> MemsafeRoadmapResponse:
    """Blocking mode — runs to completion then returns the artifact summary.

    For progressive feedback during a multi-minute LLM run, use the SSE
    variant at GET /api/memsafe-roadmap/stream.
    """
    if not Path(req.repo).resolve().is_dir():
        raise HTTPException(status_code=400, detail=f"repo path does not exist or is not a directory: {req.repo}")

    ns = _request_to_namespace(req)
    exit_code = await run_in_threadpool(memsafe_roadmap_command, ns)
    return _collect_results(req, exit_code)


@router.post("/memsafe-roadmap/stream")
async def stream_memsafe_roadmap(req: MemsafeRoadmapRequest):
    """SSE variant — yields `cli.events` emissions as Server-Sent Events.

    Event stream contract (see cli/events.py):
        event: run.start    data: {"kind":"run.start","command":"memsafe-roadmap", ...}
        event: stage        data: {"kind":"stage","name":"decompose","index":1,"total":3}
        event: detail       data: {"kind":"detail","message":"...","source":"decompose"}
        event: stage.done   data: {"kind":"stage.done","name":"decompose","adr_path":"..."}
        ...
        event: result       data: {"kind":"result","exit_code":0, ...}
        event: end          data: {"kind":"end","exit_code":0}

    The worker thread continues to completion if the client disconnects —
    wedges produce local artifacts regardless of whether the browser is
    listening. See kaizen_web/sse.py for the streaming-contract rationale.
    """
    # Deferred import keeps sse-starlette optional at top-level import time
    # — the base install without [web] still imports the package cleanly.
    from sse_starlette.sse import EventSourceResponse

    if not Path(req.repo).resolve().is_dir():
        raise HTTPException(status_code=400, detail=f"repo path does not exist or is not a directory: {req.repo}")

    ns = _request_to_namespace(req)
    return EventSourceResponse(stream_command_events(memsafe_roadmap_command, ns))
