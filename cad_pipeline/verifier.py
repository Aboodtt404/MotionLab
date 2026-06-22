"""Track A — the deterministic feature-level verifier (the differentiator, §8).

Measures a *built* solid against the spec via exact OCP/BRep introspection — never
a bounding box alone, never a tessellation, never a learned check. Returns a
structured diff: per dimension/feature  expected · measured · Δ · within-tol · category.

What it now catches (§3 — the three independent failure modes):
  • validity   — watertight/manifold (BRepCheck), single solid, positive volume
  • transcription — envelope, hole ⌀ + POSITION, fillet r, chamfer d, pocket depth/footprint
  • shape/placement (RESOLVE-TWICE, core IP) — a selector predicate ("all_vertical
    edges") is re-resolved against the BRep: the fillet/chamfer must land on exactly
    the right oriented edge SET (count + orientation), else selector-binding failure.
    This is what makes "right radius, wrong edges" / "hole in the wrong corner" caught.

Failure categories (route the §9 retry): ok · dimensional · selector-binding · missing_feature.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, List, Optional

import cadquery as cq
from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.GeomAbs import (GeomAbs_BSplineSurface, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane,
                         GeomAbs_Sphere, GeomAbs_SurfaceOfRevolution, GeomAbs_Torus)
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from .selectors import expected_edge_count, resolve
from .spec import Spec, expected_holes

_AXIS_EPS = 0.9   # |component| above this ⇒ axis-aligned along that axis


# ----------------------------------------------------------------------------- helpers
def _to_shape(obj):
    # accept `result` as a Workplane, a cq.Shape (Solid/Compound/Shell — what the .rotate()/.val()
    # idiom yields, which our own revolve/sweep/loft builders and the model both produce), or a raw
    # TopoDS shape. Requiring a Workplane was a brittle assumption that failed correct geometry.
    if isinstance(obj, cq.Workplane):
        return obj.val().wrapped
    return obj.wrapped if hasattr(obj, "wrapped") else obj


def _label(x: float, y: float, z: float) -> str:
    ax, ay, az = abs(x), abs(y), abs(z)
    if az >= _AXIS_EPS:
        return "z"
    if ax >= _AXIS_EPS:
        return "x"
    if ay >= _AXIS_EPS:
        return "y"
    return "diagonal"


def _optimal_bbox(shape):
    bb = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bb, False, False)  # geometry-exact, tessellation-independent (§8)
    return bb.Get()  # xmin,ymin,zmin,xmax,ymax,zmax


# ----------------------------------------------------------------------------- raw measurement
@dataclass
class Cyl:
    r: float
    axis: str       # x | y | z | diagonal
    x: float; y: float; z: float


@dataclass
class Plane:
    normal: str     # x | y | z | diagonal
    z: float        # location z (for pocket-floor detection)
    nz: float       # signed normal z (distinguishes up-facing floor from down-facing base)
    face: Any       # kept for on-demand face bbox


@dataclass
class Cone:
    semi: float     # semi-angle (degrees) — countersink seat, drafted cylinder; included = 2·semi
    axis: str       # x | y | z | diagonal
    x: float; y: float; z: float


@dataclass
class Measured:
    dx: float; dy: float; dz: float
    valid: bool; solids: int; volume: float
    cyls: List[Cyl] = field(default_factory=list)
    planes: List[Plane] = field(default_factory=list)
    cones: List[Cone] = field(default_factory=list)


def measure(solid) -> Measured:
    shape = _to_shape(solid)
    xmin, ymin, zmin, xmax, ymax, zmax = _optimal_bbox(shape)
    valid = bool(BRepCheck_Analyzer(shape).IsValid())
    props = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, props)

    sx = TopExp_Explorer(shape, TopAbs_SOLID); solids = 0
    while sx.More():
        solids += 1; sx.Next()

    cyls: List[Cyl] = []; planes: List[Plane] = []; cones: List[Cone] = []
    fx = TopExp_Explorer(shape, TopAbs_FACE)
    while fx.More():
        face = TopoDS.Face_s(fx.Current())
        surf = BRepAdaptor_Surface(face); t = surf.GetType()
        if t == GeomAbs_Cylinder:
            cy = surf.Cylinder(); d = cy.Axis().Direction(); loc = cy.Axis().Location()
            cyls.append(Cyl(round(cy.Radius(), 4), _label(d.X(), d.Y(), d.Z()), round(loc.X(), 4), round(loc.Y(), 4), round(loc.Z(), 4)))
        elif t == GeomAbs_Cone:
            co = surf.Cone(); d = co.Axis().Direction(); loc = co.Axis().Location()
            cones.append(Cone(round(math.degrees(abs(co.SemiAngle())), 4), _label(d.X(), d.Y(), d.Z()),
                              round(loc.X(), 4), round(loc.Y(), 4), round(loc.Z(), 4)))
        elif t == GeomAbs_Plane:
            pl = surf.Plane(); n = pl.Axis().Direction(); loc = pl.Location()
            # the plane's intrinsic normal ignores which side is material; flip by the
            # face's topological orientation to get the true OUTWARD normal (so a pocket
            # floor (+Z) is distinguished from the part's base face (−Z)).
            sign = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
            # nz kept to 6 dp (not 4): draft angle = asin(|nz|), and 4 dp rounds a 5° draft to ~5.003°
            planes.append(Plane(_label(n.X(), n.Y(), n.Z()), round(loc.Z(), 4), round(n.Z() * sign, 6), face))
        fx.Next()

    return Measured(round(xmax - xmin, 4), round(ymax - ymin, 4), round(zmax - zmin, 4),
                    valid, solids, round(float(props.Mass()), 2), cyls, planes, cones)


# ----------------------------------------------------------------------------- report types
@dataclass
class Row:
    name: str
    expected: Any
    measured: Any
    within_tol: bool
    category: str  # ok | dimensional | selector-binding | missing_feature

    @property
    def delta(self):
        if isinstance(self.measured, (int, float)) and isinstance(self.expected, (int, float)):
            return round(self.measured - self.expected, 4)
        return None


@dataclass
class Report:
    valid: bool; solids: int; volume: float
    rows: List[Row] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.valid and self.solids == 1 and self.volume > 0 and all(r.within_tol for r in self.rows)

    def failure_categories(self) -> List[str]:
        cats = sorted({r.category for r in self.rows if r.category != "ok"})
        if not self.valid:
            cats = ["validity"] + cats
        return cats

    def to_dict(self) -> dict:
        return {
            "valid": self.valid, "solids": self.solids, "volume": self.volume,
            "passed": self.passed, "failure_categories": self.failure_categories(),
            "rows": [{"name": r.name, "expected": r.expected, "measured": r.measured,
                      "delta": r.delta, "within_tol": r.within_tol, "category": r.category} for r in self.rows],
        }


# ----------------------------------------------------------------------------- verify
def _pop_nearest(target: float, pool: List[Cyl], window: float, axis: Optional[str] = None) -> Optional[Cyl]:
    best, bestd = None, window
    for c in pool:
        if axis and c.axis != axis:
            continue
        d = abs(c.r - target)
        if d <= bestd:
            best, bestd = c, d
    if best is not None:
        pool.remove(best)
    return best


def _fillet_matches(axis: str, zloc: float, r: float, dz: float, selector: str) -> bool:
    """Does a fillet cylinder belong to the selector's set? vertical ⇒ axis Z; top/bottom ⇒ a
    horizontal-axis fillet nearest the upper/lower face. A rim fillet's axis sits at z=±dz/2∓r,
    so we classify by which face-center it's NEAREST — robust even when r>dz/2 (a large fillet
    pushes a TOP cylinder's center below z=0, which a raw z-sign test would misread as bottom)."""
    kind, loc = resolve(selector)
    if kind == "vertical":
        return axis == "z"
    if axis not in ("x", "y"):
        return False
    top_c, bot_c = dz / 2 - r, -dz / 2 + r
    nearest_top = abs(zloc - top_c) <= abs(zloc - bot_c)
    if loc == "top":
        return nearest_top
    if loc == "bottom":
        return not nearest_top
    return True


def _chamfer_matches(nz: float, zloc: float, dz: float, selector: str) -> bool:
    """Does a chamfer bevel belong to the selector's set? Use the normal MAGNITUDE |nz|
    (reliable) to tell a vertical-edge bevel (normal ~horizontal, |nz|≈0) from a rim bevel
    (tilted, |nz|≈0.7); then split rim bevels top vs bottom by Z-LOCATION (the bevel sits
    near the top/bottom face). The normal SIGN is NOT used — OCP flips it inconsistently."""
    kind, loc = resolve(selector)
    is_rim = abs(nz) >= 0.3
    if kind == "vertical":
        return not is_rim
    if not is_rim:
        return False
    band = 0.15 * dz
    if loc == "top":
        return zloc > band
    if loc == "bottom":
        return zloc < -band
    return True   # any rim


def _clearances(placed: List[tuple], shape: str, dx: float, dy: float) -> List[tuple]:
    """Material clearances around the measured holes: hole↔hole edge gap and hole↔boundary
    wall. Negative ⇒ features overlap/merge (degenerate); small positive ⇒ thin wall (DFM).
    One check catches both the silent-merge blind spot and the min-wall DFM rule."""
    cl: List[tuple] = []
    for i in range(len(placed)):
        xi, yi, ri = placed[i]
        for j in range(i + 1, len(placed)):
            xj, yj, rj = placed[j]
            d = ((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5
            cl.append(("hole↔hole", d - ri - rj))
        if shape == "box":
            cl.append(("hole↔edge", min(dx / 2 - abs(xi), dy / 2 - abs(yi)) - ri))
        else:
            od = max(dx, dy) / 2
            cl.append(("hole↔wall", od - ((xi * xi + yi * yi) ** 0.5 + ri)))
    return cl


def _perp(x: float, y: float, z: float, axis: str) -> tuple:
    """The two coordinates in the plane PERPENDICULAR to a hole's axis (where its position
    actually lives): z-hole → (x,y), x-hole → (y,z), y-hole → (x,z)."""
    return {"z": (x, y), "x": (y, z), "y": (x, z)}[axis]


def _pop_hole_fragments(px: float, py: float, pz: float, r_target: float, pool: List[Cyl],
                        window: float, axis: str) -> List[Cyl]:
    """Pop ALL radius+axis-compatible cylinders at an expected hole's perpendicular position.
    A through-hole that's intersected by another hole has its cylindrical wall SPLIT into
    several coaxial fragments (same axis/radius/position) — they're all one hole, so collect
    them together rather than leaving the extras to read as 'unexpected cylinders'."""
    eu, ev = _perp(px, py, pz, axis)
    frags = []
    for c in pool:
        if c.axis != axis or abs(c.r - r_target) > window:
            continue
        cu, cv = _perp(c.x, c.y, c.z, axis)
        if ((cu - eu) ** 2 + (cv - ev) ** 2) ** 0.5 <= window:
            frags.append(c)
    for c in frags:
        pool.remove(c)
    return frags


def _face_cx(face) -> float:
    b = _optimal_bbox(face)
    return (b[0] + b[3]) / 2.0


def _verify_taper(m: "Measured", w: float, h: float, wt: float, ht: float, dim) -> None:
    """Measure a loft's two end faces (normal ∥ X): the −X face = base (w×h), the +X face = tip
    (wt×ht). This is the resolve-twice idea applied to a taper — the bounding box can't tell a
    real taper from a straight bar, so we read the actual cross-section at each end."""
    xfaces = [p for p in m.planes if p.normal == "x"]
    if len(xfaces) < 2:
        dim("loft · taper", 1.0, None)  # no two end faces ⇒ taper missing/degenerate
        return
    base = min(xfaces, key=lambda p: _face_cx(p.face))
    tip = max(xfaces, key=lambda p: _face_cx(p.face))
    bb = _optimal_bbox(base.face)
    dim("loft · base width", w, bb[4] - bb[1])
    dim("loft · base height", h, bb[5] - bb[2])
    tb = _optimal_bbox(tip.face)
    dim("loft · tip width", wt, tb[4] - tb[1])
    dim("loft · tip height", ht, tb[5] - tb[2])


_AXISYM = (GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Torus, GeomAbs_SurfaceOfRevolution)


def _surface_axis(surf, t):
    """Axis (gp_Ax1) of an axisymmetric face, whatever its concrete type."""
    if t == GeomAbs_Cylinder:
        return surf.Cylinder().Axis()
    if t == GeomAbs_Cone:
        return surf.Cone().Axis()
    if t == GeomAbs_Torus:
        return surf.Torus().Axis()
    return surf.AxeOfRevolution()  # GeomAbs_SurfaceOfRevolution


def _verify_revolve(solid, spec: Spec, tol: float) -> List[Row]:
    """A revolve is checked three ways (§ track-a-vocabulary 3.1):
      • envelope   — ⌀ = 2·max(radius), height = z-span of the meridian.
      • axisymmetry — EVERY curved face shares the Z axis (a cylinder/cone/torus/surf-of-revolution
        whose axis isn't Z, or an off-axis sphere, means it wasn't turned about the right axis).
      • full/partial — a full 360° turn has NO seam-cap planes (planes whose normal ⟂ Z); a partial
        turn has exactly 2 (the planes that contain the axis). This is what tells a wedge from a disc."""
    shape = _to_shape(solid)
    rows: List[Row] = []
    xmin, ymin, zmin, xmax, ymax, zmax = _optimal_bbox(shape)
    exp_d, exp_h = spec.revolve_extents()
    ok_d = abs(max(xmax - xmin, ymax - ymin) - exp_d) <= tol + 1e-9
    rows.append(Row("envelope · ⌀", exp_d, round(max(xmax - xmin, ymax - ymin), 4), ok_d, "ok" if ok_d else "dimensional"))
    ok_h = abs((zmax - zmin) - exp_h) <= tol + 1e-9
    rows.append(Row("envelope · height", exp_h, round(zmax - zmin, 4), ok_h, "ok" if ok_h else "dimensional"))

    off_axis, seam_caps, lateral = 0, 0, 0
    fx = TopExp_Explorer(shape, TopAbs_FACE)
    while fx.More():
        face = TopoDS.Face_s(fx.Current())
        surf = BRepAdaptor_Surface(face); t = surf.GetType()
        if t in _AXISYM:
            lateral += 1
            ax = _surface_axis(surf, t); d = ax.Direction(); loc = ax.Location()
            if abs(d.Z()) < 0.99 or (loc.X() ** 2 + loc.Y() ** 2) ** 0.5 > tol + 1e-6:
                off_axis += 1
        elif t == GeomAbs_Sphere:
            lateral += 1
            c = surf.Sphere().Position().Location()
            if (c.X() ** 2 + c.Y() ** 2) ** 0.5 > tol + 1e-6:
                off_axis += 1
        elif t == GeomAbs_Plane:
            if abs(surf.Plane().Axis().Direction().Z()) < 0.5:   # normal ⟂ Z ⇒ a seam cap
                seam_caps += 1
        fx.Next()

    axisym_ok = off_axis == 0 and lateral > 0
    rows.append(Row("revolve · axisymmetry (faces share Z)", 0, off_axis, axisym_ok,
                    "ok" if axisym_ok else "selector-binding"))
    # full 360° turn ⇒ NO seam caps; a partial turn ⇒ ≥1 plane containing the axis (the count
    # varies — a 180° turn of an axis-touching profile merges its two coplanar caps into one).
    angle = spec.envelope.get("angle", 360.0)
    if angle >= 359.0:
        caps_ok = seam_caps == 0
        rows.append(Row("revolve · full (no seam caps)", 0, seam_caps, caps_ok, "ok" if caps_ok else "selector-binding"))
    else:
        caps_ok = seam_caps >= 1
        rows.append(Row("revolve · partial (seam caps)", "≥1", seam_caps, caps_ok, "ok" if caps_ok else "selector-binding"))
    return rows


def _var_fillet_blends(solid):
    """For a variable-radius fillet: the blend faces are BSplines (variable radius can't be analytic).
    Returns (count, min_radius, max_radius) sampling each blend's principal curvature (r = 1/κ). The
    radius sweeps r1→r2 along the edge, so the range ≈ [min(r1,r2), max(r1,r2)]. Heuristic, not exact."""
    shape = _to_shape(solid)
    radii = []
    n = 0
    fx = TopExp_Explorer(shape, TopAbs_FACE)
    while fx.More():
        face = TopoDS.Face_s(fx.Current()); surf = BRepAdaptor_Surface(face)
        if surf.GetType() == GeomAbs_BSplineSurface:
            n += 1
            u0, u1, v0, v1 = surf.FirstUParameter(), surf.LastUParameter(), surf.FirstVParameter(), surf.LastVParameter()
            for i in range(5):
                for j in range(3):
                    p = BRepLProp_SLProps(surf, u0 + (u1 - u0) * i / 4, v0 + (v1 - v0) * j / 2, 2, 1e-6)
                    if p.IsCurvatureDefined():
                        k = max(abs(p.MaxCurvature()), abs(p.MinCurvature()))
                        if k > 1e-9:
                            radii.append(1.0 / k)
        fx.Next()
    return (n, min(radii), max(radii)) if radii else (n, None, None)


def _shell_wall_thickness(solid) -> Optional[float]:
    """Minimum gap between two antiparallel axis-aligned planar faces = the thinnest wall. For a
    shelled box this is the wall thickness t; for a solid box it's the smallest outer dimension
    (≫ t), so a 'not actually hollowed' part is caught. Works for open AND closed shells (unlike the
    1-vs-2-shell count, which differs between them)."""
    shape = _to_shape(solid)
    faces = []   # (axis 0/1/2, normal_is_positive, centroid_along_axis)
    fx = TopExp_Explorer(shape, TopAbs_FACE)
    while fx.More():
        face = TopoDS.Face_s(fx.Current()); surf = BRepAdaptor_Surface(face)
        if surf.GetType() == GeomAbs_Plane:
            n = surf.Plane().Axis().Direction()
            sign = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
            comps = [n.X() * sign, n.Y() * sign, n.Z() * sign]
            ax = max(range(3), key=lambda i: abs(comps[i]))
            if abs(comps[ax]) >= 0.99:   # axis-aligned wall only
                b = _optimal_bbox(face)
                cen = [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2][ax]
                faces.append((ax, comps[ax] > 0, cen))
        fx.Next()
    best = None
    for ax in (0, 1, 2):
        plus = [c for (a, s, c) in faces if a == ax and s]
        minus = [c for (a, s, c) in faces if a == ax and not s]
        for cp in plus:
            for cm in minus:
                g = cp - cm
                if g > 1e-6 and (best is None or g < best):
                    best = g
    return best


def _pop_cyl_at(pool: List[Cyl], r_target: float, x: float, y: float, window: float) -> Optional[Cyl]:
    """Pop the Z-axis cylinder of radius ≈ r_target nearest the XY point (x, y) — the pilot/recess
    bore of a counterbore/countersink lives on the Z axis through its placement."""
    best, bestd = None, window
    for c in pool:
        if c.axis != "z" or abs(c.r - r_target) > window:
            continue
        d = ((c.x - x) ** 2 + (c.y - y) ** 2) ** 0.5
        if d <= bestd:
            best, bestd = c, d
    if best is not None:
        pool.remove(best)
    return best


def _nearest_cone(cones: List[Cone], x: float, y: float, window: float) -> Optional[Cone]:
    cands = [c for c in cones if c.axis == "z" and ((c.x - x) ** 2 + (c.y - y) ** 2) ** 0.5 <= window]
    return min(cands, key=lambda c: (c.x - x) ** 2 + (c.y - y) ** 2) if cands else None


def verify(solid, spec: Spec) -> Report:
    m = measure(solid)
    tol = spec.tolerance
    window = max(0.75, tol * 5)
    rows: List[Row] = []

    # revolve has its own (axisymmetric) verification — the prismatic hole/fillet/leftover logic
    # below assumes box/cylinder topology and would mis-flag a turned body's walls as "unexpected".
    if spec.shape == "revolve":
        return Report(m.valid, m.solids, m.volume, _verify_revolve(solid, spec, tol))
    if spec.shape == "sweep":
        # a constant round section swept along the path ⇒ vol = π·r²·(path length). Back-compute the
        # effective ⌀ from the measured volume (a small number that measures exactly), so a wrong-bore
        # tube or a non-tube is caught. Validity/single-solid come from Report.passed.
        d, length = spec.envelope.get("diameter", 0.0), spec.path_length()
        d_meas = 2.0 * (m.volume / (math.pi * length)) ** 0.5 if length > 0 and m.volume > 0 else None
        rows.append(Row("sweep · profile ⌀ (from volume)", d, round(d_meas, 4) if d_meas else None,
                        d_meas is not None and abs(d_meas - d) <= tol, "ok" if (d_meas is not None and abs(d_meas - d) <= tol) else "dimensional"))
        return Report(m.valid, m.solids, m.volume, rows)

    def dim(name, exp, meas, cat_fail="dimensional"):
        if meas is None:
            rows.append(Row(name, exp, None, False, "missing_feature"))
        else:
            ok = abs(meas - exp) <= tol + 1e-9
            rows.append(Row(name, exp, round(meas, 4), ok, "ok" if ok else cat_fail))

    # envelope ---------------------------------------------------------------
    e = spec.envelope
    if spec.shape == "box":
        dim("envelope · length", e["length"], m.dx)
        dim("envelope · width", e["width"], m.dy)
        dim("envelope · height", e["height"], m.dz)
    elif spec.shape == "loft":
        ln, w, h, wt, ht = spec.loft_profiles()
        dim("envelope · length", ln, m.dx)
        dim("envelope · width (max)", max(w, wt), m.dy)
        dim("envelope · height (max)", max(h, ht), m.dz)
        # the taper itself: the −X end face must measure the base profile, the +X end the tip
        # (a plain bar that ignored the taper fails here — bbox alone can't see it).
        _verify_taper(m, w, h, wt, ht, dim)
    else:
        dim("envelope · ⌀", e["diameter"], max(m.dx, m.dy))
        dim("envelope · height", e["height"], m.dz)

    # mirror — verify SYMMETRY about the plane: vol(part ∪ reflect(part)) == vol(part). A part that
    # ignored the mirror (still asymmetric) makes the union bigger. Returns early — the mirror
    # duplicates features, which the per-feature inventory below doesn't model (symmetry is the check).
    mir = next((f for f in spec.features if f.type == "mirror"), None)
    if mir is not None:
        base = solid.val() if isinstance(solid, cq.Workplane) else solid
        v0 = base.Volume()
        vu = base.fuse(base.mirror(mir.plane)).Volume()
        sym_ok = abs(vu - v0) <= max(1e-6, 0.01 * v0)
        rows.append(Row(f"mirror · symmetric ({mir.plane})", 0.0, round(vu - v0, 3), sym_ok,
                        "ok" if sym_ok else "selector-binding"))
        return Report(m.valid, m.solids, m.volume, rows)

    pool = list(m.cyls)
    # drop the envelope's own outer wall for a cylinder part (it's not a feature)
    if spec.shape == "cylinder":
        _pop_nearest(e["diameter"] / 2, pool, window, axis="z")

    # holes — count + ⌀ + POSITION, matched per-hole by nearest position (multi-hole /
    # patterns; catches "wrong corner", missing/extra holes, mis-placed pattern), §3 ----
    exp_holes = expected_holes(spec)
    placed: List[tuple] = []   # (x, y, r) of the MEASURED holes — for clearance/DFM checks
    if exp_holes:
        matched = 0
        worst_off = 0.0
        worst_dia_off = 0.0
        for (px, py, pz, d, axis) in exp_holes:
            frags = _pop_hole_fragments(px, py, pz, d / 2, pool, window, axis)
            if not frags:
                continue
            matched += 1
            c = min(frags, key=lambda c: abs(2 * c.r - d))   # representative fragment
            if axis == "z":
                placed.append((c.x, c.y, c.r))   # clearance/DFM checks are XY-plane (z-holes)
            cu, cv = _perp(c.x, c.y, c.z, axis)
            eu, ev = _perp(px, py, pz, axis)
            worst_off = max(worst_off, ((cu - eu) ** 2 + (cv - ev) ** 2) ** 0.5)
            worst_dia_off = max(worst_dia_off, abs(2 * c.r - d))
        n = len(exp_holes)
        cnt_ok = matched == n
        rows.append(Row("holes · count", n, matched, cnt_ok, "ok" if cnt_ok else "missing_feature"))
        if matched:
            dia_ok = worst_dia_off <= tol + 1e-9
            rows.append(Row("holes · ⌀ (worst)", 0.0, round(worst_dia_off, 4), dia_ok, "ok" if dia_ok else "dimensional"))
            pos_ok = worst_off <= tol + 1e-9
            rows.append(Row("holes · position (worst)", 0.0, round(worst_off, 4), pos_ok, "ok" if pos_ok else "selector-binding"))

    # counterbore / countersink — recessed top-face holes (§3.3). Pop their cylinders from the pool
    # (so they aren't read as "unexpected") and check pilot ⌀ + recess ⌀ / cone included angle. ----
    for f in spec.features:
        if f.type == "counterbore":
            ax, ay = f.at or (0.0, 0.0)
            recess = _pop_cyl_at(pool, f.cbore_diameter / 2, ax, ay, window)
            pilot = _pop_cyl_at(pool, f.diameter / 2, ax, ay, window)
            dim("counterbore · pilot ⌀", f.diameter, 2 * pilot.r if pilot else None)
            dim("counterbore · cbore ⌀", f.cbore_diameter, 2 * recess.r if recess else None)
        elif f.type == "countersink":
            ax, ay = f.at or (0.0, 0.0)
            pilot = _pop_cyl_at(pool, f.diameter / 2, ax, ay, window)
            cone = _nearest_cone(m.cones, ax, ay, window)
            dim("countersink · pilot ⌀", f.diameter, 2 * pilot.r if pilot else None)
            dim("countersink · included°", f.csk_angle, 2 * cone.semi if cone else None)

    # cosmetic threads — verify the NOMINAL ⌀ (bore for internal, part cylinder for external) and
    # record the callout. The helix is PMI metadata, not geometry, so there's nothing helical to
    # measure (research §3.11) — this is the honest scope of a cosmetic thread. ----
    for f in spec.features:
        if f.type != "thread":
            continue
        callout = f"M{f.diameter:g}×{f.pitch:g} {f.kind}"
        if f.kind == "internal":
            ax, ay = f.at or (0.0, 0.0)
            bore = _pop_cyl_at(pool, f.diameter / 2, ax, ay, window)
            dim(f"thread · ⌀ ({callout}, cosmetic)", f.diameter, 2 * bore.r if bore else None)
        else:
            dim(f"thread · ⌀ ({callout}, cosmetic)", f.diameter, max(m.dx, m.dy))

    # clearance — integrity (overlap) + DFM (min wall), measured from the real holes (§ stress) -
    clears = _clearances(placed, spec.shape, m.dx, m.dy)
    if clears:
        worst_label, worst_clear = min(clears, key=lambda lc: lc[1])
        if worst_clear < -tol:   # features overlap/merge → degenerate (silent-pass guard)
            rows.append(Row(f"feature integrity ({worst_label})", "> 0", round(worst_clear, 4), False, "integrity"))
        elif spec.min_wall > 0:  # DFM: thinnest wall vs the required minimum
            wall_ok = worst_clear >= spec.min_wall - 1e-9
            rows.append(Row(f"dfm · min wall ({worst_label})", spec.min_wall, round(worst_clear, 4), wall_ok, "ok" if wall_ok else "dfm"))

    # DFM gates — advisory, enabled per-spec; measured from geometry/features where possible -----
    pockets = [f for f in spec.features if f.type == "pocket"]
    if spec.max_pocket_aspect > 0:   # tool reach: a deep narrow pocket exceeds tool length:dia
        for f in pockets:
            aspect = f.depth / max(1e-6, min(f.length, f.width))
            ok = aspect <= spec.max_pocket_aspect + 1e-9
            rows.append(Row("dfm · pocket aspect (tool reach)", spec.max_pocket_aspect, round(aspect, 3), ok, "ok" if ok else "dfm"))
    if spec.min_internal_radius > 0 and pockets:   # rect pockets have sharp (r≈0) internal corners
        rows.append(Row("dfm · internal corner radius", spec.min_internal_radius, 0.0, False, "dfm"))
    if spec.draft_required:   # molding: vertical side walls have 0° draft (normal in the XY plane)
        walls = sum(1 for p in m.planes if p.normal in ("x", "y"))
        ok = walls == 0
        rows.append(Row("dfm · draft (vertical walls @ 0°)", 0, walls, ok, "ok" if ok else "dfm"))
        side = sum(1 for (_px, _py, _pz, _d, ax) in exp_holes if ax != "z")  # side holes ⇒ undercut
        if side:
            rows.append(Row("dfm · undercut (side holes need a side-action)", 0, side, False, "dfm"))

    # draft — side walls tilted inward by `angle`°: a side-wall plane's outward normal lifts off
    # horizontal by exactly the draft, so draft = asin(|nz|) (a 0° wall ⇒ nz=0). Measured on the
    # walls (normal in the XY plane), excluding the ∥Z caps. §3.2 ----
    # shell — the thinnest wall must equal the requested thickness (a solid box reads as min-dim ≫ t) §3.4
    for f in spec.features:
        if f.type != "shell" or spec.shape != "box":
            continue
        t_meas = _shell_wall_thickness(solid)
        dim("shell · wall thickness", f.thickness, t_meas)

    for f in spec.features:
        if f.type != "draft" or spec.shape != "box":
            continue
        walls = [p for p in m.planes if p.normal in ("x", "y")]
        if not walls:
            rows.append(Row("draft · angle", f.angle, None, False, "missing_feature"))
            continue
        drafts = [math.degrees(math.asin(min(1.0, abs(p.nz)))) for p in walls]
        worst = max(drafts, key=lambda d: abs(d - f.angle))
        ok = abs(worst - f.angle) <= max(0.1, tol)
        rows.append(Row("draft · angle (worst wall)", f.angle, round(worst, 3), ok, "ok" if ok else "dimensional"))

    # fillets — RESOLVE-TWICE: right radius on the right oriented edge set -----
    # (box-only: cylinder/loft have no straight vertical edges, matching the builder's guard)
    for f in spec.features:
        if f.type != "fillet" or spec.shape != "box":
            continue
        want_n = expected_edge_count(spec.shape, f.edges)
        matched = [c for c in list(pool) if abs(c.r - f.radius) <= window and _fillet_matches(c.axis, c.z, f.radius, m.dz, f.edges)]
        for c in matched:
            pool.remove(c)
        if matched:
            dim("fillet · r", f.radius, sum(c.r for c in matched) / len(matched))
        else:
            rows.append(Row("fillet · r", f.radius, None, False, "missing_feature"))
        # selector binding: fillet faces on EXACTLY the resolved oriented+located edge set
        binding_ok = len(matched) == want_n
        rows.append(Row(f"fillet · binding ({f.edges})", want_n, len(matched), binding_ok,
                        "ok" if binding_ok else "selector-binding"))

    # variable-radius fillet — HEURISTIC (BSpline blends): binding count + curvature-sampled radius
    # range ≈ [min(r1,r2), max(r1,r2)]. Looser tol than analytic features (sampling ~0.05 error). §3.10
    for f in spec.features:
        if f.type != "var_fillet" or spec.shape != "box":
            continue
        want_n = expected_edge_count(spec.shape, f.edges)
        n, rmin, rmax = _var_fillet_blends(solid)
        bind_ok = n == want_n
        rows.append(Row(f"var-fillet · binding ({f.edges})", want_n, n, bind_ok, "ok" if bind_ok else "selector-binding"))
        rtol = max(0.25, tol)   # curvature sampling is approximate
        lo_ok = rmin is not None and abs(rmin - min(f.r1, f.r2)) <= rtol
        hi_ok = rmax is not None and abs(rmax - max(f.r1, f.r2)) <= rtol
        rows.append(Row("var-fillet · r-min (≈)", min(f.r1, f.r2), round(rmin, 3) if rmin else None, lo_ok, "ok" if lo_ok else "dimensional"))
        rows.append(Row("var-fillet · r-max (≈)", max(f.r1, f.r2), round(rmax, 3) if rmax else None, hi_ok, "ok" if hi_ok else "dimensional"))

    # chamfers — diagonal planar bevel faces on the resolved edge set (box-only) ----------
    for f in spec.features:
        if f.type != "chamfer" or spec.shape != "box":
            continue
        want_n = expected_edge_count(spec.shape, f.edges)
        bevels = [p for p in m.planes if p.normal == "diagonal" and _chamfer_matches(p.nz, p.z, m.dz, f.edges)]
        n = len(bevels)
        ok = n == want_n
        rows.append(Row(f"chamfer · binding ({f.edges})", want_n, n, ok, "ok" if ok else "selector-binding"))

    # pockets / panel insets — match EACH spec pocket to a floor face by footprint + position, so
    # several positioned cuts (panel lines, greeble detail) all verify (depth + footprint + position).
    pockets = [f for f in spec.features if f.type == "pocket"]
    if pockets:
        top_z = max((p.z for p in m.planes if p.nz > 0.5), default=m.dz)
        floor_pool = []
        for p in m.planes:
            if p.nz > 0.5 and p.z < top_z - 1e-3:   # an up-facing face below the top = a pocket floor
                b = _optimal_bbox(p.face)
                floor_pool.append({"z": p.z, "dims": sorted([round(b[3] - b[0], 4), round(b[4] - b[1], 4)]),
                                   "cx": (b[0] + b[3]) / 2, "cy": (b[1] + b[4]) / 2})
        for i, f in enumerate(pockets):
            tag = f"pocket[{i}]" if len(pockets) > 1 else "pocket"
            want = sorted([f.length, f.width])
            ax, ay = f.at or (0.0, 0.0)
            cands = [fl for fl in floor_pool
                     if abs(fl["dims"][0] - want[0]) <= window and abs(fl["dims"][1] - want[1]) <= window]
            floor = min(cands, key=lambda fl: (fl["cx"] - ax) ** 2 + (fl["cy"] - ay) ** 2, default=None)
            if floor is None:
                rows.append(Row(f"{tag} · depth", f.depth, None, False, "missing_feature"))
                continue
            floor_pool.remove(floor)
            dim(f"{tag} · depth", f.depth, top_z - floor["z"])
            dim(f"{tag} · footprint-min", want[0], floor["dims"][0])
            dim(f"{tag} · footprint-max", want[1], floor["dims"][1])
            if f.at is not None:
                off = ((floor["cx"] - ax) ** 2 + (floor["cy"] - ay) ** 2) ** 0.5
                dim(f"{tag} · position", 0.0, off, cat_fail="selector-binding")

    # extra / unexpected cylindrical features (over-count, §3 shape) -----------
    leftover = [c for c in pool if c.r > 0.05]
    if leftover:
        rows.append(Row("unexpected cylinders", 0, len(leftover), False, "selector-binding"))

    return Report(m.valid, m.solids, m.volume, rows)
