# SPDX-License-Identifier: Apache-2.0
"""GET /api/adr — read a single ADR markdown file by path.

Scoped to the user's explicit path input. No server-side storage; the web UI
simply displays what is on disk. Includes a minimal path-traversal guard:
the resolved path must be a regular file and readable, and the response sets
the MIME type text/markdown.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["artifacts"])


@router.get("/adr", response_class=PlainTextResponse)
def get_adr(
    path: str = Query(..., description="Absolute or relative path to an ADR markdown file"),
) -> PlainTextResponse:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"ADR not found at {resolved}")
    if resolved.suffix.lower() not in {".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=415, detail="only markdown or plain-text files supported")
    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to read ADR: {exc}") from exc
    return PlainTextResponse(content=content, media_type="text/markdown")
