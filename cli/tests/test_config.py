# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cli.config."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

import cli.config as cfg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect config_dir() to a temp directory for every test.

    platformdirs uses the OS registry / XDG on different platforms; we patch
    the module-level function directly so every test is hermetic.
    """
    monkeypatch.setattr(cfg, "config_dir", lambda: tmp_path)
    yield


# ---------------------------------------------------------------------------
# config_dir / config_path
# ---------------------------------------------------------------------------


def test_config_dir_returns_existing_path(tmp_path: Path) -> None:
    # The fixture already patches config_dir to tmp_path, which exists.
    assert cfg.config_dir().exists()


def test_config_path_is_toml_inside_config_dir(tmp_path: Path) -> None:
    path = cfg.config_path()
    assert path.name == "config.toml"
    assert path.parent == tmp_path


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_returns_empty_when_file_absent() -> None:
    result = cfg.load_config()
    assert result == {}


def test_load_config_returns_empty_for_empty_file(tmp_path: Path) -> None:
    cfg.config_path().write_text("", encoding="utf-8")
    result = cfg.load_config()
    assert result == {}


def test_load_config_parses_valid_toml(tmp_path: Path) -> None:
    cfg.config_path().write_text(
        '[providers]\ndefault = "anthropic"\n', encoding="utf-8"
    )
    result = cfg.load_config()
    assert result == {"providers": {"default": "anthropic"}}


def test_load_config_malformed_toml_returns_empty_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    cfg.config_path().write_text("this is not toml ===\n", encoding="utf-8")
    result = cfg.load_config()
    assert result == {}
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "config.toml" in captured.err


# ---------------------------------------------------------------------------
# save_config / round-trip
# ---------------------------------------------------------------------------


def test_save_and_reload_round_trip() -> None:
    original = {
        "providers": {
            "default": "anthropic",
            "anthropic": {"model": "claude-sonnet-4-5"},
        },
        "output": {
            "adr_dir": "adrs",
            "roadmap_filename": "roadmap.md",
            "plan_filename": "plan.md",
        },
        "pipeline": {
            "temperature": 0.0,
            "max_tokens": 16000,
        },
    }
    cfg.save_config(original)
    loaded = cfg.load_config()

    assert loaded["providers"]["default"] == "anthropic"
    assert loaded["providers"]["anthropic"]["model"] == "claude-sonnet-4-5"
    assert loaded["output"]["adr_dir"] == "adrs"
    assert loaded["pipeline"]["temperature"] == 0.0
    assert loaded["pipeline"]["max_tokens"] == 16000


def test_save_config_writes_file(tmp_path: Path) -> None:
    cfg.save_config({"pipeline": {"temperature": 0.5}})
    assert cfg.config_path().exists()
    content = cfg.config_path().read_text(encoding="utf-8")
    assert "temperature" in content


def test_save_config_bool_values(tmp_path: Path) -> None:
    """Boolean values must serialise as TOML true/false (not Python True/False)."""
    cfg.save_config({"flags": {"enabled": True, "verbose": False}})
    content = cfg.config_path().read_text(encoding="utf-8")
    assert "true" in content
    assert "false" in content


def test_save_config_string_escaping(tmp_path: Path) -> None:
    """Strings with backslashes and quotes must be escaped."""
    cfg.save_config({"output": {"adr_dir": 'path\\with"quotes'}})
    loaded = cfg.load_config()
    assert loaded["output"]["adr_dir"] == 'path\\with"quotes'


# ---------------------------------------------------------------------------
# apply_defaults
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    """Return a Namespace pre-populated with typical argparse defaults."""
    defaults = dict(
        command="memsafe-roadmap",
        provider="anthropic",
        model=None,
        adr_dir="adrs",
        output="roadmap.md",
        temperature=0.0,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_apply_defaults_noop_when_no_config() -> None:
    """apply_defaults must not modify args when config is absent."""
    args = _make_args()
    result = cfg.apply_defaults(args)
    assert result.provider == "anthropic"
    assert result.model is None
    assert result.adr_dir == "adrs"
    assert result.output == "roadmap.md"
    assert result.temperature == 0.0


def test_apply_defaults_overrides_provider(tmp_path: Path) -> None:
    cfg.save_config({"providers": {"default": "openai"}})
    args = _make_args(provider="anthropic")  # still at argparse default
    cfg.apply_defaults(args)
    assert args.provider == "openai"


def test_apply_defaults_overrides_model(tmp_path: Path) -> None:
    cfg.save_config({"providers": {"anthropic": {"model": "claude-opus-4-5"}}})
    args = _make_args(model=None)
    cfg.apply_defaults(args)
    assert args.model == "claude-opus-4-5"


def test_apply_defaults_overrides_adr_dir(tmp_path: Path) -> None:
    cfg.save_config({"output": {"adr_dir": "custom_adrs"}})
    args = _make_args(adr_dir="adrs")
    cfg.apply_defaults(args)
    assert args.adr_dir == "custom_adrs"


def test_apply_defaults_overrides_temperature(tmp_path: Path) -> None:
    cfg.save_config({"pipeline": {"temperature": 0.7}})
    args = _make_args(temperature=0.0)
    cfg.apply_defaults(args)
    assert args.temperature == pytest.approx(0.7)


def test_apply_defaults_overrides_max_tokens(tmp_path: Path) -> None:
    cfg.save_config({"pipeline": {"max_tokens": 8000}})
    args = _make_args(max_tokens=16000)
    cfg.apply_defaults(args)
    assert args.max_tokens == 8000


def test_apply_defaults_respects_explicit_provider(tmp_path: Path) -> None:
    """If the user explicitly passes a non-default value, it must not be overridden."""
    cfg.save_config({"providers": {"default": "openai"}})
    # Simulate user passing --provider ollama (not the argparse default "anthropic")
    args = _make_args(provider="ollama")
    cfg.apply_defaults(args)
    # "ollama" != argparse default "anthropic", so we skip override
    assert args.provider == "ollama"


def test_apply_defaults_respects_explicit_model(tmp_path: Path) -> None:
    cfg.save_config({"providers": {"anthropic": {"model": "claude-opus-4-5"}}})
    args = _make_args(model="claude-haiku-3-5")  # explicitly set (not None)
    cfg.apply_defaults(args)
    assert args.model == "claude-haiku-3-5"


def test_apply_defaults_roadmap_output(tmp_path: Path) -> None:
    cfg.save_config({"output": {"roadmap_filename": "my-roadmap.md"}})
    args = _make_args(command="memsafe-roadmap", output="roadmap.md")
    cfg.apply_defaults(args)
    assert args.output == "my-roadmap.md"


def test_apply_defaults_plan_output(tmp_path: Path) -> None:
    cfg.save_config({"output": {"plan_filename": "my-plan.md"}})
    args = _make_args(command="migrate-plan", output="plan.md")
    cfg.apply_defaults(args)
    assert args.output == "my-plan.md"


def test_apply_defaults_missing_attrs_skipped() -> None:
    """apply_defaults must be safe when args lacks some attributes."""
    # Namespace with no provider / model / etc.
    args = argparse.Namespace(command="status")
    result = cfg.apply_defaults(args)
    # No error; unrelated attrs untouched.
    assert result.command == "status"


def test_apply_defaults_returns_args() -> None:
    """apply_defaults should return the same Namespace object."""
    args = _make_args()
    result = cfg.apply_defaults(args)
    assert result is args
