# SPDX-License-Identifier: Apache-2.0
"""POST /api/recompose + /api/recompose/stream.

Calls `cli.commands.recompose.recompose_command` — the same function
`kaizen recompose` invokes. Pattern mirrors /api/decompose.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from cli.commands.recompose import recompose_command
from cli.web_server.sse import stream_command_events

router = APIRouter(tags=["pipeline"])


class RecomposeRequest(BaseModel):
    adr: str = Field(..., description="Path to the ADR markdown to recompose")
    output_dir: str = Field("recomposed", description="Output directory for recomposed source")
    target_language: str = Field("Python", description="Target implementation language")
    cross_language: bool = Field(False, description="Enable cross-language translation mode")
    emit_tests: bool = Field(False, description="Hint the model to emit tests alongside impl")
    max_tokens: int = Field(8000, description="Max LLM output tokens")
    temperature: float = Field(0.0, description="LLM sampling temperature")
    no_repair_syntax: bool = Field(False, description="Skip one-shot repair retry for syntax errors")
    target_python_version: str = Field("3.9", description="Target Python version (3.9, 3.10, etc.)")
    domain: Literal["none", "memory-safe", "framework-migration"] = "none"
    provider: Literal["anthropic", "openai"] = "anthropic"
    model: Optional[str] = None
    dry_run: bool = False


class RecomposeResponse(BaseModel):
    exit_code: int
    output_dir: Optional[str] = None
    file_count: int = 0
    files: list[str] = Field(default_factory=list)


def _request_to_namespace(req: RecomposeRequest) -> argparse.Namespace:
    return argparse.Namespace(
        adr=req.adr,
        output_dir=req.output_dir,
        target_language=req.target_language,
        cross_language=req.cross_language,
        emit_tests=req.emit_tests,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        no_repair_syntax=req.no_repair_syntax,
        target_python_version=req.target_python_version,
        domain=req.domain,
        provider=req.provider,
        model=req.model,
        dry_run=req.dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="recompose",
    )


def _collect_results(req: RecomposeRequest, exit_code: int) -> RecomposeResponse:
    output_dir = Path(req.output_dir).resolve()
    files: list[str] = []
    if output_dir.is_dir():
        files = sorted(str(p) for p in output_dir.rglob("*") if p.is_file())
    return RecomposeResponse(
        exit_code=exit_code,
        output_dir=str(output_dir) if output_dir.exists() else None,
        file_count=len(files),
        files=files[:200],
    )


@router.post("/recompose", response_model=RecomposeResponse)
async def run_recompose(req: RecomposeRequest) -> RecomposeResponse:
    """Blocking variant — runs to completion then returns produced file list.

    For progressive feedback use POST /api/recompose/stream.
    """
    if not Path(req.adr).resolve().is_file():
        raise HTTPException(status_code=400, detail=f"ADR file not found: {req.adr}")

    ns = _request_to_namespace(req)
    exit_code = await run_in_threadpool(recompose_command, ns)
    return _collect_results(req, exit_code)


@router.post("/recompose/stream")
async def stream_recompose(req: RecomposeRequest):
    """SSE variant — yields `cli.events` emissions as Server-Sent Events."""
    from sse_starlette.sse import EventSourceResponse

    if not Path(req.adr).resolve().is_file():
        raise HTTPException(status_code=400, detail=f"ADR file not found: {req.adr}")

    ns = _request_to_namespace(req)
    return EventSourceResponse(stream_command_events(recompose_command, ns))
