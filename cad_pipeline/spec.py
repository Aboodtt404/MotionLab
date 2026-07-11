"""Track A — the typed structured spec (the contract).

Both Track-A entry points target this: text→spec and (Track C) image→spec.
The generator builds CadQuery *from* it; the verifier checks the built solid
*against* it, field by field. Kept deliberately small for the L1–L2 scope.
"""
from __future__ import annotations

import math
from typing import Annotated, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field


def profile_extent(pts: List[Tuple[float, float]],
                   arcs: Optional[List[float]] = None) -> Tuple[float, float, float, float]:
    """(umin, umax, vmin, vmax) of a 2D polyline profile whose segment i has sagitta `arcs[i]`
    (mm; 0/absent = straight). An arc bows PAST its chord, so include the perpendicular apex
    (chord midpoint + sagitta along the left normal) AND every circle axis-extreme (center ± R
    along u or v) that falls inside the arc span — a strongly-bulged arc reaches its true extreme
    at an axis point, not the apex. Shared by revolve_extents (u=r, v=z) and profile_extrude."""
    if not pts:
        return 0.0, 0.0, 0.0, 0.0
    us = [u for u, _ in pts]
    vs = [v for _, v in pts]
    for i, s in enumerate(arcs or []):
        if not s or i + 1 >= len(pts):
            continue
        (u1, v1), (u2, v2) = pts[i], pts[i + 1]
        du, dv = u2 - u1, v2 - v1
        ln = math.hypot(du, dv)
        if ln < 1e-9:
            continue
        nu, nv = -dv / ln, du / ln                       # left normal n̂
        au, av = (u1 + u2) / 2 + s * nu, (v1 + v2) / 2 + s * nv   # sagitta apex
        us.append(au)
        vs.append(av)
        half_c = ln / 2.0
        R = (half_c * half_c + s * s) / (2.0 * abs(s))
        cu, cv = au - R * (s / abs(s)) * nu, av - R * (s / abs(s)) * nv   # arc circle center
        th1, th2 = math.atan2(v1 - cv, u1 - cu), math.atan2(v2 - cv, u2 - cu)
        tha = math.atan2(av - cv, au - cu)

        def _dist(a: float, b: float) -> float:
            d = (a - b) % (2 * math.pi)
            return min(d, 2 * math.pi - d)

        span1, span2 = _dist(th1, tha), _dist(th2, tha)
        for th, is_u in ((0.0, True), (math.pi, True), (math.pi / 2, False), (-math.pi / 2, False)):
            if _dist(th, tha) <= max(span1, span2) + 1e-9:
                if is_u:
                    us.append(cu + R * math.cos(th))
                else:
                    vs.append(cv + R * math.sin(th))
    return min(us), max(us), min(vs), max(vs)


def _segments_intersect(a1, a2, b1, b2) -> bool:
    """Do open segments a1a2 and b1b2 properly cross (shared endpoints don't count)?"""
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2 = cross(b1, b2, a1), cross(b1, b2, a2)
    d3, d4 = cross(a1, a2, b1), cross(a1, a2, b2)
    if ((d1 > 1e-9 and d2 < -1e-9) or (d1 < -1e-9 and d2 > 1e-9)) and \
       ((d3 > 1e-9 and d4 < -1e-9) or (d3 < -1e-9 and d4 > 1e-9)):
        return True
    return False


def profile_is_simple(pts: List[Tuple[float, float]],
                      arcs: Optional[List[float]] = None) -> bool:
    """Is the CLOSED profile a simple polygon (non-self-intersecting, ≥3 pts, positive area)?
    Arcs are flattened to a fine polyline first (the representation can't guarantee simplicity —
    it must be CHECKED; docs/research/track-a-silhouette-cutout-wheel.md §1.4). Adjacent segments
    sharing an endpoint are skipped; any other crossing ⇒ not simple."""
    if not pts or len(pts) < 3:
        return False
    poly: List[Tuple[float, float]] = []
    ring = list(pts) + [pts[0]]
    arcs = list(arcs or [])
    for i in range(len(ring) - 1):
        (u1, v1), (u2, v2) = ring[i], ring[i + 1]
        s = arcs[i] if i < len(arcs) else 0.0
        poly.append((u1, v1))
        if s:                                            # tessellate the arc into ~12 chords
            du, dv = u2 - u1, v2 - v1
            ln = math.hypot(du, dv)
            if ln > 1e-9:
                nu, nv = -dv / ln, du / ln
                au, av = (u1 + u2) / 2 + s * nu, (v1 + v2) / 2 + s * nv
                half_c = ln / 2.0
                R = (half_c * half_c + s * s) / (2.0 * abs(s))
                cu, cv = au - R * (s / abs(s)) * nu, av - R * (s / abs(s)) * nv
                th1, th2 = math.atan2(v1 - cv, u1 - cu), math.atan2(v2 - cv, u2 - cu)
                dth = (th2 - th1 + math.pi) % (2 * math.pi) - math.pi   # shortest signed sweep
                for k in range(1, 12):
                    th = th1 + dth * k / 12.0
                    poly.append((cu + R * math.cos(th), cv + R * math.sin(th)))
    n = len(poly)
    if n < 3:
        return False
    area = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    if abs(area) < 1e-6:
        return False                                     # degenerate / zero-area
    for i in range(n):
        a1, a2 = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue                                 # adjacent segments share an endpoint
            b1, b2 = poly[j], poly[(j + 1) % n]
            if _segments_intersect(a1, a2, b1, b2):
                return False
    return True


class ThroughHole(BaseModel):
    type: Literal["through_hole"] = "through_hole"
    diameter: float
    # Position (top-face XY, origin = part center). Precedence: `at` > `from_edge` > centered.
    at: Optional[Tuple[float, float]] = None       # explicit [x, y]
    from_edge: Optional[float] = None              # mm from the -X face (box only); y = 0
    axis: Literal["x", "y", "z"] = "z"


class HolePattern(BaseModel):
    """A set of equal through-holes in a regular arrangement (L2–L3: tests pattern
    reasoning, not just single placement). Expanded to points by `.points()` — the
    builder places them and the verifier re-derives the same expected set."""
    type: Literal["hole_pattern"] = "hole_pattern"
    diameter: float
    pattern: Literal["bolt_circle", "linear_x", "grid"]
    count: int = 4                  # bolt_circle / linear_x: total holes
    pitch_diameter: Optional[float] = None   # bolt_circle: PCD (centered at origin)
    spacing: Optional[float] = None          # linear_x / grid: hole-to-hole spacing
    nx: Optional[int] = None                 # grid: holes in X
    ny: Optional[int] = None                 # grid: holes in Y

    def points(self) -> List[Tuple[float, float]]:
        if self.pattern == "bolt_circle":
            r = (self.pitch_diameter or 0.0) / 2.0
            return [(round(r * math.cos(2 * math.pi * k / self.count), 6),
                     round(r * math.sin(2 * math.pi * k / self.count), 6)) for k in range(self.count)]
        if self.pattern == "linear_x":
            s = self.spacing or 0.0
            return [((k - (self.count - 1) / 2.0) * s, 0.0) for k in range(self.count)]
        # grid (centered): nx × ny at `spacing`
        nx, ny, s = self.nx or 1, self.ny or 1, self.spacing or 0.0
        return [((i - (nx - 1) / 2.0) * s, (j - (ny - 1) / 2.0) * s)
                for i in range(nx) for j in range(ny)]


class Fillet(BaseModel):
    type: Literal["fillet"] = "fillet"
    radius: float
    edges: str = "all_vertical"  # controlled selector (resolved by generator AND verifier)


class Chamfer(BaseModel):
    type: Literal["chamfer"] = "chamfer"
    distance: float
    edges: str = "all_vertical"


class VarFillet(BaseModel):
    """A VARIABLE-radius fillet (frontier — flowing sci-fi-prop blends): the radius sweeps from
    `r1` at one end of each selected edge to `r2` at the other. Box only. Built via raw OCCT (the
    fluent API is constant-radius only); the blend faces are BSplines, so verification is HEURISTIC
    — count + a curvature-sampled radius range, not the exact analytic check the constant fillet gets."""
    type: Literal["var_fillet"] = "var_fillet"
    r1: float
    r2: float
    edges: str = "all_vertical"


class Pocket(BaseModel):
    """A rectangular recess in the top face. With `at` it can be positioned anywhere — several
    positioned pockets give panel insets / panel-line grooves / greeble detail (the hard-surface
    look). Subtractive, so the envelope is unchanged."""
    type: Literal["pocket"] = "pocket"
    length: float
    width: float
    depth: float
    face: str = "top"
    at: Optional[Tuple[float, float]] = None   # top-face XY (origin = face center); None = centered


class CounterboreHole(BaseModel):
    """A counterbored hole (recess for a socket-head screw): a pilot bore of `diameter` with a
    larger flat-bottomed recess (`cbore_diameter` × `cbore_depth`) at the top face. Drilled along
    -Z from the top. BRep signature = two coaxial Z cylinders + an annular shoulder."""
    type: Literal["counterbore"] = "counterbore"
    diameter: float
    cbore_diameter: float
    cbore_depth: float
    at: Optional[Tuple[float, float]] = None   # top-face XY (origin = part center); None = centered


class CountersinkHole(BaseModel):
    """A countersunk hole (recess for a flat-head screw): a pilot bore of `diameter` with a conical
    seat of `csk_diameter` at the top, `csk_angle`° INCLUDED. BRep = pilot cylinder + a cone whose
    semi-angle = csk_angle/2."""
    type: Literal["countersink"] = "countersink"
    diameter: float
    csk_diameter: float
    csk_angle: float = 90.0       # included angle (82/90/100 standard)
    at: Optional[Tuple[float, float]] = None


class Draft(BaseModel):
    """A draft angle on a box's side walls (DFM for molding/casting): the walls tilt inward from
    the base (z−) up to the top (z+) by `angle`°, so the part releases from a mold. Box only — a
    tapered ROUND body is a `revolve` with a slanted profile (a verified cone)."""
    type: Literal["draft"] = "draft"
    angle: float  # degrees


class Shell(BaseModel):
    """Hollow a box to a thin wall of `thickness` (enclosures/housings — the biggest 'looks
    machined' upgrade after solid blocks). `open_face` leaves one face open ('top'=+Z, 'bottom'=−Z)
    or 'none' for a sealed hollow. Box only — a hollow ROUND body (cup/can) is a `revolve` with a
    U-profile. BRep: walls of thickness t separated by a cavity; verified by the min wall gap."""
    type: Literal["shell"] = "shell"
    thickness: float
    open_face: Literal["top", "bottom", "none"] = "top"


class Thread(BaseModel):
    """A COSMETIC thread (the production-standard representation — track-a-vocabulary §3.11): a
    cylindrical bore (internal) or the part's cylindrical surface (external) of nominal `diameter`,
    tagged with the thread callout (`pitch`). Real swept-helix geometry is deferred (needs a thread
    plugin like bd_warehouse; raw-OCCT helix sweeps are fragile). The verifier checks the nominal ⌀
    and records the callout — it does NOT BRep-verify a helix, which is correct: a cosmetic thread
    carries no helical geometry (it's PMI), so there is nothing helical to measure."""
    type: Literal["thread"] = "thread"
    diameter: float
    pitch: float = 1.0
    kind: Literal["internal", "external"] = "internal"
    at: Optional[Tuple[float, float]] = None   # internal bore position (z-axis), None = centered


class Mirror(BaseModel):
    """Make a part SYMMETRIC about a plane through the origin (L/R brackets, clamshells): the built
    part is reflected across `plane` and unioned, so any off-center feature is duplicated to the
    other side. The base shape is centered on the plane (envelope unchanged); the contract the
    verifier checks is symmetry itself — vol(part ∪ mirror(part)) == vol(part)."""
    type: Literal["mirror"] = "mirror"
    plane: Literal["XY", "XZ", "YZ"] = "YZ"


class Greeble(BaseModel):
    """A procedural hard-surface DETAIL PASS on a face (the sci-fi/filmic look): subdivide the face into
    a grid of panels, cut panel-line grooves along the grid, and recess a seeded `density` fraction of
    panels (greeble-detail-research.md). Cosmetic + purely SUBTRACTIVE, so the envelope is unchanged.
    Deterministic via `seed`. Recesses are inset `margin` from the grooves so cutters stay disjoint
    (no near-coincident booleans → robust). Density < 1 gives the non-uniform, focal look ('detail
    everywhere = no detail'). The builder dispatches on `spec.shape` (Stage A/B = box; Stage C = curved/
    tilted bodies): BOX → top (+Z) face; CYLINDER → lateral (+R) face (unrolled arc-length×height grid,
    radial cutters + fuzzy-boolean tol — the research's deferred robustness case); REVOLVE → lateral face
    via per-z-band local radius (cutters follow the taper); LOFT → top planar face in its own tilted
    frame. SWEEP is NOT supported (a bent, varying-frame tube — deferred; greeble is a no-op on a sweep).
    focal `center`→busy mid-height band, `edges`→busy top/bottom rings."""
    type: Literal["greeble"] = "greeble"
    face: Literal["top", "side"] = "top"   # box top (+Z) face; cylinder lateral (+R) face = "side"
    panel: float = 20.0               # nominal panel cell size (mm) — sets the subdivision granularity
    depth: float = 2.0                # recessed-panel depth
    density: float = 0.5              # fraction of panels DETAILED (0..1); <1 ⇒ focal points + rest areas
    groove: float = 1.0               # panel-line groove width AND depth (shallow)
    margin: float = 3.0               # element inset within a cell (keeps detail off the grooves)
    seed: int = 0                     # determinism: same seed ⇒ same layout (builder == emit_code == verifier)
    # --- Stage B: hierarchy + raised panels + focal mask (defaults give the richer "filmic" look) ---
    levels: int = 2                   # 1 = flat cells; ≥2 = some cells subdivide into 2×2 finer sub-recesses
    subdiv: float = 0.35              # fraction of detailed cells that subdivide (when levels≥2)
    raised: float = 0.3               # fraction of detailed cells that RAISE a panel (additive) vs recess
    raise_h: float = 1.5              # raised-panel protrusion off the face (mm) — grows box height / cyl ⌀ by this
    focal: Literal["none", "center", "edges"] = "center"  # density weighting → non-uniform, focal points
    bevel: float = 0.0                # >0 ⇒ a shallow wider STEP around each recess mouth (machined rim look)


Feature = Annotated[
    Union[ThroughHole, HolePattern, Fillet, Chamfer, Pocket, Draft, CounterboreHole, CountersinkHole,
          Mirror, Shell, VarFillet, Thread, Greeble],
    Field(discriminator="type")]


class Spec(BaseModel):
    # `kind` discriminates Spec from SketchExtrude inside a feature-program Step.operand union;
    # defaulted + additive, so every existing Spec(...) call and the planner's schema are unaffected.
    kind: Literal["spec"] = "spec"
    object: str = "part"
    asset_class: Literal["hard_surface"] = "hard_surface"
    fabrication: Literal["render", "fabricate"] = "render"
    shape: Literal["box", "cylinder", "prism", "loft", "revolve", "sweep", "profile_extrude",
                   "loft_sections"]
    # box: length/width/height · cylinder: diameter/height
    # loft (a TAPERED bar — engineered arm/strut): tapers along its length (local X) from a base
    # profile at the −X end to a tip profile at the +X end. envelope = length (taper axis) +
    # width/height (base, wide/hub end) + width_top/height_top (tip, narrow/motor end).
    # revolve (a TURNED body — shaft/hub/nozzle/flange): a meridian `profile` of (radius, z) points
    # spun about the Z axis by `envelope["angle"]`° (default 360). Straight axis-parallel runs become
    # cylinders, tapers become cones, arcs become spheres/tori — all sharing the Z axis.
    # sweep (a TUBE/CHANNEL/spar): a round profile of envelope["diameter"] swept along `path`
    # (3D points), e.g. a coolant line, handle, or curved strut. vol = π·r²·(path length).
    envelope: Dict[str, float] = Field(default_factory=dict)  # box/cylinder/loft dims; revolve uses `profile`
    profile: Optional[List[Tuple[float, float]]] = None  # revolve meridian: [(radius, z), …]
    # Curved meridian segments (continuity vocabulary): profile_arcs[i] is the SAGITTA (mm) of the
    # segment profile[i]→profile[i+1] — 0/absent = straight line, non-zero = a circular arc bowing
    # that far off the chord (sign: + bows toward the chord's LEFT normal walking i→i+1 in the (r,z)
    # plane; for an upward run that's −r, so an OUTWARD barrel bulge is NEGATIVE). Arcs revolve to
    # analytic spheres/tori, so domes/barrels/flares stay exactly verifiable.
    profile_arcs: Optional[List[float]] = None
    path: Optional[List[Tuple[float, float, float]]] = None  # sweep path: [(x, y, z), …]
    # profile_extrude (a SILHOUETTE body — car/fuselage/hull/furniture frame): the SIDE outline in
    # the X–Z plane (hood→windshield→roof→trunk) extruded along Y, optionally INTERSECTED with a
    # PLAN (top-view) outline in the X–Y plane. Each is a closed polyline in the SAME (points +
    # per-segment sagitta) convention as revolve. If plan_profile is absent the body is a plain
    # silhouette extrude of envelope["width"]; if present, the plan trims the width per-station
    # (rounded/narrowed greenhouse & nose). The X axis is SHARED and intersected; docs/research/
    # track-a-silhouette-cutout-wheel.md §1. Built centered on the origin, like box/loft.
    side_profile: Optional[List[Tuple[float, float]]] = None  # (x, z) outline points
    side_arcs: Optional[List[float]] = None                   # sagitta per side segment
    plan_profile: Optional[List[Tuple[float, float]]] = None  # (x, y) top-view outline (optional)
    plan_arcs: Optional[List[float]] = None                   # sagitta per plan segment
    # loft_sections (the HERO body — true double curvature, beyond profile_extrude's prismatic
    # flanks): N cross-section STATIONS along X, each a rounded-rect/ellipse of width×height with
    # its own center height, smoothly lofted (NOT ruled). The loft passes through each station
    # wire EXACTLY, so the verifier slices at the stations (exact) and tessellates only for the
    # between-station overshoot. sections: [{x, width, height, z_center?, kind?}] sorted by x.
    sections: Optional[List[Dict[str, Union[float, str]]]] = None
    # prism (a REGULAR N-GON bar — hex standoff/boss, hex/square nut stock, octagonal housing):
    # a regular `sides`-gon inscribed in envelope["diameter"] (the circumscribed circle, vertex-to-
    # vertex for even N), extruded to envelope["height"]. Straight edges + planar walls, so it reuses
    # the box finishing path (fillet/chamfer on |Z verticals & top/bottom rims, shell, draft, holes).
    sides: int = 6
    features: List[Feature] = Field(default_factory=list)
    tolerance: float = 0.1  # ± mm on directly-specified dimensions
    # DFM gates (advisory; each off at its zero/false default so plain specs are unaffected)
    min_wall: float = 0.0            # min manufacturable wall (mm); 0 = only flag actual overlaps
    min_internal_radius: float = 0.0  # tool radius; sharp internal pocket corners below it are flagged
    max_pocket_aspect: float = 0.0    # max pocket depth / width (tool reach); 0 = off
    draft_required: bool = False      # flag vertical walls (0° draft) for injection molding

    def loft_top_round(self) -> bool:
        """A loft whose tip profile is a CIRCLE (envelope has `diameter_top`) ⇒ a round↔rectangular
        transition/adapter, not just a tapered bar."""
        return "diameter_top" in self.envelope

    def loft_profiles(self) -> Tuple[float, float, float, float, float]:
        """(length, base_width, base_height, tip_width, tip_height) for a loft; tip defaults to
        base (⇒ a plain bar). A round tip (`diameter_top`) reports tip width = height = diameter, so
        the end-face check measures the circle's bbox."""
        e = self.envelope
        w, h = e["width"], e["height"]
        if self.loft_top_round():
            dt = e["diameter_top"]
            return e["length"], w, h, dt, dt
        return e["length"], w, h, e.get("width_top", w), e.get("height_top", h)

    def envelope_dims(self) -> Dict[str, float]:
        """Canonical (x, y, z) extents the bounding box should report."""
        e = self.envelope
        if self.shape == "box":
            return {"length": e["length"], "width": e["width"], "height": e["height"]}
        if self.shape == "loft":
            L, w, h, wt, ht = self.loft_profiles()
            return {"length": L, "width": max(w, wt), "height": max(h, ht)}
        if self.shape == "revolve":
            d, h = self.revolve_extents()
            return {"diameter": d, "height": h}
        if self.shape == "profile_extrude":
            xl, yl, zl = self.profile_extrude_extents()
            return {"length": xl, "width": yl, "height": zl}
        if self.shape == "loft_sections":
            ss = self.sections or []
            if not ss:
                return {"length": 0.0, "width": 0.0, "height": 0.0}
            zs_lo = [s.get("z_center", s["height"] / 2) - s["height"] / 2 for s in ss]
            zs_hi = [s.get("z_center", s["height"] / 2) + s["height"] / 2 for s in ss]
            return {"length": max(s["x"] for s in ss) - min(s["x"] for s in ss),
                    "width": max(s["width"] for s in ss),
                    "height": max(zs_hi) - min(zs_lo)}
        return {"diameter": e["diameter"], "height": e["height"]}

    def profile_extrude_extents(self) -> Tuple[float, float, float]:
        """(x_len, y_len, z_len) of a profile_extrude. X and Z come from the side outline (arc-aware
        via profile_extent). Y (and the X trim) come from the plan outline if present, else from
        envelope['width']. X is the SHARED axis of the two extrudes, so it's the INTERSECTION of the
        two X ranges — a plan narrower than the side in X shortens the body."""
        sx0, sx1, sz0, sz1 = profile_extent(self.side_profile or [], self.side_arcs or [])
        x0, x1, z0, z1 = sx0, sx1, sz0, sz1
        if self.plan_profile:
            px0, px1, py0, py1 = profile_extent(self.plan_profile, self.plan_arcs or [])
            x0, x1 = max(x0, px0), min(x1, px1)          # shared X axis ⇒ intersect
            y0, y1 = py0, py1
        else:
            w = self.envelope.get("width", 0.0)
            y0, y1 = -w / 2.0, w / 2.0
        return (max(0.0, x1 - x0), max(0.0, y1 - y0), max(0.0, z1 - z0))

    def path_length(self) -> float:
        """Total length of the sweep `path` polyline."""
        p = self.path or []
        return sum(sum((p[i + 1][k] - p[i][k]) ** 2 for k in range(3)) ** 0.5 for i in range(len(p) - 1))

    def revolve_extents(self) -> Tuple[float, float]:
        """(diameter, height) of a revolve from its meridian: ⌀ = 2·max(radius), height = z-span.
        Arc-aware (a bulged meridian bows past its chord) via the shared `profile_extent` — u=r,
        v=z; the same math that gives profile_extrude its (x,z) extents."""
        if not self.profile:
            return 0.0, 0.0
        rmin, rmax, zmin, zmax = profile_extent(self.profile, self.profile_arcs or [])
        return (2 * rmax, zmax - zmin)


# Feature ↔ shape compatibility (mirrors the builder's guards — single source of truth).
# BOX_ONLY features are silently SKIPPED by the builder on other shapes, which would make a
# spec/caption lie about geometry that isn't there; FLAT_TOP features sketch on a planar +Z
# face, which loft/revolve/sweep don't have.
BOX_ONLY = frozenset({"fillet", "chamfer", "draft", "shell", "var_fillet", "mirror"})
FLAT_TOP = frozenset({"pocket", "counterbore", "countersink"})


def feature_shape_conflicts(spec: "Spec") -> List[str]:
    """Feature types this spec carries that its shape cannot honestly realize."""
    out: List[str] = []
    has_draft = any(f.type == "draft" for f in spec.features)
    for f in spec.features:
        if f.type in BOX_ONLY and spec.shape != "box":
            out.append(f.type)
        elif f.type in FLAT_TOP and spec.shape not in ("box", "cylinder"):
            out.append(f.type)
        elif f.type == "thread" and getattr(f, "kind", "internal") == "internal" \
                and spec.shape not in ("box", "cylinder"):
            out.append(f.type)
        # an EXTERNAL thread lives on the part's own outer diameter — an M20 thread floating on
        # an ⌀80 axle is unrealizable (and its helical render poisons downstream booleans)
        elif f.type == "thread" and getattr(f, "kind", "internal") == "external" \
                and spec.shape == "cylinder" \
                and abs(getattr(f, "diameter", 0.0) - spec.envelope.get("diameter", 0.0)) > 1.0:
            out.append("thread⌀≠OD")
        # draft tapers the side walls, so the |Z ("all_vertical") edge selectors that fillet/
        # chamfer/var_fillet bind to no longer match anything → "Fillets requires that edges
        # be selected" at build. A drafted part gets its edge character from the taper itself.
        elif has_draft and f.type in ("fillet", "chamfer", "var_fillet"):
            out.append(f"{f.type}+draft")
    return out


def expected_holes(spec: "Spec") -> List[Tuple[float, float, float, float, str]]:
    """Every through-hole as a 3D centerline anchor (px, py, pz, diameter, axis): the point
    the hole axis passes through, with the free (along-axis) coord at the part center.
    `at` is the 2D position in the plane PERPENDICULAR to the axis — z→(x,y), x→(y,z),
    y→(x,z). Single source of truth shared by the builder (drills them) and verifier
    (re-resolves them), so a pattern/axis is specified in exactly one place."""
    out: List[Tuple[float, float, float, float, str]] = []
    L = spec.envelope.get("length", spec.envelope.get("diameter", 0.0))
    for f in spec.features:
        if isinstance(f, ThroughHole):
            ax = f.axis
            if f.at is not None:
                a, b = f.at
                px, py, pz = ({"z": (a, b, 0.0), "x": (0.0, a, b), "y": (a, 0.0, b)})[ax]
            elif f.from_edge is not None and spec.shape == "box" and ax == "z":
                px, py, pz = -L / 2 + f.from_edge, 0.0, 0.0
            else:
                px, py, pz = 0.0, 0.0, 0.0
            out.append((px, py, pz, f.diameter, ax))
        elif isinstance(f, HolePattern):
            out.extend((px, py, 0.0, f.diameter, "z") for px, py in f.points())
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Feature-program part representation (the CSG + sketch-extrude hybrid).
# docs/research/track-a-feature-program-representation.md — a Part is an ORDERED PROGRAM of steps
# executed statefully against a running solid G (the paper's `P := G; [X]`), replacing the flat
# "one primitive + fixed feature menu" model. Each step contributes a body (an OPERAND — reusing
# the full Spec shape vocabulary as the operand builder, so box/cylinder are CSG primitives and
# profile_extrude/revolve/loft_sections are sketched-profile bodies) combined into G by a boolean
# op. A hole is a `cut` with a cylinder; a boss is a `join`; the side∩plan trick is `intersect`.
# ─────────────────────────────────────────────────────────────────────────────────────────────

class SketchLoop(BaseModel):
    """One closed loop of a sketch profile (in the sketch plane's local 2D coords, mm). Either a
    full `circle` (center_u, center_v, radius) or a polyline of `pts` with per-segment modifiers.
    Segment i runs pts[i]→pts[(i+1)%N]; it is a straight LINE by default, an ARC if `arcs[i]` (a
    sagitta, same convention as revolve/profile_extrude), or a SPLINE through `splines[i]` (a list
    of on-curve points ending at the segment's end). `splines` defaults to None → old line/arc
    behaviour (backward compatible). Splines keep a NURBS curve as ONE smooth edge instead of a
    ~24-segment polyline, which otherwise explodes the face count and hangs booleans. `outer` False
    = a hole."""
    kind: Literal["sketch_loop"] = "sketch_loop"
    outer: bool = True
    circle: Optional[Tuple[float, float, float]] = None      # (center_u, center_v, radius)
    pts: Optional[List[Tuple[float, float]]] = None
    arcs: Optional[List[float]] = None
    splines: Optional[List[Optional[List[Tuple[float, float]]]]] = None  # per-segment spline pts


class SketchExtrude(BaseModel):
    """The GENERAL feature-program operand (docs/research/track-a-feature-program-representation.md
    §3.1): a sketch of loops on an ARBITRARY plane, extruded a signed distance. This is what real
    CAD is (Fusion's sketch+extrude) and what fixed-plane `profile_extrude` cannot express (arbitrary
    plane pose). Built already in WORLD coordinates (the plane carries the pose), so its Step's
    `at`/`rotate` are the identity. `symmetric` extrudes ±distance (distance is then the half-extent).
    """
    kind: Literal["sketch_extrude"] = "sketch_extrude"
    plane: List[Tuple[float, float, float]]                  # [origin, x_dir, normal] in world mm
    loops: List[SketchLoop]
    distance: float
    symmetric: bool = False


class Step(BaseModel):
    """One instruction in a part program: build `operand`, place it at `at`/`rotate`, then combine
    it into the running solid G with the boolean `op`. The operand is EITHER a single-primitive
    `Spec` (box/cylinder as CSG primitives; profile_extrude/revolve/loft_sections as sketched
    bodies) OR a general `SketchExtrude` (arbitrary-plane sketch — the native feature-program body).

    - new_body: start G (first step), or add a disjoint lump (later steps; v1 fuses it — most real
      parts are single-body, so we keep one solid rather than a multi-body compound).
    - join: G = G ∪ operand (a boss, rib, flange).
    - cut: G = G − operand (a hole, slot, pocket — the CSG 'carve').
    - intersect: G = G ∩ operand (trim to a silhouette; profile_extrude's side∩plan generalized).
    """
    op: Literal["new_body", "join", "cut", "intersect"] = "new_body"
    operand: Union["Spec", SketchExtrude] = Field(discriminator="kind")
    at: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: Tuple[float, float, float] = (0.0, 0.0, 0.0)


class Part(BaseModel):
    """A part as a program of steps (feature-program representation). The executor (`build_part`)
    folds the steps left-to-right; the verifier measures the resulting solid. A single-primitive
    Spec transpiles to a one-step program via `spec_to_part` — full backward compatibility."""
    object: str = "part"
    asset_class: Literal["hard_surface"] = "hard_surface"
    fabrication: Literal["render", "fabricate"] = "render"
    steps: List[Step] = Field(default_factory=list)
    tolerance: float = 0.1


def spec_to_part(spec: "Spec") -> Part:
    """Transpile a single-primitive Spec into a one-step program — the backward-compat bridge.
    The operand carries the spec's own features (holes/fillets/…), which the builder still applies,
    so `build_part(spec_to_part(spec))` is geometrically identical to `build(spec)`."""
    return Part(object=spec.object, asset_class=spec.asset_class, fabrication=spec.fabrication,
                tolerance=spec.tolerance,
                steps=[Step(op="new_body", operand=spec)])
