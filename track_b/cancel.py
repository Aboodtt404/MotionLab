"""Cooperative GPU-job cancellation for TRELLIS generations.

A running generation is a synchronous CUDA call inside a worker thread — you can't kill the thread or
interrupt the CUDA call cleanly. But every TRELLIS sampler calls `_inference_model` once per denoising
step, so we monkey-patch that (same technique as trellis_multiview.inject_sampler_multi_image) to raise
`Cancelled` when the job's cancel flag is set. That aborts the run within ~1 step and releases the GPU
lock (the `with` unwinds), so a queued job can start. Composes/nests cleanly with the multi-view patch.

Covers the sampling phases (the long part). The short non-sampling tail (MV-Adapter view pass, mesh
decode / 4K bake / export) is not step-interruptible — cancel takes effect at the next sampler step.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable

_SAMPLERS = ("sparse_structure_sampler", "shape_slat_sampler", "tex_slat_sampler")


class Cancelled(Exception):
    """Raised inside a sampler step to abort a generation whose job was cancelled."""


@contextmanager
def cancel_hook(pipe, should_cancel: Callable[[], bool]):
    """Patch each sampler's `_inference_model` to raise Cancelled() when should_cancel() is True
    (checked every denoising step). Restores the originals on exit."""
    patched = []
    for name in _SAMPLERS:
        s = getattr(pipe, name, None)
        if s is None:
            continue
        old = s._inference_model  # bound method (or a prior patch, e.g. multi-view) — captured to chain

        def _make(old_fn):
            def _patched(model, x_t, t, *args, **kwargs):
                if should_cancel():
                    raise Cancelled()
                return old_fn(model, x_t, t, *args, **kwargs)
            return _patched

        s._inference_model = _make(old)
        patched.append((s, old))
    try:
        yield
    finally:
        for s, old in patched:
            s._inference_model = old
