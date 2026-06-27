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

import math
from typing import List, Literal, Optional, Tuple

import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt
from pydantic import BaseModel, Field

from .builder import build
from .spec import Spec
from .verifier import measure, verify


Role = Literal["seat", "top", "base", "leg", "support", "arm", "panel", "body", "hub", "fastener", "other"]


class Component(BaseModel):
    name: str = "part"
    part: Spec
    role: Role = "other"                                    # semantic role → drives structural placement rules
    # at/rotate are the RESOLVED placement — solve_layout() writes them from the mate graph. They stay so
    # everything downstream (_place, build_assembly, verify_assembly) is unchanged; a mate-less component
    # falls back to whatever at/rotate it carries (manual specs still work).
    at: Tuple[float, float, float] = (0.0, 0.0, 0.0)        # translation (mm)
    rotate: Tuple[float, float, float] = (0.0, 0.0, 0.0)    # degrees about X, Y, Z (applied in order)


class Mate(BaseModel):
    """A NAMED structural relationship between parts (the generator emits these, not coordinates — see
    docs/research/sources.md 'emit named relationships, not coordinates'). solve_layout() resolves the
    whole graph deterministically into each component's at/rotate."""
    kind: Literal["ground", "stack", "coaxial", "radial", "flush", "mirror", "attach"]
    a: Optional[str] = None                 # primary part (ground/stack/coaxial/flush/mirror/attach)
    b: Optional[str] = None                 # reference part (a is placed relative to b)
    parts: List[str] = Field(default_factory=list)   # radial: the group of parts arranged around an axis
    around: Optional[str] = None            # radial: part whose Z axis is the circle center (None ⇒ origin)
    count: Optional[int] = None             # radial: how many (defaults to len(parts))
    radius: Optional[float] = None          # radial: circle radius mm (defaults from `around` part)
    splay_deg: float = 0.0                  # radial: outward lean of each part (° about its tangent)
    z: Optional[float] = None               # radial: explicit z for the group (else grounded/inferred)
    side: Optional[str] = None              # flush: "+x"|"-x"|"+y"|"-y"|"+z"|"-z"
    plane: Optional[str] = None             # mirror: "YZ"|"XZ"|"XY"
    overlap: float = 1.5                    # stack/flush/attach: mm the parts overlap at the joint
    offset: Tuple[float, float] = (0.0, 0.0)  # stack: extra XY offset of a on b


class Assembly(BaseModel):
    object: str = "assembly"
    components: List[Component] = Field(default_factory=list)
    mates: List[Mate] = Field(default_factory=list)   # structural relationships → solve_layout resolves placement
    fuse: bool = True   # True ⇒ one printed frame (joints fuse); False ⇒ keep parts separate
    # Joint blending (mm): after fusing, fillet the boolean-created seam edges so parts read as
    # one machined/printed body, not blocks jammed together. 0 = off. The blend must keep the
    # result a single valid solid (the verifier re-checks) — that's the whole point of doing it
    # in the deterministic builder rather than asking the model to hand-place fillet welds.
    fillet_joints: float = 0.0


class AsmPatch(BaseModel):
    """A small EDIT delta (so an edit doesn't regenerate the whole assembly): components to ADD-or-REPLACE
    (matched by name), component names to REMOVE, and optionally a replacement `mates` list when the edit
    changes how parts connect (e.g. adding a part that needs to be mated)."""
    upsert: List[Component] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)
    mates: Optional[List[Mate]] = None


def apply_patch(asm: Assembly, patch: AsmPatch) -> Assembly:
    """Apply an edit delta: drop `remove` names, add/replace each `upsert` component by name, and replace
    the mate graph if the patch supplies one (else keep the existing mates so solve_layout re-resolves)."""
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
    if patch.mates is not None:
        out.mates = patch.mates
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


def _placed_bb(bare: cq.Solid, comp: Component):
    """World-space bounding box of a component's bare solid after its current rotate+translate."""
    return _place(bare, comp).BoundingBox()


def solve_layout(asm: Assembly) -> Assembly:
    """Resolve the NAMED mate graph → each component's at/rotate, deterministically. This replaces asking
    the LLM for raw coordinates (which it's poor at). Patterns: ground (floor contact), radial (legs/spokes
    around an axis, splayed), stack (a on top of b), coaxial, flush, mirror, attach (bounded snap). Parts
    with no mate keep their given at/rotate. Mates are applied in dependency order so a support is placed
    before what rests on it; bounding boxes are recomputed per mate from the live placement."""
    comps = {c.name: c for c in asm.components}
    bare: dict = {}
    for c in asm.components:
        try:
            bare[c.name] = _bare_solid(c.part)
        except Exception:  # noqa: BLE001
            bare[c.name] = None

    def bb(name: str):
        b = bare.get(name)
        return _placed_bb(b, comps[name]) if (b is not None and name in comps) else None

    def set_at(name, x=None, y=None, z=None):
        c = comps[name]; cx, cy, cz = c.at
        c.at = (round(x if x is not None else cx, 3), round(y if y is not None else cy, 3), round(z if z is not None else cz, 3))

    def ground(name):
        b = bb(name)
        if b: set_at(name, z=comps[name].at[2] - b.zmin)   # drop so min-z = 0

    # map each part in a radial group → (axis x, axis y, group names) so a part stacked ON a leg group
    # centers on the AXIS and rests on ALL of them (not on one leg's offset center).
    radial_of: dict = {}
    for m in asm.mates:
        if m.kind == "radial":
            cx, cy = (0.0, 0.0)
            if m.around and m.around in comps and bare.get(m.around) is not None:
                ab = _placed_bb(bare[m.around], comps[m.around]); cx, cy = ab.center.x, ab.center.y
            for p in (m.parts or []):
                radial_of[p] = (cx, cy, list(m.parts or []))

    # order: radial → ground → coaxial → stack → flush → mirror → attach (supports before dependents)
    order = {"radial": 0, "ground": 1, "coaxial": 2, "stack": 3, "flush": 4, "mirror": 5, "attach": 6}
    for m in sorted(asm.mates, key=lambda m: order.get(m.kind, 9)):
        try:
            if m.kind == "radial":
                names = [n for n in (m.parts or []) if n in comps]
                if not names:
                    continue
                n = m.count or len(names)
                cx, cy = (0.0, 0.0)
                if m.around and m.around in comps:
                    ab = bb(m.around)
                    if ab: cx, cy = ab.center.x, ab.center.y
                radius = m.radius
                if radius is None:
                    ab = bb(m.around) if m.around in comps else None
                    radius = (max(ab.xlen, ab.ylen) * 0.4) if ab else 40.0
                for i, nm in enumerate(names):
                    ang = 2 * math.pi * i / max(1, n)
                    # Orientation is ROLE-driven, not one-size: a LEG/BASE stands vertical and reaches the
                    # floor; an ARM/SPOKE radiates HORIZONTALLY from the hub. Parts often taper along local X
                    # (loft), so for a vertical leg we tip that long axis up to Z; a horizontal arm keeps its
                    # natural X orientation and the Z-spin alone points it outward at this angle.
                    vertical = comps[nm].role in ("leg", "base")
                    stand = 0.0
                    bs = bare.get(nm)
                    if vertical and bs is not None:
                        lb = bs.BoundingBox()
                        if lb.xlen >= lb.ylen and lb.xlen >= lb.zlen:   # long axis X → tip up (X→Z)
                            stand = -90.0
                    comps[nm].rotate = (0.0, round(stand + m.splay_deg, 3), round(math.degrees(ang), 3))
                    set_at(nm, x=cx + radius * math.cos(ang), y=cy + radius * math.sin(ang))
                    if m.z is not None:
                        set_at(nm, z=m.z)
                    elif vertical:
                        ground(nm)                                   # legs/base reach the floor
                    elif m.around in comps:                          # arms/spokes sit at the hub's mid-height
                        ab = bb(m.around)
                        if ab: set_at(nm, z=ab.center.z)
            elif m.kind == "ground" and m.a in comps:
                ground(m.a)
            elif m.kind == "coaxial" and m.a in comps and m.b in comps:
                rb = bb(m.b)
                if rb: set_at(m.a, x=rb.center.x, y=rb.center.y)
            elif m.kind == "stack" and m.a in comps and m.b in comps:
                ba = bb(m.a)
                if m.b in radial_of:                              # stacking onto a radial group (e.g. seat on legs)
                    cx, cy, grp = radial_of[m.b]
                    tops = [bb(p).zmax for p in grp if bb(p) is not None]
                    if ba and tops:
                        set_at(m.a, x=cx + m.offset[0], y=cy + m.offset[1],
                               z=comps[m.a].at[2] + (max(tops) - m.overlap - ba.zmin))  # centered on axis, on all legs
                else:
                    rb = bb(m.b)
                    if ba and rb:
                        set_at(m.a, x=rb.center.x + m.offset[0], y=rb.center.y + m.offset[1],
                               z=comps[m.a].at[2] + (rb.zmax - m.overlap - ba.zmin))   # a's bottom onto b's top
            elif m.kind == "flush" and m.a in comps and m.b in comps:
                ba, rb = bb(m.a), bb(m.b); s = (m.side or "+z")
                if ba and rb:
                    ax = {"+x": rb.xmax - m.overlap - ba.xmin, "-x": rb.xmin + m.overlap - ba.xmax}.get(s)
                    ay = {"+y": rb.ymax - m.overlap - ba.ymin, "-y": rb.ymin + m.overlap - ba.ymax}.get(s)
                    az = {"+z": rb.zmax - m.overlap - ba.zmin, "-z": rb.zmin + m.overlap - ba.zmax}.get(s)
                    set_at(m.a, x=comps[m.a].at[0] + ax if ax is not None else None,
                           y=comps[m.a].at[1] + ay if ay is not None else None,
                           z=comps[m.a].at[2] + az if az is not None else None)
            elif m.kind == "mirror" and m.a in comps and m.b in comps:
                bx, by, bz = comps[m.b].at; pl = (m.plane or "YZ")
                set_at(m.a, x=-bx if pl == "YZ" else bx, y=-by if pl == "XZ" else by, z=-bz if pl == "XY" else bz)
                comps[m.a].rotate = comps[m.b].rotate
            elif m.kind == "attach" and m.a in comps and m.b in comps:
                ba, rb = bb(m.a), bb(m.b)
                if ba and rb:
                    d, direction = _solid_gap(_place(bare[m.a], comps[m.a]), _place(bare[m.b], comps[m.b]))
                    step = direction.multiply(d + m.overlap)
                    cx, cy, cz = comps[m.a].at
                    set_at(m.a, x=cx + step.x, y=cy + step.y, z=cz + step.z)
        except Exception:  # noqa: BLE001 — a bad mate shouldn't crash the whole layout
            continue
    return asm


def repair_connectivity(asm: Assembly, margin: float = 1.5, max_iter: int = 16, max_close: float = 18.0) -> Assembly:
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
            # ONLY close SMALL gaps. solve_layout already arranged the parts; a large gap means the part
            # is intentionally apart (e.g. a splayed leg) — dragging it to the center would collapse the
            # layout into a clump (the old bug). Leave it; the verifier flags it as disconnected instead.
            if best is not None and best[0] <= max_close:
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
    comps, placed, built = [], [], []
    for c in asm.components:
        try:
            wp = build(c.part)
            rep = verify(wp, c.part)
            comps.append({"name": c.name, "passed": rep.passed,
                          "fails": [r.name for r in rep.rows if not r.within_tol]})
            ps = _place(wp.val(), c)
            placed.append(ps); built.append((c, ps))
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
    # Structural-support check — catches the "connected but stacked/clumped" failure that the single-solid
    # connectivity test misses (the research's 'false convergence'). Intent-aware via component roles:
    #   • grounded   — the assembly rests on the floor (min-z ≈ 0), not floating or sunk
    #   • legs reach — every leg/support part actually touches the floor (no stubby hovering legs)
    #   • footprint  — ≥3 legs/supports/arms are SPREAD in XY, not piled at one center (the stool clump)
    if built:
        bbs = [(c, s.BoundingBox()) for c, s in built]
        # ground contact is only EXPECTED for STANDING objects (those with legs/base); a free frame
        # (drone, wall bracket, a 'support' member up in the air) legitimately floats — don't require z≈0
        # unless the object actually stands on legs/base. 'support' is a generic strut, not a foot.
        footed = [(c, b) for c, b in bbs if c.role in ("leg", "base")]
        min_z = min(b.zmin for _, b in bbs)
        grounded = (not footed) or abs(min_z) <= 2.0
        legs = [(c, b) for c, b in bbs if c.role == "leg"]
        legs_reach = all(b.zmin <= 2.0 for _, b in legs)   # legs must actually touch the floor
        spread = [(c, b) for c, b in bbs if c.role in ("leg", "support", "arm")]
        footprint_ok = True
        if len(spread) >= 3:
            cxs = [b.center.x for _, b in spread]; cys = [b.center.y for _, b in spread]
            span = max(max(cxs) - min(cxs), max(cys) - min(cys))
            footprint_ok = span > 10.0   # legs/arms must fan out, not clump at the axis (the old stool bug)
        supported = grounded and legs_reach and footprint_ok
        detail = "ok" if supported else ", ".join(
            x for x, ok in [("not grounded", grounded), ("legs hover", legs_reach), ("clumped", footprint_ok)] if not ok)
        rows.append({"name": "assembly · structurally supported", "expected": "ok", "measured": detail,
                     "within_tol": supported, "category": "ok" if supported else "structure"})
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
