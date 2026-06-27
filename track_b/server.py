"""Track B HTTP service — organic image-to-3D, the sibling of cad_pipeline/server.py.

  POST /image2mesh  {image_b64, pipeline_type?, seed?}  ->  {glb_b64, report, seconds, pipeline_type}

Stdlib only (no new deps). Runs in `trellis_venv` (torch 2.11/cu128 + sm_120 extensions) — kept OFF
cad_pipeline's venv. The TRELLIS.2 pipeline is loaded once at startup and kept resident; a process-wide
lock serializes generations (one GPU). Co-hosts with Track A's vLLM via the static split (vLLM at 0.65
util leaves ~33 GB, which fits TRELLIS at 512³ AND 1024_cascade on this box — measured). The vLLM
Sleep-Mode mutex (docs/research/track-b-implementation.md §6.1) is the production-robustness upgrade,
not needed for this single-user MVP.

Run:  HF_TOKEN=$(cat ~/.cache/huggingface/token) trellis_venv/bin/python -m track_b.server [port]   (default 8770)
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .backbone import _pipeline, generate, inspect_glb

_lock = threading.Lock()   # one TRELLIS job at a time (single GPU, resident pipeline)


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204); self._cors(); self.end_headers()

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/image2mesh":
            return self._json(404, {"error": "not found"})
        try:
            from PIL import Image
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            img = Image.open(io.BytesIO(base64.b64decode(body["image_b64"])))
            ptype = body.get("pipeline_type", "512")
            seed = int(body.get("seed", 42))
            with _lock:                                   # serialize — single GPU, resident model
                t = time.time()
                with tempfile.TemporaryDirectory() as d:
                    out = os.path.join(d, "mesh.glb")
                    generate(img, out, seed=seed, pipeline_type=ptype)
                    glb_b64 = base64.b64encode(open(out, "rb").read()).decode()
                    report = inspect_glb(out)
                dt = round(time.time() - t)
            self._json(200, {"glb_b64": glb_b64, "report": report, "seconds": dt, "pipeline_type": ptype})
        except Exception as e:  # noqa: BLE001
            self._json(400, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]})

    def log_message(self, *_):  # quiet
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    host = os.environ.get("CAD_BIND", "127.0.0.1")   # set CAD_BIND=0.0.0.0 to reach it over the network
    print("warming TRELLIS.2 pipeline (one-time ~40s load)...", flush=True)
    _pipeline()
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Track B API on http://{host}:{port}  (POST /image2mesh)", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
