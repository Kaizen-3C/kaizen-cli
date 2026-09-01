#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a standalone kaizen binary for the current platform using PyInstaller.

Invoked by the release CI matrix job on windows-latest, macos-14 and
ubuntu-22.04.  Also runnable locally for smoke-testing:

    pip install pyinstaller ".[demo]"
    python scripts/release/build-binaries.py

Output:
    dist/kaizen-<platform>-<arch>[.exe]
    dist/kaizen-<platform>-<arch>[.exe].sha256

The .sha256 sidecar is what the npm installer verifies before it will chmod
and install the binary.  Both files must be attached to the release.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SPEC = REPO_ROOT / "scripts" / "release" / "kaizen.spec"
DIST_DIR = REPO_ROOT / "dist"


def platform_suffix() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        "x86_64": "x64",
        "amd64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    arch = arch_map.get(machine, machine)

    if system == "windows":
        return f"windows-{arch}"
    elif system == "darwin":
        return f"macos-{arch}"
    elif system == "linux":
        return f"linux-{arch}"
    else:
        return f"{system}-{arch}"


def main() -> int:
    suffix = platform_suffix()
    is_windows = platform.system() == "Windows"
    bin_name = "kaizen.exe" if is_windows else "kaizen"
    artifact_name = f"kaizen-{suffix}.exe" if is_windows else f"kaizen-{suffix}"

    print(f"Building binary for {suffix} ...")

    DIST_DIR.mkdir(exist_ok=True)

    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--distpath", str(DIST_DIR / "_pyinstaller_out"),
            "--workpath", str(DIST_DIR / "_build"),
            "--noconfirm",
            str(SPEC),
        ],
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        print("PyInstaller failed.", file=sys.stderr)
        return result.returncode

    built = DIST_DIR / "_pyinstaller_out" / bin_name
    if not built.exists():
        print(f"Expected binary not found: {built}", file=sys.stderr)
        return 1

    artifact = DIST_DIR / artifact_name
    shutil.move(str(built), str(artifact))
    print(f"Artifact: {artifact}")

    # Quick smoke test
    smoke = subprocess.run([str(artifact), "--version"], capture_output=True, text=True)
    if smoke.returncode != 0:
        print(f"Smoke test failed:\n{smoke.stderr}", file=sys.stderr)
        return 1
    print(f"Smoke test passed: {smoke.stdout.strip()}")

    # Checksum sidecar. The npm installer refuses to install a binary it cannot
    # verify against this file, so it is not optional -- if it is missing from
    # the release, npm users get no binary at all.
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    checksum_file = artifact.with_name(artifact.name + ".sha256")
    # sha256sum-compatible format, so `sha256sum -c` works on the downloaded pair.
    checksum_file.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
    print(f"Checksum:  {digest}")
    print(f"Sidecar:   {checksum_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
