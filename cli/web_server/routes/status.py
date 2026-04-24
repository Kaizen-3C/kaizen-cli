# SPDX-License-Identifier: Apache-2.0
"""GET /api/status — summarize recent Kaizen runs under a given path.

Returns the same data `kaizen status` prints, in structured JSON. Delegates
to the same helpers in cli.commands.status so there is no reimplementation
of the scan or trajectory logic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from cli.commands.status import _latest, _last_trajectory, _scan

router = APIRouter(tags=["status"])


@router.get("/status")
def get_status(path: str = Query(default=".", description="Directory to scan")) -> dict:
    root = Path(path).resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail=f"path does not exist: {root}")

    obs_files = _scan(root, "taor_observations.jsonl")
    priors_files = _scan(root, "priors.json")

    if not obs_files and not priors_files:
        return {"path": str(root), "found": False, "message": "No Kaizen runs detected"}

    result: dict[str, object] = {"path": str(root), "found": True}

    latest_obs = _latest(obs_files)
    if latest_obs:
        traj = _last_trajectory(latest_obs)
        result["latest_observations"] = {
            "path": str(latest_obs),
            "modified": datetime.fromtimestamp(latest_obs.stat().st_mtime).isoformat(timespec="seconds"),
            "trajectory": traj,
        }

    latest_priors = _latest(priors_files)
    if latest_priors:
        result["latest_priors"] = {
            "path": str(latest_priors),
            "modified": datetime.fromtimestamp(latest_priors.stat().st_mtime).isoformat(timespec="seconds"),
        }

    result["counts"] = {
        "observations": len(obs_files),
        "priors": len(priors_files),
    }
    return result
