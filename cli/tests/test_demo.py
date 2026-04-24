# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cli.commands.demo (offline kaizen demo)."""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.commands.demo import add_demo_parser, demo_command, _find_bundled_asset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(
    *,
    no_pytest: bool = False,
    keep_temp: bool = False,
    quiet: bool = False,
) -> argparse.Namespace:
    """Build a minimal Namespace that demo_command accepts."""
    return argparse.Namespace(
        no_pytest=no_pytest,
        keep_temp=keep_temp,
        quiet=quiet,
    )


def _build_fake_tarball(dest_dir: Path) -> Path:
    """Create a minimal slugify_demo.tar.gz in *dest_dir* and return the path."""
    # Scratch area for tarball contents.
    scratch = dest_dir / "_scratch"
    demo_root = scratch / "slugify_demo"
    after_dir = demo_root / "after"
    after_dir.mkdir(parents=True)

    # adr.md — 35 lines so we exercise the "first 30 lines" truncation.
    adr_lines = ["# ADR: python-slugify demo"] + [f"Line {i}" for i in range(2, 36)]
    (demo_root / "adr.md").write_text("\n".join(adr_lines), encoding="utf-8")

    # summary.json
    summary = {"files": ["slugify.py", "__init__.py"], "elapsed_s": 12, "pass_count": 4}
    (demo_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    # Minimal Python file so pytest finds *something* (no tests — just a module).
    (after_dir / "slugify.py").write_text(
        "# kaizen recomposed\ndef slugify(s): return s.lower().replace(' ', '-')\n",
        encoding="utf-8",
    )

    tarball = dest_dir / "slugify_demo.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(scratch / "slugify_demo", arcname="slugify_demo")

    return tarball


# ---------------------------------------------------------------------------
# 1. Module surface — functions exist
# ---------------------------------------------------------------------------


def test_demo_subcommand_exists() -> None:
    """add_demo_parser and demo_command must be importable callables."""
    from cli.commands import demo as demo_mod

    assert callable(getattr(demo_mod, "add_demo_parser", None)), (
        "add_demo_parser not found in cli.commands.demo"
    )
    assert callable(getattr(demo_mod, "demo_command", None)), (
        "demo_command not found in cli.commands.demo"
    )


# ---------------------------------------------------------------------------
# 2. Graceful degradation when asset is missing
# ---------------------------------------------------------------------------


def test_demo_no_cache_graceful(capsys: pytest.CaptureFixture) -> None:
    """When the bundled tarball is absent, demo_command exits 0 with a clear message."""
    args = _make_args(no_pytest=True)

    # Patch _find_bundled_asset to simulate a missing tarball.
    with patch("cli.commands.demo._find_bundled_asset", return_value=None):
        rc = demo_command(args)

    assert rc == 0, "Expected exit code 0 when demo asset is not bundled"

    captured = capsys.readouterr()
    assert "Demo asset not bundled" in captured.out, (
        f"Expected 'Demo asset not bundled' in stdout; got:\n{captured.out}"
    )
    assert "scripts/build-demo-cache.py" in captured.out, (
        "Expected reference to build-demo-cache.py in stdout"
    )


# ---------------------------------------------------------------------------
# 3. Full demo run with a fake tarball (no real pytest invocation)
# ---------------------------------------------------------------------------


def test_demo_with_cache(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a fake tarball, demo_command extracts it and prints expected output."""
    # Build the fake asset.
    tarball = _build_fake_tarball(tmp_path)

    # Redirect tempfile.mkdtemp so we control the extraction directory.
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(extract_dir))

    # Patch asset locator to return our fake tarball.
    with patch("cli.commands.demo._find_bundled_asset", return_value=tarball):
        # Use --no-pytest so we don't invoke a subprocess in the test runner.
        args = _make_args(no_pytest=True)
        rc = demo_command(args)

    assert rc == 0, f"Expected exit code 0; got {rc}"

    captured = capsys.readouterr()
    combined = captured.out

    # Intro banner visible.
    assert "kaizen demo" in combined.lower(), "Expected 'kaizen demo' in output"

    # Step markers visible.
    assert "Step 1/3" in combined
    assert "Step 2/3" in combined
    assert "Step 3/3" in combined

    # ADR preview visible (first 30 lines shown; line 31+ truncated).
    assert "ADR: python-slugify demo" in combined
    assert "see" in combined and "adr.md" in combined  # truncation footer

    # summary.json file list visible.
    assert "slugify.py" in combined

    # Completion message + CTA visible.
    assert "Demo complete" in combined
    assert "kaizen memsafe-roadmap" in combined

    # Extraction happened: adr.md exists on disk.
    extracted_adr = extract_dir / "slugify_demo" / "adr.md"
    assert extracted_adr.exists(), f"Expected extracted adr.md at {extracted_adr}"


# ---------------------------------------------------------------------------
# 4. --quiet flag suppresses banner but preserves final result
# ---------------------------------------------------------------------------


def test_demo_quiet_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--quiet mode omits the banner but still prints the Demo complete line."""
    tarball = _build_fake_tarball(tmp_path)
    extract_dir = tmp_path / "extract_quiet"
    extract_dir.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": str(extract_dir))

    with patch("cli.commands.demo._find_bundled_asset", return_value=tarball):
        args = _make_args(no_pytest=True, quiet=True)
        rc = demo_command(args)

    assert rc == 0
    captured = capsys.readouterr()
    # Final result line always printed (force=True in _print).
    assert "Demo complete" in captured.out
    # Verbose intro banner suppressed.
    assert "offline-first" not in captured.out.lower()
    assert "no API key" not in captured.out


# ---------------------------------------------------------------------------
# 5. add_demo_parser registers subcommand with expected flags
# ---------------------------------------------------------------------------


def test_add_demo_parser_registers_subcommand() -> None:
    """add_demo_parser wires up the 'demo' subcommand with all expected flags."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_demo_parser(subparsers)

    # Bare invocation.
    ns = parser.parse_args(["demo"])
    assert ns.command == "demo"
    assert ns.no_pytest is False
    assert ns.keep_temp is False
    assert ns.quiet is False

    # All flags.
    ns2 = parser.parse_args(["demo", "--no-pytest", "--keep-temp", "--quiet"])
    assert ns2.no_pytest is True
    assert ns2.keep_temp is True
    assert ns2.quiet is True
