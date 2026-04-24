# SPDX-License-Identifier: Apache-2.0
"""POST /api/decompose + /api/decompose/stream.

Calls `cli.commands.decompose.decompose_command` — the same function that
`kaizen decompose` invokes. Event schema for the SSE variant is identical
to the wedge routes; see cli/events.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from cli.commands.decompose import decompose_command
from cli.web_server.sse import stream_command_events

router = APIRouter(tags=["pipeline"])


class DecomposeRequest(BaseModel):
    repo: str = Field(..., description="Path to the source repo")
    output: str = Field("adr-root.md", description="Output path for the ADR markdown")
    adr_id: Optional[str] = Field(None, description="ADR id (default: derived from repo dir name)")
    glob: str = Field("*", description="Source file filter glob")
    source_language: str = Field("Python", description="Source language label (Python, C, C++, JavaScript, etc.)")
    domain: Literal["none", "memory-safe", "framework-migration"] = "none"
    provider: Literal["anthropic", "openai"] = "anthropic"
    model: Optional[str] = None
    temperature: float = 0.0
    no_signatures: bool = False
    dry_run: bool = False


class DecomposeResponse(BaseModel):
    exit_code: int
    adr_path: Optional[str] = None
    adr_contents: Optional[str] = None
    adr_id: Optional[str] = None
    size_bytes: Optional[int] = None


def _request_to_namespace(req: DecomposeRequest) -> argparse.Namespace:
    return argparse.Namespace(
        repo=req.repo,
        output=req.output,
        adr_id=req.adr_id,
        glob=req.glob,
        source_language=req.source_language,
        domain=req.domain,
        provider=req.provider,
        model=req.model,
        temperature=req.temperature,
        no_signatures=req.no_signatures,
        dry_run=req.dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="decompose",
    )


def _collect_results(req: DecomposeRequest, exit_code: int) -> DecomposeResponse:
    adr_path = Path(req.output).resolve()
    contents: Optional[str] = None
    size_bytes: Optional[int] = None
    if adr_path.is_file():
        try:
            contents = adr_path.read_text(encoding="utf-8")
            size_bytes = adr_path.stat().st_size
        except OSError:
            contents = None

    return DecomposeResponse(
        exit_code=exit_code,
        adr_path=str(adr_path) if adr_path.exists() else None,
        adr_contents=contents,
        adr_id=req.adr_id,
        size_bytes=size_bytes,
    )


@router.post("/decompose", response_model=DecomposeResponse)
async def run_decompose(req: DecomposeRequest) -> DecomposeResponse:
    """Blocking variant — runs to completion and returns the ADR summary.

    For progressive feedback, POST to /api/decompose/stream instead.
    """
    if not Path(req.repo).resolve().is_dir():
        raise HTTPException(status_code=400, detail=f"repo path does not exist or is not a directory: {req.repo}")

    ns = _request_to_namespace(req)
    exit_code = await run_in_threadpool(decompose_command, ns)
    return _collect_results(req, exit_code)


@router.post("/decompose/stream")
async def stream_decompose(req: DecomposeRequest):
    """SSE variant — yields `cli.events` emissions as Server-Sent Events."""
    from sse_starlette.sse import EventSourceResponse

    if not Path(req.repo).resolve().is_dir():
        raise HTTPException(status_code=400, detail=f"repo path does not exist or is not a directory: {req.repo}")

    ns = _request_to_namespace(req)
    return EventSourceResponse(stream_command_events(decompose_command, ns))
