# SPDX-License-Identifier: Apache-2.0
"""kaizen_mcp -- expose Kaizen pipeline commands as an MCP server.

The package presents the same decompose/recompose/memsafe-roadmap/migrate-plan
surface the CLI exposes, but packaged as Model Context Protocol tools so
Claude Desktop, Cursor, Zed, and similar clients can invoke them directly.

Invariant (restated from docs/release/UI_LITE_CARVE_OUT.md): this package
does NOT re-implement pipeline logic. Tool handlers construct an
argparse.Namespace and call the existing `cli.commands.*` functions in a
worker thread, exactly as `kaizen_web/routes/*.py` does. If the CLI, web
UI, and MCP server emit different artifacts for the same inputs, that is
a bug -- they share one code path.
"""

from __future__ import annotations

from cli import __version__ as __version__

__all__ = ["__version__"]
