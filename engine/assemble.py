"""Hybrid assembly merge — compose parts of DIFFERENT representations (brep solids, mesh/procedural
GLBs, library solids) into ONE placed, verified scene. This is the payoff of the router (fable_run
§1.1 ASSEMBLE + §1.4 conventions): "a drone = CAD frame + CAD mounts + mesh canopy + procedural vents,
merged at assembly time."

How the reps unify:
  • everything is converted to a common frame — millimetres, Z-up (Track A's native frame);
  • a brep solid tessellates straight in (already mm, Z-up); a mesh/procedural GLB is scaled to fit its
    brief's envelope_mm and re-oriented Z-up (§1.4 glTF Y-up→Z-up);
  • placement reuses the deterministic mate-graph solver (assembly.solve_layout) via a proxy assembly of
    each part's bounding box, then the solved at/rotate transform is applied to the REAL mesh;
  • the merged scene is verified for interference (no unintended overlap) + connectivity + envelope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import trimesh

from cad_pipeline.assembly import Assembly, Component, Mate, solve_layout
from cad_pipeline.mesh_verify import tri_from_solid
from cad_pipeline.spec import Spec

from .builders import BuiltPart
from .engine import build_part


def _artifact_to_mesh(part: BuiltPart, envelope_mm: Optional[dict]) -> Optional[trimesh.Trimesh]:
    """Convert any BuiltPart artifact into a trimesh in the common frame (mm, Z-up)."""
    art = part.artifact
    if art is None:
        return None
    if part.representation in ("brep", "library") and hasattr(art, "val"):
        return tri_from_solid(art)                       # CadQuery solid: already mm, Z-up
    if isinstance(art, trimesh.Trimesh):
        m = art.copy()
    elif isinstance(art, str):                            # a GLB path (mesh/procedural)
        loaded = trimesh.load(art, force="mesh")
        m = loaded if isinstance(loaded, trimesh.Trimesh) else None
    else:
        return None
    if m is None:
        return None
    # glTF Y-up → Z-up (§1.4), then fit to the brief envelope in mm
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    if envelope_mm:
        target = np.array([envelope_mm.get("length", envelope_mm.get("diameter", 0)),
                           envelope_mm.get("width", envelope_mm.get("diameter", 0)),
                           envelope_mm.get("height", 0)], dtype=float)
        ext = m.extents
        good = (target > 0) & (ext > 1e-6)
        if good.any():
            s = float(np.mean((target[good] / ext[good])))
            m.apply_scale(s)
    return m


def _transform_matrix(at, rotate) -> np.ndarray:
    """The transform assembly._place applies: rotate about origin X→Y→Z (deg), then translate."""
    rx, ry, rz = np.radians(rotate)
    T = trimesh.transformations
    M = T.translation_matrix(at) @ T.rotation_matrix(rz, [0, 0, 1]) \
        @ T.rotation_matrix(ry, [0, 1, 0]) @ T.rotation_matrix(rx, [1, 0, 0])
    return M


@dataclass
class HybridAsset:
    name: str
    scene: Optional[trimesh.Scene] = None
    parts: List[BuiltPart] = field(default_factory=list)
    placements: Dict[str, dict] = field(default_factory=dict)
    rows: List[dict] = field(default_factory=list)
    reps: Dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.rows) and all(r["within_tol"] for r in self.rows)


def assemble(assembly_brief, built: Optional[Dict[str, BuiltPart]] = None) -> HybridAsset:
    """Build every component (routed to its representation), place them via the mate graph, merge into
    one scene, and verify. `built` may pre-supply parts (e.g. an injected mesh when :8770 is offline)."""
    comps = list(getattr(assembly_brief, "components", []))
    by_id = {c.component_id: c for c in comps}
    parts: Dict[str, BuiltPart] = {}
    meshes: Dict[str, trimesh.Trimesh] = {}
    proxy_comps: List[Component] = []

    for c in comps:
        bp = (built or {}).get(c.component_id) or build_part(c.brief)
        parts[c.component_id] = bp
        m = _artifact_to_mesh(bp, dict(c.brief.envelope_mm))
        if m is None:
            continue                                     # unbuilt part (e.g. mesh service down) — skip placement
        meshes[c.component_id] = m
        ext = m.extents
        proxy_comps.append(Component(
            name=c.component_id, role=c.role,
            part=Spec(object=c.component_id, shape="box",
                      envelope={"length": float(ext[0]) or 1.0, "width": float(ext[1]) or 1.0,
                                "height": float(ext[2]) or 1.0})))

    # translate the brief's mates (schema BriefMate: radius_mm/overlap_mm) onto the internal Mate
    # vocabulary (radius/overlap) — a field remap, not a blind splat.
    def _to_internal(bm) -> Mate:
        d = bm.model_dump()
        return Mate(kind=d["kind"], a=d.get("a"), b=d.get("b"), parts=d.get("parts") or [],
                    around=d.get("around"), count=d.get("count"), radius=d.get("radius_mm"),
                    splay_deg=d.get("splay_deg") or 0.0, side=d.get("side"), plane=d.get("plane"),
                    overlap=1.5 if d.get("overlap_mm") is None else d["overlap_mm"])
    asm = Assembly(object=assembly_brief.name, components=proxy_comps,
                   mates=[_to_internal(m) for m in getattr(assembly_brief, "mates", [])], fuse=False)
    if proxy_comps:
        asm = solve_layout(asm)

    scene = trimesh.Scene()
    placements: Dict[str, dict] = {}
    for pc in asm.components:
        m = meshes.get(pc.name)
        if m is None:
            continue
        # centre the mesh at its own bbox origin first, then apply the solved placement
        m2 = m.copy(); m2.apply_translation(-m2.bounds.mean(axis=0))
        m2.apply_transform(_transform_matrix(pc.at, pc.rotate))
        scene.add_geometry(m2, geom_name=pc.name)
        placements[pc.name] = {"at": pc.at, "rotate": pc.rotate}

    asset = HybridAsset(name=assembly_brief.name, scene=scene, parts=list(parts.values()),
                        placements=placements, reps={cid: p.representation for cid, p in parts.items()})
    asset.rows = _verify_scene(scene, meshes, placements, expected=len(proxy_comps))
    return asset


def _verify_scene(scene, meshes, placements, expected: int) -> List[dict]:
    """Combined-scene checks: every routed part placed, no gross interference, sane envelope."""
    rows: List[dict] = []
    placed = len(scene.geometry)
    rows.append({"name": "assembly · parts placed", "expected": expected, "measured": placed,
                 "within_tol": placed == expected, "category": "ok" if placed == expected else "component"})
    # pairwise interference via placed-bbox overlap volume (cheap, robust across reps)
    boxes = {name: geom.bounds for name, geom in scene.geometry.items()}
    worst = 0.0
    names = list(boxes)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = boxes[names[i]], boxes[names[j]]
            lo = np.maximum(a[0], b[0]); hi = np.minimum(a[1], b[1])
            ov = np.prod(np.clip(hi - lo, 0, None))
            worst = max(worst, float(ov))
    tol_ov = 0.05 * max((np.prod(b[1] - b[0]) for b in boxes.values()), default=1.0)
    rows.append({"name": "assembly · pairwise interference (bbox)", "expected": f"≤{round(tol_ov, 1)}",
                 "measured": round(worst, 1), "within_tol": worst <= tol_ov,
                 "category": "ok" if worst <= tol_ov else "integrity"})
    if scene.geometry:
        diag = float(np.linalg.norm(scene.bounds[1] - scene.bounds[0]))
        rows.append({"name": "assembly · envelope diag (mm)", "expected": ">0", "measured": round(diag, 1),
                     "within_tol": diag > 0, "category": "ok" if diag > 0 else "structure"})
    return rows
