"""Translate Fusion 360 Gallery joint sets (j1.0.0 / JoinABLe) into OUR Assembly schema.

Each joint set = two engineer-designed parts (STEP, mm, stored in a shared — usually assembled —
world frame) + a real joint (revolute/rigid, axis + limits; JSON coords are Fusion-API cm → ×10).
Per set: import both STEPs → primitive-fit each body (cylinder via the dominant cylindrical-face
census, else box via bbox) → place by bbox alignment (build our spec at origin, translate so it
lands exactly on the real part) → map the joint → verify with OUR verifier → report fit IoU
(fitted primitive ∩ real solid — the honest measure of how well our vocabulary approximates the
real part; gate the corpus on it).

Run:  cad_pipeline/.venv/bin/python -m training.translate_fusion_joints [n_sets] [--export]
"""
from __future__ import annotations

import glob
import json
import math
import sys

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane

from cad_pipeline.assembly import Assembly, Component, Joint, Mate, verify_assembly
from cad_pipeline.builder import build
from cad_pipeline.spec import Spec, ThroughHole, profile_extent, profile_is_simple

ROOT = "/workspace/.hf_home/datasets/fusion360/j1.0.0/joint"
OUT = "/workspace/.hf_home/cad_corpus/fusion_joint_assemblies.jsonl"
CM = 10.0   # Fusion API cm → our mm


def _common_vol(a: cq.Solid, b: cq.Solid) -> float:
    algo = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
    algo.Build()
    try:
        return cq.Shape.cast(algo.Shape()).Volume()
    except Exception:  # noqa: BLE001
        return 0.0


def _dominant_cylinder(solid: cq.Solid):
    """(axis 'x'|'y'|'z', radius) of the LARGEST-area cylindrical face with an axis-aligned
    direction, or None — a part whose biggest turned face dominates is a shaft/washer/wheel."""
    best = None
    for f in solid.Faces():
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            if ad.GetType() != GeomAbs_Cylinder:
                continue
            cyl = ad.Cylinder()
            d = cyl.Axis().Direction()
            comps = {"x": abs(d.X()), "y": abs(d.Y()), "z": abs(d.Z())}
            ax = max(comps, key=comps.get)
            if comps[ax] < 0.99:
                continue                       # tilted cylinder — box fallback handles it
            area = f.Area()
            if best is None or area > best[2]:
                best = (ax, cyl.Radius(), area)
        except Exception:  # noqa: BLE001
            continue
    return (best[0], best[1]) if best else None


# Spec-frame mapping per prism axis: profile_extrude builds its outline in the X–Z plane and
# extrudes along Y; to reproduce a prism whose real axis is x/y/z we express the cross-section in
# the BUILD frame (incl. the sign flips the rotation demands — sagitta signs then come out right
# because they're computed AFTER mapping) and rotate the component so build-Y lands on the axis.
_PRISM_MAP = {
    "y": (lambda p: (p.x, p.z), (0.0, 0.0, 0.0)),      # section in world XZ, extrude Y: identity
    "z": (lambda p: (p.x, -p.y), (90.0, 0.0, 0.0)),    # Rx(+90): build (a,·,b) → world (a,−b,·)
    "x": (lambda p: (-p.y, p.z), (0.0, 0.0, -90.0)),   # Rz(−90): build (a,·,b) → world (·,−a,b)
}


def _circle_hole(wire, to2d):
    """(u, v, diameter) if every edge of this inner wire lies on ONE circle (a drilled hole —
    the dominant inner-loop kind per the Fusion Gallery paper's curve census), else None."""
    center, radius = None, None
    for e in wire.Edges():
        ad = BRepAdaptor_Curve(e.wrapped)
        if ad.GetType() != GeomAbs_Circle:
            return None
        c = ad.Circle()
        p, r = c.Location(), c.Radius()
        if center is None:
            center, radius = p, r
        elif p.Distance(center) > 0.05 or abs(r - radius) > 0.01:
            return None
    if center is None:
        return None
    u, v = to2d(cq.Vector(center.X(), center.Y(), center.Z()))
    return (u, v, 2 * radius)


def _cap_outlines(solid: cq.Solid, ax: str) -> list:
    """(pts, arcs, holes) outlines of the largest planar faces perpendicular to `ax`, already mapped
    into profile_extrude's build frame. This reads the engineer's own sketch back off the B-Rep:
    cap-face outer-wire edges are exactly the sketch's lines and arcs (Fusion Gallery parts are ~all
    sketch+extrude), so lines → points and arcs → sagitta bulges; circular inner wires → through-
    holes. A non-circular inner wire (slot/frame interior) is beyond one primitive — skip that cap.
    Non-line/arc edges are approximated by an arc through their midpoint — the fit-IoU gate judges
    the result."""
    to2d, _rot = _PRISM_MAP[ax]
    caps = []
    for f in solid.Faces():
        try:
            if BRepAdaptor_Surface(f.wrapped).GetType() != GeomAbs_Plane:
                continue
            n = f.normalAt()
            if abs({"x": n.x, "y": n.y, "z": n.z}[ax]) < 0.999:
                continue
            caps.append(f)
        except Exception:  # noqa: BLE001
            continue
    caps.sort(key=lambda f: -f.Area())
    outlines = []
    for face in caps[:2]:                       # top-2: stepped parts differ top vs bottom
        holes = []
        try:
            inner = face.innerWires()
        except Exception:  # noqa: BLE001
            inner = []
        for w in inner:
            h = _circle_hole(w, to2d)
            if h is None:
                holes = None
                break                           # slot/frame interior — not representable, skip cap
            holes.append(h)
        if holes is None or len(holes) > 16:
            continue
        edges = face.outerWire().Edges()
        if not 1 < len(edges) <= 60:
            continue                            # single-edge = full circle → the cylinder fitter's job
        try:
            segs = [(e.startPoint(), e.endPoint(), e.positionAt(0.5)) for e in edges]
        except Exception:  # noqa: BLE001
            continue
        chain, used = [segs[0]], {0}            # chain end-to-end (wire edge order isn't oriented)
        ok = True
        while len(chain) < len(segs):
            cur = chain[-1][1]
            for i, (a, b, m) in enumerate(segs):
                if i in used:
                    continue
                if (a - cur).Length < 0.05:
                    used.add(i); chain.append((a, b, m)); break
                if (b - cur).Length < 0.05:
                    used.add(i); chain.append((b, a, m)); break
            else:
                ok = False; break
        if not ok or (chain[-1][1] - chain[0][0]).Length > 0.05:
            continue
        out = []
        for a, b, m in chain:
            pa, pb, pm = to2d(a), to2d(b), to2d(m)
            dx, dy = pb[0] - pa[0], pb[1] - pa[1]
            ln = math.hypot(dx, dy)
            if ln < 0.05:
                ok = False; break
            # signed sagitta: mid-edge point's offset off the chord, along the chord's left normal
            sag = (pm[0] - (pa[0] + pb[0]) / 2) * (-dy / ln) + (pm[1] - (pa[1] + pb[1]) / 2) * (dx / ln)
            out.append((pa, sag if abs(sag) > 0.02 else 0.0))
        straight = [i for i, (_, s) in enumerate(out) if s == 0.0] if ok else []
        if not straight:
            continue                            # closing segment must be a line (close() is straight)
        k = (straight[-1] + 1) % len(out)
        out = out[k:] + out[:k]
        pts = [(round(p[0], 3), round(p[1], 3)) for p, _ in out]
        arcs = [round(s, 3) for _, s in out[:-1]]
        if profile_is_simple(pts, arcs):
            outlines.append((pts, arcs if any(arcs) else None, holes))
    return outlines


_AX_ROT = {"x": (0.0, 90.0, 0.0), "y": (90.0, 0.0, 0.0), "z": (0.0, 0.0, 0.0)}


def _revolve_meridian(solid: cq.Solid, ax: str):
    """(profile, bore_r) of a TURNED part along `ax`, read analytically off the B-Rep: coaxial
    cylindrical faces are the radius steps, coaxial cones the tapers (washer/bushing/flanged shaft —
    the stepped round parts one cylinder can't fit). Convex faces build the outer envelope; a
    concave face spanning the full height is the through-bore (meridian off the axis revolves to a
    tube). Small coverage gaps (fillet rings we skip) are bridged linearly. None if not turned."""
    axv = {"x": cq.Vector(1, 0, 0), "y": cq.Vector(0, 1, 0), "z": cq.Vector(0, 0, 1)}[ax]
    along = lambda p: p.dot(axv)                       # noqa: E731
    lateral = lambda p: (p - axv * p.dot(axv))         # noqa: E731
    axis_pt = None
    outer, bores = [], []                              # (z0, z1, r0, r1)
    for f in solid.Faces():
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            typ = ad.GetType()
            if typ not in (GeomAbs_Cylinder, GeomAbs_Cone):
                continue
            geom = ad.Cylinder() if typ == GeomAbs_Cylinder else ad.Cone()
            d = geom.Axis().Direction()
            if abs({"x": d.X(), "y": d.Y(), "z": d.Z()}[ax]) < 0.99:
                return None                            # off-axis turned face — not one revolve
            loc = geom.Axis().Location()
            lat = lateral(cq.Vector(loc.X(), loc.Y(), loc.Z()))
            if axis_pt is None:
                axis_pt = lat
            elif (lat - axis_pt).Length > 0.05:
                return None                            # two different axes — not one revolve
            bb = f.BoundingBox()
            z0, z1 = {"x": (bb.xmin, bb.xmax), "y": (bb.ymin, bb.ymax), "z": (bb.zmin, bb.zmax)}[ax]
            if typ == GeomAbs_Cylinder:
                r0 = r1 = geom.Radius()
            else:
                apex = geom.Apex()
                az = along(cq.Vector(apex.X(), apex.Y(), apex.Z()))
                slope = math.tan(geom.SemiAngle())
                r0, r1 = abs(z0 - az) * abs(slope), abs(z1 - az) * abs(slope)
            # convex (outer) vs concave (bore): evaluate the ORIENTED normal at a mid-surface
            # point and dot it with the radial direction off the axis. (normalAt() dies on closed
            # cylindrical faces — their centroid sits ON the axis; the orientation flag alone is
            # unreliable — the surface winding can flip its meaning.)
            from OCP.TopAbs import TopAbs_Orientation
            from OCP.gp import gp_Pnt, gp_Vec
            um = (ad.FirstUParameter() + ad.LastUParameter()) / 2
            vm = (ad.FirstVParameter() + ad.LastVParameter()) / 2
            p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
            ad.D1(um, vm, p, du, dv)
            nrm = cq.Vector(du.Crossed(dv).X(), du.Crossed(dv).Y(), du.Crossed(dv).Z())
            if f.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
                nrm = nrm * -1
            rad = lateral(cq.Vector(p.X(), p.Y(), p.Z())) - axis_pt
            (outer if nrm.dot(rad) > 0 else bores).append((z0, z1, r0, r1))
        except Exception:  # noqa: BLE001
            return None
    if not outer:
        return None
    bb = solid.BoundingBox()
    zmin, zmax = {"x": (bb.xmin, bb.xmax), "y": (bb.ymin, bb.ymax), "z": (bb.zmin, bb.zmax)}[ax]
    span = zmax - zmin
    covered = sorted(outer)
    if sum(min(z1, zmax) - max(z0, zmin) for z0, z1, _, _ in covered) < 0.90 * span:
        return None                                    # big non-turned bands (hex head etc.)
    # outer envelope as a true max over z-bands (a flange OVERLAPS the hub's z-range — a
    # sequential walk would go backwards); z RELATIVE to zmin (bbox alignment translates).
    zs = sorted({round(v, 4) for z0, z1, _, _ in covered for v in (z0, z1)} | {zmin, zmax})
    bands = []
    for za, zb in zip(zs, zs[1:]):
        if zb - za < 1e-3:
            continue
        r_at = lambda zc: [r0 + (r1 - r0) * ((zc - z0) / (z1 - z0) if z1 > z0 else 0.0)  # noqa: E731
                           for z0, z1, r0, r1 in covered if z0 <= za + 1e-3 and zb - 1e-3 <= z1]
        ra, rb = r_at(za), r_at(zb)
        if not ra:
            if not bands:
                return None
            ra = rb = [bands[-1][3]]                   # gap → bridge previous radius
        bands.append((za, zb, max(ra), max(rb)))       # endpoint-wise max keeps cones SLOPED
    prof = []
    for za, zb, ra, rb in bands:
        pa = (round(ra, 3), round(za - zmin, 3))
        if not prof or abs(prof[-1][0] - pa[0]) > 0.01:
            prof.append(pa)                            # radial step at this height
        pb = (round(rb, 3), round(zb - zmin, 3))
        if prof[-1] != pb:
            prof.append(pb)
    # drop collinear midpoints on constant-radius runs
    prof = [p for i, p in enumerate(prof)
            if i in (0, len(prof) - 1) or not (abs(prof[i - 1][0] - p[0]) < 0.01
                                               and abs(prof[i + 1][0] - p[0]) < 0.01)]
    if len(prof) < 2 or len(prof) > 30:
        return None
    bore = max((min(r0, r1) for z0, z1, r0, r1 in bores
                if z0 - zmin < 0.05 * span and zmax - z1 < 0.05 * span), default=0.0)
    if bore >= min(p[0] for p in prof):
        bore = 0.0
    # close the loop: bottom cap → outer wall → top cap → (bore wall | axis)
    rb = round(bore, 3)
    meridian = [(rb, prof[0][1])] + prof + [(rb, prof[-1][1])]
    if ax == "y":
        # rot (90,0,0) maps build +z onto WORLD −y (an axis reversal) — mirror the meridian so a
        # non-symmetric part (tapered shaft) lands the right way around.
        zspan = prof[-1][1]
        meridian = [(r, round(zspan - z, 3)) for r, z in meridian]
    return meridian, rb


def fit_component(name: str, solid: cq.Solid, role: str) -> tuple:
    """Fit ONE primitive to a real part and keep the candidate with the best volume overlap (IoU):
    cylinder (dominant axis-aligned turned face + bbox agreement), profile_extrude (cap-face outline
    re-extruded — the sketch+extrude family the Fusion Gallery paper says these parts are), box
    (always, as the floor). Placement is EXACT by construction: build our spec at the origin, then
    translate so its bbox lands on the real part's (the corners-correction trick — shape-agnostic,
    no per-shape origin bookkeeping). Returns (Component, iou)."""
    bb = solid.BoundingBox()
    dims = {"x": bb.xlen, "y": bb.ylen, "z": bb.zlen}
    candidates = []
    cyl = _dominant_cylinder(solid)
    if cyl:
        ax, r = cyl
        perp = [a for a in "xyz" if a != ax]
        # a truly round part: both perpendicular extents ≈ the diameter
        if abs(dims[perp[0]] - 2 * r) < 0.25 * dims[perp[0]] and \
           abs(dims[perp[1]] - 2 * r) < 0.25 * dims[perp[1]]:
            candidates.append((Spec(object=name, shape="cylinder",
                                    envelope={"diameter": round(2 * r, 3),
                                              "height": round(dims[ax], 3)}),
                               _AX_ROT[ax]))
    for ax in "xyz":
        rv = _revolve_meridian(solid, ax)
        if rv:
            meridian, _bore = rv
            candidates.append((Spec(object=name, shape="revolve", profile=meridian),
                               _AX_ROT[ax]))
    for ax in "xyz":
        for pts, arcs, holes in _cap_outlines(solid, ax):
            # holes are drilled in the BUILD frame (extrusion is always along build-Y; the
            # component rotation carries them to the world axis) and positioned relative to the
            # CENTERED part — profile_extent is the same arc-aware math the builder centers by.
            u0, u1, v0, v1 = profile_extent(pts, arcs or [])
            cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
            feats = [ThroughHole(diameter=round(d, 3),
                                 at=(round(u - cu, 3), round(v - cv, 3)), axis="y")
                     for u, v, d in holes]
            candidates.append((Spec(object=name, shape="profile_extrude",
                                    envelope={"width": round(dims[ax], 3)},
                                    side_profile=pts, side_arcs=arcs, features=feats),
                               _PRISM_MAP[ax][1]))
    candidates.append((Spec(object=name, shape="box",
                            envelope={"length": round(bb.xlen, 3), "width": round(bb.ylen, 3),
                                      "height": round(bb.zlen, 3)}),
                       (0.0, 0.0, 0.0)))
    best = None
    for spec, rot in candidates:
        try:
            built = build(spec).val()
            for rx_ax, ang in (((1, 0, 0), rot[0]), ((0, 1, 0), rot[1]), ((0, 0, 1), rot[2])):
                if ang:
                    built = built.rotate((0, 0, 0), rx_ax, ang)
            fb = built.BoundingBox()
            at = tuple(round(v, 3) for v in
                       (bb.xmin - fb.xmin, bb.ymin - fb.ymin, bb.zmin - fb.zmin))
            placed = built.translate(cq.Vector(*at))
            inter = _common_vol(placed, solid)
            union = placed.Volume() + solid.Volume() - inter
            iou = inter / union if union > 0 else 0.0
        except Exception:  # noqa: BLE001 — a failed candidate just drops out
            continue
        if best is None or iou > best[1]:
            best = (Component(name=name, role=role, part=spec, at=at, rotate=rot), iou)
    if best is None:
        raise ValueError(f"no primitive candidate could be built for {name}")
    return best


_AXIS_NAME = {"XAxisJointDirection": "x", "YAxisJointDirection": "y", "ZAxisJointDirection": "z"}


def _apply_pose(solid: cq.Solid, tf: dict) -> cq.Solid:
    """Apply a joint-set `transform` (the body's ASSEMBLED pose: rotation as x/y/z axis columns +
    origin in cm) to a stored-pose solid. The dataset stores bodies displaced; this field is what
    assembles them (confirmed: body_two is identity/base, body_one's transform lands it exactly
    on the reference render's pose)."""
    if not tf:
        return solid
    import numpy as np
    o = tf["origin"]
    cols = np.array([[tf[a]["x"], tf[a]["y"], tf[a]["z"]] for a in ("x_axis", "y_axis", "z_axis")]).T
    # JSON axes carry float noise OCCT rejects ("non-orthogonal GTrsf") — Gram-Schmidt them.
    x = cols[:, 0] / np.linalg.norm(cols[:, 0])
    y = cols[:, 1] - np.dot(cols[:, 1], x) * x
    y = y / np.linalg.norm(y)
    z = np.cross(x, y)
    if np.dot(z, cols[:, 2]) < 0:
        raise ValueError("mirrored body transform (left-handed frame) — unsupported")
    R = np.column_stack([x, y, z])
    t = (o["x"] * CM, o["y"] * CM, o["z"] * CM)
    # raw OCP: cq.Matrix→transformShape rejects even exactly-orthonormal rotations here (its
    # GTrsf→Trsf conversion), while gp_Trsf.SetValues takes the same numbers happily.
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    tr = gp_Trsf()
    tr.SetValues(R[0][0], R[0][1], R[0][2], t[0],
                 R[1][0], R[1][1], R[1][2], t[1],
                 R[2][0], R[2][1], R[2][2], t[2])
    return cq.Shape.cast(BRepBuilderAPI_Transform(solid.wrapped, tr, True).Shape())


def translate_set(path: str) -> dict:
    d = json.load(open(path))
    b1, b2 = d["body_one"], d["body_two"]
    j0 = d["joints"][0]
    s1 = _apply_pose(cq.importers.importStep(f"{ROOT}/{b1}.step").val(),
                     j0["geometry_or_origin_one"].get("transform"))
    s2 = _apply_pose(cq.importers.importStep(f"{ROOT}/{b2}.step").val(),
                     j0["geometry_or_origin_two"].get("transform"))
    c1, iou1 = fit_component("base_part", s1, "base")
    c2, iou2 = fit_component("moving_part", s2, "other")
    j = d["joints"][0]
    jm = j["joint_motion"]
    jtype = jm.get("joint_type", "RigidJointType")
    joints, mates = [], []
    if jtype not in ("RevoluteJointType", "CylindricalJointType", "RigidJointType"):
        # slider/planar/ball/pin-slot carry DOFs our v1 joint vocabulary can't express — skipping
        # is honest; translating them as welds would be semantically WRONG training data.
        return {"set": path.split("/")[-1], "skip": f"{jtype} not representable (v1 is revolute)"}
    if jtype in ("RevoluteJointType", "CylindricalJointType"):
        # cylindrical = spin + slide on one axis; we keep the (real) spin and drop the slide —
        # a conservative subset, unlike the weld fallback.
        g = j["geometry_or_origin_one"]
        av = g.get("primary_axis_vector", {})
        comps = {"x": abs(av.get("x", 0)), "y": abs(av.get("y", 0)), "z": abs(av.get("z", 1))}
        ax = max(comps, key=comps.get)
        if comps[ax] < 0.99:
            return {"set": path.split("/")[-1], "skip": "tilted joint axis (v1 is axis-aligned)"}
        lim = jm.get("rotation_limits", {})
        lo = lim.get("minimum_value", 0.0) if lim.get("is_minimum_value_enabled") else 0.0
        hi = lim.get("maximum_value", 0.0) if lim.get("is_maximum_value_enabled") else 0.0
        if hi - lo < 1.0:
            lo, hi = 0.0, 360.0                       # unlimited spin — the common case
        o = g["origin"]
        joints.append(Joint(kind="revolute", a="moving_part", b="base_part", axis=ax,
                            at=(o["x"] * CM, o["y"] * CM, o["z"] * CM),
                            limits=(math.degrees(lo) if abs(lo) < 7 else lo,
                                    math.degrees(hi) if abs(hi) < 7 else hi)))
    else:
        mates.append(Mate(kind="attach", a="moving_part", b="base_part"))
    # joint sets are subassembly FRAGMENTS floating wherever the source assembly had them —
    # recenter onto the floor (xy about origin, min-z = 0) so grounding/statics read normally.
    import cadquery as _cq
    zmin = min(s.BoundingBox().zmin for s in (s1, s2))
    cx = sum(s.BoundingBox().center.x for s in (s1, s2)) / 2
    cy = sum(s.BoundingBox().center.y for s in (s1, s2)) / 2
    for c in (c1, c2):
        c.at = (round(c.at[0] - cx, 3), round(c.at[1] - cy, 3), round(c.at[2] - zmin, 3))
    for jt in joints:
        if jt.at is not None:
            jt.at = (round(jt.at[0] - cx, 3), round(jt.at[1] - cy, 3), round(jt.at[2] - zmin, 3))
    asm = Assembly(object=f"fusion joint set {d.get('name', b1)}",
                   components=[c1, c2], mates=mates, joints=joints, fuse=not joints)
    rep = verify_assembly(asm)
    fails = [r["name"] for r in rep["rows"] if not r["within_tol"]]
    # these sets are two-part FRAGMENTS of larger machines — "balances free-standing on the
    # floor" (statics) is not a property the source assembly ever promised; waive it for the
    # keep decision (every other row still gates).
    frag_fails = [f for f in fails if "statics" not in f]
    return {"set": path.split("/")[-1], "bodies": [b1, b2], "joint": jtype,
            "fit_iou": [round(iou1, 3), round(iou2, 3)],
            "shapes": [c1.part.shape, c2.part.shape],
            "passed": rep["passed"], "passed_fragment": not frag_fails,
            "fails": fails,
            "assembly": asm.model_dump()}


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    export = "--export" in sys.argv
    # resume-safe: every processed set is logged to a sidecar; reruns skip them (no duplicate keeps)
    seen_path = OUT.replace(".jsonl", ".processed.txt")
    try:
        seen = set(open(seen_path).read().split())
    except FileNotFoundError:
        seen = set()
    sets = [p for p in sorted(glob.glob(f"{ROOT}/joint_set_*.json"))
            if p.split("/")[-1] not in seen][:n * 3]   # headroom for skips
    done = kept = 0
    for p in sets:
        if done >= n:
            break
        with open(seen_path, "a") as sf:
            sf.write(p.split("/")[-1] + "\n")
        try:
            r = translate_set(p)
        except Exception as e:  # noqa: BLE001 — one bad set must not stop the sweep
            print(f"{p.split('/')[-1]}: ERROR {type(e).__name__}: {e}")
            continue
        if "skip" in r:
            print(f"{r['set']}: SKIP {r['skip']}")
            continue
        done += 1
        keep = r["passed_fragment"] and min(r["fit_iou"]) >= 0.8
        kept += keep
        print(f"{r['set']}: {r['joint']:<18} shapes={r['shapes']} fit_iou={r['fit_iou']} "
              f"passed={r['passed']} keep={keep} fails={r['fails'][:3]}", flush=True)
        if export and keep:
            with open(OUT, "a") as f:
                f.write(json.dumps(r) + "\n")
    print(f"\nkeep-rate: {kept}/{done} ({100 * kept / max(done, 1):.0f}%) — "
          f"verifier-passing (statics waived for fragments) with both fit IoU >= 0.8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
