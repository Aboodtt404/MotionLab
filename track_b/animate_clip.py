"""/animate_clip backend: rigged GLB + (motion prompt | reference MP4) -> GLB with an animation clip.

Pipeline (Puppeteer video-guided differentiable optimization, validated 2026-07-20 on
torch 2.13+cu130 / sm_120 — see docs/research/rig-animate-research.md):

  1. glb_to_obj_rig     — rigged GLB -> decimated proxy mesh.obj + rig.txt (anim_convert.py)
  2. guidance video     — user MP4 (normalized to square) OR text: render first frame in the
                          Puppeteer venv, then LTX /i2v (image+prompt -> motion mp4, sidecar :8771)
  3. frames + flow      — ffmpeg fps=10 + ptlflow dpflow (Puppeteer venv, GPU)
  4. optimization.py    — recovers per-frame joint quats + root motion (GPU, the long stage)
  5. motion_to_glb      — quats -> glTF animation channels on the ORIGINAL full-res GLB

Caller (server.py) holds the GPU lock for steps 3-4; step 2's LTX call must run WITHOUT it
(the sidecar takes the same cross-process lock itself).
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request

from .anim_convert import glb_to_obj_rig, motion_to_glb

PUP_ROOT = os.environ.get("PUPPETEER_DIR", "/workspace/.hf_home/Puppeteer")
PUP_ANIM = os.path.join(PUP_ROOT, "animation")
PUP_PY = os.path.join(PUP_ROOT, ".venv", "bin", "python")
LTX_SERVICE_URL = os.environ.get("LTX_SERVICE_URL", "http://127.0.0.1:8771")

GUIDE_SIZE = 960          # square guidance resolution == optimizer img_size (must match)
GUIDE_FPS = 10            # Puppeteer's expected frame rate
MAX_GUIDE_SECONDS = 8     # optimizer time/VRAM scale with frame count

_PUP_ENV = {"PYTHONPATH": f".{os.pathsep}./third_partys/ptlflow",
            "HF_HUB_OFFLINE": "0",   # ptlflow fetches its flow ckpt on first run
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}


def _pup(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(_PUP_ENV)
    r = subprocess.run([PUP_PY, *cmd], cwd=PUP_ANIM, env=env,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-600:]
        raise RuntimeError(f"{os.path.basename(cmd[0])} failed: {tail}")
    return r


def normalize_guidance(src_mp4: str, dst_mp4: str) -> None:
    """Center-crop to square, scale to GUIDE_SIZE, cap duration, strip audio."""
    vf = (f"crop='min(iw,ih)':'min(iw,ih)',scale={GUIDE_SIZE}:{GUIDE_SIZE}")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src_mp4,
                        "-t", str(MAX_GUIDE_SECONDS), "-vf", vf, "-an", dst_mp4],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(dst_mp4):
        raise RuntimeError("guidance video normalize failed: " + (r.stderr or "")[-300:])


def render_first_frame(inputs_dir: str, seq: str) -> str:
    """Render the (proxy) mesh from 4 viewpoints; return the front view PNG path."""
    _pup(["utils/render_first_frame.py", "--input_path", inputs_dir, "--seq_name", seq,
          "-s", str(GUIDE_SIZE)], timeout=900)
    front = os.path.join(inputs_dir, seq, "first_frames", "render_front.png")
    if not os.path.exists(front):
        cands = sorted(os.listdir(os.path.join(inputs_dir, seq, "first_frames")))
        if not cands:
            raise RuntimeError("first-frame render produced no images")
        front = os.path.join(inputs_dir, seq, "first_frames", cands[0])
    return front


def text_to_guidance(prompt: str, first_frame_png: str, out_mp4: str) -> None:
    """LTX sidecar image+prompt -> motion mp4. Caller must NOT hold the GPU lock."""
    payload = json.dumps({
        "prompt": prompt,
        "image_png_b64": base64.b64encode(open(first_frame_png, "rb").read()).decode(),
        "height": 768, "width": 768, "num_frames": 121, "frame_rate": 24.0,
    }).encode()
    req = urllib.request.Request(LTX_SERVICE_URL + "/i2v", data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as f:
            resp = json.loads(f.read())
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "LTX motion-video sidecar unreachable — start it with "
            f"~/LTX-2/.venv/bin/python track_b/ltx_service.py ({e})") from e
    if "mp4_b64" not in resp:
        raise RuntimeError("LTX i2v failed: " + str(resp.get("error", "no video"))[:300])
    open(out_mp4, "wb").write(base64.b64decode(resp["mp4_b64"]))


def prepare_inputs(glb_path: str, workdir: str, seq: str = "clip") -> dict:
    """Step 1: converter A into Puppeteer's expected inputs/{seq}/ layout."""
    seq_dir = os.path.join(workdir, "inputs", seq)
    os.makedirs(seq_dir, exist_ok=True)
    meta = glb_to_obj_rig(glb_path, seq_dir)
    return meta


def extract_and_flow(workdir: str, seq: str, guidance_mp4: str, on_stage=None) -> int:
    """Steps 3: frames at GUIDE_FPS + optical flow. Returns the frame count."""
    seq_dir = os.path.join(workdir, "inputs", seq)
    dst = os.path.join(seq_dir, "input.mp4")
    if os.path.abspath(guidance_mp4) != os.path.abspath(dst):
        normalize_guidance(guidance_mp4, dst)
    imgs = os.path.join(seq_dir, "imgs")
    os.makedirs(imgs, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", dst,
                        "-vf", f"fps={GUIDE_FPS}", os.path.join(imgs, "frame_%04d.png")],
                       capture_output=True, text=True, timeout=300)
    n = len([f for f in os.listdir(imgs) if f.endswith(".png")])
    if r.returncode != 0 or n < 4:
        raise RuntimeError(f"frame extraction failed ({n} frames): " + (r.stderr or "")[-200:])
    if on_stage:
        on_stage("optical flow")
    _pup(["utils/save_flow.py", "--input_path", os.path.join(workdir, "inputs"),
          "--seq_name", seq], timeout=1800)
    return n


def optimize(workdir: str, seq: str, iters: int = 150, coherence_weight: float = 5.0) -> str:
    """Step 4: the long GPU stage. Returns the motion dir (smoothed if present, else raw)."""
    _pup(["optimization.py", "--save_path", os.path.join(workdir, "results"),
          "--iter", str(iters), "--input_path", os.path.join(workdir, "inputs"),
          "--img_size", str(GUIDE_SIZE), "--seq_name", seq, "--save_name", seq,
          "--coherence_weight", str(coherence_weight)], timeout=3 * 3600)
    out = os.path.join(workdir, "results", seq, seq)
    for sub in ("smoothed", "raw"):
        d = os.path.join(out, sub)
        if os.path.exists(os.path.join(d, "local_quats.pt")):
            return d
    raise RuntimeError(f"optimizer produced no motion files under {out}")


def embed_clip(glb_path: str, motion_dir: str, seq_dir: str, out_glb: str) -> dict:
    """Step 5: write the animation into the ORIGINAL full-res GLB."""
    import shutil
    meta_src = os.path.join(seq_dir, "rig_meta.json")
    shutil.copy(meta_src, os.path.join(motion_dir, "rig_meta.json"))
    return motion_to_glb(glb_path, motion_dir, out_glb, fps=float(GUIDE_FPS))
