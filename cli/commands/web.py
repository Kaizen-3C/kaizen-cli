# SPDX-License-Identifier: Apache-2.0
"""`kaizen web` — start the lite web UI (FastAPI + optional SPA bundle).

Requires the `[web]` optional dependency group:
    pip install 'kaizen-cli[web]'

Runs uvicorn on 127.0.0.1:7865 by default. See
`docs/release/UI_LITE_CARVE_OUT.md` for the full design.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser

from .. import output
from ..output import Style


def add_web_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "web",
        help="Start the lite web UI (requires `pip install 'kaizen-cli[web]'`)",
        description=(
            "Start the kaizen lite web UI: a local FastAPI server that surfaces the "
            "same pipeline capabilities as the CLI, via a browser. Dev-local tool with "
            "no authentication. For multi-user / audit / approval surfaces, use the "
            "Kaizen Enterprise UI (Commercial)."
        ),
    )
    p.add_argument("--host", default="127.0.0.1",
                   help="Bind host (default: 127.0.0.1). Use 0.0.0.0 to expose on the network — insecure.")
    p.add_argument("--port", type=int, default=7865,
                   help="Bind port (default: 7865)")
    p.add_argument("--open", action="store_true",
                   help="Open the default browser to the UI after the server is ready")
    p.add_argument("--log-level", default="info",
                   choices=["critical", "error", "warning", "info", "debug", "trace"],
                   help="Uvicorn log level (default: info)")
    p.add_argument("--reload", action="store_true",
                   help="Auto-reload on source changes (development only)")
    return p


def web_command(args: argparse.Namespace) -> int:
    style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        output.error(
            style,
            "kaizen web requires the [web] optional dependency group. "
            "Install it with:  pip install 'kaizen-cli[web]'",
        )
        return 2

    try:
        from cli.web_server.server import create_app
        from cli.web_server.settings import Settings
    except ImportError as exc:
        output.error(style, f"failed to import cli.web_server: {exc}")
        return 2

    settings = Settings.from_env(host=args.host, port=args.port)

    if settings.is_public_bind():
        print(style.bold("  ⚠  WARNING: binding to a non-loopback host"), file=sys.stderr)
        print("     The kaizen web UI has no authentication. Do NOT run it on an", file=sys.stderr)
        print("     untrusted network. For shared deployments, use the Kaizen", file=sys.stderr)
        print("     Enterprise UI (Commercial).", file=sys.stderr)
        print(file=sys.stderr)

    static_dir = settings.resolve_static_dir()
    if static_dir is None:
        print(style.dim(
            "  (no ui-lite SPA bundle found; serving API only. Build ui-lite/ and "
            "re-run, or `pip install kaizen-cli[web]` from a wheel that bundles it.)"
        ), file=sys.stderr)

    url = f"http://{settings.host}:{settings.port}/"
    print(f"{style.bold('kaizen web')}  listening on  {style.bold(url)}")
    print(f"  API docs:  {url}api/docs")
    print()

    if args.open:
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover — best effort
            pass

    # Deferred import; create_app fails clearly if fastapi isn't installed.
    app = create_app(settings)

    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=args.log_level,
        reload=args.reload,
    )
    return 0
