# SPDX-License-Identifier: Apache-2.0
"""FastAPI app factory for `kaizen web`.

Usage:
    from cli.web_server.server import create_app
    app = create_app()

Mounted surface:
    /api/*       — all route modules under cli.web_server.routes
    /healthz     — liveness probe (200 {"status": "ok"})
    /            — static SPA bundle if present, else JSON placeholder

No authentication. No multi-tenancy. Dev-local tool.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .settings import Settings

if TYPE_CHECKING:  # avoid hard dependency on fastapi at import time
    from fastapi import FastAPI

logger = logging.getLogger("kaizen_web")


def create_app(settings: Settings | None = None) -> "FastAPI":
    """Build the FastAPI application.

    Import of `fastapi` is intentionally deferred so that `import cli.web_server`
    in a base (non-[web]) install does not fail. The cost is paid only when
    someone actually invokes `kaizen web`.
    """
    try:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover — exercised in non-[web] installs
        raise RuntimeError(
            "kaizen web requires the [web] optional dependency group. "
            "Install it with:  pip install 'kaizen-3c-cli[web]'"
        ) from exc

    settings = settings or Settings.from_env()

    app = FastAPI(
        title="kaizen web",
        version=__import__("cli.web_server", fromlist=["__version__"]).__version__,
        description="Lite web UI for kaizen-3c-cli. Developer-local tool; no authentication.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    # --- Routes ---
    from .routes import adr, decompose, memsafe, migrate, priors, providers, recompose, runs, status, version

    app.include_router(version.router, prefix="/api")
    app.include_router(providers.router, prefix="/api")
    app.include_router(status.router, prefix="/api")
    app.include_router(priors.router, prefix="/api")
    app.include_router(decompose.router, prefix="/api")
    app.include_router(recompose.router, prefix="/api")
    app.include_router(memsafe.router, prefix="/api")
    app.include_router(migrate.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(adr.router, prefix="/api")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # --- Static SPA bundle (ui-lite) ---
    static_dir = settings.resolve_static_dir()
    if static_dir is not None:
        # Mount at `/` so the SPA router controls path resolution; unresolved
        # routes fall through to 404 from StaticFiles.
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui-lite")
        logger.info("Serving SPA bundle from %s", static_dir)
    else:
        @app.get("/")
        def _placeholder() -> JSONResponse:
            return JSONResponse({
                "name": "kaizen web",
                "version": app.version,
                "status": "API only — ui-lite SPA bundle not found",
                "hint": "This install has no SPA bundled. Use the API at /api/docs,"
                        " or see docs/release/UI_LITE_CARVE_OUT.md to build ui-lite.",
                "api_docs": "/api/docs",
            })

    return app
