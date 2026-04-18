# SPDX-License-Identifier: Apache-2.0
"""`kaizen priors` — inspect or reset Thompson-sampling priors files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import output
from ..output import Style


def add_priors_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "priors",
        help="Inspect or reset Thompson-sampling priors files",
        description="Inspect or reset Thompson-sampling priors files.",
    )
    sub = p.add_subparsers(dest="priors_cmd", metavar="ACTION")
    sub.required = True

    show = sub.add_parser("show", help="Pretty-print a priors JSON file")
    show.add_argument("path", nargs="?", default="./priors.json",
                      help="Priors file path (default: ./priors.json)")

    reset = sub.add_parser("reset", help="Delete a priors file (with confirmation)")
    reset.add_argument("path", nargs="?", default="./priors.json",
                       help="Priors file path (default: ./priors.json)")
    reset.add_argument("--yes", action="store_true",
                       help="Skip confirmation prompt")

    return p


def _show(args: argparse.Namespace, style: Style) -> int:
    path = Path(args.path).resolve()
    if not path.exists():
        output.error(style, f"priors file not found: {path}")
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        output.error(style, f"priors file is not valid JSON: {exc}")
        return 1
    except OSError as exc:
        output.error(style, f"could not read priors file: {exc}")
        return 1

    print(style.bold(f"priors @ {path}"))
    print(json.dumps(data, indent=2, sort_keys=True, default=str))
    return 0


def _reset(args: argparse.Namespace, style: Style) -> int:
    path = Path(args.path).resolve()
    if not path.exists():
        output.error(style, f"priors file not found: {path}")
        return 2

    if not args.yes:
        try:
            resp = input(f"Delete {path}? [y/N] ").strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("y", "yes"):
            print("aborted")
            return 0

    try:
        path.unlink()
    except OSError as exc:
        output.error(style, f"could not delete priors file: {exc}")
        return 1
    print(f"deleted {path}")
    return 0


def priors_command(args: argparse.Namespace) -> int:
    style = Style(use_color=(not args.no_color) if hasattr(args, "no_color") else None)
    if args.priors_cmd == "show":
        return _show(args, style)
    if args.priors_cmd == "reset":
        return _reset(args, style)
    output.error(style, f"unknown priors action: {args.priors_cmd}")
    return 2
