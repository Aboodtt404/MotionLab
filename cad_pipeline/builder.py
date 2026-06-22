"""Deterministic spec → CadQuery solid.

In production the *generator* (LLM) emits CadQuery; this hand-written builder is
the **golden reference** used to self-test the verifier (build a known-good solid
from a spec, confirm the verifier measures it back to ~0 error) and a fallback
oracle. Mirrors the operation vocabulary the generator is allowed to use.
"""
from __future__ import annotations

import cadquery as cq
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

from .selectors import CQ_EDGE
from .spec import Spec, expected_holes


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
