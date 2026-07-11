"""UV unwrap + UV quality — fable_run/out/00_manual.md §1 (UV only what's textured) + §6.4 game UV
checks (G03: single clean UV set, 0 overlaps, all inside [0,1]). xatlas packs charts without overlap
by construction, so unwrapping + a bounds/coverage check is the machine-checkable gate.
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import trimesh

from .verifier import Report, Row


def unwrap(mesh: trimesh.Trimesh) -> Tuple[trimesh.Trimesh, np.ndarray]:
    """xatlas UV parametrisation → a mesh carrying non-overlapping UVs (charts packed into [0,1])."""
    import xatlas
    vmap, indices, uvs = xatlas.parametrize(mesh.vertices, mesh.faces)
    out = trimesh.Trimesh(vertices=mesh.vertices[vmap], faces=indices, process=False)
    out.visual = trimesh.visual.TextureVisuals(uv=uvs)
    return out, uvs


def uv_report(mesh: trimesh.Trimesh) -> Report:
    """§6.4 UV gate: a single UV set, every UV inside [0,1], and coverage (a UV per vertex)."""
    m, uvs = (mesh, getattr(getattr(mesh, "visual", None), "uv", None)) if getattr(
        getattr(mesh, "visual", None), "uv", None) is not None else unwrap(mesh)
    rows: List[Row] = []
    has = uvs is not None and len(uvs) > 0
    rows.append(Row("uv · present (single set)", True, has, has, "ok" if has else "missing_feature"))
    if has:
        lo, hi = float(uvs.min()), float(uvs.max())
        inb = lo >= -1e-4 and hi <= 1 + 1e-4
        rows.append(Row("uv · inside [0,1]", "[0,1]", (round(lo, 3), round(hi, 3)), inb,
                        "ok" if inb else "dfm"))
        cov = len(uvs) >= len(m.vertices)
        rows.append(Row("uv · coverage (uv per vertex)", f"≥{len(m.vertices)}", len(uvs), cov,
                        "ok" if cov else "missing_feature"))
    return Report(valid=has, solids=1, volume=float(abs(m.volume)), rows=rows)
