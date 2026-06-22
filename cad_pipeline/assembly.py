"""Multi-part assemblies — the step from single parts toward whole mechanisms (a drone
airframe, a bracket-set, …). Deliberately scoped to FUSED hard-surface assemblies for now:
components are parametric Parts (reusing Spec), each placed by rotate+translate, then fused
into one solid (a printed/CNC frame). Kinematic/mating assemblies (moving parts, fits) are a
later, separate concern (design doc §12.3).

Verifier-first, as always: each component is verified in its own LOCAL frame against its
sub-spec (reusing the part verifier), and the ASSEMBLY adds two checks the parts can't see:
  • connectivity — the fused result must be a SINGLE solid (a floating/short arm that doesn't
    reach the hub leaves >1 solid → caught).
  • validity — the fused BRep is watertight/valid.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt
from pydantic import BaseModel, Field

from .builder import build
from .spec import Spec
from .verifier import measure, verify


class Component(BaseModel):
    name: str = "part"
    part: Spec
    at: Tuple[float, float, float] = (0.0, 0.0, 0.0)        # translation (mm)
    rotate: Tuple[float, float, float] = (0.0, 0.0, 0.0)    # degrees about X, Y, Z (applied in order)


class Assembly(BaseModel):
    object: str = "assembly"
    components: List[Component] = Field(default_factory=list)
    fuse: bool = True   # True ⇒ one printed frame (joints fuse); False ⇒ keep parts separate
    # Joint blending (mm): after fusing, fillet the boolean-created seam edges so parts read as
    # one machined/printed body, not blocks jammed together. 0 = off. The blend must keep the
    # result a single valid solid (the verifier re-checks) — that's the whole point of doing it
    # in the deterministic builder rather than asking the model to hand-place fillet welds.
    fillet_joints: float = 0.0


def _place(solid: cq.Solid, comp: Component) -> cq.Solid:
    rx, ry, rz = comp.rotate
    s = solid
    if rx:
        s = s.rotate((0, 0, 0), (1, 0, 0), rx)
    if ry:
        s = s.rotate((0, 0, 0), (0, 1, 0), ry)
    if rz:
        s = s.rotate((0, 0, 0), (0, 0, 1), rz)
    return s.translate(cq.Vector(*comp.at))


def _placed_solids(asm: Assembly) -> List[cq.Solid]:
    """Place each buildable component; a part that fails to build (e.g. an infeasible fillet)
    is SKIPPED rather than crashing the whole assembly — the verifier flags it separately."""
    out = []
    for c in asm.components:
        try:
            out.append(_place(build(c.part).val(), c))
        except Exception:  # noqa: BLE001 — one bad part must not kill the assembly
            pass
    return out


def _pt_on_solid(p: cq.Vector, solid: cq.Solid, eps: float) -> bool:
    """Is point p on (or essentially touching) the surface of `solid`?"""
    v = BRepBuilderAPI_MakeVertex(gp_Pnt(p.x, p.y, p.z)).Vertex()
    return BRepExtrema_DistShapeShape(v, solid.wrapped).Value() <= eps


def _edge_mid(e: cq.Edge):
    try:
        return e.positionAt(0.5)
    except Exception:  # noqa: BLE001 — a degenerate edge has no midpoint
        return None


def _seam_groups(fused: cq.Solid, placed: List[cq.Solid], eps: float = 0.05):
    """Group the fused solid's SEAM edges by which part-pair they belong to. A seam edge's
    midpoint lies on TWO+ of the original placed solids (where parts intersect); a plain edge
    lies on exactly one. Returns {frozenset(part indices): [midpoint, ...]} — we store midpoints
    (not edge handles) so we can re-find each group on the EVOLVING solid after earlier fillets
    invalidate handles. Largest joints first = blend the structural seams before the slivers."""
    groups: dict = {}
    for e in cq.Workplane(obj=fused).edges().vals():
        mid = _edge_mid(e)
        if mid is None:
            continue
        on = tuple(i for i, s in enumerate(placed) if _pt_on_solid(mid, s, eps))
        if len(on) >= 2:
            groups.setdefault(frozenset(on), []).append(mid)
    return groups


def _near_any(e: cq.Edge, mids, tol: float) -> bool:
    mid = _edge_mid(e)
    return mid is not None and any((mid - m).Length <= tol for m in mids)


def _blend_joints(fused: cq.Solid, placed: List[cq.Solid], radius: float) -> Tuple[cq.Solid, int]:
    """Fillet the boolean seams so fused parts read as one machined body. Returns (solid, n).
    Incremental + robust: a single all-edges fillet is infeasible on heavily-overlapping parts
    (OCP gives up on the whole set), so we blend ONE part-pair joint at a time on the evolving
    solid, stepping the radius down per joint, and SKIP any joint that won't take a fillet — a
    partial blend is fine; a failed blend must never break the assembly."""
    if radius <= 0:
        return fused, 0
    groups = _seam_groups(fused, placed)
    solid, total = fused, 0
    for _key, mids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cur = cq.Workplane(obj=solid)
        sel = [e for e in cur.edges().vals() if _near_any(e, mids, 0.05)]
        if not sel:
            continue
        for r in (radius, radius * 0.5, radius * 0.25):
            try:
                solid = cur.newObject(sel).fillet(r).val()
                total += len(sel)
                break
            except Exception:  # noqa: BLE001 — smaller radius, then skip this joint
                continue
    return solid, total


def _fuse(placed: List[cq.Solid]) -> cq.Solid:
    combined = placed[0]
    for s in placed[1:]:
        combined = combined.fuse(s)
    return combined


def build_assembly(asm: Assembly) -> cq.Workplane:
    """Place buildable components, fuse (default) into one solid, then blend the joints."""
    solids = _placed_solids(asm)
    if not solids:
        raise ValueError("assembly has no buildable components")
    if not asm.fuse:
        return cq.Workplane(obj=cq.Compound.makeCompound(solids))
    fused = _fuse(solids)
    blended, _ = _blend_joints(fused, solids, asm.fillet_joints)
    return cq.Workplane(obj=blended)


def verify_assembly(asm: Assembly) -> dict:
    """Per-component local verify (build-failure-tolerant) + assembly connectivity & validity."""
    comps, placed = [], []
    for c in asm.components:
        try:
            wp = build(c.part)
            rep = verify(wp, c.part)
            comps.append({"name": c.name, "passed": rep.passed,
                          "fails": [r.name for r in rep.rows if not r.within_tol]})
            placed.append(_place(wp.val(), c))
        except Exception as e:  # noqa: BLE001 — a part that won't build is a (caught) failure
            comps.append({"name": c.name, "passed": False, "fails": [f"build error: {type(e).__name__}"]})
    built_all = len(placed) == len(asm.components)
    n_blended = 0
    if placed:
        if asm.fuse:
            fused = _fuse(placed)
            blended, n_blended = _blend_joints(fused, placed, asm.fillet_joints)
            shape = blended
        else:
            shape = cq.Compound.makeCompound(placed)
        m = measure(cq.Workplane(obj=shape))
        solids, valid, env = m.solids, m.valid, {"dx": m.dx, "dy": m.dy, "dz": m.dz, "volume": m.volume}
    else:
        solids, valid, env = 0, False, {"dx": 0.0, "dy": 0.0, "dz": 0.0, "volume": 0.0}
    expected_solids = 1 if asm.fuse else len(asm.components)
    comps_ok = all(c["passed"] for c in comps) and built_all
    connectivity_ok = built_all and solids == expected_solids
    rows = [
        {"name": "assembly · components", "expected": len(asm.components),
         "measured": sum(1 for c in comps if c["passed"]), "within_tol": comps_ok,
         "category": "ok" if comps_ok else "component"},
        {"name": "assembly · connectivity (single solid)" if asm.fuse else "assembly · part count",
         "expected": expected_solids, "measured": solids, "within_tol": connectivity_ok,
         "category": "ok" if connectivity_ok else "disconnected"},
        {"name": "assembly · valid (watertight)", "expected": True, "measured": valid,
         "within_tol": valid, "category": "ok" if valid else "validity"},
    ]
    # Joint blending is informational — surface the count so a render's "smoothed joints" is
    # auditable. It FAILS only if blending corrupted the solid (no seams to blend, e.g. a single
    # part or parts that merely abut, is fine — n_blended=0 with a still-valid solid passes).
    if asm.fuse and asm.fillet_joints > 0:
        blend_ok = valid and solids == expected_solids
        rows.append({"name": "assembly · joints blended", "expected": "≥ 0",
                     "measured": n_blended, "within_tol": blend_ok,
                     "category": "ok" if blend_ok else "blend"})
    return {"passed": all(r["within_tol"] for r in rows), "solids": solids,
            "envelope": env, "components": comps, "rows": rows}
