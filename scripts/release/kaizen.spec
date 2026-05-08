# SPDX-License-Identifier: Apache-2.0
# PyInstaller spec for kaizen standalone binaries.
#
# Bundles the base CLI surface (anthropic, openai, httpx, platformdirs) and all
# data assets.  The [web] and [mcp] extras are deliberately excluded — they add
# ~30 MB of FastAPI/uvicorn/mcp deps for features that are equally accessible
# via `pip install kaizen-3c-cli[web,mcp]`.  `kaizen web` and `kaizen mcp-serve`
# print a helpful "install the [web] extra" message when those imports are absent.
#
# Build:
#   python scripts/release/build-binaries.py
# or directly:
#   pyinstaller scripts/release/kaizen.spec --distpath dist/

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent.parent  # repo root

a = Analysis(
    [str(ROOT / "cli" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "cli" / "demo_assets"), "cli/demo_assets"),
        (str(ROOT / "cli" / "web_server" / "static"), "cli/web_server/static"),
        (str(ROOT / "cli" / "pipeline"), "cli/pipeline"),
        (str(ROOT / "cli" / "bench"), "cli/bench"),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "NOTICE"), "."),
    ],
    hiddenimports=[
        "anthropic",
        "anthropic._models",
        "anthropic.resources",
        "openai",
        "openai.resources",
        "httpx",
        "platformdirs",
        "cli",
        "cli.commands",
        "cli.commands.decompose",
        "cli.commands.recompose",
        "cli.commands.memsafe_roadmap",
        "cli.commands.migrate_plan",
        "cli.commands.init",
        "cli.commands.status",
        "cli.commands.priors",
        "cli.commands.resume",
        "cli.commands.bench",
        "cli.commands.demo",
        "cli.commands.web",
        "cli.commands.mcp_serve",
        "cli.pipeline",
        "cli.output",
        # stdlib extras sometimes missed by the hook
        "email.mime.text",
        "email.mime.multipart",
        "json",
        "pathlib",
        "shutil",
        "tempfile",
    ],
    excludes=[
        # [web] extra — not bundled; pip install kaizen-3c-cli[web]
        "fastapi",
        "uvicorn",
        "starlette",
        "pydantic",
        "sse_starlette",
        # [mcp] extra — not bundled; pip install kaizen-3c-cli[mcp]
        "mcp",
        # test/dev deps
        "pytest",
        "ruff",
        "_pytest",
        # heavy unused stdlib
        "tkinter",
        "turtle",
        "curses",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="kaizen",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
