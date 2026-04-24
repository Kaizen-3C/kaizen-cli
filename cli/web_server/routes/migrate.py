# SPDX-License-Identifier: Apache-2.0
"""POST /api/migrate-plan — run `kaizen migrate-plan` via HTTP.

Same pattern as memsafe.py: constructs an argparse.Namespace and calls the
existing CLI command function in a threadpool.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from cli.commands.migrate_plan import migrate_plan_command
from cli.web_server.sse import stream_command_events

router = APIRouter(tags=["wedges"])


# Keep aligned with _SUPPORTED_PAIRS in cli/commands/migrate_plan.py.
_FROM_FW = Literal[
    "angularjs", "jquery", "dotnet-framework", "python2", "spring4", "java8",
]
_TO_FW = Literal[
    "angular", "react", "dotnet8", "dotnet9", "python3", "spring-boot3",
    "java17", "java21",
]


class MigratePlanRequest(BaseModel):
    repo: str = Field(..., description="Path to the source repo to plan a migration for")
    from_fw: _FROM_FW = Field(..., alias="from")
    to_fw: _TO_FW = Field(..., alias="to")
    output: str = Field("plan.md", description="Output path for the migration plan markdown")
    adr_dir: str = Field("adrs/", description="Directory for per-module ADR stubs")
    glob: Optional[str] = Field(None, description="Override source file filter glob")
    plain: bool = Field(False, description="Skip the framework-migration domain schema (baseline arm)")
    recompose: bool = Field(False, description="Recompose the target codebase after planning")
    target_output: str = Field("migrated/", description="Output dir for recomposed target code")
    provider: Literal["anthropic", "openai", "ollama", "litellm", "mixed"] = "anthropic"
    model: Optional[str] = Field(None, description="Override provider default model")
    dry_run: bool = Field(False, description="Print the resolved plan and exit without running")

    model_config = {"populate_by_name": True}


class MigratePlanResponse(BaseModel):
    exit_code: int
    plan_path: Optional[str] = None
    plan_contents: Optional[str] = None
    adr_dir: Optional[str] = None
    adr_files: list[str] = Field(default_factory=list)
    target_output: Optional[str] = None


def _request_to_namespace(req: MigratePlanRequest) -> argparse.Namespace:
    return argparse.Namespace(
        repo=req.repo,
        from_fw=req.from_fw,
        to_fw=req.to_fw,
        output=req.output,
        adr_dir=req.adr_dir,
        glob=req.glob,
        plain=req.plain,
        recompose=req.recompose,
        target_output=req.target_output,
        provider=req.provider,
        model=req.model,
        dry_run=req.dry_run,
        format="human",
        no_color=True,
        verbose=False,
        command="migrate-plan",
    )


def _collect_results(req: MigratePlanRequest, exit_code: int) -> MigratePlanResponse:
    plan_path = Path(req.output).resolve()
    adr_dir = Path(req.adr_dir).resolve()
    target_out = Path(req.target_output).resolve() if req.recompose else None

    plan_contents: Optional[str] = None
    if plan_path.is_file():
        try:
            plan_contents = plan_path.read_text(encoding="utf-8")
        except OSError:
            plan_contents = None

    adr_files: list[str] = []
    if adr_dir.is_dir():
        adr_files = sorted(str(p) for p in adr_dir.rglob("*.md"))

    return MigratePlanResponse(
        exit_code=exit_code,
        plan_path=str(plan_path) if plan_path.exists() else None,
        plan_contents=plan_contents,
        adr_dir=str(adr_dir) if adr_dir.exists() else None,
        adr_files=adr_files,
        target_output=str(target_out) if target_out and target_out.exists() else None,
    )


@router.post("/migrate-plan", response_model=MigratePlanResponse)
async def run_migrate_plan(req: MigratePlanRequest) -> MigratePlanResponse:
    """Blocking mode — runs to completion then returns the artifact summary.

    For progressive feedback, use the SSE variant at POST /api/migrate-plan/stream.
    """
    if not Path(req.repo).resolve().is_dir():
        raise HTTPException(status_code=400, detail=f"repo path does not exist or is not a directory: {req.repo}")

    ns = _request_to_namespace(req)
    exit_code = await run_in_threadpool(migrate_plan_command, ns)
    return _collect_results(req, exit_code)


@router.post("/migrate-plan/stream")
async def stream_migrate_plan(req: MigratePlanRequest):
    """SSE variant — yields `cli.events` emissions as Server-Sent Events.

    See /api/memsafe-roadmap/stream for the event-stream contract.
    """
    from sse_starlette.sse import EventSourceResponse

    if not Path(req.repo).resolve().is_dir():
        raise HTTPException(status_code=400, detail=f"repo path does not exist or is not a directory: {req.repo}")

    ns = _request_to_namespace(req)
    return EventSourceResponse(stream_command_events(migrate_plan_command, ns))
