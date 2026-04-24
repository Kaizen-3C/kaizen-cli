# SPDX-License-Identifier: Apache-2.0
"""GET /api/runs — list recent roadmap/plan/ADR artifacts under a working directory.

Complements /api/status (which is focused on observations + priors). This
route enumerates the files the lite UI's RunsListPage needs to render:
- *.md files that look like roadmaps, plans, or ADR stubs
- grouped by parent directory, sorted by mtime descending
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["artifacts"])

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__",
    "node_modules", "venv", ".venv", "env",
    "target", "build", "dist", ".mypy_cache", ".pytest_cache",
}

_INTERESTING_STEMS = (
    "roadmap",
    "plan",
    "adr-root",
    "adr-",
)


def _is_artifact(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    stem = path.stem.lower()
    return any(stem.startswith(s) or s in stem for s in _INTERESTING_STEMS)


@router.get("/runs")
def list_runs(
    path: str = Query(default=".", description="Directory to scan"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    root = Path(path).resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail=f"path does not exist: {root}")

    hits: list[Path] = []
    for p in root.rglob("*.md"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if _is_artifact(p):
            hits.append(p)

    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    hits = hits[:limit]

    entries = [
        {
            "path": str(p),
            "name": p.name,
            "directory": str(p.parent),
            "size_bytes": p.stat().st_size,
            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        }
        for p in hits
    ]
    return {"scanned": str(root), "count": len(entries), "artifacts": entries}
