# SPDX-License-Identifier: Apache-2.0
"""GET /api/version — return the kaizen-cli version."""

from __future__ import annotations

from fastapi import APIRouter

from cli import __version__

router = APIRouter(tags=["meta"])


@router.get("/version")
def get_version() -> dict[str, str]:
    return {"version": __version__, "name": "kaizen-cli"}
