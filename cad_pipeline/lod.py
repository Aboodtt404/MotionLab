"""LOD generation + acceptance — fable_run/out/00_manual.md §4.2. Generate a level-of-detail chain by
quadric decimation to a face budget, and ACCEPT each LOD only if its silhouette matches LOD0: render
both at 8 canonical views and require silhouette IoU ≥ 0.97 (LOD1) / 0.92 (LOD2). Emits the standard
Row/Report envelope. (Retopo/UV/bake are the deeper §4 art workflow; this is the machine-checkable core
that gates the game/mesh LOD tasks G07/M13/W06.)
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import trimesh
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .verifier import Report, Row

# 8 canonical views (elev, azim degrees) — the §4.2 silhouette-IoU sample set
_VIEWS = [(20, a) for a in range(0, 360, 90)] + [(-20, a) for a in range(45, 360, 90)]


def generate_lods(mesh: trimesh.Trimesh, budgets: List[int]) -> List[trimesh.Trimesh]:
    """Decimate to each face budget (descending), quadric-collapse from the source each time."""
    out = []
    for b in budgets:
        out.append(mesh if len(mesh.faces) <= b else mesh.simplify_quadric_decimation(face_count=b))
    return out


def _silhouette(mesh: trimesh.Trimesh, elev: float, azim: float, res: int = 128) -> np.ndarray:
    """Orthographic silhouette mask (True where the mesh projects) at one view — rasterised via Agg."""
    e, a = np.radians(elev), np.radians(azim)
    # view basis: rotate the mesh into the camera frame, drop depth
    Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    v = mesh.vertices @ (Rx @ Rz).T
    tv = v[mesh.faces][:, :, :2]                      # (ntri, 3, 2) projected triangle verts
    fig = Figure(figsize=(1, 1), dpi=res); canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    from matplotlib.collections import PolyCollection
    ax.add_collection(PolyCollection(tv, facecolors="k", edgecolors="k", antialiased=False))
    lo, hi = v[:, :2].min(0), v[:, :2].max(0); c = (lo + hi) / 2; r = (hi - lo).max() / 2 * 1.1 or 1
    ax.set_xlim(c[0] - r, c[0] + r); ax.set_ylim(c[1] - r, c[1] + r)
    canvas.draw()
    buf = np.asarray(canvas.buffer_rgba())[:, :, 0]
    return buf < 128                                  # black (mesh) → True


def silhouette_iou(a: trimesh.Trimesh, b: trimesh.Trimesh, res: int = 128) -> float:
    """Mean silhouette IoU over the 8 canonical views (§4.2 LOD acceptance metric)."""
    ious = []
    for elev, azim in _VIEWS:
        ma, mb = _silhouette(a, elev, azim, res), _silhouette(b, elev, azim, res)
        inter = np.logical_and(ma, mb).sum(); union = np.logical_or(ma, mb).sum()
        ious.append(inter / union if union else 1.0)
    return float(np.mean(ious))


def verify_lod_chain(source: trimesh.Trimesh, lods: List[trimesh.Trimesh], budgets: List[int],
                     iou_min: Optional[List[float]] = None) -> Report:
    """§4.2: each LOD hits its tri budget (±5%) and keeps silhouette IoU ≥ threshold vs the source."""
    iou_min = iou_min or ([0.97, 0.92, 0.85] + [0.80] * len(lods))[:len(lods)]
    rows: List[Row] = []
    for i, (lo, b, thr) in enumerate(zip(lods, budgets, iou_min)):
        n = len(lo.faces)
        budget_ok = n <= int(b * 1.05)
        rows.append(Row(f"lod{i} · tris ≤ budget", b, n, budget_ok, "ok" if budget_ok else "dfm"))
        iou = silhouette_iou(source, lo)
        ok = iou >= thr
        rows.append(Row(f"lod{i} · silhouette IoU (≥{thr})", f"≥{thr}", round(iou, 3), ok,
                        "ok" if ok else "dfm"))
    return Report(valid=True, solids=1, volume=float(abs(source.volume)), rows=rows)
