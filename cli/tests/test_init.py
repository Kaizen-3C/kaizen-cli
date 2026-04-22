# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cli.commands.init (first-run wizard)."""

from __future__ import annotations

import argparse
from pathlib import Path
from io import StringIO
from unittest.mock import patch

import pytest

import cli.config as cfg
from cli.commands.init import init_command, add_init_parser, _resolve_provider_choice


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect config_dir() to a temp directory for every test."""
    monkeypatch.setattr(cfg, "config_dir", lambda: tmp_path)
    yield


def _make_args(non_interactive: bool = False, show: bool = False) -> argparse.Namespace:
    return argparse.Namespace(non_interactive=non_interactive, show=show)


# ---------------------------------------------------------------------------
# --non-interactive: creates config with defaults
# ---------------------------------------------------------------------------


def test_non_interactive_creates_config(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _make_args(non_interactive=True)
    rc = init_command(args)
    assert rc == 0

    # Config file must now exist.
    config_file = cfg.config_path()
    assert config_file.exists()

    loaded = cfg.load_config()
    assert loaded["providers"]["default"] == "anthropic"
    assert loaded["providers"]["anthropic"]["model"] == "claude-sonnet-4-5"
    assert loaded["output"]["adr_dir"] == "adrs"
    assert loaded["output"]["roadmap_filename"] == "roadmap.md"
    assert loaded["output"]["plan_filename"] == "plan.md"
    assert loaded["pipeline"]["temperature"] == pytest.approx(0.0)
    assert loaded["pipeline"]["max_tokens"] == 16000


def test_non_interactive_prints_config_path(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _make_args(non_interactive=True)
    init_command(args)
    captured = capsys.readouterr()
    assert "config.toml" in captured.out or str(tmp_path) in captured.out


def test_non_interactive_exit_code_zero() -> None:
    args = _make_args(non_interactive=True)
    assert init_command(args) == 0


# ---------------------------------------------------------------------------
# --show: prints config without disk changes
# ---------------------------------------------------------------------------


def test_show_when_no_config(capsys: pytest.CaptureFixture) -> None:
    args = _make_args(show=True)
    rc = init_command(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "No config file found" in captured.out


def test_show_prints_existing_config(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # Create a config first.
    init_command(_make_args(non_interactive=True))
    capsys.readouterr()  # discard init output

    args = _make_args(show=True)
    rc = init_command(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "anthropic" in captured.out


def test_show_does_not_modify_disk(tmp_path: Path) -> None:
    # Write a sentinel file.
    cfg.config_path().write_text("# sentinel\n[providers]\ndefault = \"openai\"\n", encoding="utf-8")
    mtime_before = cfg.config_path().stat().st_mtime

    init_command(_make_args(show=True))

    mtime_after = cfg.config_path().stat().st_mtime
    assert mtime_before == mtime_after


# ---------------------------------------------------------------------------
# Overwrite prompt: piping "n" aborts without change
# ---------------------------------------------------------------------------


def test_overwrite_prompt_no_aborts(tmp_path: Path) -> None:
    # Create initial config.
    init_command(_make_args(non_interactive=True))
    original_content = cfg.config_path().read_text(encoding="utf-8")

    # Simulate interactive run with "n" answer to overwrite prompt.
    with patch("builtins.input", side_effect=["n"]):
        args = _make_args(non_interactive=False)
        rc = init_command(args)

    assert rc == 0
    assert cfg.config_path().read_text(encoding="utf-8") == original_content


def test_overwrite_prompt_yes_overwrites(tmp_path: Path) -> None:
    """Answering 'y' at the overwrite prompt then using defaults completes ok."""
    init_command(_make_args(non_interactive=True))

    # Simulate "y" to overwrite, then all defaults accepted.
    inputs = iter(["y", "", "", "", "", "", "", ""])
    with patch("builtins.input", side_effect=lambda prompt: next(inputs, "")):
        args = _make_args(non_interactive=False)
        rc = init_command(args)

    assert rc == 0
    loaded = cfg.load_config()
    assert loaded["providers"]["default"] == "anthropic"


# ---------------------------------------------------------------------------
# KeyboardInterrupt returns 130
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_returns_130(capsys: pytest.CaptureFixture) -> None:
    with patch("cli.commands.init._run_wizard", side_effect=KeyboardInterrupt):
        args = _make_args(non_interactive=False)
        rc = init_command(args)
    assert rc == 130
    captured = capsys.readouterr()
    assert "aborted" in captured.err


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def test_add_init_parser_registers_subcommand() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_init_parser(subparsers)

    # --non-interactive flag
    ns = parser.parse_args(["init", "--non-interactive"])
    assert ns.non_interactive is True
    assert ns.show is False

    # --show flag
    ns = parser.parse_args(["init", "--show"])
    assert ns.show is True
    assert ns.non_interactive is False


# ---------------------------------------------------------------------------
# Provider choice resolver
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("1", "anthropic"),
    ("2", "openai"),
    ("3", "ollama"),
    ("4", "litellm"),
    ("anthropic", "anthropic"),
    ("openai", "openai"),
    ("ant", "anthropic"),   # prefix match
    ("open", "openai"),
    ("99", None),
    ("xyz", None),
])
def test_resolve_provider_choice(raw: str, expected: str | None) -> None:
    assert _resolve_provider_choice(raw) == expected


# ---------------------------------------------------------------------------
# API key probe output
# ---------------------------------------------------------------------------


def test_api_key_found_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    init_command(_make_args(non_interactive=True))
    captured = capsys.readouterr()
    assert "found" in captured.out.lower() or "ANTHROPIC_API_KEY" in captured.out


def test_api_key_not_set_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    init_command(_make_args(non_interactive=True))
    captured = capsys.readouterr()
    assert "ANTHROPIC_API_KEY" in captured.out
