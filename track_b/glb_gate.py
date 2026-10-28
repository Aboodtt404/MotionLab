"""GLB quality gate — the mesh/web mistake catalog (05_mistakes M1–M11, W1–W5) as
machine-checkable rows, trimesh-only (no GPU, no Blender).

The Track A verifier's philosophy applied to Track B: every generated GLB gets a
deterministic report of {name, expected, measured, within_tol, category} rows plus a
pass/fail, with the catalog's REPAIR prescription attached to each failing row (so a
UI or an agent knows what to do, not just what's wrong).

Severity: rows are `error` (fail the gate) or `warn` (reported, doesn't fail) — a
render-only asset legitimately ships non-watertight marching-cubes topology, a print
job doesn't. `profile="render"` (default) vs `profile="print"` moves that line.

Run:  track_b/.venv/bin/python -m track_b.glb_gate <file.glb> [render|print]
"""
from __future__ import annotations

import os
import sys

_REPAIR = {
    "M1": "delete duplicate faces, merge-by-distance 1e-4, or voxel-remesh",
    "M2": "fill_holes(); cap each boundary loop; last resort voxel rebuild",
    "M3": "flood-fill coherent orientation from a seed face; recompute outward normals",
    "M4": "unify winding per connected component (seed = largest-area face)",
    "M6": "collapse edges < 1e-3; delete degenerates; re-triangulate the ring",
    "M7": "weld by distance 1e-4; rebuild split normals from angle threshold",
    "M8": "quadric-edge-collapse to budget with volume preservation ±2% (/lowpoly)",
    "M10": "bake transform: origin = base-center (min-z = 0, centroid xy = 0)",
    "W2": "convert units at export (mm→m ×0.001); assert height in class range",
    "W5": "resize/atlas textures to power-of-two ≤ 4096; re-reference in material",
}


def validate_glb(path: str, profile: str = "render", face_budget: int = 1_200_000,
                 expect_height: tuple | None = None) -> dict:
    """Catalog rows over one GLB. `expect_height=(lo, hi)` enables the W2 scale row."""
    import numpy as np
    import trimesh

    rows: list = []

    def row(rid: str, name: str, expected, measured, ok: bool, severity: str) -> None:
        r = {"name": f"{rid} · {name}", "expected": expected, "measured": measured,
             "within_tol": bool(ok), "category": "ok" if ok else severity}
        if not ok and rid in _REPAIR:
            r["repair"] = _REPAIR[rid]
        rows.append(r)

    scene = trimesh.load(path)
    geoms = list(scene.geometry.values()) if getattr(scene, "geometry", None) else [scene]
    g = max(geoms, key=lambda m: len(m.faces))          # judge the main body
    nf, nv = len(g.faces), len(g.vertices)

    # M1 non-manifold edges: any edge shared by >2 faces
    edges = g.edges_sorted
    _, counts = np.unique(edges, axis=0, return_counts=True)
    nonmanifold = int((counts > 2).sum())
    row("M1", "non-manifold edges", 0, nonmanifold, nonmanifold == 0, "error")

    # M2 watertight / boundary edges (leaky mesh) — error only for print
    boundary = int((counts == 1).sum())
    row("M2", "watertight (boundary edges)", "watertight", f"{boundary} boundary edges",
        bool(g.is_watertight), "error" if profile == "print" else "warn")

    # M3 flipped normals: signed volume must be positive (only meaningful when watertight)
    if g.is_watertight:
        row("M3", "outward normals (signed volume)", "> 0", round(float(g.volume), 3),
            float(g.volume) > 0, "error")

    # M4 winding consistency across islands. On an OPEN mesh (raw marching-cubes topology,
    # remesh=False — our documented default) trimesh can't establish a coherent orientation to
    # judge against, so inconsistency is a visual-quality warn there; it is a hard error on
    # closed meshes (lit-inverted islands) and always for print.
    m4_sev = "error" if (g.is_watertight or profile == "print") else "warn"
    row("M4", "winding consistent", True, bool(g.is_winding_consistent),
        bool(g.is_winding_consistent), m4_sev)

    # M6 degenerate faces
    degenerate = int((g.area_faces < 1e-8).sum())
    row("M6", "degenerate faces", 0, degenerate, degenerate == 0, "warn")

    # M7 duplicate vertices (UV/shading seams legitimately split — catalog floor 0.7)
    uniq = len(np.unique(g.vertices.round(4), axis=0))
    ratio = uniq / max(1, nv)
    row("M7", "unique-position ratio", "≥ 0.7", round(ratio, 3), ratio >= 0.7, "warn")

    # M8 over-tessellation vs budget
    row("M8", "faces within budget", f"≤ {face_budget}", nf, nf <= face_budget, "warn")

    # M10 pivot: centroid xy near bbox center (asset orbits sanely in the studio)
    bb = scene.bounds if getattr(scene, "bounds", None) is not None else g.bounds
    diag = float(np.linalg.norm(bb[1] - bb[0]))
    center_xy = (bb[0][:2] + bb[1][:2]) / 2.0
    centroid = g.vertices.mean(axis=0)
    off = float(np.linalg.norm(centroid[:2] - center_xy))
    row("M10", "pivot near center (xy)", f"≤ 5% of diag ({round(0.05 * diag, 3)})",
        round(off, 3), off <= 0.05 * diag, "warn")

    # W2 absolute scale vs class prior (opt-in — needs a class expectation)
    if expect_height is not None:
        height = float(bb[1][1] - bb[0][1])             # GLB is Y-up
        lo, hi = expect_height
        row("W2", "height in class range (m, Y-up)", f"{lo}–{hi}", round(height, 3),
            lo <= height <= hi, "error")

    # W5 texture sanity: power-of-two, ≤ 4096
    tex_bad = []
    for m in geoms:
        mat = getattr(getattr(m, "visual", None), "material", None)
        for attr in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture", "emissiveTexture"):
            img = getattr(mat, attr, None) if mat is not None else None
            if img is None:
                continue
            w, h = img.size
            if w > 4096 or h > 4096 or (w & (w - 1)) or (h & (h - 1)):
                tex_bad.append(f"{attr} {w}×{h}")
    row("W5", "textures POT ≤ 4096", "all", tex_bad or "all", not tex_bad, "warn")

    passed = not any((not r["within_tol"]) and r["category"] == "error" for r in rows)
    return {"passed": passed, "profile": profile, "faces": nf, "verts": nv,
            "size_mb": round(os.path.getsize(path) / 1e6, 1), "rows": rows,
            "warnings": sum(1 for r in rows if not r["within_tol"] and r["category"] == "warn")}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m track_b.glb_gate <file.glb> [render|print]")
        return 2
    rep = validate_glb(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "render")
    for r in rep["rows"]:
        mark = "ok " if r["within_tol"] else ("WARN" if r["category"] == "warn" else "FAIL")
        print(f"  [{mark}] {r['name']}: measured {r['measured']} (expected {r['expected']})")
        if "repair" in r:
            print(f"         repair: {r['repair']}")
    print(f"GATE {'PASSED' if rep['passed'] else 'FAILED'} — {rep['faces']} faces, "
          f"{rep['warnings']} warnings, {rep['size_mb']} MB")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
