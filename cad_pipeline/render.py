"""Headless render of a CadQuery solid → PNG bytes, for the visual (VLM) critique loop.

Greeble has no ground-truth dimensions, so the only quality signal for "does it look filmic" is to
LOOK at it (Seek-CAD, arXiv 2505.17702: render → VLM critique → refine). This module is the render
half: tessellate the solid and shade it with matplotlib's Agg backend (no display, no GPU, no extra
deps — matplotlib + numpy ship with the cad venv). Fixed cameras ⇒ stable, comparable frames.
"""
from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")  # headless — must precede pyplot import
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

import cadquery as cq

# (elev, azim) camera angles — a 3/4 hero view + a near-side view so panel relief reads from two sides.
_VIEWS = [(28.0, -52.0), (14.0, -110.0)]
_LIGHT = np.array([0.4, -0.5, 0.75])
_LIGHT = _LIGHT / np.linalg.norm(_LIGHT)


def _mesh(solid, tol: float = 0.4):
    shape = solid.val() if isinstance(solid, cq.Workplane) else solid
    verts, tris = shape.tessellate(tol)
    v = np.array([(p.x, p.y, p.z) for p in verts], dtype=float)
    f = np.array(tris, dtype=int)
    return v, f


def _shade(tv):
    """Per-triangle Lambert shading → (ntri,3) grey RGB, so recesses/relief read as depth."""
    n = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    lum = 0.30 + 0.70 * np.clip(np.abs(n @ _LIGHT), 0.0, 1.0)   # ambient + diffuse (|·| so back-faces lit too)
    return np.repeat(lum[:, None], 3, axis=1) * np.array([0.74, 0.76, 0.80])


def render_views(solid, n: int = 2, size: int = 440, tol: float = 0.4) -> list[bytes]:
    """Render `n` fixed-camera shaded views of `solid` → list of PNG byte blobs (one per view)."""
    v, f = _mesh(solid, tol)
    tv = v[f]                                   # (ntri, 3, 3) triangle vertex coords
    fc = _shade(tv)
    ctr = v.mean(axis=0)
    span = float((v.max(axis=0) - v.min(axis=0)).max()) / 2.0 or 1.0
    out: list[bytes] = []
    for elev, azim in _VIEWS[:max(1, n)]:
        fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
        ax = fig.add_subplot(111, projection="3d")
        coll = Poly3DCollection(tv, facecolors=fc, edgecolors="none")
        ax.add_collection3d(coll)
        for setlim, c in ((ax.set_xlim, ctr[0]), (ax.set_ylim, ctr[1]), (ax.set_zlim, ctr[2])):
            setlim(c - span, c + span)           # equal aspect → no distortion of the detail
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor="#11141a")
        plt.close(fig)
        out.append(buf.getvalue())
    return out
