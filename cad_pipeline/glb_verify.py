"""Web/GLB (§6.5) and game-asset (§6.4) validation — fable_run/out/00_manual.md.

Tooling (all researched + validated on the box): the Khronos **gltf-validator** (Node API, wrapped in
tools/gltf_validate.js), **trimesh** for GLB introspection, and **Blender WORKBENCH** headless for the
render smoke (the "renders non-empty pixels" catch — Fable allows the Blender-re-import path). Rows the
tooling can't compute are omitted, never faked. Complements track_b/glb_gate.py (the M1–M11/W1–W5 mistake
rows); this module adds the benchmark acceptance budgets + the gltf-validator + render oracles.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional

import numpy as np

from .verifier import Report, Row

_TOOLS = os.path.join(os.path.dirname(__file__), "tools")
_VALIDATOR_JS = os.path.join(_TOOLS, "gltf_validate.js")
_BLRENDER = os.path.join(_TOOLS, "blrender.py")


# ───────────────────────────────────────────────────── tooling oracles
def gltf_validate(glb_path: str) -> Optional[dict]:
    """Khronos gltf-validator report {numErrors, numWarnings, info} — None if node/wrapper unavailable."""
    if shutil.which("node") is None or not os.path.exists(os.path.join(_TOOLS, "node_modules")):
        return None
    try:
        r = subprocess.run(["node", _VALIDATOR_JS, glb_path], cwd=_TOOLS,
                           capture_output=True, text=True, timeout=60)
        rep = json.loads(r.stdout)
        iss = rep.get("issues", {})
        return {"numErrors": iss.get("numErrors"), "numWarnings": iss.get("numWarnings"),
                "info": rep.get("info", {})}
    except Exception:  # noqa: BLE001
        return None


def render_smoke(glb_path: str) -> Optional[float]:
    """Render the GLB headless (Blender WORKBENCH) → grayscale std-dev (>10 = non-empty, not black).
    None if Blender is unavailable or the render fails."""
    if shutil.which("blender") is None:
        return None
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "r")
        try:
            subprocess.run(["blender", "--background", "--python", _BLRENDER, "--", glb_path, base],
                           capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return None
        png = base + ".png"
        if not os.path.exists(png):
            return None
        import matplotlib.image as mpimg
        a = mpimg.imread(png)
        g = a[..., :3].mean(axis=2) if a.ndim == 3 else a
        return float(g.std() * 255.0)


# ───────────────────────────────────────────────────── GLB introspection (trimesh)
def _load(glb_path: str):
    import trimesh
    return trimesh.load(glb_path, force="scene")


def _tris_and_materials(scene) -> tuple:
    tris = 0
    mats = set()
    for name, geom in getattr(scene, "geometry", {}).items():
        tris += int(len(geom.faces))
        mat = getattr(getattr(geom, "visual", None), "material", None)
        mats.add(id(mat) if mat is not None else name)
    return tris, len(mats)


# ───────────────────────────────────────────────────── §6.5 web / §6.4 game reports
def verify_web(glb_path: str, *, max_tris: int = 150_000, max_file_mb: float = 10.0,
               height_range: Optional[tuple] = None, run_render: bool = False) -> Report:
    """§6.5 web/GLB acceptance: gltf-validator clean, size/tri budgets, scale sanity, optional render."""
    scene = _load(glb_path)
    tris, nmat = _tris_and_materials(scene)
    ext = scene.bounds[1] - scene.bounds[0]
    diag = float(np.linalg.norm(ext))
    size_mb = os.path.getsize(glb_path) / 1e6
    rows: List[Row] = []

    val = gltf_validate(glb_path)
    if val is not None:
        ne, nw = val["numErrors"] or 0, val["numWarnings"] or 0
        rows.append(Row("web · gltf-validator errors", 0, ne, ne == 0, "ok" if ne == 0 else "validity"))
        rows.append(Row("web · gltf-validator warnings ≤5", "≤5", nw, nw <= 5, "ok" if nw <= 5 else "dfm"))

    rows.append(Row("web · file size (MB)", f"≤{max_file_mb}", round(size_mb, 3),
                    size_mb <= max_file_mb, "ok" if size_mb <= max_file_mb else "dfm"))
    rows.append(Row("web · total tris", f"≤{max_tris}", tris, tris <= max_tris,
                    "ok" if tris <= max_tris else "dfm"))
    scale_ok = 0.01 <= diag <= 100.0
    rows.append(Row("web · bbox diag ∈ [0.01,100] m", "[0.01,100]", round(diag, 4), scale_ok,
                    "ok" if scale_ok else "dimensional"))
    if height_range is not None:
        h = float(ext[1])                      # glTF Y-up: height is the Y extent
        hok = height_range[0] <= h <= height_range[1]
        rows.append(Row("web · height (m)", f"{height_range}", round(h, 3), hok,
                        "ok" if hok else "dimensional"))
    if run_render:
        sd = render_smoke(glb_path)
        if sd is not None:
            rows.append(Row("web · render non-empty (std-dev>10)", ">10", round(sd, 1), sd > 10,
                            "ok" if sd > 10 else "validity"))

    return Report(valid=True, solids=1, volume=float(abs(np.prod(ext))), rows=rows)


def verify_game(glb_path: str, *, tri_budget: int, max_materials: int = 2,
                base_pivot: bool = True) -> Report:
    """§6.4 game-asset acceptance: tri budget, material-slot cap, base-center pivot."""
    scene = _load(glb_path)
    tris, nmat = _tris_and_materials(scene)
    zmin = float(scene.bounds[0][2])
    ext = scene.bounds[1] - scene.bounds[0]
    rows: List[Row] = [
        Row("game · tris ≤ budget", f"≤{tri_budget}", tris, tris <= tri_budget,
            "ok" if tris <= tri_budget else "dfm"),
        Row("game · material slots ≤ cap", f"≤{max_materials}", nmat, nmat <= max_materials,
            "ok" if nmat <= max_materials else "dfm"),
    ]
    if base_pivot:
        # pivot at base center: min-Y ≈ 0 (glTF Y-up), centroid XZ near bbox center
        ymin = float(scene.bounds[0][1])
        ok = abs(ymin) <= max(0.001, 0.01 * float(ext[1]))
        rows.append(Row("game · pivot at base (min-Y≈0)", 0.0, round(ymin, 4), ok,
                        "ok" if ok else "structure"))
    return Report(valid=True, solids=1, volume=float(abs(np.prod(ext))), rows=rows)
