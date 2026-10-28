"""Track B HTTP service — organic image/text-to-3D, the sibling of cad_pipeline/server.py.

  POST /image2mesh  {image_b64, pipeline_type?, seed?}   -> {job_id}
  POST /text2mesh   {prompt, pipeline_type?, seed?}       -> {job_id}        (FLUX concept → TRELLIS)
  GET  /job/<id>    -> {status: queued|running|done|error, stage, elapsed, ...result when done}

ASYNC by design: a hero TRELLIS generation (1536_cascade) takes minutes, but Cloudflare quick-tunnels
cut any single request at ~100s (524). So a POST enqueues a job and returns immediately; a background
worker runs the (GPU-serialized) job while the client polls GET /job/<id> with short requests. Each HTTP
round-trip stays well under the tunnel limit, so arbitrarily-long generations work over the tunnel.

Stdlib only (no new deps). Runs in `trellis_venv` (torch 2.11/cu128 + sm_120 extensions) — kept OFF
cad_pipeline's venv. The TRELLIS.2 pipeline (and FLUX, lazily) are loaded once and kept resident; a
process-wide GPU lock serializes generations (single GPU). Co-hosts with Track A's vLLM (0.65 util).

Run:  HF_TOKEN=$(cat ~/.cache/huggingface/token) trellis_venv/bin/python -m track_b.server [port]   (default 8770)
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid

# Phase-1 cinematic render (Blender/Cycles) — a subprocess, not a venv import (Blender has its own python).
BLENDER = os.environ.get("BLENDER_BIN", os.path.expanduser("~/blender/blender"))
CINEMATIC = os.path.join(os.path.dirname(__file__), "cinematic.py")
DECIMATE = os.path.join(os.path.dirname(__file__), "decimate.py")   # Low-Poly / Remesh pass (CPU, Blender subprocess)
# Infinigen terrain tile: generate terrain-only (its own venv), then bake → vertex-colored GLB (Blender).
TERRAIN_EXPORT = os.path.join(os.path.dirname(__file__), "terrain_export.py")
INFINIGEN_PY = os.environ.get("INFINIGEN_PY", os.path.expanduser("~/infinigen_venv/bin/python"))
INFINIGEN_DIR = os.environ.get("INFINIGEN_DIR", os.path.expanduser("~/infinigen"))
_TERRAIN_BIOMES = {"plain", "desert", "forest", "snowy_mountain", "arctic", "mountain", "coast", "canyon", "cliff", "river"}
# Cinematic MOTION pass (LTX-2.3 · 3DREAL) — a resident sidecar in its own venv; we proxy to it over localhost.
LTX_SERVICE_URL = os.environ.get("LTX_SERVICE_URL", "http://127.0.0.1:8771")
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ._gpulock import gpu_lock
from .backbone import _pipeline, generate, inspect_glb
from .cancel import Cancelled, cancel_hook

_gpu = threading.Lock()           # one TRELLIS/FLUX job on the GPU at a time (single GPU, resident models)
_jobs: dict = {}                  # job_id -> job dict (status/stage/result/error/times)
_jobs_lock = threading.Lock()     # guards _jobs
_MAX_JOBS = 24                    # keep the last N jobs' results in memory, prune older


def _new_job() -> str:
    jid = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[jid] = {"status": "queued", "stage": "queued", "created": time.time(),
                      "started": None, "result": None, "error": None}
        # prune oldest finished jobs to bound memory (each GLB result is tens of MB)
        if len(_jobs) > _MAX_JOBS:
            old = sorted(_jobs.items(), key=lambda kv: kv[1]["created"])[: len(_jobs) - _MAX_JOBS]
            for k, _ in old:
                _jobs.pop(k, None)
    return jid


def _set(jid: str, **kw):
    with _jobs_lock:
        if jid in _jobs:
            _jobs[jid].update(kw)


def _run_job(jid: str, kind: str, body: dict):
    """Background worker: runs the (GPU-serialized) generation and stores the result on the job."""
    ptype = body.get("pipeline_type", "1536_cascade")
    seed = int(body.get("seed", 42))
    _set(jid, status="running", started=time.time())
    try:
        if kind == "render":                             # Cycles photoreal beauty still + turntable (Blender subprocess)
            _set(jid, stage="rendering")
            with _gpu, gpu_lock(), tempfile.TemporaryDirectory() as d:
                glb = os.path.join(d, "in.glb")
                open(glb, "wb").write(base64.b64decode(body["glb_b64"]))
                cmd = [BLENDER, "-b", "-P", CINEMATIC, "--", glb, d,
                       str(int(body.get("samples", 128))), str(int(body.get("res", 1280))),
                       str(int(body.get("turn_frames", 36)))]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
                if "RENDER_OK" not in r.stdout:
                    raise RuntimeError("blender render failed: " + (r.stderr[-400:] or r.stdout[-400:]))
                beauty, mp4 = os.path.join(d, "beauty.png"), os.path.join(d, "turntable.mp4")
                result = {"beauty_png_b64": base64.b64encode(open(beauty, "rb").read()).decode() if os.path.exists(beauty) else None,
                          "seconds": round(time.time() - _jobs[jid]["started"])}
                if os.path.exists(mp4):
                    result["turntable_mp4_b64"] = base64.b64encode(open(mp4, "rb").read()).decode()
            _set(jid, status="done", stage="done", result=result)
            return
        if kind == "animate":                            # cinematic MOTION pass — proxy to the resident LTX sidecar
            _set(jid, stage="animating")                 # LTX holds the GPU lock itself; no local _gpu needed here
            import urllib.error
            import urllib.request
            payload = json.dumps({
                "turntable_mp4_b64": body["turntable_mp4_b64"],
                "first_frame_png_b64": body["first_frame_png_b64"],
                "prompt": body.get("prompt", ""),
                "variant": body.get("variant", "strong"),
                "num_frames": int(body.get("num_frames", 49)),
                "height": int(body.get("height", 768)),
                "width": int(body.get("width", 768)),
                "seed": seed,
            }).encode()
            req = urllib.request.Request(LTX_SERVICE_URL + "/animate", data=payload,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=1800) as r:   # blocks ~40s+; tunnel-safe via our async job
                    resp = json.loads(r.read())
            except urllib.error.URLError as e:
                raise RuntimeError(f"LTX motion service unreachable at {LTX_SERVICE_URL} — "
                                   f"start it with ~/LTX-2/.venv/bin/python track_b/ltx_service.py ({e})")
            if "mp4_b64" not in resp:
                raise RuntimeError("LTX service: " + str(resp.get("error", resp)))
            _set(jid, status="done", stage="done",
                 result={"animated_mp4_b64": resp["mp4_b64"], "seconds": resp.get("seconds"),
                         "variant": resp.get("variant")})
            return
        if kind == "terrain":                            # Infinigen terrain TILE: gen terrain-only (CPU ~5min) → bake → GLB
            biome = body.get("biome", "plain")
            if biome not in _TERRAIN_BIOMES:
                biome = "plain"
            with tempfile.TemporaryDirectory() as d:
                _set(jid, stage="generating terrain")    # Infinigen runs in its OWN venv; CPU-bound, no GPU lock here
                gen = subprocess.run(
                    [INFINIGEN_PY, "-m", "infinigen_examples.generate_nature", "--seed", str(seed),
                     "--task", "coarse", "-g", biome, "dev", "no_assets",
                     "--output_folder", os.path.join(d, "coarse")],
                    cwd=INFINIGEN_DIR, capture_output=True, text=True, timeout=2400)
                blend = os.path.join(d, "coarse", "scene.blend")
                if not os.path.exists(blend):
                    raise RuntimeError("terrain gen failed: " + (gen.stderr[-600:] or gen.stdout[-600:]))
                _set(jid, stage="baking tile")           # bake material → vertex colors + GLB export (GPU — serialize)
                tile = os.path.join(d, "terrain.glb")
                with _gpu, gpu_lock():
                    exp = subprocess.run([BLENDER, "-b", "-P", TERRAIN_EXPORT, "--", blend, tile,
                                          str(int(body.get("target_faces", 40000)))],
                                         capture_output=True, text=True, timeout=900)
                if "TERRAIN_TILE_OK" not in exp.stdout:
                    raise RuntimeError("terrain export failed: " + (exp.stderr[-500:] or exp.stdout[-500:]))
                glb_b64 = base64.b64encode(open(tile, "rb").read()).decode()
                report = inspect_glb(tile)
            _set(jid, status="done", stage="done",
                 result={"glb_b64": glb_b64, "report": report, "biome": biome,
                         "seconds": round(time.time() - _jobs[jid]["started"])})
            return
        if kind == "repair":                             # printability gate + repair loop (Slice 2; CPU, no GPU lock)
            _set(jid, stage="repairing")
            with tempfile.TemporaryDirectory() as d:
                gin = os.path.join(d, "in.glb")
                open(gin, "wb").write(base64.b64decode(body["glb_b64"]))
                from .repair_glb import repair_glb
                rep = repair_glb(gin, body.get("profile", "print"), os.path.join(d, "out.glb"))
                glb_b64 = base64.b64encode(open(rep["out_path"], "rb").read()).decode()
            _set(jid, status="done", stage="done",
                 result={"glb_b64": glb_b64, "passed": rep["passed"], "passes": rep["passes"],
                         "actions": rep["actions"], "surface_rebuilt": rep["surface_rebuilt"],
                         "before": rep["before"], "after": rep["after"],
                         "seconds": round(time.time() - _jobs[jid]["started"])})
            return
        if kind == "rig":                                # Auto-rig: mesh GLB → game-ready rigged GLB (SkinTokens venv)
            from .rig import inspect_rig, rig_glb        # subprocess into its own py3.11 venv — see rig.py
            _set(jid, stage="rigging")
            with _gpu, gpu_lock():                       # SkinTokens inference needs ~14 GB
                with tempfile.TemporaryDirectory() as d:
                    gin, gout = os.path.join(d, "in.glb"), os.path.join(d, "out.glb")
                    open(gin, "wb").write(base64.b64decode(body["glb_b64"]))
                    rig_glb(gin, gout)
                    _set(jid, stage="verifying rig")
                    rep = inspect_rig(gout)
                    glb_b64 = base64.b64encode(open(gout, "rb").read()).decode()
            _set(jid, status="done", stage="done",
                 result={"glb_b64": glb_b64, "rig_report": rep, "passed": rep["passed"],
                         "seconds": round(time.time() - _jobs[jid]["started"])})
            return
        if kind == "animate_clip":                       # rigged GLB + (motion prompt | ref MP4) → GLB with an animation clip
            from . import animate_clip as anim           # Puppeteer video-guided optimizer — see animate_clip.py
            workdir = tempfile.mkdtemp(prefix="animclip_")
            try:
                gin = os.path.join(workdir, "in.glb")
                open(gin, "wb").write(base64.b64decode(body["glb_b64"]))
                _set(jid, stage="building rig proxy")
                meta = anim.prepare_inputs(gin, workdir, "clip")   # raises if the GLB has no skeleton
                seq_dir = os.path.join(workdir, "inputs", "clip")
                guide = os.path.join(workdir, "guide.mp4")
                if body.get("mp4_b64"):                  # reference-video path
                    src = os.path.join(workdir, "ref.mp4")
                    open(src, "wb").write(base64.b64decode(body["mp4_b64"]))
                    _set(jid, stage="preparing your video")
                    anim.normalize_guidance(src, guide)
                elif body.get("prompt"):                 # text path: render first frame → LTX i2v motion video
                    _set(jid, stage="rendering first frame")
                    with _gpu, gpu_lock():
                        front = anim.render_first_frame(os.path.join(workdir, "inputs"), "clip")
                    _set(jid, stage="generating motion video")   # sidecar takes the GPU lock itself
                    anim.text_to_guidance(body["prompt"], front, guide)
                else:
                    raise RuntimeError("need a motion prompt or a reference mp4")
                with _gpu, gpu_lock():                   # flow + the long optimization stage
                    _set(jid, stage="extracting frames")
                    nframes = anim.extract_and_flow(workdir, "clip", guide,
                                                    on_stage=lambda s: _set(jid, stage=s))
                    iters = int(body.get("iters", 150))
                    _set(jid, stage=f"optimizing motion ({nframes} frames, {iters} iters — slow)")
                    motion_dir = anim.optimize(workdir, "clip", iters=iters)
                _set(jid, stage="embedding clip")
                gout = os.path.join(workdir, "out.glb")
                report = anim.embed_clip(gin, motion_dir, seq_dir, gout)
                report.update(proxy_verts=meta["n_verts"], full_verts=meta["n_verts_full"], iters=iters)
                glb_b64 = base64.b64encode(open(gout, "rb").read()).decode()
                _set(jid, status="done", stage="done",
                     result={"glb_b64": glb_b64, "anim_report": report, "passed": True,
                             "seconds": round(time.time() - _jobs[jid]["started"])})
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
            return
        if kind == "lowpoly":                            # Low-Poly / Remesh: decimate a GLB to a face budget (CPU, no GPU)
            _set(jid, stage="decimating")
            with tempfile.TemporaryDirectory() as d:
                gin, gout = os.path.join(d, "in.glb"), os.path.join(d, "out.glb")
                open(gin, "wb").write(base64.b64decode(body["glb_b64"]))
                cmd = [BLENDER, "-b", "-P", DECIMATE, "--", gin, gout, str(int(body.get("target_faces", 5000)))]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if "DECIMATE_OK" not in r.stdout:
                    raise RuntimeError("decimate failed: " + (r.stderr[-400:] or r.stdout[-400:]))
                glb_b64 = base64.b64encode(open(gout, "rb").read()).decode()
                report = inspect_glb(gout)
            _set(jid, status="done", stage="done",
                 result={"glb_b64": glb_b64, "report": report,
                         "seconds": round(time.time() - _jobs[jid]["started"])})
            return
        with _gpu, gpu_lock():                           # serialize GPU access across all jobs (+ cross-process)
            concept_b64 = None
            if kind == "text2mesh":
                _set(jid, stage="concept")               # FLUX text → concept image
                from .t2i import text_to_image
                kw = {"seed": seed, "raw": bool(body.get("raw"))}   # let t2i pick dev-appropriate steps/guidance
                if body.get("steps"):
                    kw["steps"] = int(body["steps"])
                img = text_to_image(body["prompt"], **kw)
                buf = io.BytesIO(); img.save(buf, "PNG")
                concept_b64 = base64.b64encode(buf.getvalue()).decode()
                _set(jid, concept_png_b64=concept_b64)   # surface to pollers NOW (before the long TRELLIS stage)
            else:                                        # uploaded reference image
                from PIL import Image
                img = Image.open(io.BytesIO(base64.b64decode(body["image_b64"])))
            _set(jid, stage="generating")                # TRELLIS sampling + mesh extraction (the long part)
            scancel = lambda: bool((_jobs.get(jid) or {}).get("cancel"))   # noqa: E731
            if scancel():
                raise Cancelled()
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "mesh.glb")
                with cancel_hook(_pipeline(), scancel):  # abort within ~1 sampler step if the job is cancelled
                    if body.get("multiview"):            # hi-fi: hero → MV-Adapter 6 views → multi-view TRELLIS
                        from .backbone import generate_multiview
                        def _on_views(vs):               # downscale → base64 PNGs for a UI collage preview
                            enc = []
                            for v in vs:
                                t = v.copy(); t.thumbnail((256, 256))
                                b = io.BytesIO(); t.save(b, "PNG"); enc.append(base64.b64encode(b.getvalue()).decode())
                            _set(jid, mv_views_b64=enc)
                        generate_multiview(img, out, text=body.get("prompt", ""), seed=seed,
                                           pipeline_type=ptype, on_stage=lambda s: _set(jid, stage=s), on_views=_on_views)
                    else:
                        generate(img, out, seed=seed, pipeline_type=ptype)
                glb_b64 = base64.b64encode(open(out, "rb").read()).decode()
                report = inspect_glb(out)
        result = {"glb_b64": glb_b64, "report": report, "pipeline_type": ptype,
                  "seconds": round(time.time() - _jobs[jid]["started"])}
        if concept_b64 is not None:
            result["concept_png_b64"] = concept_b64
        _set(jid, status="done", stage="done", result=result)
    except Cancelled:
        _set(jid, status="cancelled", stage="cancelled")   # user aborted; GPU lock already released
    except Exception as e:  # noqa: BLE001
        _set(jid, status="error", stage="error",
             error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-800:])
    finally:
        # release cached GPU blocks back to the driver after every job — the server is long-lived and
        # co-hosts with vLLM on a tight budget; without this, fragmentation creeps until the heaviest
        # tier (1536_cascade) CUDA-errors in CuMesh (as it did). Cheap; keeps headroom stable.
        try:
            import gc, torch
            gc.collect(); torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
        route = self.path.rstrip("/")
        if route.startswith("/cancel/"):                 # cooperative cancel: flag the job; worker aborts at next step
            jid = route[len("/cancel/"):]
            with _jobs_lock:
                ok = jid in _jobs
                if ok:
                    _jobs[jid]["cancel"] = True
            return self._json(200 if ok else 404, {"ok": ok, "cancelling": jid})
        kind = {"/image2mesh": "image2mesh", "/text2mesh": "text2mesh",
                "/render": "render", "/animate": "animate", "/lowpoly": "lowpoly",
                "/terrain": "terrain", "/repair": "repair", "/rig": "rig",
                "/animate_clip": "animate_clip"}.get(route)
        if kind is None:
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            jid = _new_job()
            threading.Thread(target=_run_job, args=(jid, kind, body), daemon=True).start()
            self._json(202, {"job_id": jid})             # accepted — poll GET /job/<id>
        except Exception as e:  # noqa: BLE001
            self._json(400, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]})

    def do_GET(self):  # noqa: N802
        route = self.path.rstrip("/")
        if route.startswith("/job/"):
            jid = route[len("/job/"):]
            with _jobs_lock:
                job = _jobs.get(jid)
                snap = dict(job) if job else None
            if snap is None:
                return self._json(404, {"error": "unknown job"})
            base = snap["started"] or snap["created"]
            resp = {"status": snap["status"], "stage": snap["stage"],
                    "elapsed": round(time.time() - base)}
            # push the FLUX concept image ONCE, the moment it's ready, so the UI previews it mid-generation
            # (not re-sent every poll — ~1.4 MB; the final `done` result carries it again anyway).
            if snap["status"] in ("queued", "running"):
                if snap.get("concept_png_b64") and not snap.get("concept_sent"):
                    resp["concept_png_b64"] = snap["concept_png_b64"]
                    _set(jid, concept_sent=True)
                if snap.get("mv_views_b64") and not snap.get("mv_views_sent"):   # the multi-view collage, once
                    resp["mv_views_b64"] = snap["mv_views_b64"]
                    _set(jid, mv_views_sent=True)
            if snap["status"] == "done":
                resp.update(snap["result"])
            elif snap["status"] == "error":
                resp["error"] = snap["error"]; resp["trace"] = snap.get("trace", "")
            return self._json(200, resp)
        if route in ("/health", "/"):
            return self._json(200, {"ok": True, "jobs": len(_jobs)})
        return self._json(404, {"error": "not found"})

    def log_message(self, *_):  # quiet
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    host = os.environ.get("CAD_BIND", "127.0.0.1")   # set CAD_BIND=0.0.0.0 to reach it over the network
    print("warming TRELLIS.2 pipeline (one-time ~40s load)...", flush=True)
    _pipeline()
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Track B API on http://{host}:{port}  (POST /text2mesh|/image2mesh -> job_id; GET /job/<id>)", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
