# SPDX-License-Identifier: Apache-2.0
"""Runtime settings for the kaizen web server.

Resolved from environment variables and sensible defaults. No external
config file; the web UI is a developer-local tool by default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7865


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    # Where to resolve the pre-built SPA static bundle. When running from a
    # source checkout the bundle lives at `ui-lite/dist`; when installed via
    # `pip install kaizen-cli[web]` it is packaged alongside this module at
    # `kaizen_web/static`. The server tries both and serves whichever exists.
    static_candidates: tuple[Path, ...] = ()
    # Hard cap on sync request time before the server responds with 504.
    # Wedge pipelines can take minutes; we deliberately allow long waits
    # but cap at 30 minutes as a safety net.
    request_timeout_seconds: int = 30 * 60

    @classmethod
    def from_env(cls, *, host: str | None = None, port: int | None = None) -> "Settings":
        module_dir = Path(__file__).resolve().parent
        repo_root = module_dir.parent
        return cls(
            host=host or os.environ.get("KAIZEN_WEB_HOST", DEFAULT_HOST),
            port=port or int(os.environ.get("KAIZEN_WEB_PORT", DEFAULT_PORT)),
            static_candidates=(
                module_dir / "static",
                repo_root / "ui-lite" / "dist",
            ),
        )

    def resolve_static_dir(self) -> Path | None:
        for candidate in self.static_candidates:
            if candidate.is_dir() and (candidate / "index.html").is_file():
                return candidate
        return None

    def is_public_bind(self) -> bool:
        """Return True if the configured host binds beyond loopback."""
        return self.host not in {"127.0.0.1", "localhost", "::1"}
