"""Deterministic spec → CadQuery solid.

In production the *generator* (LLM) emits CadQuery; this hand-written builder is
the **golden reference** used to self-test the verifier (build a known-good solid
from a spec, confirm the verifier measures it back to ~0 error) and a fallback
oracle. Mirrors the operation vocabulary the generator is allowed to use.
"""
from __future__ import annotations

import math
import random

import cadquery as cq
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from .selectors import CQ_EDGE
from .spec import Spec, expected_holes


def _ensure_positive(r):
    """After fuzzy greeble booleans on curved/tilted faces, OCCT can return a VALID but INSIDE-OUT solid
    (negative signed volume → inverted export normals). Reverse it so orientation points outward (>0)."""
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(r.val().wrapped, g)
    return cq.Workplane(obj=cq.Shape(r.val().wrapped.Reversed())) if g.Mass() < 0 else r


def _greeble_layout(L: float, W: float, H: float, g) -> tuple:
    """Deterministic greeble layout for a top-face pass → (cut_boxes, raise_boxes), each a list of
    (corner_xyz, size_xyz). Panel-line grooves on the grid + DETAILED cells that either recess (cut) or
    raise (additive) a panel, with a `density` weighted by a `focal` mask and a `levels`/`subdiv`
    hierarchy that splits some cells into 2×2 finer recesses (greeble-detail-research.md). Cut tops
    overshoot the surface and raises dip into it ⇒ no coincident faces; all elements inset `margin`
    off the grooves ⇒ disjoint. Shared by build(), emit_code(), and the verifier so they agree exactly.
    RNG advances identically for EVERY cell (fixed draw order) regardless of outcome → stable layout."""
    rng = random.Random(g.seed)
    tz = H / 2.0
    over = 0.5
    nx = max(1, round(L / g.panel)); ny = max(1, round(W / g.panel))
    max_cells = 48                       # bound the boolean count (each cell → ≤4 cuts) so dense/large
    if nx * ny > max_cells:              # panels stay fast; deterministic, coarsens the grid uniformly
        f = (nx * ny / max_cells) ** 0.5
        nx = max(1, round(nx / f)); ny = max(1, round(ny / f))
    cx, cy = L / nx, W / ny
    gw = gd = g.groove
    cuts: list = []; raises: list = []

    def add_recess(cx, cy, w, h, d):                         # a recessed panel + (bevel>0) a shallow wider lip
        cuts.append(((round(cx - w / 2, 4), round(cy - h / 2, 4), round(tz - d, 4)),
                     (round(w, 4), round(h, 4), round(d + over, 4))))
        b = min(g.bevel, g.margin * 0.6, d * 0.8)            # keep the lip off the grooves + above the floor
        if b > 0:                                            # stepped rim around the mouth = machined-edge look
            cuts.append(((round(cx - w / 2 - b, 4), round(cy - h / 2 - b, 4), round(tz - b, 4)),
                         (round(w + 2 * b, 4), round(h + 2 * b, 4), round(b + over, 4))))

    for i in range(1, nx):                                   # grooves (cut) at constant x (run along Y)
        x = -L / 2 + i * cx
        cuts.append(((x - gw / 2, -W / 2, tz - gd), (gw, W, gd + over)))
    for j in range(1, ny):                                   # grooves at constant y (run along X)
        y = -W / 2 + j * cy
        cuts.append(((-L / 2, y - gw / 2, tz - gd), (L, gw, gd + over)))

    def focal_w(px, py):                                     # density weight by region (non-uniform look)
        if g.focal == "center":
            r = ((px / (L / 2)) ** 2 + (py / (W / 2)) ** 2) ** 0.5      # 0 at center → ~1.4 at corners
            return max(0.15, 1.0 - 0.7 * min(1.0, r))                   # busier in the middle
        if g.focal == "edges":
            r = max(abs(px) / (L / 2), abs(py) / (W / 2))
            return max(0.15, 0.3 + 0.7 * r)                            # busier near the border
        return 1.0

    for i in range(nx):
        for j in range(ny):
            px = -L / 2 + (i + 0.5) * cx; py = -W / 2 + (j + 0.5) * cy
            roll = rng.random(); kind = rng.random(); sub = rng.random(); df = 0.6 + 0.4 * rng.random()
            if roll >= g.density * focal_w(px, py):
                continue
            rw = max(1.0, cx - 2 * g.margin); rh = max(1.0, cy - 2 * g.margin)
            if kind < g.raised:                              # RAISED panel (additive; dips into the part)
                raises.append(((px - rw / 2, py - rh / 2, tz - over),
                               (round(rw, 4), round(rh, 4), round(g.raise_h + over, 4))))
            elif g.levels >= 2 and sub < g.subdiv:           # SUBDIVIDED: 2×2 finer recesses (hierarchy)
                sm = g.margin * 0.6; sw = max(0.8, (rw - sm) / 2); sh = max(0.8, (rh - sm) / 2); d = g.depth * df
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        add_recess(px + sx * (sw + sm) / 2, py + sy * (sh + sm) / 2, sw, sh, d)
            else:                                            # plain RECESSED panel
                add_recess(px, py, rw, rh, g.depth * df)
    return cuts, raises


GREEBLE_OVER = 0.5      # radial/face overshoot so cutters never share a face with the part (robust booleans)
GREEBLE_FUZZY = 1e-3    # OCCT fuzzy-boolean tolerance for near-tangent cuts on the CURVED face (SetFuzzyValue)

# emitted self-contained orientation fix (matches _ensure_positive) — fuzzy greeble booleans can flip a
# valid solid inside-out (negative signed volume); reverse it so the exported normals point outward.
_EMIT_ORIENT_FIX = [
    "from OCP.GProp import GProp_GProps as _GP",
    "from OCP.BRepGProp import BRepGProp as _BG",
    "_gpv = _GP(); _BG.VolumeProperties_s(result.val().wrapped, _gpv)",
    "result = cq.Workplane(obj=cq.Shape(result.val().wrapped.Reversed())) if _gpv.Mass() < 0 else result",
]


def _greeble_layout_cyl(R: float, H: float, g) -> tuple:
    """Greeble layout for a CYLINDER lateral (+R) face → (cuts, rings, raises). The same design as
    `_greeble_layout` but in the cylinder's UNROLLED (arc-length × height) space (greeble-detail-
    research.md: production tools greeble curved faces in the surface's local frame). Cells tile the
    circumference (nθ around) × height (nz up). Detail elements are RADIAL flat boxes — built tangent at
    +X spanning radius [R−depth, R+over], then ROTATED by θ about Z to the cell's angular position; the
    box∩cylinder cut is OCCT's documented fuzzy-boolean case, so build() passes GREEBLE_FUZZY as `tol`.
      • cuts/raises: (theta_deg, corner_xyz, size_xyz) — a box from corner+size, rotated theta about Z.
      • rings: (z0, gd, R) — a ring (horizontal panel-line groove) = annular slab at z0, cut separately.
    Cylinder spans z∈[0,H] (extruded from XY at z=0). RNG draws identically per cell (fixed order) ⇒
    stable layout. Shared by build(), emit_code(), and the verifier so they agree exactly."""
    rng = random.Random(g.seed)
    over, gd = GREEBLE_OVER, g.groove
    circ = 2 * math.pi * R
    nth = max(1, round(circ / g.panel)); nz = max(1, round(H / g.panel))
    max_cells = 48                       # bound the boolean count (each cell → ≤4 cuts), like the box path
    if nth * nz > max_cells:
        f = (nth * nz / max_cells) ** 0.5
        nth = max(1, round(nth / f)); nz = max(1, round(nz / f))
    cell_ang = 2 * math.pi / nth; cell_z = H / nz
    aw = R * cell_ang                                          # nominal arc/tangential width of a cell
    cuts: list = []; rings: list = []; raises: list = []

    def add_recess(th, oy, oz, ww, hh, d):                   # radial recess + (bevel>0) a shallow wider lip
        cuts.append((round(th, 4), (round(R - d, 4), round(oy - ww / 2, 4), round(oz - hh / 2, 4)),
                     (round(d + over, 4), round(ww, 4), round(hh, 4))))
        b = min(g.bevel, g.margin * 0.6, d * 0.8)
        if b > 0:                                            # stepped rim at the +R mouth = machined-edge look
            cuts.append((round(th, 4), (round(R - b, 4), round(oy - ww / 2 - b, 4), round(oz - hh / 2 - b, 4)),
                         (round(b + over, 4), round(ww + 2 * b, 4), round(hh + 2 * b, 4))))

    # vertical grooves (constant θ): thin radial box at each angular grid line, full height
    for i in range(nth):
        th = math.degrees(i * cell_ang)
        cuts.append((round(th, 4), (round(R - gd, 4), round(-gd / 2, 4), 0.0), (round(gd + over, 4), round(gd, 4), round(H, 4))))
    # ring grooves (constant z): annular slab at each height grid line (cut as outer−inner cylinder)
    for j in range(1, nz):
        rings.append((round(j * cell_z - gd / 2, 4), round(gd, 4), round(R, 4)))

    def focal_w(zc):                                          # density weight by height band (non-uniform)
        r = abs(zc - H / 2) / (H / 2) if H else 0.0           # 0 at mid-height → 1 at the ends
        if g.focal == "center":
            return max(0.15, 1.0 - 0.7 * min(1.0, r))         # busier in the middle band
        if g.focal == "edges":
            return max(0.15, 0.3 + 0.7 * min(1.0, r))         # busier near the top/bottom rings
        return 1.0

    for i in range(nth):
        th = math.degrees((i + 0.5) * cell_ang)               # panel centered between two vertical grooves
        for j in range(nz):
            zc = (j + 0.5) * cell_z
            roll = rng.random(); kind = rng.random(); sub = rng.random(); df = 0.6 + 0.4 * rng.random()
            if roll >= g.density * focal_w(zc):
                continue
            w = max(1.0, aw - 2 * g.margin); h = max(1.0, cell_z - 2 * g.margin)   # tangential × vertical
            if kind < g.raised:                               # RAISED panel (additive; protrudes to R+raise_h)
                raises.append((round(th, 4), (round(R - over, 4), round(-w / 2, 4), round(zc - h / 2, 4)),
                               (round(g.raise_h + over, 4), round(w, 4), round(h, 4))))
            elif g.levels >= 2 and sub < g.subdiv:            # SUBDIVIDED: 2×2 finer recesses (hierarchy)
                sm = g.margin * 0.6; sw = max(0.8, (w - sm) / 2); sh = max(0.8, (h - sm) / 2); d = g.depth * df
                for sy in (-1, 1):
                    for sz in (-1, 1):
                        add_recess(th, sy * (sw + sm) / 2, zc + sz * (sh + sm) / 2, sw, sh, d)
            else:                                             # plain RECESSED panel (flat-bottomed pocket)
                add_recess(th, 0.0, zc, w, h, g.depth * df)
    return cuts, rings, raises


def _cyl_ring_cutter(z0: float, gd: float, R: float) -> cq.Solid:
    """A ring (horizontal panel-line groove) cutter: annular slab at z0, radius [R−gd, R+over], thickness
    gd. Built outer−inner so the boolean removes a clean groove around the full circumference."""
    over = GREEBLE_OVER
    outer = cq.Solid.makeCylinder(R + over, gd, cq.Vector(0, 0, z0))
    inner = cq.Solid.makeCylinder(R - gd, gd + 1.0, cq.Vector(0, 0, z0 - 0.5))
    return outer.cut(inner)


def _apply_radial_greeble(r, cuts, rings, raises):
    """Apply a radial greeble layout (cylinder OR revolve — same rotated-box + ring descriptors) to the
    solid. DEFER CLEANING: every op clean=False, then one clean() — a per-op clean under fuzzy tol
    fragments the solid into slivers and a later fuzzy UNION on that compound collapses to empty. Rings
    first (most fragile), then cuts, then raises; pass GREEBLE_FUZZY (near-tangent curved-face booleans)."""
    for z0, gd, Rr in rings:
        r = r.cut(_cyl_ring_cutter(z0, gd, Rr), tol=GREEBLE_FUZZY, clean=False)
    for th, corner, (sx, sy, sz) in cuts:
        r = r.cut(cq.Solid.makeBox(sx, sy, sz, cq.Vector(*corner)).rotate((0, 0, 0), (0, 0, 1), th),
                  tol=GREEBLE_FUZZY, clean=False)
    for th, corner, (sx, sy, sz) in raises:
        r = r.union(cq.Solid.makeBox(sx, sy, sz, cq.Vector(*corner)).rotate((0, 0, 0), (0, 0, 1), th),
                    tol=GREEBLE_FUZZY, clean=False)
    return _ensure_positive(r.clean())


def _radius_at(profile, z: float) -> float:
    """Outer radius of a revolved meridian `profile` ([[r,z],..]) at height z — piecewise-linear over the
    segments that span z, taking the MAX (handles re-entrant meridians). Falls back to the max r."""
    best = None
    for (r0, z0), (r1, z1) in zip(profile, profile[1:]):
        lo, hi = sorted((z0, z1))
        if lo - 1e-9 <= z <= hi + 1e-9 and abs(z1 - z0) > 1e-9:
            ri = r0 + (r1 - r0) * (z - z0) / (z1 - z0)
            best = ri if best is None else max(best, ri)
        elif abs(z1 - z0) <= 1e-9 and abs(z - z0) < 1e-9:
            best = max(r0, r1) if best is None else max(best, r0, r1)
    return best if best is not None else max((r for r, _ in profile), default=0.0)


def _greeble_layout_rev(profile, g) -> tuple:
    """Greeble layout for a REVOLVE body (axis on Z, radius varies with z per `profile`). A turned body is
    a stack of local-radius cylinders, so this reuses the cylinder rotated-box + ring descriptors — but
    each z-band uses its LOCAL radius `_radius_at(zc)` (so cutters follow the taper). Same (cuts, rings,
    raises) format as `_greeble_layout_cyl` ⇒ shares `_apply_radial_greeble`/emit. Stage C."""
    zs = [z for _, z in profile]
    zmin, zmax = min(zs), max(zs); H = zmax - zmin
    Rmax = max(r for r, _ in profile)
    rng = random.Random(g.seed); over, gd = GREEBLE_OVER, g.groove
    circ = 2 * math.pi * Rmax
    nth = max(1, round(circ / g.panel)); nz = max(1, round(H / g.panel)) if H else 1
    max_cells = 48
    if nth * nz > max_cells:
        f = (nth * nz / max_cells) ** 0.5
        nth = max(1, round(nth / f)); nz = max(1, round(nz / f))
    cell_ang = 2 * math.pi / nth; cell_z = H / nz
    cuts: list = []; rings: list = []; raises: list = []

    def add_recess(th, R, oy, oz, ww, hh, d):
        cuts.append((round(th, 4), (round(R - d, 4), round(oy - ww / 2, 4), round(oz - hh / 2, 4)),
                     (round(d + over, 4), round(ww, 4), round(hh, 4))))
        b = min(g.bevel, g.margin * 0.6, d * 0.8)
        if b > 0:
            cuts.append((round(th, 4), (round(R - b, 4), round(oy - ww / 2 - b, 4), round(oz - hh / 2 - b, 4)),
                         (round(b + over, 4), round(ww + 2 * b, 4), round(hh + 2 * b, 4))))

    for j in range(1, nz):                                    # ring grooves at the LOCAL radius per z line
        z = zmin + j * cell_z
        rings.append((round(z - gd / 2, 4), round(gd, 4), round(_radius_at(profile, z), 4)))

    def focal_w(zc):
        rr = abs(zc - (zmin + H / 2)) / (H / 2) if H else 0.0
        if g.focal == "center":
            return max(0.15, 1.0 - 0.7 * min(1.0, rr))
        if g.focal == "edges":
            return max(0.15, 0.3 + 0.7 * min(1.0, rr))
        return 1.0

    for i in range(nth):
        th = math.degrees((i + 0.5) * cell_ang)
        for j in range(nz):
            zc = zmin + (j + 0.5) * cell_z; R = _radius_at(profile, zc)
            roll = rng.random(); kind = rng.random(); sub = rng.random(); df = 0.6 + 0.4 * rng.random()
            if R <= 1.0 or roll >= g.density * focal_w(zc):
                continue
            cuts.append((round(th, 4), (round(R - gd, 4), round(-gd / 2, 4), round(zmin + j * cell_z, 4)),
                         (round(gd + over, 4), round(gd, 4), round(cell_z, 4))))   # vertical groove segment
            w = max(1.0, R * cell_ang - 2 * g.margin); h = max(1.0, cell_z - 2 * g.margin)
            if kind < g.raised:
                raises.append((round(th, 4), (round(R - over, 4), round(-w / 2, 4), round(zc - h / 2, 4)),
                               (round(g.raise_h + over, 4), round(w, 4), round(h, 4))))
            elif g.levels >= 2 and sub < g.subdiv:
                sm = g.margin * 0.6; sw = max(0.8, (w - sm) / 2); sh = max(0.8, (h - sm) / 2); d = g.depth * df
                for sy in (-1, 1):
                    for sz in (-1, 1):
                        add_recess(th, R, sy * (sw + sm) / 2, zc + sz * (sh + sm) / 2, sw, sh, d)
            else:
                add_recess(th, R, 0.0, zc, w, h, g.depth * df)
    return cuts, rings, raises


def _greeble_loft(r, spec, g):
    """Greeble the loft's TOP (+Z-most) face. A ruled loft has PLANAR faces, so reuse the flat box layout
    in that face's own frame: lay cutters in canonical XY (surface at z=0, +z outward), then `.moved` onto
    the face plane. Covers the tapered-bar / engineered-arm look; fuzzy tol + deferred clean. Stage C."""
    face = max(r.val().Faces(), key=lambda f: f.normalAt().z)   # the upward-facing planar face
    n = face.normalAt(); c = face.Center()
    gx = cq.Vector(1, 0, 0)
    u = (gx - n.multiply(gx.dot(n)))
    u = u.normalized() if u.Length > 1e-6 else cq.Vector(0, 1, 0)
    v = n.cross(u)
    pts = [vx.toTuple() for vx in face.Vertices()]
    us = [(cq.Vector(*p) - c).dot(u) for p in pts]; vs = [(cq.Vector(*p) - c).dot(v) for p in pts]
    Lu, Lv = max(us) - min(us), max(vs) - min(vs)
    origin = c + u.multiply((max(us) + min(us)) / 2) + v.multiply((max(vs) + min(vs)) / 2)  # face bbox center
    cuts, raises = _greeble_layout(Lu * 0.94, Lv * 0.94, 10.0, g)   # inset off the slanted face edges
    loc = cq.Plane(origin=origin.toTuple(), xDir=u.toTuple(), normal=n.toTuple()).location
    for corner, (sx, sy, sz) in cuts:
        box = cq.Solid.makeBox(sx, sy, sz, cq.Vector(*corner)).translate(cq.Vector(0, 0, -5.0)).moved(loc)
        r = r.cut(box, tol=GREEBLE_FUZZY, clean=False)
    for corner, (sx, sy, sz) in raises:
        box = cq.Solid.makeBox(sx, sy, sz, cq.Vector(*corner)).translate(cq.Vector(0, 0, -5.0)).moved(loc)
        r = r.union(box, tol=GREEBLE_FUZZY, clean=False)
    return _ensure_positive(r.clean())


def build(spec: Spec) -> cq.Workplane:
    if spec.shape == "box":
        L, W, H = spec.envelope["length"], spec.envelope["width"], spec.envelope["height"]
        draft = next((f for f in spec.features if f.type == "draft"), None)
        if draft is not None:   # molded walls: base L×W at z−, tapered inward to the top (z+)
            r = cq.Workplane("XY").workplane(offset=-H / 2).rect(L, W).extrude(H, taper=draft.angle)
        else:
            r = cq.Workplane("XY").box(L, W, H)  # centered at origin
    elif spec.shape == "loft":
        r = _loft_solid(spec)
    elif spec.shape == "revolve":
        r = _revolve_solid(spec)
    elif spec.shape == "sweep":
        r = _sweep_solid(spec)
    else:
        D, H = spec.envelope["diameter"], spec.envelope["height"]
        r = cq.Workplane("XY").circle(D / 2).extrude(H)

    # Edge-mods first (before cuts change the edge set), but IN THE SPEC'S ORDER so
    # chamfer-then-fillet vs fillet-then-chamfer is faithful (operation-order sensitivity).
    # Each binds to its own selector's edge set (CQ_EDGE), so distinct sets don't conflict.
    # fillet/chamfer are only meaningful on a box's straight edges — a cylinder/loft has none,
    # so we skip them there (a model slip can't corrupt the solid; the verifier agrees, below).
    for f in spec.features:
        if spec.shape != "box":
            break
        if f.type == "fillet":
            r = r.edges(CQ_EDGE.get(f.edges, "|Z")).fillet(f.radius)
        elif f.type == "chamfer":
            r = r.edges(CQ_EDGE.get(f.edges, "|Z")).chamfer(f.distance)
    # variable-radius fillet (box): raw OCCT — the fluent API can't vary the radius along an edge
    vf = next((f for f in spec.features if f.type == "var_fillet"), None)
    if vf is not None and spec.shape == "box":
        mk = BRepFilletAPI_MakeFillet(r.val().wrapped)
        for e in r.edges(CQ_EDGE.get(vf.edges, "|Z")).vals():
            mk.Add(vf.r1, vf.r2, e.wrapped)
        r = cq.Workplane(obj=cq.Shape(mk.Shape()))
    # shell (box): hollow to a thin wall, optionally leaving one face open. Before pockets/holes so
    # those cut through the finished wall.
    sh = next((f for f in spec.features if f.type == "shell"), None)
    if sh is not None and spec.shape == "box":
        if sh.open_face == "none":
            r = r.shell(-sh.thickness)
        else:
            r = r.faces({"top": ">Z", "bottom": "<Z"}[sh.open_face]).shell(-sh.thickness)
    for f in spec.features:
        if f.type == "pocket":
            # centerOption=CenterOfBoundBox ⇒ origin is ALWAYS the face center (absolute), so a
            # later pocket's .center() doesn't accumulate the previous one's offset (the .center trap).
            wp = r.faces(">Z").workplane(centerOption="CenterOfBoundBox")
            if f.at is not None:
                wp = wp.center(f.at[0], f.at[1])
            r = wp.rect(f.length, f.width).cutBlind(-f.depth)
    # greeble — procedural hard-surface detail pass on the top face (Stage A: box). One boolean with a
    # compound of DISJOINT cutters (grooves on the grid + recessed panels inset off them) ⇒ robust.
    g = next((f for f in spec.features if f.type == "greeble"), None)
    if g is not None and spec.shape == "box":
        L_, W_, H_ = spec.envelope["length"], spec.envelope["width"], spec.envelope["height"]
        cuts, raises = _greeble_layout(L_, W_, H_, g)
        # sequential booleans (a Compound cutter yields an invalid/negative-volume solid in OCCT here);
        # disjoint + axis-aligned boxes that overshoot/dip the surface ⇒ each op is clean. Cut then raise.
        for corner, (sx, sy, sz) in cuts:
            r = r.cut(cq.Solid.makeBox(sx, sy, sz, cq.Vector(*corner)))
        for corner, (sx, sy, sz) in raises:
            r = r.union(cq.Solid.makeBox(sx, sy, sz, cq.Vector(*corner)))
    elif g is not None and spec.shape == "cylinder":
        # Stage C: greeble the CYLINDER lateral face. Radial flat-box cutters (built at +X, rotated to θ)
        # + ring grooves — near-tangent to the curved surface (the research's #1 robustness risk); the
        # shared helper applies them with fuzzy tol + deferred clean. Never a Compound cutter.
        cuts, rings, raises = _greeble_layout_cyl(spec.envelope["diameter"] / 2.0, spec.envelope["height"], g)
        r = _apply_radial_greeble(r, cuts, rings, raises)
    elif g is not None and spec.shape == "revolve":
        # Stage C: greeble a REVOLVE (turned body) — a stack of local-radius cylinders, so it reuses the
        # cylinder radial machinery with a per-z-band radius (cutters follow the taper).
        cuts, rings, raises = _greeble_layout_rev(spec.profile or [], g)
        r = _apply_radial_greeble(r, cuts, rings, raises)
    elif g is not None and spec.shape == "loft":
        # Stage C: greeble the loft's top planar face in its own (tilted) frame.
        r = _greeble_loft(r, spec, g)
    # all through-holes (single + patterns + ANY axis) as explicit cylinder cutters
    for px, py, pz, d, axis in expected_holes(spec):
        r = r.cut(_hole_cutter(px, py, pz, d, axis, spec))
    # cosmetic internal thread — a nominal bore (the helix is metadata, not geometry)
    for f in spec.features:
        if f.type == "thread" and f.kind == "internal":
            ax, ay = f.at or (0.0, 0.0)
            r = r.cut(_hole_cutter(ax, ay, 0.0, f.diameter, "z", spec))
    # counterbore / countersink — recessed holes drilled from the top (+Z) face
    for f in spec.features:
        if f.type == "counterbore":
            r = r.faces(">Z").workplane().pushPoints([f.at or (0.0, 0.0)]).cboreHole(f.diameter, f.cbore_diameter, f.cbore_depth)
        elif f.type == "countersink":
            r = r.faces(">Z").workplane().pushPoints([f.at or (0.0, 0.0)]).cskHole(f.diameter, f.csk_diameter, f.csk_angle)
    # mirror LAST — reflect the fully-featured part across the plane and union into one symmetric solid
    mir = next((f for f in spec.features if f.type == "mirror"), None)
    if mir is not None:
        r = r.mirror(mir.plane, union=True)
    return r


_DIR = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _loft_solid(spec: Spec) -> cq.Workplane:
    """A tapered bar lofted along X (centered): base profile (W×H) at −X, tip (Wt×Ht) at +X.
    Built on the YZ plane (its normal = X), so `offset=L` walks along the taper axis; ruled ⇒
    straight (flat-faced) taper, the engineered-arm look. Then centered on the origin like box."""
    L, W, H, Wt, Ht = spec.loft_profiles()
    top = cq.Workplane("YZ").rect(W, H).workplane(offset=L)
    top = top.circle(spec.envelope["diameter_top"] / 2) if spec.loft_top_round() else top.rect(Wt, Ht)
    return cq.Workplane(obj=top.loft(ruled=True).val().translate(cq.Vector(-L / 2, 0, 0)))


def _revolve_solid(spec: Spec) -> cq.Workplane:
    """A turned body: revolve the meridian `profile` (radius, z) about the Z axis by `angle`°.
    Built in XY (x=radius, y=axial) and revolved about the in-plane Y axis (the working idiom —
    revolving about the plane normal is degenerate), then rotated +90° about X so the body stands
    on the Z axis like a cylinder (axial → +Z). `ruled` straight runs ⇒ analytic cylinders/cones."""
    pts = spec.profile or []
    angle = spec.envelope.get("angle", 360.0)
    wp = cq.Workplane("XY").polyline([(r, z) for r, z in pts]).close().revolve(angle, (0, 0, 0), (0, 1, 0))
    solid = wp.val().rotate((0, 0, 0), (1, 0, 0), 90)   # axial (local Y) → global Z
    return cq.Workplane(obj=solid)


def _sweep_solid(spec: Spec) -> cq.Workplane:
    """A round tube: sweep a circle of envelope['diameter'] along the 3D `path` polyline. The path
    wire is assembled from 3D line edges (so non-planar paths work), and the profile sits on a plane
    perpendicular to the first segment so it starts square to the path."""
    pts = [cq.Vector(*p) for p in (spec.path or [])]
    d = spec.envelope["diameter"]
    edges = [cq.Edge.makeLine(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    path_wire = cq.Wire.assembleEdges(edges)
    t0 = (pts[1] - pts[0]).normalized()
    prof = cq.Workplane(cq.Plane(origin=pts[0].toTuple(), normal=t0.toTuple())).circle(d / 2)
    return prof.sweep(cq.Workplane(obj=path_wire), isFrenet=True)


def _axis_extent(spec: Spec, axis: str) -> float:
    """Full part extent along an axis (so the cutter spans the whole part + margin)."""
    if spec.shape == "box":
        return {"x": spec.envelope["length"], "y": spec.envelope["width"], "z": spec.envelope["height"]}[axis]
    if spec.shape == "loft":
        L, W, H, Wt, Ht = spec.loft_profiles()
        return {"x": L, "y": max(W, Wt), "z": max(H, Ht)}[axis]
    if spec.shape == "revolve":
        d, h = spec.revolve_extents()
        return h if axis == "z" else d
    return spec.envelope["height"] if axis == "z" else spec.envelope["diameter"]


def _hole_cutter(px: float, py: float, pz: float, d: float, axis: str, spec: Spec) -> cq.Solid:
    """A through-cylinder along `axis` passing through (px,py,pz), spanning the part + margin.
    Works for any axis (x/y/z), so cross-drilled 'Swiss-cheese' holes are first-class."""
    dx, dy, dz = _DIR[axis]
    half = _axis_extent(spec, axis) / 2 + 1.0
    start = cq.Vector(px - dx * half, py - dy * half, pz - dz * half)
    return cq.Solid.makeCylinder(d / 2, _axis_extent(spec, axis) + 2.0, start, cq.Vector(dx, dy, dz))


def emit_code(spec: Spec) -> str:
    """Spec → CadQuery *source string* that assigns the final solid to `result`
    (the convention the executor/generator use; cf. Zero-to-CAD style, track-a §6).
    Used by the golden/mock generators; the LLM generator emits the same shape.
    """
    L: list[str] = ["import cadquery as cq", f"# {spec.object}"]
    e = spec.envelope
    if spec.shape == "box":
        L.append(f"L, W, H = {e['length']}, {e['width']}, {e['height']}")
        _dr = next((f for f in spec.features if f.type == "draft"), None)
        if _dr is not None:
            L.append(f'result = cq.Workplane("XY").workplane(offset=-H / 2).rect(L, W).extrude(H, taper={_dr.angle})')
        else:
            L.append('result = cq.Workplane("XY").box(L, W, H)')
    elif spec.shape == "loft":
        ln, w, h, wt, ht = spec.loft_profiles()
        _top = f'.circle({spec.envelope["diameter_top"] / 2})' if spec.loft_top_round() else f".rect({wt}, {ht})"
        L.append(f"Ln, W, H = {ln}, {w}, {h}")
        L.append(f'_lf = cq.Workplane("YZ").rect(W, H).workplane(offset=Ln){_top}.loft(ruled=True)')
        L.append("result = cq.Workplane(obj=_lf.val().translate(cq.Vector(-Ln / 2, 0, 0)))")
        L.append("L = Ln")
    elif spec.shape == "revolve":
        ang = spec.envelope.get("angle", 360.0)
        L.append(f"_pts = {[[r, z] for r, z in (spec.profile or [])]}")
        L.append(f'_rv = cq.Workplane("XY").polyline(_pts).close().revolve({ang}, (0, 0, 0), (0, 1, 0))')
        L.append("result = cq.Workplane(obj=_rv.val().rotate((0, 0, 0), (1, 0, 0), 90))")
        L.append(f"L = {spec.revolve_extents()[0]}")
    elif spec.shape == "sweep":
        L.append(f"_pts = [cq.Vector(*p) for p in {[list(p) for p in (spec.path or [])]}]")
        L.append("_edges = [cq.Edge.makeLine(_pts[i], _pts[i+1]) for i in range(len(_pts)-1)]")
        L.append("_path = cq.Wire.assembleEdges(_edges); _t0 = (_pts[1]-_pts[0]).normalized()")
        L.append(f'result = cq.Workplane(cq.Plane(origin=_pts[0].toTuple(), normal=_t0.toTuple())).circle({e["diameter"] / 2}).sweep(cq.Workplane(obj=_path), isFrenet=True)')
        L.append(f"L = {e['diameter']}")
    else:
        L.append(f"D, H = {e['diameter']}, {e['height']}")
        L.append('result = cq.Workplane("XY").circle(D / 2).extrude(H)')
        L.append("L = W = D")
    for f in spec.features:
        if f.type == "fillet":
            L.append(f'result = result.edges("{CQ_EDGE.get(f.edges, "|Z")}").fillet({f.radius})')
        elif f.type == "chamfer":
            L.append(f'result = result.edges("{CQ_EDGE.get(f.edges, "|Z")}").chamfer({f.distance})')
    _vf = next((f for f in spec.features if f.type == "var_fillet"), None)
    if _vf is not None and spec.shape == "box":
        L.insert(0, "from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet")
        L.append(f'_mk = BRepFilletAPI_MakeFillet(result.val().wrapped)')
        L.append(f'for _e in result.edges("{CQ_EDGE.get(_vf.edges, "|Z")}").vals(): _mk.Add({_vf.r1}, {_vf.r2}, _e.wrapped)')
        L.append("result = cq.Workplane(obj=cq.Shape(_mk.Shape()))")
    _sh = next((f for f in spec.features if f.type == "shell"), None)
    if _sh is not None and spec.shape == "box":
        if _sh.open_face == "none":
            L.append(f"result = result.shell(-{_sh.thickness})")
        else:
            L.append(f'result = result.faces("{ {"top": ">Z", "bottom": "<Z"}[_sh.open_face] }").shell(-{_sh.thickness})')
    for f in spec.features:
        if f.type == "pocket":
            _ctr = f".center({f.at[0]}, {f.at[1]})" if f.at is not None else ""
            L.append(f'result = result.faces(">Z").workplane(centerOption="CenterOfBoundBox"){_ctr}'
                     f".rect({f.length}, {f.width}).cutBlind(-{f.depth})")
    _g = next((f for f in spec.features if f.type == "greeble"), None)
    if _g is not None and spec.shape == "box":
        # greeble = grooves + recessed/subdivided panels (cut) and raised panels (union). Emit the
        # precomputed layout literally so the code is self-contained and EXACTLY matches build().
        _cuts, _raises = _greeble_layout(e["length"], e["width"], e["height"], _g)
        L.append(f"_gcuts = {_cuts}")
        L.append(f"_graise = {_raises}")
        L.append("for _c, _s in _gcuts: result = result.cut(cq.Solid.makeBox(_s[0], _s[1], _s[2], cq.Vector(*_c)))")
        L.append("for _c, _s in _graise: result = result.union(cq.Solid.makeBox(_s[0], _s[1], _s[2], cq.Vector(*_c)))")
    elif _g is not None and spec.shape in ("cylinder", "revolve"):
        # cylinder/revolve greeble (Stage C): radial rotated-box cutters + ring grooves, near-tangent ⇒
        # fuzzy tol + deferred clean. Same descriptor format for both (revolve uses per-band radii).
        _ccuts, _crings, _craise = (_greeble_layout_cyl(e["diameter"] / 2.0, e["height"], _g)
                                    if spec.shape == "cylinder" else _greeble_layout_rev(spec.profile or [], _g))
        L.append(f"_gcuts = {_ccuts}")
        L.append(f"_grings = {_crings}")
        L.append(f"_graise = {_craise}")
        L.append(f"_gover, _gtol = {GREEBLE_OVER}, {GREEBLE_FUZZY}")
        # defer cleaning (clean=False per op, clean once at end) — matches build()'s robustness pattern.
        L.append("for _z, _gd, _R in _grings: result = result.cut("
                 "cq.Solid.makeCylinder(_R+_gover,_gd,cq.Vector(0,0,_z)).cut("
                 "cq.Solid.makeCylinder(_R-_gd,_gd+1.0,cq.Vector(0,0,_z-0.5))), tol=_gtol, clean=False)")
        L.append("for _th, _c, _s in _gcuts: result = result.cut("
                 "cq.Solid.makeBox(_s[0], _s[1], _s[2], cq.Vector(*_c)).rotate((0,0,0),(0,0,1),_th), tol=_gtol, clean=False)")
        L.append("for _th, _c, _s in _graise: result = result.union("
                 "cq.Solid.makeBox(_s[0], _s[1], _s[2], cq.Vector(*_c)).rotate((0,0,0),(0,0,1),_th), tol=_gtol, clean=False)")
        L.append("result = result.clean()")
        L.extend(_EMIT_ORIENT_FIX)
    elif _g is not None and spec.shape == "loft":
        # loft greeble (Stage C): box layout placed on the top planar face. Layout sized here (from the
        # built loft's top face); the face frame is RE-DERIVED at runtime from `result` so it stays exact.
        _ls = _loft_solid(spec); _fc = max(_ls.val().Faces(), key=lambda f: f.normalAt().z)
        _nn = _fc.normalAt(); _cc = _fc.Center()
        _ux = cq.Vector(1, 0, 0); _u = (_ux - _nn.multiply(_ux.dot(_nn)))
        _u = _u.normalized() if _u.Length > 1e-6 else cq.Vector(0, 1, 0)
        _vv = _nn.cross(_u); _pp = [q.toTuple() for q in _fc.Vertices()]
        _us = [(cq.Vector(*q) - _cc).dot(_u) for q in _pp]; _vs = [(cq.Vector(*q) - _cc).dot(_vv) for q in _pp]
        _cuts, _raises = _greeble_layout((max(_us) - min(_us)) * 0.94, (max(_vs) - min(_vs)) * 0.94, 10.0, _g)
        L.append(f"_gcuts = {_cuts}"); L.append(f"_graise = {_raises}; _gtol = {GREEBLE_FUZZY}")
        L.append("_f = max(result.val().Faces(), key=lambda f: f.normalAt().z); _n = _f.normalAt(); _c = _f.Center()")
        L.append("_ux = cq.Vector(1,0,0); _u = (_ux - _n.multiply(_ux.dot(_n)))")
        L.append("_u = _u.normalized() if _u.Length > 1e-6 else cq.Vector(0,1,0); _v = _n.cross(_u)")
        L.append("_p = [q.toTuple() for q in _f.Vertices()]")
        L.append("_us = [(cq.Vector(*q)-_c).dot(_u) for q in _p]; _vs = [(cq.Vector(*q)-_c).dot(_v) for q in _p]")
        L.append("_org = _c + _u.multiply((max(_us)+min(_us))/2) + _v.multiply((max(_vs)+min(_vs))/2)")
        L.append("_loc = cq.Plane(origin=_org.toTuple(), xDir=_u.toTuple(), normal=_n.toTuple()).location")
        L.append("for _q, _s in _gcuts: result = result.cut(cq.Solid.makeBox(_s[0],_s[1],_s[2],cq.Vector(*_q))"
                 ".translate(cq.Vector(0,0,-5.0)).moved(_loc), tol=_gtol, clean=False)")
        L.append("for _q, _s in _graise: result = result.union(cq.Solid.makeBox(_s[0],_s[1],_s[2],cq.Vector(*_q))"
                 ".translate(cq.Vector(0,0,-5.0)).moved(_loc), tol=_gtol, clean=False)")
        L.append("result = result.clean()")
        L.extend(_EMIT_ORIENT_FIX)
    for px, py, pz, d, axis in expected_holes(spec):
        dx, dy, dz = _DIR[axis]
        ext = _axis_extent(spec, axis)
        h = round(ext / 2 + 1.0, 4)
        L.append(f'result = result.cut(cq.Solid.makeCylinder({d / 2}, {round(ext + 2.0, 4)}, '
                 f'cq.Vector({round(px - dx * h, 4)}, {round(py - dy * h, 4)}, {round(pz - dz * h, 4)}), '
                 f'cq.Vector({dx}, {dy}, {dz})))')
    for f in spec.features:
        if f.type == "thread" and f.kind == "internal":
            ax, ay = f.at or (0.0, 0.0)
            ext = _axis_extent(spec, "z"); h = round(ext / 2 + 1.0, 4)
            L.append(f'result = result.cut(cq.Solid.makeCylinder({f.diameter / 2}, {round(ext + 2.0, 4)}, '
                     f'cq.Vector({ax}, {ay}, {-h}), cq.Vector(0.0, 0.0, 1.0)))')
    for f in spec.features:
        if f.type == "counterbore":
            L.append(f'result = result.faces(">Z").workplane().pushPoints([{list(f.at or (0.0, 0.0))}])'
                     f'.cboreHole({f.diameter}, {f.cbore_diameter}, {f.cbore_depth})')
        elif f.type == "countersink":
            L.append(f'result = result.faces(">Z").workplane().pushPoints([{list(f.at or (0.0, 0.0))}])'
                     f'.cskHole({f.diameter}, {f.csk_diameter}, {f.csk_angle})')
    _mir = next((f for f in spec.features if f.type == "mirror"), None)
    if _mir is not None:
        L.append(f'result = result.mirror("{_mir.plane}", union=True)')
    return "\n".join(L)
