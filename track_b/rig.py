"""Auto-rigging via SkinTokens (VAST, MIT) — mesh GLB → game-ready rigged GLB, verifier-gated.

Chosen over Puppeteer/UniRig/RigAnything by the 2026-07-20 deep-research + hands-on probes
(docs/research/rig-animate-research.md): Blackwell-native stack (torch 2.7/cu128, prebuilt
flash-attn), native GLB output, ≤4 skin influences by construction, quadruped-verified on our own
TRELLIS meshes (49s @ 760k verts). Runs as a SUBPROCESS in its own venv — SkinTokens needs py3.11
(bpy wheels) and its own torch; never import it into trellis_venv.

The rig gate is our signature move applied to rigging: nobody in this field verifies rigs.
Rows are game-engine constraints measured with bpy (also subprocess — bpy lives in the
SkinTokens venv, not ours).
"""
from __future__ import annotations

import json
import os
import subprocess

SKINTOKENS_DIR = os.environ.get("SKINTOKENS_DIR", "/workspace/.hf_home/SkinTokens")
_PY = os.path.join(SKINTOKENS_DIR, ".venv", "bin", "python")

# bone budget: glTF has no hard cap but real-time targets do — 256 is the common engine palette
# limit (matrix palette per draw call); we flag above 128 as "heavy" and fail above 256.
BONE_BUDGET_FAIL = 256
BONE_BUDGET_WARN = 128

_INSPECT_SRC = r"""
import json, sys
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=sys.argv[-1])
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
out = {"armatures": len(arms), "meshes": len(meshes), "bones": 0, "roots": 0,
       "max_influences": 0, "verts_over4": 0, "verts": 0, "skinned_meshes": 0}
if arms:
    bones = arms[0].data.bones
    out["bones"] = len(bones)
    out["roots"] = len([b for b in bones if not b.parent])
for m in meshes:
    if not m.vertex_groups:
        continue
    out["skinned_meshes"] += 1
    for v in m.data.vertices:
        n = len([g for g in v.groups if g.weight > 1e-4])
        out["max_influences"] = max(out["max_influences"], n)
        if n > 4:
            out["verts_over4"] += 1
    out["verts"] += len(m.data.vertices)
print("RIG_INSPECT_JSON:" + json.dumps(out))
"""


def rig_glb(in_glb: str, out_glb: str, timeout: int = 900) -> None:
    """mesh GLB → rigged GLB (skeleton + skin weights, texture/scale preserved). ~50s + model
    load on first call; needs ~14 GB VRAM — callers must hold the GPU lock."""
    r = subprocess.run(
        [_PY, "demo.py", "--input", os.path.abspath(in_glb),
         "--output", os.path.abspath(out_glb), "--use_transfer"],
        cwd=SKINTOKENS_DIR,                      # checkpoints resolve relative to the repo dir
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "HF_HUB_OFFLINE": "1"},   # weights are local; HF is flaky on this box
    )
    if not os.path.exists(out_glb):
        raise RuntimeError("rig failed: " + (r.stderr[-400:] or r.stdout[-400:]))


def inspect_rig(glb_path: str, timeout: int = 300) -> dict:
    """Deterministic rig gate — verifier rows over game-engine constraints."""
    r = subprocess.run([_PY, "-c", _INSPECT_SRC, os.path.abspath(glb_path)],
                       cwd=SKINTOKENS_DIR, capture_output=True, text=True, timeout=timeout)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RIG_INSPECT_JSON:")), None)
    if not line:
        raise RuntimeError("rig inspect failed: " + (r.stderr[-300:] or r.stdout[-300:]))
    m = json.loads(line.split(":", 1)[1])
    rows = [
        {"name": "rig · armature present", "expected": 1, "measured": m["armatures"],
         "within_tol": m["armatures"] == 1},
        {"name": "rig · single root bone", "expected": 1, "measured": m["roots"],
         "within_tol": m["roots"] == 1},
        {"name": f"rig · bone budget (≤{BONE_BUDGET_FAIL})", "expected": f"≤ {BONE_BUDGET_FAIL}",
         "measured": m["bones"], "within_tol": 0 < m["bones"] <= BONE_BUDGET_FAIL},
        {"name": "rig · skin influences ≤ 4/vertex", "expected": "0 over",
         "measured": m["verts_over4"], "within_tol": m["verts_over4"] == 0},
        {"name": "rig · mesh skinned", "expected": "≥ 1", "measured": m["skinned_meshes"],
         "within_tol": m["skinned_meshes"] >= 1},
    ]
    for r_ in rows:
        r_["category"] = "ok" if r_["within_tol"] else "rig"
    passed = all(r_["within_tol"] for r_ in rows)
    note = "heavy rig (>128 bones)" if m["bones"] > BONE_BUDGET_WARN else ""
    return {"passed": passed, "rows": rows, "bones": m["bones"], "verts": m["verts"], "note": note}
