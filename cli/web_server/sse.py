# SPDX-License-Identifier: Apache-2.0
"""SSE streaming helper for wedge routes.

Runs a CLI command function in a worker thread, captures `cli.events` emissions
into a queue, and yields each event as a Server-Sent Events message to the
browser. The CLI command's `events.set_sink(queue.put)` side effect is what
makes this work — no subprocess, no stdout parsing.

Usage pattern:

    @router.post("/memsafe-roadmap")
    async def route(req, stream: bool = False):
        if not stream:
            exit_code = await run_in_threadpool(memsafe_roadmap_command, ns)
            return _collect_results(req, exit_code)
        return EventSourceResponse(
            stream_command_events(memsafe_roadmap_command, ns),
            sep="\\n",
        )
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any, AsyncIterator, Callable

from cli import events

# Sentinel emitted on the queue when the worker thread finishes.
_END_SENTINEL: dict[str, Any] = {"kind": "__end__"}


async def stream_command_events(
    command: Callable[..., int],
    *args: Any,
    poll_interval: float = 0.05,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-shaped event dicts as the command emits them.

    Each yielded dict has the shape {"event": <kind>, "data": <json-string>}
    which sse-starlette's EventSourceResponse serializes directly onto the wire.

    The command runs in a dedicated worker thread. The route handler should
    return EventSourceResponse(stream_command_events(cmd, *args)).

    On client disconnect, the generator is cancelled; the worker thread
    continues to completion in the background (pipeline already started).
    This is an acceptable trade-off for a developer-local tool — the wedge
    produces local artifacts regardless of whether the browser is listening.
    """
    q: queue.Queue = queue.Queue()
    exit_code_holder: dict[str, int] = {}

    def sink(event: dict) -> None:
        q.put(event)

    def worker() -> None:
        previous_sink = events._get_sink()  # type: ignore[attr-defined]
        events.set_sink(sink)
        try:
            rc = command(*args)
            exit_code_holder["code"] = int(rc) if isinstance(rc, int) else 0
        except Exception as exc:  # noqa: BLE001 — any failure becomes an SSE event
            events.error(f"{exc.__class__.__name__}: {exc}")
            exit_code_holder["code"] = 1
        finally:
            events.set_sink(previous_sink if previous_sink is not events._default_stdout_sink else None)  # type: ignore[attr-defined]
            q.put(_END_SENTINEL)

    thread = threading.Thread(target=worker, daemon=True, name="kaizen-web-worker")
    thread.start()

    try:
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(poll_interval)
                continue
            if event is _END_SENTINEL or event.get("kind") == "__end__":
                # Synthesize a terminal event so the browser knows we're done.
                yield {
                    "event": "end",
                    "data": json.dumps({
                        "kind": "end",
                        "exit_code": exit_code_holder.get("code", 0),
                    }),
                }
                return
            yield {
                "event": event.get("kind", "message"),
                "data": json.dumps(event, default=str),
            }
    finally:
        # Best-effort; the thread is daemonized and will be cleaned up with
        # the process. For long-running commands that outlive the generator
        # (client disconnected), we let them finish in the background.
        pass
