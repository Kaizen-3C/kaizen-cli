# SPDX-License-Identifier: Apache-2.0
"""`cli.review` -- adversarial LLM review of an ADR (anti-vibe-coding guardrail).

Implements the `--llm-review` flag for v0.4.0. Per ADR-0009, a *different*
model instance (no shared context with the write/draft agent) reviews the ADR
against anti-vibe-coding heuristics before the recompose stage executes.

The review is driven by `cli/pipeline/specialist_review.py`. Because that
script requires `--source-dir` (to compare the ADR against source files), a
synthetic single-file source dir is created when no source-dir is available --
specialist_review will find no files matching its glob and produce an empty-
findings review rather than refusing to run.  See the "Caveats" section in the
integration spec for details.

Public API
----------
    from cli.review import run_llm_review
    result = run_llm_review(Path("adr-root.md"), provider="anthropic")
    # -> {"exit_code": 0, "review_path": ".../adr-root.review.json",
    #     "findings_count": 2, "critical_findings": 0, "model": "claude-sonnet-4-6"}
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from . import events

# ---------------------------------------------------------------------------
# Model selection constants
# ---------------------------------------------------------------------------

# Default review models per provider -- intentionally different from the
# write/draft defaults (claude-sonnet-4-5 / gpt-4o) per ADR-0009.
_DEFAULT_REVIEW_MODEL: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4.1",
}

# When the write model is one of these, flip to the paired review model so
# the reviewer has no shared model-version state with the writer.
_WRITE_TO_REVIEW_MODEL: dict[str, str] = {
    "claude-sonnet-4-5": "claude-sonnet-4-6",
    "claude-sonnet-4-6": "claude-sonnet-4-5",
    "claude-opus-4-5": "claude-sonnet-4-6",
    "gpt-4o": "gpt-4.1",
    "gpt-4.1": "gpt-4o",
}

_CLI_PACKAGE_ROOT = Path(__file__).resolve().parent
_SPECIALIST_REVIEW_SCRIPT = _CLI_PACKAGE_ROOT / "pipeline" / "specialist_review.py"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_subprocess_env() -> dict:
    """Return an environment dict for subprocesses, with .env loaded from the
    caller's CWD (preferred) or the dev-checkout repo root.  Matches the
    pattern in cli/commands/recompose.py exactly."""
    env = dict(os.environ)
    kaizen_root = _CLI_PACKAGE_ROOT.parent
    for candidate in (Path.cwd() / ".env", kaizen_root / ".env"):
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in env:
                        env[k] = v
                break
            except (OSError, UnicodeDecodeError):
                pass
    return env


def _pick_review_model(
    write_model: Optional[str],
    provider: str,
    explicit_review_model: Optional[str],
) -> str:
    """Select the review model following the ADR-0009 heuristic.

    Priority:
    1. ``explicit_review_model`` -- user passed ``--review-model``.
    2. ``write_model`` flip -- if the write model is known, use its pair.
    3. Provider default -- ``_DEFAULT_REVIEW_MODEL[provider]``.
    """
    if explicit_review_model:
        return explicit_review_model
    if write_model and write_model in _WRITE_TO_REVIEW_MODEL:
        return _WRITE_TO_REVIEW_MODEL[write_model]
    return _DEFAULT_REVIEW_MODEL.get(provider, _DEFAULT_REVIEW_MODEL["anthropic"])


def _parse_review_output(review_json_path: Path) -> tuple[int, int]:
    """Return (findings_count, critical_findings) from the review JSON output.

    Returns (-1, -1) if the file is absent or unparseable, so callers can
    still emit a result without crashing.
    """
    try:
        data = json.loads(review_json_path.read_text(encoding="utf-8"))
        n = data.get("n_findings", -1)
        sev = data.get("severity_counts", {})
        crit = sev.get("critical", -1) if isinstance(sev, dict) else -1
        return int(n), int(crit)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return -1, -1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_llm_review(
    adr_path: Path,
    *,
    provider: str = "anthropic",
    model: Optional[str] = None,
    review_model: Optional[str] = None,
    output_path: Optional[Path] = None,
    source_dir: Optional[Path] = None,
    use_domain_schema: bool = False,
) -> dict:
    """Run the specialist_review pipeline against *adr_path*.

    Parameters
    ----------
    adr_path:
        Path to the ADR markdown file to review.  Must exist.
    provider:
        LLM provider passed to the write/draft stage (used for model flip).
    model:
        The write/draft model (used for model flip heuristic).
    review_model:
        Explicit override for the review model; skips the flip heuristic.
    output_path:
        Where to write the review JSON.  Defaults to
        ``<adr_stem>.review.json`` next to *adr_path*.
    source_dir:
        Original source directory for cross-referencing.  When absent (common
        for standalone ``kaizen decompose --llm-review`` use), a temporary
        empty directory is used so specialist_review.py runs without error.
    use_domain_schema:
        Unused by the review script directly; reserved for future schema-aware
        prompting.  Forwarded as metadata in the return dict.

    Returns
    -------
    dict with keys:
        exit_code (int), review_path (str | None), findings_count (int),
        critical_findings (int), model (str), triggered (bool).
    """
    adr_path = Path(adr_path).resolve()

    # --- Validate input -------------------------------------------------------
    if not adr_path.exists() or not adr_path.is_file():
        events.error(f"llm-review: ADR not found at {adr_path}")
        return {
            "exit_code": 2,
            "review_path": None,
            "findings_count": -1,
            "critical_findings": -1,
            "model": _pick_review_model(model, provider, review_model),
            "triggered": False,
            "error": f"ADR not found: {adr_path}",
        }

    # --- Resolve output path --------------------------------------------------
    if output_path is None:
        output_path = adr_path.parent / f"{adr_path.stem}.review.json"
    else:
        output_path = Path(output_path).resolve()

    # --- Pick review model (ADR-0009 heuristic) --------------------------------
    chosen_model = _pick_review_model(model, provider, review_model)

    # --- Resolve source dir ---------------------------------------------------
    # specialist_review.py requires --source-dir. When the caller has no source
    # directory (e.g. standalone review), supply a temp dir.  The script's glob
    # will find no files and produce a clean "no findings" review rather than
    # erroring out.  See "Caveats" in the integration spec.
    _tmp_dir_obj = None
    if source_dir is None or not Path(source_dir).is_dir():
        _tmp_dir_obj = tempfile.TemporaryDirectory()
        effective_source_dir = Path(_tmp_dir_obj.name)
    else:
        effective_source_dir = Path(source_dir).resolve()

    # --- Build subprocess command ---------------------------------------------
    cmd = [
        sys.executable,
        str(_SPECIALIST_REVIEW_SCRIPT),
        "--adr", str(adr_path),
        "--source-dir", str(effective_source_dir),
        "--output", str(output_path),
        "--force",   # always run (no roundtrip report available here)
    ]

    # --- Emit stage event and run subprocess ----------------------------------
    try:
        rc = events.run_subprocess_with_logs(
            cmd,
            env=_build_subprocess_env(),
            source="llm-review",
        )
    finally:
        # Clean up the temp dir (if we created one) regardless of outcome.
        if _tmp_dir_obj is not None:
            _tmp_dir_obj.cleanup()

    # --- Parse review output to extract findings counts -----------------------
    review_path_str: Optional[str] = None
    findings_count = -1
    critical_findings = -1
    triggered = False

    if output_path.exists():
        review_path_str = str(output_path)
        findings_count, critical_findings = _parse_review_output(output_path)
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
            triggered = bool(data.get("triggered", False))
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "exit_code": rc,
        "review_path": review_path_str,
        "findings_count": findings_count,
        "critical_findings": critical_findings,
        "model": chosen_model,
        "triggered": triggered,
    }
