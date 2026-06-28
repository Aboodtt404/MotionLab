"""Cross-process GPU mutex.

track_b/server.py (TRELLIS/FLUX/Blender, in trellis_venv) and ltx_service.py (LTX-2.3, in LTX-2/.venv)
are SEPARATE processes sharing one GPU. Each has its own in-process threading.Lock, but those don't
coordinate across processes — so a TRELLIS generation and an LTX animate could land on the card at the
same time and OOM. A file lock (flock) is the one mutex both processes can see. Pure stdlib so it imports
in either venv. Hold it only around the GPU-heavy section; it's released if the process dies.
"""
from __future__ import annotations

import contextlib
import fcntl
import os

_LOCK_PATH = os.environ.get("MOTIONLAB_GPU_LOCK", "/tmp/motionlab_gpu.lock")


@contextlib.contextmanager
def gpu_lock():
    """Block until the single-GPU lock is held, then release on exit (or process death)."""
    f = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()
