# SPDX-License-Identifier: Apache-2.0
"""`kaizen init` -- first-run configuration wizard.

Interactively prompts the user for preferred provider, model, output paths,
and pipeline settings, then writes ``~/.kaizen/config.toml`` (platform path
via ``cli.config``).

Flags:
    --non-interactive   Use all defaults without prompting (CI-safe).
    --show              Print current config without modifying disk.

Keyboard interrupt (Ctrl-C) is caught: prints "aborted" to stderr, returns
exit code 130, and does NOT perform a partial write.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .. import __version__
from .. import config as _config


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

_PROVIDERS = ["anthropic", "openai", "ollama", "litellm"]

_PROVIDER_ENV_VARS: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": None,           # local server, no key required
    "litellm": "LITELLM_API_KEY",
}

_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4.1",
    "ollama": "llama3",
    "litellm": "gpt-4",
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def add_init_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "init",
        help="Run the first-run configuration wizard (writes ~/.kaizen/config.toml)",
        description=(
            "Interactive setup wizard. Prompts for provider, model, output paths, "
            "and pipeline settings, then writes the kaizen config file. "
            "Use --non-interactive for CI or --show to inspect the current config."
        ),
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Accept all defaults without prompting (CI-safe mode)",
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="Print the current config file contents without making changes",
    )
    return p


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------


def init_command(args: argparse.Namespace) -> int:
    """Wizard entrypoint; returns an exit code."""
    # --show: read-only inspection, no writes.
    if args.show:
        return _show_config()

    try:
        return _run_wizard(non_interactive=args.non_interactive)
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130


# ---------------------------------------------------------------------------
# --show helper
# ---------------------------------------------------------------------------


def _show_config() -> int:
    path = _config.config_path()
    if not path.exists():
        print(f"No config file found at {path}")
        print("Run `kaizen init` to create one.")
        return 0
    print(f"Config file: {path}")
    print()
    print(path.read_text(encoding="utf-8"))
    return 0


# ---------------------------------------------------------------------------
# Wizard logic
# ---------------------------------------------------------------------------


def _prompt(prompt_text: str, default: str, non_interactive: bool) -> str:
    """Display *prompt_text* and return the user's answer (or *default* in CI)."""
    if non_interactive:
        return default
    try:
        answer = input(f"{prompt_text} [{default}]: ").strip()
    except EOFError:
        return default
    return answer if answer else default


def _run_wizard(*, non_interactive: bool) -> int:
    """Core wizard; returns exit code."""
    # Banner
    print(f"Welcome to kaizen-3c-cli {__version__}. Let's configure a default provider.")
    print()

    cfg_path = _config.config_path()

    # Load existing config (may be empty dict on first run).
    existing = _config.load_config()

    # ------------------------------------------------------------------
    # Overwrite guard
    # ------------------------------------------------------------------
    if cfg_path.exists() and existing and not non_interactive:
        answer = _prompt(
            f"Config already exists at {cfg_path}. Overwrite?",
            default="N",
            non_interactive=False,
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("Keeping existing config. Run `kaizen init --show` to view it.")
            return 0

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------
    existing_providers = existing.get("providers", {})
    existing_provider = existing_providers.get("default", "anthropic")

    print("  [1] Anthropic    (env var: ANTHROPIC_API_KEY)")
    print("  [2] OpenAI       (env var: OPENAI_API_KEY)")
    print("  [3] Ollama       (local server, no key required)")
    print("  [4] LiteLLM      (env var: LITELLM_API_KEY)")
    print()

    default_choice = str(_PROVIDERS.index(existing_provider) + 1) if existing_provider in _PROVIDERS else "1"
    raw_choice = _prompt("Choice", default=default_choice, non_interactive=non_interactive)

    provider = _resolve_provider_choice(raw_choice)
    if provider is None:
        print(f"  Unknown provider choice: {raw_choice!r}; defaulting to anthropic", file=sys.stderr)
        provider = "anthropic"

    print(f"  Selected provider: {provider}")

    # ------------------------------------------------------------------
    # API key probe
    # ------------------------------------------------------------------
    env_var = _PROVIDER_ENV_VARS.get(provider)
    if env_var:
        found = bool(os.environ.get(env_var, "").strip())
        status = "found" if found else "not set -- add it to your shell profile before running pipeline commands"
        mark = "+" if found else "!"
        print(f"  [{mark}] {env_var}: {status}")
    print()

    # ------------------------------------------------------------------
    # Model override
    # ------------------------------------------------------------------
    default_model = (
        existing_providers.get(provider, {}).get("model")
        or _PROVIDER_DEFAULT_MODELS.get(provider, "")
    )
    model = _prompt(
        f"Default model for {provider} (empty = use provider default)",
        default=default_model,
        non_interactive=non_interactive,
    )
    print()

    # ------------------------------------------------------------------
    # Output paths
    # ------------------------------------------------------------------
    existing_output = existing.get("output", {})

    adr_dir = _prompt(
        "Default ADR output directory",
        default=existing_output.get("adr_dir", "adrs"),
        non_interactive=non_interactive,
    )
    roadmap_filename = _prompt(
        "Default roadmap filename",
        default=existing_output.get("roadmap_filename", "roadmap.md"),
        non_interactive=non_interactive,
    )
    plan_filename = _prompt(
        "Default migration-plan filename",
        default=existing_output.get("plan_filename", "plan.md"),
        non_interactive=non_interactive,
    )
    print()

    # ------------------------------------------------------------------
    # Pipeline settings
    # ------------------------------------------------------------------
    existing_pipeline = existing.get("pipeline", {})

    raw_temp = _prompt(
        "Default temperature (0.0 = deterministic)",
        default=str(existing_pipeline.get("temperature", 0.0)),
        non_interactive=non_interactive,
    )
    try:
        temperature = float(raw_temp)
    except ValueError:
        print(f"  Invalid temperature {raw_temp!r}; using 0.0", file=sys.stderr)
        temperature = 0.0

    raw_mt = _prompt(
        "Default max_tokens",
        default=str(existing_pipeline.get("max_tokens", 16000)),
        non_interactive=non_interactive,
    )
    try:
        max_tokens = int(raw_mt)
    except ValueError:
        print(f"  Invalid max_tokens {raw_mt!r}; using 16000", file=sys.stderr)
        max_tokens = 16000
    print()

    # ------------------------------------------------------------------
    # Assemble and write config (no partial write on error)
    # ------------------------------------------------------------------
    new_config: dict = {
        "providers": {
            "default": provider,
            provider: {"model": model},
        },
        "output": {
            "adr_dir": adr_dir,
            "roadmap_filename": roadmap_filename,
            "plan_filename": plan_filename,
        },
        "pipeline": {
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    }

    _config.save_config(new_config)

    print(f"Config written to: {cfg_path}")
    print()
    print("Next steps:")
    if env_var and not os.environ.get(env_var, "").strip():
        print(f"  export {env_var}=<your-key>")
    print(f"  kaizen memsafe-roadmap ./your-repo")

    return 0


# ---------------------------------------------------------------------------
# Provider choice resolver
# ---------------------------------------------------------------------------


def _resolve_provider_choice(raw: str) -> str | None:
    """Return a provider name from a numeric choice or direct name, or None."""
    raw = raw.strip().lower()
    # Numeric choice
    if raw in ("1", "2", "3", "4"):
        return _PROVIDERS[int(raw) - 1]
    # Direct name
    if raw in _PROVIDERS:
        return raw
    # Prefix match (e.g. "ant" -> "anthropic")
    matches = [p for p in _PROVIDERS if p.startswith(raw)]
    if len(matches) == 1:
        return matches[0]
    return None
