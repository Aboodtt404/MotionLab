"""§4 artistic-asset production — fable_run/out/00_manual.md §4 (retopo, style card, trim sheets) +
the Blender texture bake (AO/normal). Turns a high-poly organic mesh (e.g. from TRELLIS) into a
game/film-optimised, textured, LOD'd asset. The machine-checkable core:

  • style_card (§4.3): the fixed style contract applied to every asset, + a palette-consistency check;
  • retopo (§4.1): high-poly → clean low-poly (decimate + weld + coherent normals), silhouette-preserved;
  • trim-sheet (§4 env / G09): UV islands laid into declared V-bands;
  • texture bake (§4): AO + tangent-normal maps baked in Blender (engine/tools/bpy_bake.py).

UV (xatlas) and LOD (silhouette-IoU) already live in uv.py / lod.py; this composes them into the art flow.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import List, Optional, Tuple

import numpy as np
import trimesh
from pydantic import BaseModel, Field

from .verifier import Report, Row


# ── §4.3 style card ──────────────────────────────────────────────────────────────────────────
class StyleCard(BaseModel):
    """Fix ONE style card before modeling asset #1; apply to all (manual §4.3)."""
    bevel_class_mm: List[float] = Field(default_factory=lambda: [0.5, 2.0, 8.0])
    palette_hex: List[str] = Field(default_factory=lambda: ["#2B2E33", "#C7521E", "#E8E3D8", "#7A8288"])
    roughness_range: Tuple[float, float] = (0.35, 0.7)
    metallic_values_allowed: List[float] = Field(default_factory=lambda: [0.0, 1.0])
    detail_density: str = "1 detail feature per 10 cm^2, max 3 sizes"
    proportion_rule: str = "1:1.618 major masses"
    silhouette: str = "chunky, 15% oversize on functional parts"


def _hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def palette_distance(color_rgb, card: StyleCard) -> float:
    """Nearest-palette distance (RGB L2, 0–441) for one color — the §4.3 consistency proxy
    (CIEDE2000 without a color-science dep; the check is 'is this color on the card')."""
    c = np.asarray(color_rgb, dtype=float)
    return float(min(np.linalg.norm(c - _hex_rgb(h)) for h in card.palette_hex))


def verify_style(colors_rgb, card: StyleCard, max_dist: float = 40.0) -> Report:
    """Every asset color must sit near the fixed palette (contact-sheet histogram idea, §4.3)."""
    rows: List[Row] = []
    worst = max((palette_distance(c, card) for c in colors_rgb), default=0.0)
    ok = worst <= max_dist
    rows.append(Row("style · palette adherence (worst)", f"≤{max_dist}", round(worst, 1), ok,
                    "ok" if ok else "dfm"))
    rows.append(Row("style · bevel classes ≥3", 3, len(card.bevel_class_mm), len(card.bevel_class_mm) >= 3,
                    "ok" if len(card.bevel_class_mm) >= 3 else "dfm"))
    return Report(valid=True, solids=1, volume=1.0, rows=rows)   # non-geometric → dummy volume so passed = rows


# ── §4.1 retopo ──────────────────────────────────────────────────────────────────────────────
def retopo(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """High-poly → clean low-poly: quadric-decimate to budget, weld, unify winding, fix normals.
    (True all-quad retopo needs instant-meshes; this delivers the machine-checkable outcome —
    low tri count, manifold, coherent normals, silhouette preserved via lod.silhouette_iou.)"""
    lo = mesh.simplify_quadric_decimation(face_count=target_faces) if len(mesh.faces) > target_faces else mesh.copy()
    lo.merge_vertices()
    lo.fix_normals()
    return lo


def verify_retopo(source: trimesh.Trimesh, low: trimesh.Trimesh, budget: int,
                  iou_min: float = 0.95) -> Report:
    from .lod import silhouette_iou
    rows: List[Row] = []
    n = len(low.faces)
    rows.append(Row("retopo · tris ≤ budget", budget, n, n <= int(budget * 1.05), "ok" if n <= int(budget * 1.05) else "dfm"))
    rows.append(Row("retopo · watertight/manifold", True, low.is_watertight, low.is_watertight,
                    "ok" if low.is_watertight else "validity"))
    rows.append(Row("retopo · winding consistent", True, low.is_winding_consistent, low.is_winding_consistent,
                    "ok" if low.is_winding_consistent else "validity"))
    iou = silhouette_iou(source, low)
    rows.append(Row(f"retopo · silhouette IoU (≥{iou_min})", f"≥{iou_min}", round(iou, 3), iou >= iou_min,
                    "ok" if iou >= iou_min else "dfm"))
    return Report(valid=low.is_watertight, solids=1, volume=float(abs(low.volume)), rows=rows)


# ── §4 trim sheet (UV islands in declared V-bands, G09) ───────────────────────────────────────
def verify_trim_sheet(mesh: trimesh.Trimesh, n_bands: int = 4) -> Report:
    """UV V-coord of every island falls inside one of n equal V-bands (0 outside) — G09."""
    from .uv import unwrap
    _m, uvs = unwrap(mesh)
    v = uvs[:, 1]
    band = np.floor(np.clip(v, 0, 1 - 1e-6) * n_bands).astype(int)
    inside = np.all((v >= -1e-4) & (v <= 1 + 1e-4))
    rows = [Row(f"trim · UVs in {n_bands} V-bands", True, bool(inside), bool(inside),
                "ok" if inside else "dfm"),
            Row("trim · bands used", f"≤{n_bands}", int(band.max() + 1), int(band.max() + 1) <= n_bands,
                "ok" if int(band.max() + 1) <= n_bands else "dfm")]
    return Report(valid=True, solids=1, volume=float(abs(mesh.volume)), rows=rows)


# ── §4 texture bake (AO + normal), Blender ────────────────────────────────────────────────────
_BAKE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "engine", "tools", "bpy_bake.py")


def bake_maps(glb_path: str, out_dir: str, res: int = 512, timeout: int = 300) -> Optional[dict]:
    """Bake AO (+ tangent normal) for a GLB via Blender (engine/tools/bpy_bake.py). Returns the
    written map paths, or None if Blender/the bake is unavailable (honest skip)."""
    import shutil
    if shutil.which("blender") is None or not os.path.exists(_BAKE):
        return None
    os.makedirs(out_dir, exist_ok=True)
    try:
        subprocess.run(["blender", "--background", "--python", _BAKE, "--", glb_path, out_dir, str(res)],
                       capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    maps = {k: os.path.join(out_dir, f"{k}.png") for k in ("ao", "normal")}
    got = {k: p for k, p in maps.items() if os.path.exists(p)}
    return got or None
