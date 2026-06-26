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


class AsmPatch(BaseModel):
    """A small EDIT delta (so an edit doesn't regenerate the whole assembly): components to ADD-or-REPLACE
    (matched by name) and component names to REMOVE."""
    upsert: List[Component] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


def apply_patch(asm: Assembly, patch: AsmPatch) -> Assembly:
    """Apply an edit delta: drop `remove` names, then add/replace each `upsert` component by name."""
    out = asm.model_copy(deep=True)
    rm = set(patch.remove)
    comps = [c for c in out.components if c.name not in rm]
    pos = {c.name: i for i, c in enumerate(comps)}
    for comp in patch.upsert:
        if comp.name in pos:
            comps[pos[comp.name]] = comp
        else:
            pos[comp.name] = len(comps); comps.append(comp)
    out.components = comps
    return out


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


def _bare_solid(part: Spec):
    """Build a part WITHOUT its greeble pass — connectivity depends on the gross shape, and greeble adds
    hundreds of faces that make the distance probe slow. The bare solid's overlap ≈ the greebled one's."""
    p = part.model_copy(deep=True)
    p.features = [f for f in p.features if f.type != "greeble"]
    return build(p).val()


def _solid_gap(s1: cq.Solid, s2: cq.Solid):
    """(min distance, unit direction from s1's nearest point toward s2's) between two placed solids."""
    m = BRepExtrema_DistShapeShape(s1.wrapped, s2.wrapped)
    d = m.Value()
    p1, p2 = m.PointOnShape1(1), m.PointOnShape2(1)
    v = cq.Vector(p2.X() - p1.X(), p2.Y() - p1.Y(), p2.Z() - p1.Z())
    return d, (v.normalized() if v.Length > 1e-9 else cq.Vector(1, 0, 0))


def repair_connectivity(asm: Assembly, margin: float = 1.5, max_iter: int = 16) -> Assembly:
    """Deterministically snap disconnected parts together so a fused assembly is ONE solid — the LLM
    planner routinely leaves gaps at joints, so verify_assembly reports 'disconnected'. Group parts by
    real solid proximity (union-find over BRepExtrema distance), then rigidly translate each non-anchor
    group toward the largest (anchor) group along the closest-point direction until they overlap by
    `margin`; re-evaluate each round. Distances use the BARE (un-greebled) solids (fast, same gross
    overlap). Mutates each moved component's `at` so the fix persists in the editable Assembly. No model."""
    if not asm.fuse or len(asm.components) < 2:
        return asm
    bare = [None] * len(asm.components)
    for i, c in enumerate(asm.components):
        try:
            bare[i] = _bare_solid(c.part)
        except Exception:  # noqa: BLE001 — an unbuildable part can't be snapped; skip it
            pass
    idx = [i for i, s in enumerate(bare) if s is not None]
    if len(idx) < 2:
        return asm
    for _ in range(max_iter):
        placed = {i: _place(bare[i], asm.components[i]) for i in idx}
        parent = {i: i for i in idx}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                if _solid_gap(placed[idx[a]], placed[idx[b]])[0] < 0.4:   # touching/overlapping ⇒ connected
                    parent[find(idx[a])] = find(idx[b])
        groups: dict = {}
        for i in idx:
            groups.setdefault(find(i), []).append(i)
        if len(groups) == 1:
            return asm                                   # fully connected
        order = sorted(groups.values(), key=lambda g: -len(g))
        anchor, moved = order[0], False
        for g in order[1:]:                              # snap the nearest non-anchor group to the anchor
            best = None
            for i in g:
                for j in anchor:
                    d, direction = _solid_gap(placed[i], placed[j])
                    if best is None or d < best[0]:
                        best = (d, direction)
            if best is not None:
                step = best[1].multiply(best[0] + margin)   # close the gap + overlap by margin
                for i in g:                                 # rigid move of the whole group (keeps layout)
                    cx, cy, cz = asm.components[i].at
                    asm.components[i].at = (round(cx + step.x, 3), round(cy + step.y, 3), round(cz + step.z, 3))
                moved = True
                break                                       # re-evaluate groups after one move
        if not moved:
            break
    return asm


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
    if radius <= 0 or len(placed) > 8:
        return fused, 0
    # Seam detection is O(edges x parts) with a BRep distance probe per pair; greeble adds hundreds of
    # edges per part, so on a many-part greebled assembly it explodes (effectively hangs). Skip the
    # cosmetic blend past an edge budget — the surface detail, not rounded joints, is the look there.
    if len(cq.Workplane(obj=fused).edges().vals()) > 1200:
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
