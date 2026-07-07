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
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps
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
    # Frame hierarchy: when `parent` names another component, at/rotate are LOCAL to that parent's
    # frame and the world placement composes as M_world = M_parent · M_child (a lug placed once in
    # the wheel's frame rides wherever the wheel goes). Parented components are sub-assembly members:
    # solve_layout/repair move only their ROOT — children follow through the composition.
    parent: Optional[str] = None


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


class Joint(BaseModel):
    """A KINEMATIC connection — unlike a mate it does NOT fuse. The two sides stay separate
    rigid groups sharing an axis; `angle` poses the moving side; the verifier sweeps the range.

    Constraint-algebra semantics (v1, revolute/hinge only): the joint imposes 'axes coincide',
    leaving exactly 1 DOF (spin about `axis`). Rigid groups are the mate/parent-welded islands;
    a joint whose two sides land in the SAME group is OVER-CONSTRAINED (a weld short-circuits
    the hinge — it can't move) and the DOF row flags it. v1 poses each joint independently
    (single-level linkages: door-on-frame, lid-on-box); chained linkages are a later rung."""
    kind: Literal["revolute"] = "revolute"
    a: str                                              # moving side (its whole rigid group swings)
    b: str                                              # fixed/reference side
    axis: Literal["x", "y", "z"] = "z"
    at: Optional[Tuple[float, float, float]] = None     # point on the hinge axis (world); None ⇒ derived
    #                                                     from the closest point between the two groups
    angle: float = 0.0                                  # current pose (degrees)
    limits: Tuple[float, float] = (0.0, 90.0)           # motion range the pose sweep must clear


class Assembly(BaseModel):
    object: str = "assembly"
    components: List[Component] = Field(default_factory=list)
    mates: List[Mate] = Field(default_factory=list)   # structural relationships → solve_layout resolves placement
    joints: List[Joint] = Field(default_factory=list)  # kinematic connections (NOT fused; posed + swept)
    fuse: bool = True   # True ⇒ one printed frame (joints fuse); False ⇒ keep parts separate
    # Joint blending (mm): after fusing, fillet the boolean-created seam edges so parts read as
    # one machined/printed body, not blocks jammed together. 0 = off. The blend must keep the
    # result a single valid solid (the verifier re-checks) — that's the whole point of doing it
    # in the deterministic builder rather than asking the model to hand-place fillet welds.
    fillet_joints: float = 0.0


class AsmPatch(BaseModel):
    """A small EDIT delta (so an edit doesn't regenerate the whole assembly): components to ADD-or-REPLACE
    (matched by name), component names to REMOVE, and optionally a replacement `mates`/`joints` list when
    the edit changes how parts connect or move (e.g. adding a lid that needs a hinge)."""
    upsert: List[Component] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)
    mates: Optional[List[Mate]] = None
    joints: Optional[List[Joint]] = None


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
    if patch.joints is not None:
        out.joints = patch.joints
    return out


def _place(solid: cq.Solid, comp: Component) -> cq.Solid:
    """One rigid transform M = T·R (rotate about the frame origin, then translate)."""
    rx, ry, rz = comp.rotate
    s = solid
    if rx:
        s = s.rotate((0, 0, 0), (1, 0, 0), rx)
    if ry:
        s = s.rotate((0, 0, 0), (0, 1, 0), ry)
    if rz:
        s = s.rotate((0, 0, 0), (0, 0, 1), rz)
    return s.translate(cq.Vector(*comp.at))


def _frame_chain(comp: Component, comps: dict, max_depth: int = 8) -> List[Component]:
    """leaf→root list of frames for a component (cycle-guarded). Applying each frame's
    transform in this order realizes p_world = M_root · … · M_parent · M_child · p_local."""
    chain, seen, cur = [comp], {comp.name}, comp
    while cur.parent and cur.parent in comps and cur.parent not in seen and len(chain) < max_depth:
        cur = comps[cur.parent]
        seen.add(cur.name)
        chain.append(cur)
    return chain


def _place_world(solid: cq.Solid, comp: Component, comps: dict) -> cq.Solid:
    """Hierarchy-aware placement: apply the leaf's local M first, then each ancestor's —
    matrix composition M_world = M_parent · M_child realized as successive rigid moves."""
    s = solid
    for frame in _frame_chain(comp, comps):
        s = _place(s, frame)
    return s


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


def _placed_bb(bare: cq.Solid, comp: Component, comps: Optional[dict] = None):
    """World-space bounding box of a component's bare solid (frame-chain aware when comps given)."""
    if comps is not None:
        return _place_world(bare, comp, comps).BoundingBox()
    return _place(bare, comp).BoundingBox()


# --------------------------------------------------------------------- interference & statics
def _common_volume(s1: cq.Solid, s2: cq.Solid) -> float:
    """vol(A ∩ B) in mm³ — the exact set-theory interference measure (collision ⇔ vol(A∩B) > 0).
    OCCT boolean common + volume properties; 0.0 on any boolean failure (a failed common on
    disjoint parts is not interference)."""
    try:
        algo = BRepAlgoAPI_Common(s1.wrapped, s2.wrapped)
        algo.Build()
        if not algo.IsDone():
            return 0.0
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(algo.Shape(), props)
        return max(0.0, float(props.Mass()))
    except Exception:  # noqa: BLE001
        return 0.0


def _bb_overlap(b1, b2, pad: float = 0.1) -> bool:
    """AABB broad-phase (the SAT axis test on world axes) — skip the exact boolean when the
    boxes don't even overlap."""
    return (b1.xmin - pad <= b2.xmax and b2.xmin - pad <= b1.xmax and
            b1.ymin - pad <= b2.ymax and b2.ymin - pad <= b1.ymax and
            b1.zmin - pad <= b2.zmax and b2.zmin - pad <= b1.zmax)


def _mated_pairs(asm: Assembly) -> set:
    """Component pairs whose overlap is SANCTIONED — their mate fuses them deliberately
    (stack/flush/attach/coaxial overlap by `overlap` mm to weld). A part stacked on a radial
    group rests on ALL its members. Every other pair must not share volume."""
    radial_groups: dict = {}
    for m in asm.mates:
        if m.kind == "radial":
            for p in m.parts or []:
                radial_groups[p] = list(m.parts or [])
    siblings: dict = {}                          # parent → its sub-assembly members
    for c in asm.components:
        if c.parent:
            siblings.setdefault(c.parent, []).append(c.name)
    pairs: set = set()
    for m in asm.mates:
        if m.kind in ("stack", "flush", "attach", "coaxial") and m.a and m.b:
            if m.b in radial_groups:
                for p in radial_groups[m.b]:
                    pairs.add(frozenset((m.a, p)))
            else:
                pairs.add(frozenset((m.a, m.b)))
            # mating onto a SUB-ASSEMBLY member means resting on the whole sub-assembly (a PCB
            # stacked on one standoff seats on all of them) — same rule as stack-onto-radial-group.
            parent = next((c.parent for c in asm.components if c.name == m.b and c.parent), None)
            if parent:
                pairs.add(frozenset((m.a, parent)))
                for sib in siblings.get(parent, []):
                    if sib != m.a:
                        pairs.add(frozenset((m.a, sib)))
    for c in asm.components:                    # sub-assembly members sit ON their parent by design
        if c.parent:
            pairs.add(frozenset((c.name, c.parent)))
    return pairs


def _hull2d(pts: list) -> list:
    """Convex hull (Andrew monotone chain), CCW. The support polygon is the hull of the
    ground-contact points."""
    pts = sorted(set(pts))
    if len(pts) <= 2:
        return list(pts)
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo: list = []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    up: list = []
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def _hull_margin(pt: tuple, hull: list) -> float:
    """Signed distance from pt to the hull boundary: POSITIVE inside (stability margin, mm),
    negative outside (tips over). Static stability ⇔ CoM projects inside the support polygon."""
    if len(hull) < 3:
        if not hull:
            return -1e9
        return -min(math.hypot(pt[0] - h[0], pt[1] - h[1]) for h in hull)
    def seg_dist(p, a, b):
        vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
        return math.hypot(p[0] - (a[0] + t * vx), p[1] - (a[1] + t * vy))
    inside = all((b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0]) >= 0
                 for a, b in zip(hull, hull[1:] + hull[:1]))
    d = min(seg_dist(pt, a, b) for a, b in zip(hull, hull[1:] + hull[:1]))
    return d if inside else -d


def _contact_patch_pts(solid: cq.Solid, z_top: float = 1.0) -> list:
    """XY corners of the part's ACTUAL ground-contact region — the solid clipped to a thin slab
    at the floor (not the whole-part bbox, which would fake a wide stance for a tilted leg)."""
    bb = solid.BoundingBox()
    if bb.zmin > z_top:
        return []
    z0 = min(bb.zmin, -0.5) - 0.5
    slab = cq.Solid.makeBox(bb.xlen + 2, bb.ylen + 2, z_top - z0, cq.Vector(bb.xmin - 1, bb.ymin - 1, z0))
    try:
        algo = BRepAlgoAPI_Common(solid.wrapped, slab.wrapped)
        algo.Build()
        if algo.IsDone():
            cb = cq.Shape(algo.Shape()).BoundingBox()
            if cb.xlen > 1e-6 and cb.ylen > 1e-6:
                return [(cb.xmin, cb.ymin), (cb.xmin, cb.ymax), (cb.xmax, cb.ymin), (cb.xmax, cb.ymax)]
    except Exception:  # noqa: BLE001
        pass
    return [(bb.xmin, bb.ymin), (bb.xmin, bb.ymax), (bb.xmax, bb.ymin), (bb.xmax, bb.ymax)]


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
        return _placed_bb(b, comps[name], comps) if (b is not None and name in comps) else None

    def set_at(name, x=None, y=None, z=None):
        c = comps[name]
        if c.parent:      # sub-assembly member: its placement is LOCAL to the parent — mates move roots only
            return
        cx, cy, cz = c.at
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
                ab = _placed_bb(bare[m.around], comps[m.around], comps); cx, cy = ab.center.x, ab.center.y
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
                    if comps[nm].parent:      # sub-assembly member — root placement only
                        continue
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
                if not comps[m.a].parent:
                    comps[m.a].rotate = comps[m.b].rotate
            elif m.kind == "attach" and m.a in comps and m.b in comps:
                ba, rb = bb(m.a), bb(m.b)
                if ba and rb:
                    d, direction = _solid_gap(_place_world(bare[m.a], comps[m.a], comps),
                                              _place_world(bare[m.b], comps[m.b], comps))
                    step = direction.multiply(d + m.overlap)
                    cx, cy, cz = comps[m.a].at
                    set_at(m.a, x=cx + step.x, y=cy + step.y, z=cz + step.z)
        except Exception:  # noqa: BLE001 — a bad mate shouldn't crash the whole layout
            continue

    # Joint placement — a joint's moving side must sit ADJACENT to its reference with a running
    # CLEARANCE (fit band, mistakes-catalog A6: 0.1–0.3 mm), never welded: overlap would put both
    # sides in one rigid group and over-constrain the hinge. Snap `a` along the closest-approach
    # direction to a 0.3 mm gap (attach-with-gap). Only parts the mates didn't already place
    # relative to `b` move; parented members ride their root.
    mated_names = {n for m in asm.mates for n in ((m.a, m.b) if m.kind != "radial" else tuple(m.parts or []))
                   if n}
    for j in asm.joints:
        try:
            if j.a not in comps or j.b not in comps or comps[j.a].parent:
                continue
            if bare.get(j.a) is None or bare.get(j.b) is None:
                continue
            if j.a not in mated_names:
                # The moving side is (correctly) unmated, so nothing placed it — it's wherever it
                # was authored, typically the origin, buried in the reference. Give it the natural
                # CLOSED pose: seated over its reference side's rigid group (group-bbox center),
                # resting a fit-clearance above it. The sweep then judges the whole motion range.
                gid = _rigid_groups(asm)
                grp = [n for n in comps if gid.get(n) == gid.get(j.b) and bare.get(n) is not None]
                boxes = [_placed_bb(bare[n], comps[n], comps) for n in grp]
                ba = _placed_bb(bare[j.a], comps[j.a], comps)
                if boxes and ba:
                    gx = (min(b.xmin for b in boxes) + max(b.xmax for b in boxes)) / 2
                    gy = (min(b.ymin for b in boxes) + max(b.ymax for b in boxes)) / 2
                    gz = max(b.zmax for b in boxes)
                    cx, cy, cz = comps[j.a].at
                    comps[j.a].at = (round(cx + gx - ba.center.x, 3), round(cy + gy - ba.center.y, 3),
                                     round(cz + gz + 0.3 - ba.zmin, 3))
                continue
            d, direction = _solid_gap(_place_world(bare[j.a], comps[j.a], comps),
                                      _place_world(bare[j.b], comps[j.b], comps))
            step = d - 0.3   # land at a 0.3 mm running clearance
            if abs(step) < 1e-6 or d <= 0.3:
                continue     # already adjacent (or authored tighter — leave it; the verifier judges)
            mv = direction.multiply(step)
            cx, cy, cz = comps[j.a].at
            comps[j.a].at = (round(cx + mv.x, 3), round(cy + mv.y, 3), round(cz + mv.z, 3))
        except Exception:  # noqa: BLE001 — a bad joint shouldn't crash the layout
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
    if asm.joints:
        # a kinematic assembly is SUPPOSED to be several separate bodies with clearance at the
        # joints — gap-closing would weld the hinge shut. Placement is solve_layout's job here;
        # the verifier's group-connectivity / DOF / sweep rows judge the result.
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
    comps_map = {c.name: c for c in asm.components}
    for _ in range(max_iter):
        placed = {i: _place_world(bare[i], asm.components[i], comps_map) for i in idx}
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
                    if asm.components[i].parent:            # children ride with their root's frame
                        continue
                    cx, cy, cz = asm.components[i].at
                    asm.components[i].at = (round(cx + step.x, 3), round(cy + step.y, 3), round(cz + step.z, 3))
                moved = True
                break                                       # re-evaluate groups after one move
        if not moved:
            break
    return asm


def _placed_solids(asm: Assembly) -> List[cq.Solid]:
    """Place each buildable component (frame-chain aware); a part that fails to build (e.g. an
    infeasible fillet) is SKIPPED rather than crashing the whole assembly — the verifier flags it."""
    out = []
    comps = {c.name: c for c in asm.components}
    for c in asm.components:
        try:
            out.append(_place_world(build(c.part).val(), c, comps))
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


# --------------------------------------------------------------------- kinematics (revolute v1)
def _rigid_groups(asm: Assembly) -> dict:
    """Partition components into RIGID groups: union-find over everything that welds — mate
    pairs (incl. stack-on-radial expansion) and parent links. Joints connect groups without
    welding. Returns {component name → group id (the group's lexicographically-first member)}."""
    names = [c.name for c in asm.components]
    parent = {n: n for n in names}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    for pair in _mated_pairs(asm):
        a, b = sorted(pair)
        union(a, b)
    for m in asm.mates:                       # radial members weld to what gets stacked on them via
        if m.kind == "mirror" and m.a and m.b:  # _mated_pairs; mirror pairs are the SAME rigid frame
            union(m.a, m.b)
    roots: dict = {}
    for n in names:
        r = find(n)
        roots.setdefault(r, []).append(n)
    gid_of = {}
    for r, members in roots.items():
        gid = min(members)
        for n in members:
            gid_of[n] = gid
    return gid_of


_AXIS_DIR = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _joint_axis_point(joint: Joint, ga: cq.Solid, gb: cq.Solid) -> Tuple[float, float, float]:
    """The point the hinge axis passes through: explicit `at`, else the midpoint of the closest
    approach between the two groups (a hinge lives where the parts meet)."""
    if joint.at is not None:
        return joint.at
    m = BRepExtrema_DistShapeShape(ga.wrapped, gb.wrapped)
    p1, p2 = m.PointOnShape1(1), m.PointOnShape2(1)
    return ((p1.X() + p2.X()) / 2, (p1.Y() + p2.Y()) / 2, (p1.Z() + p2.Z()) / 2)


def _rotate_about(solid: cq.Solid, at: Tuple[float, float, float], axis: str, angle: float) -> cq.Solid:
    """Rigid rotation about the axis LINE through `at` along `axis` — the joint's 1 DOF."""
    if abs(angle) < 1e-12:
        return solid
    d = _AXIS_DIR[axis]
    p2 = (at[0] + d[0], at[1] + d[1], at[2] + d[2])
    return solid.rotate(cq.Vector(*at), cq.Vector(*p2), angle)


def _group_solids(asm: Assembly, placed_by_name: dict, gid_of: dict) -> dict:
    """Fuse each rigid group's placed solids → {gid: solid} (a group with no buildable member
    is absent)."""
    buckets: dict = {}
    for n, s in placed_by_name.items():
        buckets.setdefault(gid_of.get(n, n), []).append(s)
    return {g: _fuse(ss) for g, ss in buckets.items() if ss}


def _pose_groups(asm: Assembly, group_solids: dict, gid_of: dict, angles: Optional[dict] = None) -> dict:
    """Apply each joint's rotation to its MOVING group: {gid: posed solid}. `angles` overrides
    per-joint pose (keyed by joint index) — the sweep uses this; None ⇒ each joint's own angle."""
    posed = dict(group_solids)
    for k, j in enumerate(asm.joints):
        ga_id, gb_id = gid_of.get(j.a), gid_of.get(j.b)
        if ga_id is None or gb_id is None or ga_id == gb_id or ga_id not in posed or gb_id not in posed:
            continue     # over-constrained/unbuildable — flagged by the DOF row, not posed
        theta = (angles or {}).get(k, j.angle)
        at = _joint_axis_point(j, posed[ga_id], posed[gb_id])
        posed[ga_id] = _rotate_about(posed[ga_id], at, j.axis, theta)
    return posed


def build_assembly(asm: Assembly) -> cq.Workplane:
    """Place buildable components; joints ⇒ fuse each rigid group and POSE them (a compound of
    separate movable bodies); no joints ⇒ fuse everything (default) and blend the seams."""
    comps = {c.name: c for c in asm.components}
    placed_by_name: dict = {}
    for c in asm.components:
        try:
            placed_by_name[c.name] = _place_world(build(c.part).val(), c, comps)
        except Exception:  # noqa: BLE001 — one bad part must not kill the assembly
            pass
    if not placed_by_name:
        raise ValueError("assembly has no buildable components")
    solids = list(placed_by_name.values())
    if asm.joints:
        gid_of = _rigid_groups(asm)
        posed = _pose_groups(asm, _group_solids(asm, placed_by_name, gid_of), gid_of)
        return cq.Workplane(obj=cq.Compound.makeCompound(list(posed.values())))
    if not asm.fuse:
        return cq.Workplane(obj=cq.Compound.makeCompound(solids))
    fused = _fuse(solids)
    blended, _ = _blend_joints(fused, solids, asm.fillet_joints)
    return cq.Workplane(obj=blended)


def verify_assembly(asm: Assembly) -> dict:
    """Per-component local verify (build-failure-tolerant) + assembly connectivity & validity."""
    comps, placed, built = [], [], []
    comps_map = {c.name: c for c in asm.components}
    for c in asm.components:
        try:
            wp = build(c.part)
            rep = verify(wp, c.part)
            comps.append({"name": c.name, "passed": rep.passed,
                          "fails": [r.name for r in rep.rows if not r.within_tol]})
            ps = _place_world(wp.val(), c, comps_map)
            placed.append(ps); built.append((c, ps))
        except Exception as e:  # noqa: BLE001 — a part that won't build is a (caught) failure
            comps.append({"name": c.name, "passed": False, "fails": [f"build error: {type(e).__name__}"]})
    built_all = len(placed) == len(asm.components)
    placed_by_name = {c.name: s for c, s in built}
    n_blended = 0
    gid_of: dict = {}
    groups: dict = {}
    if placed:
        if asm.joints:
            # kinematic assembly: each rigid group fuses internally; groups stay SEPARATE
            # bodies, posed at each joint's current angle. Expected solid count = group count.
            gid_of = _rigid_groups(asm)
            groups = _group_solids(asm, placed_by_name, gid_of)
            posed = _pose_groups(asm, groups, gid_of)
            shape = cq.Compound.makeCompound(list(posed.values()))
        elif asm.fuse:
            fused = _fuse(placed)
            blended, n_blended = _blend_joints(fused, placed, asm.fillet_joints)
            shape = blended
        else:
            shape = cq.Compound.makeCompound(placed)
        m = measure(cq.Workplane(obj=shape))
        solids, valid, env = m.solids, m.valid, {"dx": m.dx, "dy": m.dy, "dz": m.dz, "volume": m.volume}
    else:
        solids, valid, env = 0, False, {"dx": 0.0, "dy": 0.0, "dz": 0.0, "volume": 0.0}
    if asm.joints:
        expected_solids = max(1, len(groups))
    else:
        expected_solids = 1 if asm.fuse else len(asm.components)
    comps_ok = all(c["passed"] for c in comps) and built_all
    connectivity_ok = built_all and solids == expected_solids
    conn_name = ("assembly · connectivity (fused rigid groups)" if asm.joints
                 else "assembly · connectivity (single solid)" if asm.fuse else "assembly · part count")
    rows = [
        {"name": "assembly · components", "expected": len(asm.components),
         "measured": sum(1 for c in comps if c["passed"]), "within_tol": comps_ok,
         "category": "ok" if comps_ok else "component"},
        {"name": conn_name,
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
        # Statics — the real test behind the heuristic above: c = (1/m)∫ρ·p dV must project INSIDE
        # the support polygon (convex hull of the actual ground-contact patches), else it tips.
        # Uniform density (GProp volume centroid); measured = the stability margin in mm (signed
        # distance from the CoM's XY projection to the hull boundary; positive = inside).
        if footed and grounded:
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape.wrapped if hasattr(shape, "wrapped") else shape, props)
            com = props.CentreOfMass()
            contact_pts: list = []
            for _c, s in built:
                if s.BoundingBox().zmin <= 1.0:
                    contact_pts += _contact_patch_pts(s)
            hull = _hull2d([(round(x, 3), round(y, 3)) for x, y in contact_pts])
            margin = _hull_margin((com.X(), com.Y()), hull)
            st_ok = margin > 0.0
            rows.append({"name": "assembly · statics (CoM inside support polygon)", "expected": "> 0 mm",
                         "measured": round(margin, 2), "within_tol": st_ok,
                         "category": "ok" if st_ok else "structure"})
    # Part↔part interference — the set-theory inequality vol(A∩B) ≤ ε for every pair NOT joined
    # by a mate (mated pairs overlap DELIBERATELY, ~1–4 mm, to weld). Catches legs colliding at a
    # too-small radius, a mirrored part crossing the plane, an arm buried in the hub. Bare
    # (un-greebled) solids for speed; AABB broad-phase before the exact boolean.
    # Only run when the assembly DECLARES relationships (mates/joints/parents): a raw-coordinate
    # manual assembly carries no sanction information — every weld overlap is intentional there,
    # so the check would flag correct assemblies by design.
    has_intent = bool(asm.mates or asm.joints or any(c.parent for c in asm.components))
    if len(asm.components) >= 2 and has_intent:
        sanctioned = _mated_pairs(asm)
        bare_placed: dict = {}
        for c in asm.components:
            try:
                bare_placed[c.name] = _place_world(_bare_solid(c.part), c, comps_map)
            except Exception:  # noqa: BLE001 — unbuildable part is already flagged above
                pass
        names = [c.name for c in asm.components if c.name in bare_placed]
        worst_v, worst_pair = 0.0, ""
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if frozenset((a, b)) in sanctioned:
                    continue
                sa, sb = bare_placed[a], bare_placed[b]
                if not _bb_overlap(sa.BoundingBox(), sb.BoundingBox()):
                    continue
                v = _common_volume(sa, sb)
                if v > worst_v:
                    worst_v, worst_pair = v, f"{a}↔{b}"
        inter_ok = worst_v <= 1.0   # mm³ — measure-zero touching passes; real interpenetration fails
        rows.append({"name": "assembly · interference (worst non-mated pair)", "expected": "≤ 1 mm³",
                     "measured": round(worst_v, 2), "within_tol": inter_ok,
                     "category": "ok" if inter_ok else "integrity"})
        if not inter_ok:
            rows[-1]["name"] = f"assembly · interference (worst non-mated pair: {worst_pair})"

    # Kinematics — DOF accounting + configuration-space clearance (only when joints declared).
    if asm.joints and groups:
        # DOF bookkeeping: a free body has 6; the group weld takes them all; each valid revolute
        # returns exactly 1. A joint whose sides landed in the SAME group is over-constrained
        # (welded hinge); a repeat joint between the same two groups is redundant (also flagged).
        movable, problems, seen_pairs = 0, [], set()
        for j in asm.joints:
            ga, gb = gid_of.get(j.a), gid_of.get(j.b)
            if ga is None or gb is None:
                problems.append(f"{j.a}/{j.b} unknown")
            elif ga == gb:
                problems.append(f"{j.a}↔{j.b} welded (over-constrained)")
            elif frozenset((ga, gb)) in seen_pairs:
                problems.append(f"{j.a}↔{j.b} redundant")
            else:
                seen_pairs.add(frozenset((ga, gb)))
                movable += 1
        # under-constraint: every group must reach the BASE group (the largest) through joints —
        # else it's a free-floating 6-DOF body nothing holds.
        adj: dict = {}
        for pair in seen_pairs:
            x, y = tuple(pair)
            adj.setdefault(x, []).append(y)
            adj.setdefault(y, []).append(x)
        base = max(groups, key=lambda g: sum(1 for n in gid_of if gid_of[n] == g))
        reach, stack_ = {base}, [base]
        while stack_:
            for nxt in adj.get(stack_.pop(), []):
                if nxt not in reach:
                    reach.add(nxt); stack_.append(nxt)
        floating = [g for g in groups if g not in reach]
        dof_ok = movable == len(asm.joints) and not floating
        rows.append({"name": "assembly · DOF (1 per revolute)"
                     + ("" if dof_ok else f" [{'; '.join(problems) or 'floating: ' + ', '.join(floating)}]"),
                     "expected": len(asm.joints), "measured": movable, "within_tol": dof_ok,
                     "category": "ok" if dof_ok else "kinematic"})
        # Pose sweep (configuration space): clearance must hold at EVERY sampled pose across each
        # joint's limits, not just the rest pose — gap(θ) > 0 for all θ. Samples: lo, mid, hi.
        sweep_worst, sweep_detail = 0.0, ""
        for k, j in enumerate(asm.joints):
            ga, gb = gid_of.get(j.a), gid_of.get(j.b)
            if ga is None or gb is None or ga == gb or ga not in groups:
                continue
            lo, hi = j.limits
            for theta in (lo, (lo + hi) / 2.0, hi):
                posed_t = _pose_groups(asm, groups, gid_of, {k: theta})
                mv = posed_t[ga]
                mb = mv.BoundingBox()
                for g2, s2 in posed_t.items():
                    if g2 == ga or not _bb_overlap(mb, s2.BoundingBox()):
                        continue
                    v = _common_volume(mv, s2)
                    if v > sweep_worst:
                        sweep_worst, sweep_detail = v, f"{j.a} @ {theta:g}°"
        sweep_ok = sweep_worst <= 1.0
        rows.append({"name": "assembly · pose sweep (worst ∩ over joint range)"
                     + ("" if sweep_ok else f" [{sweep_detail}]"),
                     "expected": "≤ 1 mm³", "measured": round(sweep_worst, 2), "within_tol": sweep_ok,
                     "category": "ok" if sweep_ok else "kinematic"})
    # Joint blending is informational — surface the count so a render's "smoothed joints" is
    # auditable. It FAILS only if blending corrupted the solid (no seams to blend, e.g. a single
    # part or parts that merely abut, is fine — n_blended=0 with a still-valid solid passes).
    if asm.fuse and asm.fillet_joints > 0 and not asm.joints:
        blend_ok = valid and solids == expected_solids
        rows.append({"name": "assembly · joints blended", "expected": "≥ 0",
                     "measured": n_blended, "within_tol": blend_ok,
                     "category": "ok" if blend_ok else "blend"})
    return {"passed": all(r["within_tol"] for r in rows), "solids": solids,
            "envelope": env, "components": comps, "rows": rows}
