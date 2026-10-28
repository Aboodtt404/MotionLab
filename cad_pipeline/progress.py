"""Live job progress — the generation-theater channel.

The dev server (server.py) sets a per-job sink at the top of each job THREAD; any pipeline code
running synchronously inside that job (planner streaming, asm_loop attempts, build_assembly part
placement) calls `publish(**fields)` and the fields land in the job record that GET /job/<id>
polls. Everywhere else (evals, training, tests) no sink is set and publish() is a zero-cost no-op —
pipeline behavior is byte-identical when inactive.

contextvars, not a global: each job runs in its own thread, and ContextVar values set inside a
thread are invisible to sibling threads, so concurrent jobs can't cross-publish.
"""
from __future__ import annotations

import contextvars
from typing import Callable, Optional

_SINK: contextvars.ContextVar[Optional[Callable[..., None]]] = contextvars.ContextVar(
    "cad_progress_sink", default=None)


def set_sink(fn: Optional[Callable[..., None]]) -> None:
    """Install the per-job sink (call from the job thread). Pass None to clear."""
    _SINK.set(fn)


def active() -> bool:
    """True when a sink is installed — gate any work done ONLY for progress (e.g. per-part STL
    tessellation, token streaming) behind this so evals never pay for it."""
    return _SINK.get() is not None


def publish(**fields) -> None:
    """Merge fields into the live job record. Never raises into pipeline code."""
    fn = _SINK.get()
    if fn is None:
        return
    try:
        fn(**fields)
    except Exception:  # noqa: BLE001 — the theater must never kill the job
        pass
