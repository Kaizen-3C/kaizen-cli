# SPDX-License-Identifier: Apache-2.0
"""kaizen_web — FastAPI backend for the `kaizen web` lite UI.

Thin HTTP shim over the Python functions that `kaizen-cli` already exposes.
Every route calls the same code path the CLI does; no pipeline logic is
re-implemented here. If the CLI and a web route ever diverge on the same
input, that is a bug.

See `docs/release/UI_LITE_CARVE_OUT.md` for the full design.
"""

from cli import __version__

__all__ = ["__version__"]
