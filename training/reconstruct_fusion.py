"""Reconstruction oracle for the feature-program representation (design doc §5, §9 step 4).

Translate a Fusion 360 Gallery *reconstruction* construction sequence (human sketch+extrude+boolean
DSL) into our feature-program grammar, execute it, and measure IoU against the shipped ground-truth
solid. A high exact-reconstruction rate is the GO/NO-GO on the representation AND (dual-use) the
corpus-admission gate — a faithful translation is a clean (part → our-grammar program) training pair.

The DSL: each ExtrudeFeature references a profile (a trimmed loop of Line3D/Arc3D/Circle3D in the
sketch's LOCAL 2D plane, z=0), on a sketch whose `transform` (origin + x/y/z axis) places that plane
in world; `extent_one.distance` (signed, cm) is the extrude length; `operation` is the boolean.
Units: JSON = cm; the STEPs declare cm and OCCT auto-converts to mm on import → we build JSON coords
×10 so both sides are mm (the joint-data lesson).

Run:  cad_pipeline/.venv/bin/python -m training.reconstruct_fusion [n] [--debug ID]
"""
from __future__ import annotations

import glob
import math
import sys

import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

import json

from cad_pipeline.builder import _sketch_extrude_solid, build_part
from cad_pipeline.spec import Part, SketchExtrude, SketchLoop, Step

ROOT = "/workspace/.hf_home/datasets/fusion360/r1.0.1/extracted/r1.0.1/reconstruction"
CM = 10.0

_OP = {"NewBodyFeatureOperation": "new_body", "JoinFeatureOperation": "join",
       "CutFeatureOperation": "cut", "IntersectFeatureOperation": "intersect"}


def _p(pt) -> tuple:
    """A sketch-local Point3D (z=0) → 2D (u, v) in mm."""
    return (pt["x"] * CM, pt["y"] * CM)


def _curve_ends(c: dict):
    """(start_uv, end_uv) of a curve in mm, or None for a full circle/ellipse (single-curve loop).
    NurbsCurve3D has no start/end_point — a clamped B-spline starts/ends at its first/last control
    point (knot vector 0,0,0,0…)."""
    t = c["type"]
    if t in ("Circle3D",) or (t == "Ellipse3D" and "start_point" not in c):
        return None
    if t == "NurbsCurve3D":
        cp = c["control_points"]
        return _p(cp[0]), _p(cp[-1])
    return _p(c["start_point"]), _p(c["end_point"])


def _arc_mid(c: dict):
    """The EXACT midpoint of an Arc3D on its true sweep, in sketch-local mm. The DSL gives
    center + radius + reference_vector + normal + start/end_angle (angle measured CCW about
    `normal` from `reference_vector`), so the midpoint is unambiguous — unlike an atan2 heuristic,
    which mis-orients major (>180°) arcs and self-intersects the wire (the dominant recon bug)."""
    cen = _p(c["center_point"])
    rad = c["radius"] * CM
    ref = (c["reference_vector"]["x"], c["reference_vector"]["y"])
    rn = math.hypot(*ref) or 1.0
    ref = (ref[0] / rn, ref[1] / rn)
    nz = c["normal"]["z"]                                    # +z ⇒ CCW, −z ⇒ CW in the local plane
    perp = (-ref[1], ref[0]) if nz >= 0 else (ref[1], -ref[0])
    th = (c["start_angle"] + c["end_angle"]) / 2
    ct, st = math.cos(th), math.sin(th)
    return (cen[0] + rad * (ct * ref[0] + st * perp[0]),
            cen[1] + rad * (ct * ref[1] + st * perp[1]))


def _nurbs_points(c: dict, reverse: bool, n: int = 24):
    """On-curve sample points of a NurbsCurve3D (exact to tolerance), via an OCP Geom_BSplineCurve
    built from the poles/knots/degree — control points are the hull, NOT on the curve, so sampling
    the real curve is far better than a spline through control points."""
    from OCP.Geom import Geom_BSplineCurve
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
    cps = c["control_points"]
    deg = c["degree"]
    poles = TColgp_Array1OfPnt(1, len(cps))
    for i, p in enumerate(cps):
        poles.SetValue(i + 1, gp_Pnt(p["x"] * CM, p["y"] * CM, 0.0))
    # collapse the clamped knot vector into distinct knots + multiplicities
    kv = c["knots"]
    uniq, mult = [], []
    for k in kv:
        if uniq and abs(k - uniq[-1]) < 1e-12:
            mult[-1] += 1
        else:
            uniq.append(k); mult.append(1)
    ka = TColStd_Array1OfReal(1, len(uniq))
    ma = TColStd_Array1OfInteger(1, len(uniq))
    for i, (k, m) in enumerate(zip(uniq, mult)):
        ka.SetValue(i + 1, k); ma.SetValue(i + 1, m)
    crv = Geom_BSplineCurve(poles, ka, ma, deg)
    t0, t1 = crv.FirstParameter(), crv.LastParameter()
    pts = []
    for i in range(1, n + 1):                               # skip i=0 (current point); include end
        t = t0 + (t1 - t0) * i / n
        pnt = crv.Value(t)
        pts.append((pnt.X(), pnt.Y()))
    return pts[::-1] if reverse else pts


TOL = 1e-4 * CM


def _sagitta(c: dict, s, e) -> float:
    """Signed sagitta of Arc3D `c` for the chord s→e: perpendicular offset of the arc's TRUE
    midpoint (from `_arc_mid`, exact) off the chord, along the chord's left normal — the same
    convention `_profile_wire`/`sagittaArc` consume in the builder."""
    mid = _arc_mid(c)
    dx, dy = e[0] - s[0], e[1] - s[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return 0.0
    return (mid[0] - (s[0] + e[0]) / 2) * (-dy / L) + (mid[1] - (s[1] + e[1]) / 2) * (dx / L)


def _chain(curves: list) -> list:
    """Order a loop's curves head-to-tail (they are NOT stored ordered): returns [(curve, start,
    end)] with each curve oriented so end==next start. Raises on an open loop."""
    segs = [(c, _curve_ends(c)) for c in curves]
    segs = [(c, en) for c, en in segs if en is not None]     # drop stray full circles
    if not segs:
        raise ValueError("no traceable curves")
    order = [(segs[0][0], segs[0][1][0], segs[0][1][1])]
    used = {0}
    cur = segs[0][1][1]
    while len(order) < len(segs):
        for i, (c, (s, e)) in enumerate(segs):
            if i in used:
                continue
            if math.dist(s, cur) < TOL:
                order.append((c, s, e)); used.add(i); cur = e; break
            if math.dist(e, cur) < TOL:
                order.append((c, e, s)); used.add(i); cur = s; break   # traversed reversed
        else:
            raise ValueError("open loop")
    return order


def _loop_to_sketchloop(lp: dict) -> SketchLoop:
    """Convert a profile loop → our SketchLoop (pts + per-segment sagitta, or a full circle).
    NURBS segments expand to an on-curve polyline (straight sub-segments). The loop is rotated so a
    STRAIGHT segment closes it (the builder's `close()` draws the last segment straight)."""
    curves = lp["profile_curves"]
    outer = lp.get("is_outer", True)
    if len(curves) == 1 and _curve_ends(curves[0]) is None:
        c = curves[0]
        cu, cv = _p(c["center_point"])
        rr = (c.get("radius") or c.get("major_radius", 0.0)) * CM
        return SketchLoop(outer=outer, circle=(round(cu, 4), round(cv, 4), round(rr, 4)))
    order = _chain(curves)
    segs = []                                                # (start_point, sagitta, spline_pts|None)
    for c, s, e in order:
        if c["type"] == "NurbsCurve3D":
            ns, _ = _curve_ends(c)
            rev = math.dist(ns, s) > TOL
            # ONE spline edge through the on-curve samples (ending at e) — NOT a ~24-segment
            # polyline (that exploded face counts → over-faceting → gated out; the complex-part skew).
            segs.append((s, 0.0, _nurbs_points(c, rev)))
        elif c["type"] == "Arc3D":
            segs.append((s, _sagitta(c, s, e), None))
        else:
            segs.append((s, 0.0, None))
    # One entry per segment INCLUDING the closer segs[-1]→segs[0] (`_loop_wire` draws every segment,
    # so all-arc/spline loops close correctly). pts/arcs/splines are parallel arrays.
    pts = [(round(p[0], 4), round(p[1], 4)) for p, _, _ in segs]
    arcs = [round(sg, 4) for _, sg, _ in segs]
    splines = [([(round(x, 4), round(y, 4)) for x, y in sp] if sp else None) for _, _, sp in segs]
    return SketchLoop(outer=outer, pts=pts, arcs=arcs,
                      splines=splines if any(splines) else None)


def _sketchextrude_from(sketch: dict, profile_id: str, ex: dict) -> SketchExtrude:
    """One (sketch, profile, extrude) → a SketchExtrude operand in world coords."""
    tf = sketch["transform"]
    o, x, z = tf["origin"], tf["x_axis"], tf["z_axis"]
    plane = [(o["x"] * CM, o["y"] * CM, o["z"] * CM), (x["x"], x["y"], x["z"]),
             (z["x"], z["y"], z["z"])]
    prof = sketch["profiles"][profile_id]
    loops = [_loop_to_sketchloop(lp) for lp in prof["loops"]]
    dist = ex["extent_one"]["distance"]["value"] * CM
    symmetric = ex.get("extent_type") == "SymmetricFeatureExtentType"
    # Fusion's symmetric `distance` is the TOTAL extent → half each side (verified on 100797)
    return SketchExtrude(plane=plane, loops=loops,
                         distance=dist / 2 if symmetric else dist, symmetric=symmetric)


def _part_from(d: dict):
    """Translate a whole construction sequence → (Part, skipped). Each (extrude × profile) that
    BUILDS becomes a Step (op = its boolean, first is new_body); an operand that fails to build is
    dropped and counted (per-extrude isolation) so one bad profile can't sink the part."""
    ents = d["entities"]
    steps, skipped, ops = [], 0, []
    for step in d["sequence"]:
        if step["type"] != "ExtrudeFeature":
            continue
        ex = ents[step["entity"]]
        op = _OP.get(ex["operation"], "join")
        ops.append(op)
        for ref in ex["profiles"]:
            try:
                se = _sketchextrude_from(ents[ref["sketch"]], ref["profile"], ex)
                s = _sketch_extrude_solid(se)                # pre-validate it builds
                if s is None or s.Volume() <= 1e-9:
                    skipped += 1; continue
            except Exception:  # noqa: BLE001
                skipped += 1; continue
            steps.append(Step(op="new_body" if not steps else op, operand=se))
    return Part(object=d.get("metadata", {}).get("parent_project", "part"), steps=steps), skipped, ops


def _common_vol(a, b) -> float:
    """|a ∩ b|, robust to OCCT Common failing on complex/thin solids (it can silently return an
    empty shape → a false IoU=0 on a GOOD reconstruction). Retry with a fuzzy tolerance."""
    for fuzzy in (0.0, 1e-3, 1e-2):
        try:
            algo = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
            if fuzzy:
                algo.SetFuzzyValue(fuzzy)
            algo.Build()
            v = cq.Shape.cast(algo.Shape()).Volume()
            if v > 1e-9:
                return v
        except Exception:  # noqa: BLE001
            continue
    return 0.0


def _iou(a, b) -> float:
    inter = _common_vol(a, b)
    union = a.Volume() + b.Volume() - inter
    return inter / union if union > 0 else 0.0


def _voxel_iou(a, b, res: int = 26) -> float:
    """DETERMINISTIC, hang-free IoU via point-in-solid occupancy over a shared grid. Replaces the
    boolean `_iou`, which proved NON-DETERMINISTIC on complex solids (gave 0.0 and 1.0 for the
    identical pair across runs) AND hangs on high-face solids. `a` and `b` share the STEP's world
    frame (reconstruction), so no alignment/rotation is needed — a common bbox grid suffices."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN
    ba, bb = a.BoundingBox(), b.BoundingBox()
    x0, y0, z0 = min(ba.xmin, bb.xmin), min(ba.ymin, bb.ymin), min(ba.zmin, bb.zmin)
    x1, y1, z1 = max(ba.xmax, bb.xmax), max(ba.ymax, bb.ymax), max(ba.zmax, bb.zmax)
    dx, dy, dz = (x1 - x0) / res, (y1 - y0) / res, (z1 - z0) / res
    ca = BRepClass3d_SolidClassifier(a.wrapped)
    cb = BRepClass3d_SolidClassifier(b.wrapped)
    inter = only_a = only_b = 0
    for i in range(res):
        px = x0 + (i + 0.5) * dx
        for j in range(res):
            py = y0 + (j + 0.5) * dy
            for k in range(res):
                pt = gp_Pnt(px, py, z0 + (k + 0.5) * dz)
                ca.Perform(pt, 1e-7); ina = ca.State() == TopAbs_IN
                cb.Perform(pt, 1e-7); inb = cb.State() == TopAbs_IN
                if ina and inb:
                    inter += 1
                elif ina:
                    only_a += 1
                elif inb:
                    only_b += 1
    union = inter + only_a + only_b
    return inter / union if union else 0.0


def reconstruct(path: str, debug: bool = False, want_part: bool = False) -> dict:
    """Translate a construction sequence into a Part program, build it with the SHIPPED `build_part`
    executor, and score IoU vs the ground-truth solid. `want_part` returns the Part JSON (corpus)."""
    d = json.load(open(path))
    stem = path.rsplit("/", 1)[-1][:-5]
    part, skipped, ops = _part_from(d)
    n_ex = len(ops)
    g = None
    if part.steps:
        try:
            g = build_part(part).val()
        except Exception:  # noqa: BLE001
            g = None
    if g is None:
        res = {"id": stem, "extrudes": n_ex, "ops": ops, "iou": 0.0, "skipped": skipped}
        if want_part:
            res["part"] = part.model_dump()
        return res
    gt = cq.importers.importStep(f"{ROOT}/{stem}.step").val()
    # Over-faceting guard: our SketchExtrude schema has no SPLINE segment, so NURBS profile curves
    # get downgraded to ~24-segment polylines → face-count explosions on curve-heavy parts (seen:
    # 2002 faces vs a 148-face ground truth). OCCT booleans (Common in _iou) HANG on such solids,
    # and the geometry is bad anyway → skip the IoU and gate the part OUT. (Known limitation: add a
    # spline segment to SketchLoop to recover the ~5% NURBS-heavy parts.)
    nf, ngt = len(g.Faces()), len(gt.Faces())
    if nf > max(800, 8 * ngt):
        res = {"id": stem, "extrudes": n_ex, "ops": ops, "iou": 0.0, "skipped": skipped,
               "over_faceted": nf}
        if want_part:
            res["part"] = part.model_dump()
        return res
    iou = _voxel_iou(g, gt)   # deterministic + hang-free (boolean _iou is neither — see _voxel_iou)
    res = {"id": stem, "extrudes": n_ex, "ops": ops, "iou": round(iou, 4), "skipped": skipped}
    if want_part:
        res["part"] = part.model_dump()
    if debug:
        gb, tb = g.BoundingBox(), gt.BoundingBox()
        res["our_bbox"] = [round(gb.xlen, 2), round(gb.ylen, 2), round(gb.zlen, 2)]
        res["gt_bbox"] = [round(tb.xlen, 2), round(tb.ylen, 2), round(tb.zlen, 2)]
        res["our_vol"] = round(g.Volume(), 1)
        res["gt_vol"] = round(gt.Volume(), 1)
    return res


def main() -> int:
    if "--debug" in sys.argv:
        i = sys.argv.index("--debug")
        stem = sys.argv[i + 1]
        print(json.dumps(reconstruct(f"{ROOT}/{stem}.json", debug=True), indent=2))
        return 0
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 50
    files = sorted(glob.glob(f"{ROOT}/*.json"))[:n]
    ious, keep, byops = [], 0, {}
    for p in files:
        try:
            r = reconstruct(p)
        except Exception as e:  # noqa: BLE001
            print(f"{p.rsplit('/',1)[-1][:-5]}: ERROR {type(e).__name__}: {str(e)[:60]}")
            ious.append(0.0)
            continue
        ious.append(r["iou"])
        keep += r["iou"] >= 0.95
        byops.setdefault(r["extrudes"], []).append(r["iou"])
        print(f"{r['id']}: {r['extrudes']}ex {r['ops']} IoU={r['iou']}")
    n = len(ious)
    print(f"\nexact-recon (IoU>=0.95): {keep}/{n} ({100*keep/max(n,1):.0f}%)   "
          f"mean IoU {sum(ious)/max(n,1):.3f}")
    for k in sorted(byops):
        v = byops[k]
        print(f"  {k} extrude(s): {sum(i>=0.95 for i in v)}/{len(v)} exact, mean {sum(v)/len(v):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
