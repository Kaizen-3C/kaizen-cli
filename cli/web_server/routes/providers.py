# SPDX-License-Identifier: Apache-2.0
"""GET /api/providers — report which LLM providers have credentials configured.

The server never stores or returns actual API keys — only a boolean per provider
saying whether the environment has a usable key. The browser UI uses this to
grey out provider options that won't work out of the box.
"""

from __future__ import annotations

import os

from fastapi import APIRouter

router = APIRouter(tags=["meta"])

# Mirror of the provider set supported by the CLI's --provider flag.
# Keep in sync with cli/pipeline/decompose_v2.py argparse choices.
_PROVIDERS = (
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("ollama", None),  # local; no key required
    ("litellm", "LITELLM_API_KEY"),
)


@router.get("/providers")
def list_providers() -> dict[str, list[dict[str, object]]]:
    entries = []
    for name, env_var in _PROVIDERS:
        if env_var is None:
            configured = True
            note = "local — no API key required (ensure Ollama is running)"
        else:
            configured = bool(os.environ.get(env_var))
            note = f"{env_var} {'present' if configured else 'not set'}"
        entries.append({"name": name, "configured": configured, "note": note})
    # "mixed" is a valid CLI value but not a standalone provider; report separately.
    entries.append({
        "name": "mixed",
        "configured": any(e["configured"] for e in entries[:2]),  # needs at least anthropic or openai
        "note": "uses multiple providers per agent tier",
    })
    return {"providers": entries}
