# SPDX-License-Identifier: Apache-2.0
"""GET /api/priors — read a Thompson priors file.
POST /api/priors/reset — delete a Thompson priors file (guarded by confirm=True).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["priors"])

_DEFAULT_PRIORS_PATH = "priors.json"


class ResetRequest(BaseModel):
    path: str = _DEFAULT_PRIORS_PATH
    confirm: bool = False


@router.get("/priors")
def get_priors(path: str = Query(default=_DEFAULT_PRIORS_PATH)) -> dict:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"priors file not found at {resolved}")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"failed to read priors: {exc}") from exc
    return {"path": str(resolved), "priors": data}


@router.post("/priors/reset")
def reset_priors(req: ResetRequest) -> dict:
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="destructive — pass confirm=true in the request body to proceed",
        )
    resolved = Path(req.path).resolve()
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"priors file not found at {resolved}")
    try:
        resolved.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to delete priors: {exc}") from exc
    return {"path": str(resolved), "deleted": True}
