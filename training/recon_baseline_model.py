"""HONEST baseline: can the local model reconstruct REAL Fusion parts (not my toy prompts) from
their dataset-rendered thumbnail into a feature-program? Non-circular — I author neither the input
(dataset .png) nor the ground truth (shipped .step).

Measurement caveats handled:
- Conditioning = the part's THUMBNAIL image (image→CAD), so I don't author a leaky text prompt.
- Pose/scale ambiguity: an image gives no absolute orientation/scale, so raw IoU-vs-STEP would be
  falsely ~0. We score a POSE/SCALE-NORMALIZED voxel IoU (center + uniform-scale to unit bbox +
  best-of-24 axis-aligned rotations) — the CADBench/Procrustes-style fair metric.
This measures IMAGE→CAD reconstruction of real MECHANICAL parts — a hard, non-circular proxy, NOT
text→CAD generation and NOT the assembly/organic ceiling. Report it as exactly that.

Run:  cad_pipeline/.venv/bin/python -m training.recon_baseline_model [n]
"""
from __future__ import annotations

import base64
import glob
import itertools
import json
import re
import sys
import urllib.request

import cadquery as cq
import numpy as np
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN

from cad_pipeline.verifier import measure

ROOT = "/workspace/.hf_home/datasets/fusion360/r1.0.1/extracted/r1.0.1/reconstruction"
ENDPOINT = "http://localhost:8002/v1/chat/completions"
MODEL = "qwen3.6-27b"
RES = 24

SYSTEM = ("You are a CAD reverse-engineer. Given an image of ONE mechanical part, write CadQuery "
          "(Python) that reconstructs it and assigns the solid to `result`. Model it as sketch→"
          "extrude→boolean steps (`.box`/`.circle().extrude()`, `.union`/`.cut`/`.intersect`). "
          "Millimetres; match the shape you see. Output ONLY one python code block.")


def _rotations_24():
    """The 24 proper (det=+1) axis-aligned rotation matrices — the cube's rotation group."""
    mats = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = np.zeros((3, 3))
            for i, p in enumerate(perm):
                m[i, p] = signs[i]
            if abs(np.linalg.det(m) - 1.0) < 1e-6:
                mats.append(m)
    return mats


ROT24 = _rotations_24()


def _voxel_centers(solid) -> np.ndarray:
    """Occupied voxel centers of `solid`, normalized (bbox-centered, uniform-scaled to unit max
    extent) → coords in ~[-0.5,0.5]. Returns (K,3) float array."""
    bb = solid.BoundingBox()
    cx, cy, cz = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2
    scale = max(bb.xlen, bb.ylen, bb.zlen) or 1.0
    clf = BRepClass3d_SolidClassifier(solid.wrapped)
    lo, hi = -scale * 0.6, scale * 0.6
    step = (hi - lo) / RES
    pts = []
    for i in range(RES):
        x = cx + lo + (i + 0.5) * step
        for j in range(RES):
            y = cy + lo + (j + 0.5) * step
            for k in range(RES):
                z = cz + lo + (k + 0.5) * step
                clf.Perform(gp_Pnt(x, y, z), 1e-6)
                if clf.State() == TopAbs_IN:
                    pts.append(((x - cx) / scale, (y - cy) / scale, (z - cz) / scale))
    return np.array(pts) if pts else np.zeros((0, 3))


def _quantize(pts: np.ndarray) -> set:
    return set(map(tuple, np.round(pts * RES).astype(int)))


def norm_iou(a, b) -> float:
    """Pose/scale-invariant voxel IoU: normalize both, try all 24 rotations of B, take best."""
    va = _voxel_centers(a)
    vb = _voxel_centers(b)
    if len(va) == 0 or len(vb) == 0:
        return 0.0
    sa = _quantize(va)
    best = 0.0
    for R in ROT24:
        sb = _quantize(vb @ R.T)
        inter = len(sa & sb)
        union = len(sa | sb)
        if union:
            best = max(best, inter / union)
    return best


THINK = False  # set by --think: measure the reasoning-ON config (slower, bigger budget)


def _call_vision(png_path: str) -> str:
    b64 = base64.b64encode(open(png_path, "rb").read()).decode()
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": [
                         {"type": "text", "text": "Reconstruct this part as CadQuery (`result`)."},
                         {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}],
        "temperature": 0.2,
    }
    if THINK:  # reasoning-ON: needs a big budget (reasoning eats 1000s of tokens before the code)
        body["max_tokens"] = 5000
    else:      # reasoning-OFF: complete code in ~350 tokens
        body["max_tokens"] = 1500
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _extract(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def _exec_solid(code: str):
    ns = {"cq": cq, "__name__": "__sbx__"}
    exec(code, ns)  # noqa: S102
    res = ns.get("result")
    s = res.val() if isinstance(res, cq.Workplane) else res
    return s if (s is not None and s.Solids()) else None


def _n_extrudes(stem: str) -> int:
    d = json.load(open(f"{ROOT}/{stem}.json"))
    return sum(1 for s in d["sequence"] if s["type"] == "ExtrudeFeature")


def main() -> int:
    global THINK
    THINK = "--think" in sys.argv
    nargs = [a for a in sys.argv[1:] if a.isdigit()]
    n = int(nargs[0]) if nargs else 30
    files = sorted(glob.glob(f"{ROOT}/*.json"))
    sample = files[:: max(1, len(files) // n)][:n]
    scores, valids, byc = [], 0, {}
    for p in sample:
        stem = p.rsplit("/", 1)[-1][:-5]
        png, step = f"{ROOT}/{stem}.png", f"{ROOT}/{stem}.step"
        try:
            solid = _exec_solid(_extract(_call_vision(png)))
            gt = cq.importers.importStep(step).val()
            iou = norm_iou(solid, gt) if solid is not None else 0.0
            valid = solid is not None and measure(solid).valid and measure(solid).solids == 1
        except Exception as e:  # noqa: BLE001
            iou, valid = 0.0, False
            print(f"  {stem}: ERR {type(e).__name__}: {str(e)[:50]}", flush=True)
        scores.append(iou); valids += bool(valid)
        b = min(_n_extrudes(stem), 4)
        byc.setdefault(b, []).append(iou)
        print(f"{stem}: normIoU={iou:.3f} valid={valid}", flush=True)
    m = len(scores)
    print(f"\nIMAGE→CAD RECON BASELINE (local {MODEL}, real parts, n={m}, "
          f"thinking={'ON' if THINK else 'OFF'}):")
    print(f"  mean normIoU {sum(scores)/m:.3f}   good(≥0.7) {sum(s>=0.7 for s in scores)}/{m}   "
          f"valid-solid {valids}/{m}")
    for k in sorted(byc):
        v = byc[k]
        lbl = f"{k}+" if k == 4 else str(k)
        print(f"  {lbl} extrude(s): mean {sum(v)/len(v):.3f} (n={len(v)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
