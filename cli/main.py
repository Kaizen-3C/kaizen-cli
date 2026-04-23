# SPDX-License-Identifier: Apache-2.0
"""kaizen — top-level CLI entry point.

Dispatches to the subcommand modules under `cli.commands`. Stdlib only.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from cli import __version__
from cli.commands.decompose import add_decompose_parser, decompose_command
from cli.commands.recompose import add_recompose_parser, recompose_command
from cli.commands.memsafe_roadmap import (
    add_memsafe_roadmap_parser,
    memsafe_roadmap_command,
)
from cli.commands.migrate_plan import (
    add_migrate_plan_parser,
    migrate_plan_command,
)
from cli.commands.init import add_init_parser, init_command
from cli.commands.mcp_serve import add_mcp_serve_parser, mcp_serve_command
from cli.commands.priors import add_priors_parser, priors_command
from cli.commands.resume import add_resume_parser, resume_command
from cli.commands.status import add_status_parser, status_command
from cli.commands.web import add_web_parser, web_command
from cli.commands.bench import add_bench_parser, bench_command
from cli.commands.demo import add_demo_parser, demo_command
from cli.output import Style, error

# Note: `kaizen run` (the pre-reframe generic bootstrap orchestrator under
# cli/commands/run.py) is intentionally NOT registered in v0.3.0. It imports
# from `agents.src.bootstrap_orchestrator`, and the transitive closure of
# that module is not shipped in the PyPI wheel (see pyproject.toml
# packages.find). The Phase B wedges (memsafe-roadmap, migrate-plan) and
# the primitives (decompose, recompose) cover the public surface; `kaizen
# run` stays in kaizen-delta for dev use. If we later decide to ship it,
# either add `agents*` to packages.find or refactor run.py to use the
# decompose/recompose pipeline directly.


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kaizen",
        description="Kaizen CD-AOR CLI — architecture-aware autonomous code engineering",
    )
    parser.add_argument("--version", action="version", version=f"kaizen {__version__}")
    parser.add_argument("--verbose", action="store_true",
                        help="Print stack traces on error and enable extra logging")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color output")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # Direct pipeline access (the wedges compose these under the hood).
    add_decompose_parser(subparsers)
    add_recompose_parser(subparsers)
    # Wedge subcommands (Phase B end-to-end).
    add_memsafe_roadmap_parser(subparsers)
    add_migrate_plan_parser(subparsers)
    # Inspection / utility.
    add_status_parser(subparsers)
    add_priors_parser(subparsers)
    add_resume_parser(subparsers)
    # First-run wizard + config inspection.
    add_init_parser(subparsers)
    # Lite web UI — requires the [web] optional dependency group.
    add_web_parser(subparsers)
    # MCP server — requires the [mcp] optional dependency group.
    add_mcp_serve_parser(subparsers)
    # Architectural-weakness benchmarking — funnel-mouth for Kaizen-3C/benchmarks
    # methodology. Vendored analysis scripts; see cli/bench/.
    add_bench_parser(subparsers)
    # First-run "wow" walkthrough — offline, no API key required (when the
    # bundled cache asset is present). See cli/commands/demo.py.
    add_demo_parser(subparsers)

    # version subcommand kept for backwards compat with Sprint 1
    subparsers.add_parser("version", help="Print the kaizen-cli version and exit")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    style = Style(use_color=(not args.no_color))

    try:
        if args.command == "status":
            return status_command(args)
        if args.command == "priors":
            return priors_command(args)
        if args.command == "memsafe-roadmap":
            return memsafe_roadmap_command(args)
        if args.command == "migrate-plan":
            return migrate_plan_command(args)
        if args.command == "decompose":
            return decompose_command(args)
        if args.command == "recompose":
            return recompose_command(args)
        if args.command == "web":
            return web_command(args)
        if args.command == "mcp-serve":
            return mcp_serve_command(args)
        if args.command == "init":
            return init_command(args)
        if args.command == "resume":
            return resume_command(args)
        if args.command == "bench":
            return bench_command(args)
        if args.command == "demo":
            return demo_command(args)
        if args.command == "version":
            print(__version__)
            return 0
        parser.print_help()
        return 2
    except KeyboardInterrupt:
        error(style, "interrupted")
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        error(style, f"{exc.__class__.__name__}: {exc}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        else:
            print(style.dim("  (run with --verbose for stack trace)"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
