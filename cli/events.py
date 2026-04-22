# SPDX-License-Identifier: Apache-2.0
"""Event emitter for Kaizen CLI progress output.

Design goal: one event-emission call site in the CLI code, two consumers.

CLI users (default):
    Events render as human-readable text to stdout — same UX as the legacy
    `print(...)` calls this module replaces.

Streaming consumers (web UI via SSE, CI log ingestion, `jq` pipelines):
    Events render as one JSON object per line (NDJSON) to stdout. Mode is
    selected via:
      - `KAIZEN_EVENT_STREAM=ndjson` environment variable, or
      - `events.set_mode("ndjson")` at runtime.

In-process consumers (kaizen_web routes) can install a custom sink via
`set_sink()` or the `capture()` context manager. The sink is a callable that
receives the event dict directly — no serialization round-trip needed.

Event schema (see docs/release/UI_LITE_CARVE_OUT.md for the stable list):
    {"kind": "run.start",  "command": str, "repo": str, ...options}
    {"kind": "stage",      "name": str, "index": int, "total": int}
    {"kind": "stage.done", "name": str, "artifacts": {...}}
    {"kind": "detail",     "message": str, ...fields}
    {"kind": "warn",       "message": str}
    {"kind": "error",      "message": str}
    {"kind": "result",     "exit_code": int, ...fields}

Events are append-only. Adding new kinds is a minor version bump; removing
or renaming fields is a major-version break.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
from typing import Any, Callable, Iterator, List, Optional

EventSink = Callable[[dict], None]

_lock = threading.Lock()
_mode: str = "human"
_sink: EventSink | None = None  # populated on first use


def _fmt_human(event: dict) -> str | None:
    """Return a line of human text for an event, or None to suppress output.

    Kept deliberately simple — no color codes; the event transport may not be
    a TTY. CLI users on a TTY still get the subprocess output of the pipeline
    scripts (which is unaffected), so the overall terminal experience is
    comparable to the legacy print-based wedge commands.
    """
    kind = event.get("kind", "info")
    if kind == "stage":
        idx = event.get("index", "?")
        tot = event.get("total", "?")
        name = event.get("name", "")
        return f"[{idx}/{tot}] {name}"
    if kind == "stage.done":
        name = event.get("name", "")
        arts = event.get("artifacts") or {}
        if arts:
            parts = ", ".join(f"{k}={v}" for k, v in arts.items())
            return f"       done: {name} ({parts})"
        return f"       done: {name}"
    if kind == "detail":
        return f"       {event.get('message', '')}"
    if kind == "warn":
        return f"  WARN: {event.get('message', '')}"
    if kind == "error":
        return f"  ERROR: {event.get('message', '')}"
    if kind == "result":
        ec = event.get("exit_code", "?")
        return f"result: exit_code={ec}"
    if kind == "run.start":
        cmd = event.get("command", "?")
        repo = event.get("repo", "")
        return f"kaizen {cmd}  {repo}".rstrip()
    # Unknown kinds — suppress in human mode; they're still captured in sinks.
    return None


def _default_stdout_sink(event: dict) -> None:
    if _mode == "ndjson":
        sys.stdout.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
        sys.stdout.flush()
        return
    line = _fmt_human(event)
    if line is None:
        return
    stream = sys.stderr if event.get("kind") in ("warn", "error") else sys.stdout
    stream.write(line + "\n")
    stream.flush()


def _init_from_env() -> None:
    global _mode
    mode = os.environ.get("KAIZEN_EVENT_STREAM", "").strip().lower()
    if mode in ("ndjson", "json", "jsonl"):
        _mode = "ndjson"


def _get_sink() -> EventSink:
    global _sink
    with _lock:
        if _sink is None:
            _sink = _default_stdout_sink
        return _sink


def set_mode(mode: str) -> None:
    """Set the output mode for the default stdout sink. Accepts 'human' | 'ndjson'."""
    global _mode
    if mode not in ("human", "ndjson"):
        raise ValueError(f"unknown event mode: {mode!r}")
    with _lock:
        _mode = mode


def get_mode() -> str:
    return _mode


def set_sink(sink: Optional[EventSink]) -> None:
    """Replace the event sink. Pass None to restore the default stdout sink."""
    global _sink
    with _lock:
        _sink = sink if sink is not None else _default_stdout_sink


@contextlib.contextmanager
def capture() -> Iterator[List[dict]]:
    """Collect events into a list for the duration of the block.

    Useful for tests:
        with events.capture() as captured:
            run_something()
        assert captured[0]["kind"] == "run.start"
    """
    captured: List[dict] = []
    previous = _get_sink()
    set_sink(captured.append)
    try:
        yield captured
    finally:
        set_sink(previous if previous is not _default_stdout_sink else None)


@contextlib.contextmanager
def ndjson_mode() -> Iterator[None]:
    """Temporarily switch the default stdout sink to NDJSON output."""
    previous = get_mode()
    set_mode("ndjson")
    try:
        yield
    finally:
        set_mode(previous)


def emit(kind: str, **fields: Any) -> None:
    """Emit a single event. Safe to call from any thread."""
    event = {"kind": kind, **fields}
    _get_sink()(event)


# --- Convenience helpers (stable API; prefer these over emit()) --------------


def run_start(command: str, **fields: Any) -> None:
    emit("run.start", command=command, **fields)


def stage(name: str, *, index: int, total: int, **fields: Any) -> None:
    emit("stage", name=name, index=index, total=total, **fields)


def stage_done(name: str, **fields: Any) -> None:
    emit("stage.done", name=name, **fields)


def detail(message: str, **fields: Any) -> None:
    emit("detail", message=message, **fields)


def warn(message: str, **fields: Any) -> None:
    emit("warn", message=message, **fields)


def error(message: str, **fields: Any) -> None:
    emit("error", message=message, **fields)


def result(exit_code: int, **fields: Any) -> None:
    emit("result", exit_code=exit_code, **fields)


def run_subprocess_with_logs(
    cmd: list,
    env: dict | None = None,
    source: str = "subprocess",
) -> int:
    """Run a subprocess and emit its stdout line-by-line as 'detail' events.

    Drop-in replacement for `subprocess.run(cmd).returncode` when you want
    the subprocess output to flow as structured events (for web UI SSE,
    log capture, or NDJSON pipelines).

    Behavior:
    - Each line of subprocess stdout becomes one `detail` event with
      `source=<source>`.
    - stderr is NOT captured — it passes through to the parent's stderr
      unchanged. LLM-provider errors and stack traces stay visible in the
      terminal.
    - Return value is the subprocess exit code, same as
      `subprocess.run(cmd).returncode`.
    """
    import subprocess

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    try:
        assert proc.stdout is not None  # for type checkers
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip("\n")
            if line:
                detail(line, source=source)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        proc.wait()
    return proc.returncode


# Initialize mode from env at import time — CLI users get NDJSON when they
# invoke `KAIZEN_EVENT_STREAM=ndjson kaizen memsafe-roadmap ...`
_init_from_env()
