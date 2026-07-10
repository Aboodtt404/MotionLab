"""Mesh verifier — fable_run/out/00_manual.md §6.1 (mesh validation) + the min-wall raycast (§2.3).

Emits the SAME Row/Report envelope as the B-rep verifier, so mesh artifacts flow through the identical
corpus/schema path. Geometry always comes from our OCCT/CadQuery builder (tessellated); trimesh is the
measurement oracle only — its boolean backend is absent, so we never build geometry in it.

Thresholds are Fable's §6.1 table verbatim. Self-intersection (§6.1) needs pymeshlab and is deferred
(a row we cannot honestly measure yet is OMITTED, not passed — Fable's "no unverified sample" rule).
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

import numpy as np

from .verifier import Report, Row

try:
    import trimesh
    _HAVE_TRIMESH = True
except Exception:  # noqa: BLE001 — the module must import even where trimesh is absent
    _HAVE_TRIMESH = False


def tri_from_solid(solid, tol: float = 0.1):
    """Tessellate an OCCT solid / CadQuery Workplane into a trimesh.Trimesh (render.py `_mesh` format)."""
    shape = solid.val() if hasattr(solid, "val") else solid
    verts, tris = shape.tessellate(tol)
    v = np.array([(p.x, p.y, p.z) for p in verts], dtype=float)
    f = np.array(tris, dtype=int)
    return trimesh.Trimesh(vertices=v, faces=f, process=True)


def _as_mesh(mesh_or_solid, tol: float = 0.1):
    if _HAVE_TRIMESH and isinstance(mesh_or_solid, trimesh.Trimesh):
        return mesh_or_solid
    return tri_from_solid(mesh_or_solid, tol)


def min_wall(mesh, samples: int = 6000) -> Optional[float]:
    """Minimum wall thickness by inward surface raycast (Fable §2.3). Samples the surface, casts each
    ray along −face_normal, and returns the nearest opposite-wall distance. None if no ray hits."""
    m = _as_mesh(mesh)
    pts, fidx = trimesh.sample.sample_surface(m, samples)
    nrm = m.face_normals[fidx]
    origins = pts - nrm * 1e-3                         # nudge inside so the origin face isn't the hit
    locs, ray_idx, _tri = m.ray.intersects_location(origins, -nrm, multiple_hits=False)
    if len(ray_idx) == 0:
        return None
    d = np.linalg.norm(locs - origins[ray_idx], axis=1)
    d = d[d > 1e-3]                                    # drop degenerate self-hits
    return float(d.min()) if len(d) else None


def _non_manifold_edges(m) -> int:
    deg = Counter(map(tuple, np.sort(m.edges, axis=1)))
    return sum(1 for c in deg.values() if c != 2)


def _duplicate_vertices(m, tol_frac: float = 1e-4) -> int:
    diag = float(np.linalg.norm(m.bounds[1] - m.bounds[0]))
    tol = max(diag * tol_frac, 1e-9)
    keys = np.round(m.vertices / tol).astype(np.int64)
    uniq = len({tuple(k) for k in keys})
    return int(len(m.vertices) - uniq)


def _components(m) -> int:
    try:
        return int(m.body_count)
    except Exception:  # noqa: BLE001
        import trimesh.graph as g
        return len(g.connected_components(m.edges, min_len=1, nodes=np.arange(len(m.vertices))))


def mesh_report(mesh_or_solid, *, expected_components: int = 1, watertight_required: bool = True,
                min_wall_mm: Optional[float] = None, max_triangles: Optional[int] = None,
                expected_euler: Optional[int] = None, tol: float = 0.1) -> Report:
    """§6.1 mesh validation → Report. `valid` = watertight (or, if not required, winding-consistent);
    `solids` = connected-component count; rows carry the individual §6.1 thresholds."""
    if not _HAVE_TRIMESH:
        return Report(valid=False, solids=0, volume=0.0,
                      rows=[Row("mesh · trimesh available", True, False, False, "validity")])
    m = _as_mesh(mesh_or_solid, tol)
    rows: List[Row] = []

    watertight = bool(m.is_watertight)
    winding = bool(m.is_winding_consistent)
    vol = float(m.volume)
    comps = _components(m)
    bbox_area = float(np.prod(m.bounds[1] - m.bounds[0]))
    degenerate = int((m.area_faces < 1e-10 * max(bbox_area, 1e-12)).sum())
    dup = _duplicate_vertices(m)
    nonman = _non_manifold_edges(m)

    rows.append(Row("mesh · watertight", True, watertight,
                    watertight or not watertight_required, "ok" if (watertight or not watertight_required) else "validity"))
    rows.append(Row("mesh · non_manifold_edges", 0, nonman, nonman == 0, "ok" if nonman == 0 else "validity"))
    rows.append(Row("mesh · winding_consistent (normals)", True, winding, winding, "ok" if winding else "validity"))
    rows.append(Row("mesh · signed_volume > 0", True, vol > 0, vol > 0, "ok" if vol > 0 else "validity"))
    rows.append(Row("mesh · degenerate_faces", 0, degenerate, degenerate == 0, "ok" if degenerate == 0 else "validity"))
    rows.append(Row("mesh · duplicate_vertices", 0, dup, dup == 0, "ok" if dup == 0 else "validity"))
    rows.append(Row("mesh · isolated_components", expected_components, comps,
                    comps == expected_components, "ok" if comps == expected_components else "component"))
    if expected_euler is not None:
        rows.append(Row("mesh · euler_number", expected_euler, int(m.euler_number),
                        int(m.euler_number) == expected_euler,
                        "ok" if int(m.euler_number) == expected_euler else "structure"))
    if max_triangles is not None:
        n = int(len(m.faces))
        rows.append(Row("mesh · triangles ≤ budget", max_triangles, n, n <= max_triangles,
                        "ok" if n <= max_triangles else "dfm"))
    if min_wall_mm is not None:
        mw = min_wall(m)
        ok = mw is not None and mw >= min_wall_mm - 1e-3
        rows.append(Row("mesh · min_wall", f"≥{min_wall_mm}", round(mw, 3) if mw is not None else None,
                        ok, "ok" if ok else "dfm"))

    valid = watertight if watertight_required else winding
    return Report(valid=valid, solids=comps, volume=abs(vol), rows=rows)
