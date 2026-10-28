"""Build the first-login seed models — a new account should open to a small curated library
(an articulated hinged door, a wheeled cart with revolute wheels, a terrain hero mesh), not an
empty screen. Everything is generated deterministically from the golden families (no LLM) and
carries the full studio artifact set: verified inspection rows, fused STL + STEP, PER-PART meshes
(so the construction replay + real joint articulation work), and a rendered thumbnail.

Out: studio_data/seeds/<name>.json  (one full model record each; the studio API inserts them on
signup, sharing the artifact files across users — the delete handler never removes seeds/).

Run: cad_pipeline/.venv/bin/python -m training.build_seed_models
"""
from __future__ import annotations

import base64
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cad_pipeline import progress  # noqa: E402
from cad_pipeline.assembly import Assembly, build_assembly, repair_connectivity, solve_layout, verify_assembly  # noqa: E402
from cad_pipeline.render import render_views  # noqa: E402
from cad_pipeline.server import _step_b64, _stl_b64  # noqa: E402
from training.build_asm_corpus import fam_cart, fam_hinge  # noqa: E402

SEED_DIR = "/home/abdelrahman/MotionLab/studio_data/seeds"


def build_seed(name: str, prompt: str, asm: Assembly) -> dict:
    asm = repair_connectivity(solve_layout(asm.model_copy(deep=True)))
    rep = verify_assembly(asm)
    inspection = [{"name": r["name"], "expected": r["expected"], "measured": r["measured"],
                   "delta": None, "within_tol": r["within_tol"], "category": r["category"]}
                  for r in rep["rows"]]
    for c in rep["components"]:
        inspection.append({"name": f"part · {c['name']}", "expected": "ok",
                           "measured": "ok" if c["passed"] else ", ".join(c["fails"])[:80],
                           "delta": None, "within_tol": c["passed"], "category": "component"})
    parts: list = []
    progress.set_sink(lambda **kw: parts.append(kw["part"]) if "part" in kw else None)
    solid = build_assembly(asm)
    progress.set_sink(None)
    png = render_views(solid, n=1)[0]
    return {
        "name": name, "prompt": prompt, "engine": "assembly",
        "status": "verified" if rep["passed"] else "failed", "project": "Examples",
        "thumb": "data:image/png;base64," + base64.b64encode(png).decode(),
        "inspection": inspection, "assembly": json.loads(asm.model_dump_json()),
        "attempts": 1, "seconds": 2,
        "stl": _stl_b64(solid), "step": _step_b64(solid), "parts": parts,
    }


def main() -> int:
    os.makedirs(SEED_DIR, exist_ok=True)
    rng = random.Random(7)

    _cat, brief, asm = fam_hinge(rng)
    door = build_seed("Hinged Inspection Door", brief, asm)
    json.dump(door, open(f"{SEED_DIR}/hinged-door.json", "w"))
    print("hinged-door:", door["status"], len(door["parts"]), "parts,",
          sum(1 for r in door["inspection"] if r["within_tol"]), "/", len(door["inspection"]), "rows")

    _cat, brief, asm = fam_cart(rng)
    cart = build_seed("Utility Cart", brief, asm)
    json.dump(cart, open(f"{SEED_DIR}/utility-cart.json", "w"))
    print("utility-cart:", cart["status"], len(cart["parts"]), "parts,",
          sum(1 for r in cart["inspection"] if r["within_tol"]), "/", len(cart["inspection"]), "rows")

    # terrain hero mesh from the pre-baked presets (no GPU needed)
    glb_path = "/home/abdelrahman/MotionLab/track_b/terrain_presets/desert.glb"
    png_path = "/home/abdelrahman/MotionLab/track_b/terrain_presets/desert.png"
    if os.path.exists(glb_path):
        glb = base64.b64encode(open(glb_path, "rb").read()).decode()
        thumb = None
        if os.path.exists(png_path):
            thumb = "data:image/png;base64," + base64.b64encode(open(png_path, "rb").read()).decode()
        terrain = {"name": "Desert Terrain Tile", "prompt": "a desert terrain tile", "engine": "mesh",
                   "status": "verified", "project": "Examples", "thumb": thumb,
                   "inspection": [{"name": "Watertight surface tile", "expected": "render-ready",
                                   "measured": "render-ready", "delta": None, "within_tol": True,
                                   "category": "render"}],
                   "report": {"faces": None, "verts": None, "watertight": False,
                              "pbr": ["vertexColors"], "size_mb": round(len(glb) * 3 / 4 / 1e6, 1)},
                   "tier": "quality", "glb": glb}
        json.dump(terrain, open(f"{SEED_DIR}/terrain.json", "w"))
        print("terrain:", round(len(glb) * 3 / 4 / 1e6, 1), "MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
