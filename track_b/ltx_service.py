"""LTX-2.3 · 3DREAL render-to-real sidecar — the cinematic MOTION pass.

Turns a Cycles turntable (+ its beauty still as the first frame) into a photoreal clip via LTX-2.3 with
the 3DREAL IC-LoRA. Runs in its OWN venv (`~/LTX-2/.venv`: torch 2.9.1+cu128, ltx_pipelines) — kept off
trellis_venv — and keeps the 22B model RESIDENT so each animate is fast (no 43GB reload per call). The
model is heavy, so this is a long-lived service, mirroring how vLLM hosted Track A.

  POST /animate  {turntable_mp4_b64, first_frame_png_b64, prompt, variant?, height?, width?,
                  num_frames?, seed?, skip_stage_2?}   -> {mp4_b64, seconds, variant, frames}
  GET  /health   -> {ok, loaded_variant}

SYNCHRONOUS by design: track_b/server.py's async /animate JOB calls this over localhost and blocks its
worker thread on it (the tunnel-safe submit→poll contract lives in track_b, not here). A process-wide
threading lock serializes calls, and the cross-process file lock (_gpulock) keeps it off the GPU while
TRELLIS/FLUX/Blender are working in the other process.

Run:  ~/LTX-2/.venv/bin/python track_b/ltx_service.py [port]   (default 8771; binds 127.0.0.1)
      env: LTX_MODELS_DIR (default /workspace/.hf_home/ltx-models), HF_HOME, HF_HUB_OFFLINE=1
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# share the one cross-process GPU mutex with track_b/server.py (same lock file)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _gpulock import gpu_lock  # noqa: E402

MODELS = os.environ.get("LTX_MODELS_DIR", "/workspace/.hf_home/ltx-models")
CKPT = os.path.join(MODELS, "ltx-2.3-22b-distilled-1.1.safetensors")
UPSAMPLER = os.path.join(MODELS, "ltx-2.3-spatial-upscaler-x2-1.1.safetensors")
GEMMA = os.path.join(MODELS, "gemma-3-12b")
LORAS = {
    "strong": os.path.join(MODELS, "3dreal", "3DREAL-strong.safetensors"),
    "light": os.path.join(MODELS, "3dreal", "3DREAL-light.safetensors"),
}

_lock = threading.Lock()      # one animate at a time (resident model, single GPU)
_pipe = None                  # (variant, ICLoraPipeline) — one resident; switching variant rebuilds


def _get_pipeline(variant: str):
    """Return the resident ICLoraPipeline for *variant*, (re)building it if the variant changed.

    Only one pipeline is kept resident to bound VRAM; switching light<->strong evicts and reloads
    (~30s). Most sessions stay on one variant, so this is amortized to ~free."""
    global _pipe
    if _pipe is not None and _pipe[0] == variant:
        return _pipe[1]
    import gc

    import torch
    from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP, LoraPathStrengthAndSDOps
    from ltx_pipelines.ic_lora import ICLoraPipeline
    from ltx_pipelines.utils.quantization_factory import QuantizationKind

    if variant not in LORAS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {sorted(LORAS)}")
    if _pipe is not None:                       # evict the old variant first to free VRAM before reloading
        _pipe = None
        gc.collect(); torch.cuda.empty_cache()
    print(f"[ltx] loading ICLoraPipeline (variant={variant}, fp8-cast)…", flush=True)
    t0 = time.time()
    lora = LoraPathStrengthAndSDOps(LORAS[variant], 1.0, LTXV_LORA_COMFY_RENAMING_MAP)
    quant = QuantizationKind("fp8-cast").to_policy(checkpoint_path=CKPT)
    pipe = ICLoraPipeline(
        distilled_checkpoint_path=CKPT,
        spatial_upsampler_path=UPSAMPLER,
        gemma_root=GEMMA,
        loras=(lora,),
        quantization=quant,
    )
    _pipe = (variant, pipe)
    print(f"[ltx] pipeline ready in {time.time() - t0:.0f}s", flush=True)
    return pipe


def _strip_audio(src: str, dst: str) -> str:
    """Re-mux video-only (drop LTX's generated audio track) — product turntables shouldn't carry sound.
    Falls back to the original (with audio) if ffmpeg isn't available."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-an", "-c:v", "copy", dst],
            capture_output=True, text=True, timeout=120,
        )
        return dst if r.returncode == 0 and os.path.exists(dst) else src
    except Exception:  # noqa: BLE001
        return src


def animate(turntable_path: str, first_frame_path: str, prompt: str, variant: str = "strong",
            height: int = 768, width: int = 768, num_frames: int = 49, frame_rate: float = 24.0,
            seed: int = 42, skip_stage_2: bool = False) -> str:
    """Render-to-real: (turntable video + first-frame image + prompt) -> photoreal mp4 path."""
    import torch
    from ltx_core.model.video_vae import TilingConfig, get_video_chunks_number
    from ltx_pipelines.utils.args import ImageConditioningInput
    from ltx_pipelines.utils.media_io import encode_video

    if not prompt.strip().lower().startswith("3dreal"):
        prompt = "3DREAL. " + prompt.strip()                 # the LoRA's required trigger, at the front

    workdir = tempfile.mkdtemp(prefix="ltx_anim_")
    raw = os.path.join(workdir, "raw.mp4")
    out = os.path.join(workdir, "animated.mp4")
    with _lock, gpu_lock():                                   # one at a time, exclusive GPU across processes
        try:
            pipe = _get_pipeline(variant)                    # loads on first use / variant switch (under lock)
            tiling = TilingConfig.default()
            with torch.inference_mode():
                video, audio = pipe(
                    prompt=prompt, seed=seed, height=height, width=width,
                    num_frames=num_frames, frame_rate=frame_rate,
                    images=[ImageConditioningInput(first_frame_path, 0, 1.0)],   # beauty still drives frame 0
                    video_conditioning=[(turntable_path, 1.0)],                  # turntable drives the motion
                    tiling_config=tiling, skip_stage_2=skip_stage_2,
                )
                encode_video(video=video, fps=frame_rate, audio=audio, output_path=raw,
                             video_chunks_number=get_video_chunks_number(num_frames, tiling))
        finally:
            import gc
            gc.collect(); torch.cuda.empty_cache()           # release transients; keep the resident model
    return _strip_audio(raw, out)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/health", ""):
            return self._json(200, {"ok": True, "loaded_variant": _pipe[0] if _pipe else None})
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/animate":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"bad request: {e}"})

        workdir = tempfile.mkdtemp(prefix="ltx_in_")
        try:
            tt = os.path.join(workdir, "turntable.mp4")
            ff = os.path.join(workdir, "first.png")
            open(tt, "wb").write(base64.b64decode(body["turntable_mp4_b64"]))
            open(ff, "wb").write(base64.b64decode(body["first_frame_png_b64"]))
            t0 = time.time()
            mp4 = animate(
                tt, ff,
                prompt=body.get("prompt", ""),
                variant=body.get("variant", "strong"),
                height=int(body.get("height", 768)),
                width=int(body.get("width", 768)),
                num_frames=int(body.get("num_frames", 49)),
                frame_rate=float(body.get("frame_rate", 24.0)),
                seed=int(body.get("seed", 42)),
                skip_stage_2=bool(body.get("skip_stage_2", False)),
            )
            data = base64.b64encode(open(mp4, "rb").read()).decode()
            self._json(200, {"mp4_b64": data, "seconds": round(time.time() - t0),
                             "variant": body.get("variant", "strong"),
                             "frames": int(body.get("num_frames", 49))})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-900:]})

    def log_message(self, *_):  # quiet
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8771
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    for p in (CKPT, UPSAMPLER, GEMMA, LORAS["strong"]):
        if not os.path.exists(p):
            print(f"[ltx] WARNING: missing model asset: {p}", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"LTX-2.3 3DREAL sidecar on http://127.0.0.1:{port}  (POST /animate ; model loads on first call)",
          flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
