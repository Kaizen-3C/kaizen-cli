# SPDX-License-Identifier: Apache-2.0
"""`kaizen mcp-serve` -- run the MCP server that exposes pipeline tools.

Requires the `[mcp]` optional dependency group:
    pip install 'kaizen-3c-cli[mcp]'

Defaults to stdio transport so Claude Desktop / Cursor / Zed can spawn the
process directly; `--transport sse` exposes an HTTP surface on a
configurable port (7866 by default -- one higher than the web UI's 7865).

See `cli/mcp_server/server.py` for the tool set. Startup mirrors `kaizen web`:
the server is constructible without any LLM API key -- keys only matter at
tool-call time, and the error surfaces in the pipeline subprocess, not
here.
"""

from __future__ import annotations

import argparse
import sys

from .. import output
from ..output import Style


def add_mcp_serve_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "mcp-serve",
        help="Run the kaizen Model Context Protocol server (requires `pip install 'kaizen-3c-cli[mcp]'`)",
        description=(
            "Start an MCP server that exposes kaizen's pipeline commands (decompose, "
            "recompose, memsafe-roadmap, migrate-plan) as tools for MCP-capable AI "
            "clients -- Claude Desktop, Cursor, Zed, and others. Tool handlers call "
            "the SAME Python functions the CLI uses, so behavior stays in lockstep."
        ),
    )
    p.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help=(
            "Transport protocol. 'stdio' (default) is what most MCP clients spawn "
            "directly via a command entry. 'sse' exposes an HTTP endpoint for "
            "clients that prefer a network transport."
        ),
    )
    p.add_argument(
        "--host", default="127.0.0.1",
        help="Bind host for --transport sse (default: 127.0.0.1). Loopback only by default.",
    )
    p.add_argument(
        "--port", type=int, default=7866,
        help="Bind port for --transport sse (default: 7866 -- one above the web UI's 7865)",
    )
    return p


def _print_banner(style: Style, transport: str, host: str, port: int) -> None:
    """Short startup banner with configuration hints for MCP clients.

    For stdio transport the banner goes to stderr so it never pollutes the
    JSON-RPC stream on stdout. For SSE the banner goes to stdout since
    stdout is free.
    """
    stream = sys.stderr if transport == "stdio" else sys.stdout
    print(style.bold("kaizen mcp-serve"), file=stream)
    if transport == "stdio":
        print("  transport: stdio (JSON-RPC over stdin/stdout)", file=stream)
        print(
            "  Configure your MCP client (Claude Desktop, Cursor, Zed, ...) to spawn:",
            file=stream,
        )
        print("      kaizen mcp-serve", file=stream)
        print(
            "  e.g. in Claude Desktop's claude_desktop_config.json:",
            file=stream,
        )
        print('      "kaizen": { "command": "kaizen", "args": ["mcp-serve"] }', file=stream)
    else:
        print(f"  transport: sse  listening on  http://{host}:{port}/sse", file=stream)
        print(
            "  Configure your MCP client to connect via SSE to the URL above.",
            file=stream,
        )
    print("", file=stream)


def mcp_serve_command(args: argparse.Namespace) -> int:
    style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)

    # Deferred import: keeps `kaizen --help` fast and allows the error path
    # to be tested without actually having `mcp` installed.
    try:
        import mcp  # noqa: F401 -- availability probe
    except ImportError:
        output.error(
            style,
            "kaizen mcp-serve requires the [mcp] optional dependency group. "
            "Install it with:  pip install 'kaizen-3c-cli[mcp]'",
        )
        return 2

    try:
        from cli.mcp_server.server import create_server
    except ImportError as exc:
        output.error(style, f"failed to import cli.mcp_server: {exc}")
        return 2

    _print_banner(style, args.transport, args.host, args.port)

    server = create_server()
    if args.transport == "sse":
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="sse")
    else:
        server.run(transport="stdio")
    return 0
