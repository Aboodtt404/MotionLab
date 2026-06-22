"""Spec → IDIOMATIC CadQuery source (the Phase-2 targeted-layer target code).

`builder.emit_code` emits the literal builder TRACE — through-holes/patterns become raw
`cq.Solid.makeCylinder(..., cq.Vector(-15,-15,-7), ...)` with magic numbers. That is the
*opposite* of what the fine-tune should emit. This emitter produces code matching the canonical
idioms in `rag._EXAMPLES` (the recipes the vocab eval proved lift first-attempt correctness):
named params, `pushPoints([...]).hole(d)`, `cboreHole/cskHole`, `sketch→revolve`, etc.

See `docs/research/track-a-targeted-layer.md` §2. The ONLY divergence from `emit_code` is the
hole/thread block: top-face (z-axis) holes on a FLAT-top shape (box/cylinder) use the fluent
`pushPoints([...]).hole(d)` idiom (grouped by diameter, single source of truth = `expected_holes`);
cross-drilled (x/y) holes and non-flat-top shapes (revolve/loft/sweep) keep the robust
`makeCylinder` cutter (no clean fluent idiom, and the fluent top-face form is unreliable there).

Correctness is not assumed: every emission is exec→verify gated (the golden-spec self-test in
`tests/test_emit_idiomatic.py`, and the per-sample accept gate in the targeted-layer driver).
`builder.emit_code` is left untouched (golden-verify reference + live /generate path).
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Tuple

from .builder import _DIR, _axis_extent
from .selectors import CQ_EDGE
from .spec import Spec, expected_holes

_FLAT_TOP = {"box", "cylinder"}  # shapes whose +Z face is a flat disc/rect ⇒ fluent .hole() is safe


def _make_cylinder_cut(px: float, py: float, pz: float, d: float, axis: str, spec: Spec) -> str:
    """The robust through-cutter (mirrors builder._hole_cutter) — used for cross-drilled holes."""
    dx, dy, dz = _DIR[axis]
    ext = _axis_extent(spec, axis)
    h = round(ext / 2 + 1.0, 4)
    return (f"result = result.cut(cq.Solid.makeCylinder({round(d / 2, 4)}, {round(ext + 2.0, 4)}, "
            f"cq.Vector({round(px - dx * h, 4)}, {round(py - dy * h, 4)}, {round(pz - dz * h, 4)}), "
            f"cq.Vector({dx}, {dy}, {dz})))")


def _emit_holes(spec: Spec) -> List[str]:
    """Idiomatic hole emission. Top-face z-holes on a flat-top shape → grouped pushPoints().hole();
    everything else → makeCylinder cutter. Order/positions come from `expected_holes` (the single
    source of truth the verifier re-derives), so geometry matches `build()` exactly."""
    lines: List[str] = []
    flat = spec.shape in _FLAT_TOP
    # group flat-top z-holes by diameter so one .pushPoints([...]).hole(d) covers each ⌀
    z_by_d: dict = defaultdict(list)
    for px, py, pz, d, axis in expected_holes(spec):
        if flat and axis == "z":
            z_by_d[round(d, 6)].append((round(px, 4), round(py, 4)))
        else:
            lines.append(_make_cylinder_cut(px, py, pz, d, axis, spec))
    for d, pts in z_by_d.items():
        if len(pts) == 1 and pts[0] == (0.0, 0.0):
            lines.append(f'result = result.faces(">Z").workplane().hole({d})  # centered through-hole')
        else:
            lines.append(f'result = result.faces(">Z").workplane().pushPoints({pts}).hole({d})')
    return lines


def emit_idiomatic(spec: Spec) -> str:
    """Spec → idiomatic CadQuery source assigning the final solid to `result`."""
    e = spec.envelope
    out: List[str] = ["import cadquery as cq", f"# {spec.object}"]

    # ---- base shape (canonical idioms; named params) --------------------------------------
    if spec.shape == "box":
        out.append(f"L, W, H = {e['length']}, {e['width']}, {e['height']}")
        dr = next((f for f in spec.features if f.type == "draft"), None)
        if dr is not None:   # molded walls: base L×W at z−, tapered inward to the top
            out.append('result = cq.Workplane("XY").workplane(offset=-H / 2).rect(L, W)'
                       f".extrude(H, taper={dr.angle})")
        else:
            out.append('result = cq.Workplane("XY").box(L, W, H)  # centered at origin')
    elif spec.shape == "cylinder":
        out.append(f"D, H = {e['diameter']}, {e['height']}")
        out.append('result = cq.Workplane("XY").circle(D / 2).extrude(H)')
    elif spec.shape == "loft":
        ln, w, h, wt, ht = spec.loft_profiles()
        out.append(f"L, W, H = {ln}, {w}, {h}")
        top = (f".circle({round(e['diameter_top'] / 2, 4)})" if spec.loft_top_round()
               else f".rect({wt}, {ht})")
        out.append(f'_lf = cq.Workplane("YZ").rect(W, H).workplane(offset=L){top}.loft(ruled=True)')
        out.append("result = cq.Workplane(obj=_lf.val().translate(cq.Vector(-L / 2, 0, 0)))")
    elif spec.shape == "revolve":
        ang = e.get("angle", 360.0)
        out.append(f"_meridian = {[[r, z] for r, z in (spec.profile or [])]}  # [radius, z] points")
        out.append(f'_rv = cq.Workplane("XY").polyline(_meridian).close().revolve({ang}, (0, 0, 0), (0, 1, 0))')
        out.append("result = cq.Workplane(obj=_rv.val().rotate((0, 0, 0), (1, 0, 0), 90))  # stand on Z")
    elif spec.shape == "sweep":
        out.append(f"_pts = [cq.Vector(*p) for p in {[list(p) for p in (spec.path or [])]}]")
        out.append("_path = cq.Wire.assembleEdges([cq.Edge.makeLine(_pts[i], _pts[i + 1]) "
                   "for i in range(len(_pts) - 1)])")
        out.append("_t0 = (_pts[1] - _pts[0]).normalized()  # profile ⟂ first segment")
        out.append(f'result = cq.Workplane(cq.Plane(origin=_pts[0].toTuple(), normal=_t0.toTuple()))'
                   f".circle({round(e['diameter'] / 2, 4)}).sweep(cq.Workplane(obj=_path), isFrenet=True)")
    else:
        raise ValueError(f"unknown shape {spec.shape!r}")

    # ---- edge mods (box only), in SPEC ORDER (op-order sensitive) -------------------------
    var_fillet_used = False
    for f in spec.features:
        if spec.shape != "box":
            break
        if f.type == "fillet":
            out.append(f'result = result.edges("{CQ_EDGE.get(f.edges, "|Z")}").fillet({f.radius})')
        elif f.type == "chamfer":
            out.append(f'result = result.edges("{CQ_EDGE.get(f.edges, "|Z")}").chamfer({f.distance})')
    vf = next((f for f in spec.features if f.type == "var_fillet"), None)
    if vf is not None and spec.shape == "box":
        var_fillet_used = True
        out.append("_mk = BRepFilletAPI_MakeFillet(result.val().wrapped)")
        out.append(f'for _e in result.edges("{CQ_EDGE.get(vf.edges, "|Z")}").vals(): '
                   f"_mk.Add({vf.r1}, {vf.r2}, _e.wrapped)  # radius varies r1→r2 along each edge")
        out.append("result = cq.Workplane(obj=cq.Shape(_mk.Shape()))")

    # ---- shell (box), before pockets/holes so they cut the finished wall ------------------
    sh = next((f for f in spec.features if f.type == "shell"), None)
    if sh is not None and spec.shape == "box":
        if sh.open_face == "none":
            out.append(f"result = result.shell(-{sh.thickness})  # sealed hollow")
        else:
            face = {"top": ">Z", "bottom": "<Z"}[sh.open_face]
            out.append(f'result = result.faces("{face}").shell(-{sh.thickness})  # {sh.open_face}-open shell')

    # NOTE on ordering: holes/cbore/csk/thread are emitted BEFORE pockets. All four are subtractive
    # and commute with pockets, so the final solid is identical to build()'s pocket-first order — but
    # drilling on the PRISTINE top face avoids a `.hole()` over a pocket void (no material at the
    # workplane point → malformed cutter). build() uses absolute makeCylinder cutters so it is immune;
    # the idiomatic fluent .hole() is not, hence this reorder.

    # ---- through-holes (idiomatic) --------------------------------------------------------
    out.extend(_emit_holes(spec))

    # ---- cosmetic internal thread = a nominal bore + the thread callout -------------------
    for f in spec.features:
        if f.type == "thread" and f.kind == "internal":
            ax, ay = f.at or (0.0, 0.0)
            callout = f"  # M{f.diameter}x{f.pitch} tapped (cosmetic)"
            if spec.shape in _FLAT_TOP and (ax, ay) == (0.0, 0.0):
                out.append(f'result = result.faces(">Z").workplane().hole({f.diameter}){callout}')
            elif spec.shape in _FLAT_TOP:
                out.append(f'result = result.faces(">Z").workplane().pushPoints([({ax}, {ay})]).hole({f.diameter}){callout}')
            else:
                out.append(_make_cylinder_cut(ax, ay, 0.0, f.diameter, "z", spec) + callout)

    # ---- counterbore / countersink (already idiomatic in emit_code) -----------------------
    for f in spec.features:
        if f.type == "counterbore":
            at = f.at or (0.0, 0.0)
            out.append(f'result = result.faces(">Z").workplane().pushPoints([({at[0]}, {at[1]})])'
                       f".cboreHole({f.diameter}, {f.cbore_diameter}, {f.cbore_depth})")
        elif f.type == "countersink":
            at = f.at or (0.0, 0.0)
            out.append(f'result = result.faces(">Z").workplane().pushPoints([({at[0]}, {at[1]})])'
                       f".cskHole({f.diameter}, {f.csk_diameter}, {f.csk_angle})")

    # ---- pockets (spec order; CenterOfBoundBox avoids the .center accumulation trap) ------
    for f in spec.features:
        if f.type == "pocket":
            ctr = f".center({f.at[0]}, {f.at[1]})" if f.at is not None else ""
            out.append(f'result = result.faces(">Z").workplane(centerOption="CenterOfBoundBox"){ctr}'
                       f".rect({f.length}, {f.width}).cutBlind(-{f.depth})")

    # ---- mirror LAST (reflect the fully-featured part, union into one symmetric solid) ----
    mir = next((f for f in spec.features if f.type == "mirror"), None)
    if mir is not None:
        out.append(f'result = result.mirror("{mir.plane}", union=True)')

    if var_fillet_used:
        out.insert(0, "from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet")
    return "\n".join(out)
