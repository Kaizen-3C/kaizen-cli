# SPDX-License-Identifier: Apache-2.0
"""kaizen — top-level CLI entry point.

Dispatches to the subcommand modules under `cli.commands`. Stdlib only.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from cli import __version__
from cli.commands.priors import add_priors_parser, priors_command
from cli.commands.run import add_run_parser, run_command
from cli.commands.status import add_status_parser, status_command
from cli.output import Style, error


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

    add_run_parser(subparsers)
    add_status_parser(subparsers)
    add_priors_parser(subparsers)

    # version subcommand kept for backwards compat with Sprint 1
    subparsers.add_parser("version", help="Print the kaizen-cli version and exit")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    style = Style(use_color=(not args.no_color))

    try:
        if args.command == "run":
            return run_command(args)
        if args.command == "status":
            return status_command(args)
        if args.command == "priors":
            return priors_command(args)
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
