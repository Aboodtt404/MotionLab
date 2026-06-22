"""Verifier self-test (track-a-design.md §8).

Two halves, both required:
  GOLDEN — build known-good solids from specs; the verifier must measure them back
           to ~0 (proves it's correct before we trust it on model output).
  ADVERSARIAL — build deliberately-WRONG solids vs a correct spec; the verifier must
           REJECT each with the right failure category (proves the resolve-twice IP
           actually catches "wrong edges / wrong corner / extra feature", not just
           that golden passes). §3: a naive presence check would pass these.

Run:  python -m cad_pipeline.tests.selftest
"""
from __future__ import annotations

import math
import sys

import cadquery as cq

from ..assembly import Assembly, Component, verify_assembly
from ..builder import build
from ..spec import Spec
from ..verifier import Report, verify


def _quad_frame(arm_at: float) -> Assembly:
    """A hub plate + 4 radial arms (the start of a drone airframe). At arm_at=40 the arms
    overlap the hub → one fused solid; too far → disconnected."""
    plate = Spec(object="hub", shape="box", envelope={"length": 50, "width": 50, "height": 6})
    arm = Spec(object="arm", shape="box", envelope={"length": 60, "width": 10, "height": 6})
    comps = [Component(name="hub", part=plate)]
    for i, ang in enumerate((0, 90, 180, 270)):
        x, y = arm_at * math.cos(math.radians(ang)), arm_at * math.sin(math.radians(ang))
        comps.append(Component(name=f"arm{i}", part=arm, rotate=(0, 0, ang), at=(round(x, 3), round(y, 3), 0)))
    # blend the hub↔arm seams: a fused frame must read as one body, and the blend must keep it
    # a single valid solid (verify_assembly re-checks) — that's the joint-fillet contract.
    return Assembly(object="quad frame", components=comps, fillet_joints=2.0)


def _ribbed_plate() -> Assembly:
    """Ribs/gussets are composed from primitives (no native rib op — track-a-vocabulary §Tier2): a
    baseplate + thin stiffening webs, fused. The thin webs each dip into the plate so the result is
    one solid; verify_assembly checks per-web validity + connectivity + the joint blend."""
    plate = Spec(object="base", shape="box", envelope={"length": 80, "width": 60, "height": 6})
    web = Spec(object="rib", shape="box", envelope={"length": 80, "width": 3, "height": 20})
    comps = [Component(name="base", part=plate)]
    for i, y in enumerate((-18, 18)):   # two ribs straddling the plate, dipping 2 mm into it
        comps.append(Component(name=f"rib{i}", part=web, at=(0, y, 6 / 2 + 20 / 2 - 2)))
    return Assembly(object="ribbed plate", components=comps, fillet_joints=1.5)

GOLD_EPS = 1e-3

GOLDEN = [
    Spec(object="rectangular bracket", shape="box", envelope={"length": 80, "width": 50, "height": 30},
         features=[{"type": "fillet", "radius": 4, "edges": "all_vertical"}, {"type": "through_hole", "diameter": 12, "from_edge": 18}], tolerance=0.1),
    Spec(object="shaft collar", shape="cylinder", envelope={"diameter": 40, "height": 25},
         features=[{"type": "through_hole", "diameter": 12}], tolerance=0.1),
    Spec(object="mounting plate", shape="box", envelope={"length": 100, "width": 60, "height": 6},
         features=[{"type": "fillet", "radius": 5, "edges": "all_vertical"}, {"type": "through_hole", "diameter": 5, "from_edge": 20}], tolerance=0.1),
    Spec(object="chamfered block", shape="box", envelope={"length": 60, "width": 40, "height": 20},
         features=[{"type": "chamfer", "distance": 3, "edges": "all_vertical"}], tolerance=0.1),
    Spec(object="pocket plate", shape="box", envelope={"length": 100, "width": 60, "height": 10},
         features=[{"type": "pocket", "length": 40, "width": 24, "depth": 5}], tolerance=0.1),
    # --- L2/L3 multi-hole + pattern goldens ---
    Spec(object="4-hole mounting plate", shape="box", envelope={"length": 100, "width": 60, "height": 8},
         features=[{"type": "fillet", "radius": 4, "edges": "all_vertical"},
                   {"type": "through_hole", "diameter": 6, "at": [-35, -20]},
                   {"type": "through_hole", "diameter": 6, "at": [35, -20]},
                   {"type": "through_hole", "diameter": 6, "at": [-35, 20]},
                   {"type": "through_hole", "diameter": 6, "at": [35, 20]}], tolerance=0.1),
    Spec(object="bolt-circle flange", shape="cylinder", envelope={"diameter": 70, "height": 10},
         features=[{"type": "through_hole", "diameter": 12},
                   {"type": "hole_pattern", "pattern": "bolt_circle", "count": 6, "pitch_diameter": 50, "diameter": 6}], tolerance=0.1),
    Spec(object="linear vent panel", shape="box", envelope={"length": 90, "width": 30, "height": 6},
         features=[{"type": "hole_pattern", "pattern": "linear_x", "count": 5, "spacing": 15, "diameter": 4}], tolerance=0.1),
    # distinct-edge selectors + operation order (a lipped enclosure: rounded top rim, beveled base)
    Spec(object="lipped enclosure", shape="box", envelope={"length": 90, "width": 60, "height": 30},
         features=[{"type": "fillet", "radius": 5, "edges": "top"}, {"type": "chamfer", "distance": 3, "edges": "bottom"}], tolerance=0.1),
    # multi-axis / cross-drilled holes (Swiss-cheese class)
    Spec(object="cross-drilled block", shape="box", envelope={"length": 80, "width": 50, "height": 40},
         features=[{"type": "through_hole", "diameter": 10, "axis": "z", "at": [0, 0]},
                   {"type": "through_hole", "diameter": 8, "axis": "x", "at": [0, 0]}], tolerance=0.1),
    Spec(object="3-axis hub", shape="box", envelope={"length": 60, "width": 60, "height": 60},
         features=[{"type": "through_hole", "diameter": 8, "axis": "x", "at": [0, 0]},
                   {"type": "through_hole", "diameter": 8, "axis": "y", "at": [0, 0]},
                   {"type": "through_hole", "diameter": 8, "axis": "z", "at": [0, 0]}], tolerance=0.1),
    # tapered bar (engineered arm/strut) — the taper must measure exactly at BOTH ends
    Spec(object="tapered arm", shape="loft",
         envelope={"length": 200, "width": 30, "height": 15, "width_top": 16, "height_top": 10}, tolerance=0.1),
    # round↔rectangular transition (multi-profile loft) — rect base, circular tip (an adapter/duct)
    Spec(object="rect-round adapter", shape="loft",
         envelope={"length": 80, "width": 40, "height": 30, "diameter_top": 24}, tolerance=0.1),
    # variable-radius fillet (frontier, heuristic) — vertical edges blend r1=2 → r2=10
    Spec(object="var-fillet block", shape="box", envelope={"length": 60, "width": 40, "height": 30},
         features=[{"type": "var_fillet", "r1": 2, "r2": 10, "edges": "all_vertical"}], tolerance=0.1),
    # cosmetic threads — internal tapped hole and an external threaded stud; nominal ⌀ verified
    Spec(object="nut plate", shape="box", envelope={"length": 40, "width": 40, "height": 12},
         features=[{"type": "thread", "diameter": 12, "pitch": 1.75, "kind": "internal", "at": [0, 0]}], tolerance=0.1),
    Spec(object="threaded stud", shape="cylinder", envelope={"diameter": 16, "height": 30},
         features=[{"type": "thread", "diameter": 16, "pitch": 2.0, "kind": "external"}], tolerance=0.1),
    # turned bodies (revolve) — axisymmetry + envelope; a stepped hub and a tapered nozzle
    Spec(object="stepped hub", shape="revolve",
         profile=[(0, 0), (20, 0), (20, 10), (12, 10), (12, 30), (0, 30)], tolerance=0.1),
    Spec(object="tapered nozzle", shape="revolve",
         profile=[(0, 0), (20, 0), (20, 10), (8, 25), (8, 40), (0, 40)], tolerance=0.1),
    # drafted molding wall (DFM) — the side walls must measure the requested draft angle
    Spec(object="molded housing", shape="box", envelope={"length": 60, "width": 40, "height": 25},
         features=[{"type": "draft", "angle": 5}], tolerance=0.1),
    # counterbored + countersunk fastener holes — pilot bore + recess geometry must measure exactly
    Spec(object="counterbore plate", shape="box", envelope={"length": 50, "width": 50, "height": 20},
         features=[{"type": "counterbore", "diameter": 6, "cbore_diameter": 12, "cbore_depth": 4, "at": [0, 0]}], tolerance=0.1),
    Spec(object="countersink plate", shape="box", envelope={"length": 50, "width": 50, "height": 20},
         features=[{"type": "countersink", "diameter": 6, "csk_diameter": 12, "csk_angle": 90, "at": [0, 0]}], tolerance=0.1),
    # mirrored bracket — an off-center hole reflected about YZ ⇒ a left/right-symmetric part
    Spec(object="symmetric bracket", shape="box", envelope={"length": 80, "width": 40, "height": 20},
         features=[{"type": "through_hole", "diameter": 8, "at": [25, 0]}, {"type": "mirror", "plane": "YZ"}], tolerance=0.1),
    # shelled enclosures — thin-wall, top-open and sealed; the wall thickness must measure exactly
    Spec(object="open enclosure", shape="box", envelope={"length": 60, "width": 40, "height": 30},
         features=[{"type": "shell", "thickness": 3, "open_face": "top"}], tolerance=0.1),
    Spec(object="sealed hollow", shape="box", envelope={"length": 50, "width": 50, "height": 40},
         features=[{"type": "shell", "thickness": 2.5, "open_face": "none"}], tolerance=0.1),
    # swept tubes — a planar L-pipe and a non-planar 3D coolant line; effective bore must match
    Spec(object="L pipe", shape="sweep", envelope={"diameter": 10}, path=[(0, 0, 0), (60, 0, 0), (60, 0, 40)], tolerance=0.1),
    Spec(object="coolant line", shape="sweep", envelope={"diameter": 8}, path=[(0, 0, 0), (40, 0, 0), (40, 30, 0), (40, 30, 25)], tolerance=0.1),
    # paneled plate — two positioned insets + a panel-line groove (greeble detail); each pocket's
    # depth + footprint + POSITION must verify, and the .center trap must not drift the 2nd inset
    Spec(object="paneled plate", shape="box", envelope={"length": 100, "width": 60, "height": 8},
         features=[{"type": "pocket", "length": 24, "width": 24, "depth": 2, "at": [-28, 0]},
                   {"type": "pocket", "length": 24, "width": 24, "depth": 2, "at": [28, 0]},
                   {"type": "pocket", "length": 80, "width": 3, "depth": 1.5, "at": [0, -22]}], tolerance=0.1),
]


def _swept(path, d):
    pts = [cq.Vector(*p) for p in path]
    edges = [cq.Edge.makeLine(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    t0 = (pts[1] - pts[0]).normalized()
    return cq.Workplane(cq.Plane(origin=pts[0].toTuple(), normal=t0.toTuple())).circle(d / 2).sweep(
        cq.Workplane(obj=cq.Wire.assembleEdges(edges)), isFrenet=True)


def _revolved(profile, angle):
    wp = cq.Workplane("XY").polyline(profile).close().revolve(angle, (0, 0, 0), (0, 1, 0))
    return cq.Workplane(obj=wp.val().rotate((0, 0, 0), (1, 0, 0), 90))


_HUB = Spec(object="stepped hub", shape="revolve",
            profile=[(0, 0), (20, 0), (20, 10), (12, 10), (12, 30), (0, 30)], tolerance=0.1)
_WEDGE = Spec(object="quarter hub", shape="revolve", envelope={"angle": 90},
              profile=[(0, 0), (20, 0), (20, 30), (0, 30)], tolerance=0.1)

_BRACKET = Spec(object="rectangular bracket", shape="box", envelope={"length": 80, "width": 50, "height": 30},
                features=[{"type": "fillet", "radius": 4, "edges": "all_vertical"}, {"type": "through_hole", "diameter": 12, "from_edge": 18}], tolerance=0.1)


def _filleted_box():
    return cq.Workplane("XY").box(80, 50, 30).edges("|Z").fillet(4)


_FLANGE = Spec(object="bolt-circle flange", shape="cylinder", envelope={"diameter": 70, "height": 10},
               features=[{"type": "through_hole", "diameter": 12},
                         {"type": "hole_pattern", "pattern": "bolt_circle", "count": 6, "pitch_diameter": 50, "diameter": 6}], tolerance=0.1)


def _ring(pcd, n):
    rr = pcd / 2
    return [(rr * math.cos(2 * math.pi * k / n), rr * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _flange(bolt_pts):
    r = cq.Workplane("XY").circle(35).extrude(10).faces(">Z").workplane().hole(12)
    return r.faces(">Z").workplane().pushPoints(bolt_pts).hole(6)


# (label, correct spec, wrong-solid builder, expected failure category)
ADVERSARIAL = [
    ("hole in the WRONG corner (⌀ right, position wrong)", _BRACKET,
     lambda: _filleted_box().faces(">Z").workplane().pushPoints([(40 - 18, 0)]).hole(12), "selector-binding"),
    ("fillet on the WRONG (horizontal/top) edges", _BRACKET,
     lambda: cq.Workplane("XY").box(80, 50, 30).edges(">Z").fillet(4).faces(">Z").workplane().pushPoints([(-22, 0)]).hole(12), "selector-binding"),
    ("an EXTRA unspecified hole", _BRACKET,
     lambda: _filleted_box().faces(">Z").workplane().pushPoints([(-22, 0), (22, 0)]).hole(12), "selector-binding"),
    ("hole OVERSIZE (transcription error)", _BRACKET,
     lambda: _filleted_box().faces(">Z").workplane().pushPoints([(-22, 0)]).hole(13.0), "dimensional"),
    ("bolt circle MISSING one hole (5 of 6)", _FLANGE,
     lambda: _flange(_ring(50, 6)[:5]), "missing_feature"),
    ("bolt circle at the WRONG pitch diameter (60 vs 50)", _FLANGE,
     lambda: _flange(_ring(60, 6)), "selector-binding"),
    # distinct-edge resolve-twice: spec says fillet the TOP rim; wrong solid fillets the VERTICAL edges
    ("fillet on the WRONG edge set (vertical, not the top rim)",
     Spec(object="top-filleted plate", shape="box", envelope={"length": 80, "width": 50, "height": 20},
          features=[{"type": "fillet", "radius": 4, "edges": "top"}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(80, 50, 20).edges("|Z").fillet(4), "selector-binding"),
    # multi-axis resolve-twice: spec says an X-axis cross-hole; wrong solid drills it on Z
    ("hole on the WRONG axis (Z instead of the specified X)",
     Spec(object="cross-drilled bar", shape="box", envelope={"length": 80, "width": 50, "height": 40},
          features=[{"type": "through_hole", "diameter": 10, "axis": "x", "at": [0, 0]}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(80, 50, 40).faces(">Z").workplane().hole(10), "selector-binding"),
    # taper IGNORED: spec asks for a tapered arm (tip 16×10) but the solid is a straight bar —
    # the bbox matches at the base, so only the end-face cross-section check catches it
    ("taper ignored (straight bar built for a tapered-arm spec)",
     Spec(object="tapered arm", shape="loft",
          envelope={"length": 200, "width": 30, "height": 15, "width_top": 16, "height_top": 10}, tolerance=0.1),
     lambda: cq.Workplane("XY").box(200, 30, 15), "dimensional"),
    # NOT TURNED: a box with the hub's bounding box but no axisymmetry — only the revolve axis
    # check catches it (envelope ⌀/height both match the box)
    ("not turned (box built for a revolve-hub spec)", _HUB,
     lambda: cq.Workplane("XY").box(40, 40, 30), "selector-binding"),
    # WRONG ANGLE: a full 360° turn built where a 90° wedge was specified — caught by seam caps
    ("full turn built for a partial-wedge spec",
     _WEDGE, lambda: _revolved([(0, 0), (20, 0), (20, 30), (0, 30)], 360), "selector-binding"),
    # DRAFT IGNORED: spec asks for 5° draft but the solid has vertical (0°) walls — the envelope
    # matches; only the wall-tilt measurement catches it
    ("draft ignored (vertical-walled box built for a 5° draft spec)",
     Spec(object="molded housing", shape="box", envelope={"length": 60, "width": 40, "height": 25},
          features=[{"type": "draft", "angle": 5}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(60, 40, 25), "dimensional"),
    # COUNTERBORE MISSING RECESS: spec asks for a counterbore but the solid is a plain through-hole —
    # the pilot matches, only the missing recess cylinder catches it
    ("counterbore recess missing (plain hole built for a cbore spec)",
     Spec(object="counterbore plate", shape="box", envelope={"length": 50, "width": 50, "height": 20},
          features=[{"type": "counterbore", "diameter": 6, "cbore_diameter": 12, "cbore_depth": 4, "at": [0, 0]}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(50, 50, 20).faces(">Z").workplane().hole(6), "missing_feature"),
    # COUNTERSINK WRONG ANGLE: 82° seat built where 90° was specified — caught by the cone angle
    ("countersink wrong included angle (82° built for a 90° spec)",
     Spec(object="countersink plate", shape="box", envelope={"length": 50, "width": 50, "height": 20},
          features=[{"type": "countersink", "diameter": 6, "csk_diameter": 12, "csk_angle": 90, "at": [0, 0]}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(50, 50, 20).faces(">Z").workplane().cskHole(6, 12, 82), "dimensional"),
    # NOT MIRRORED: spec asks for a symmetric (mirrored) part but the solid keeps the single
    # off-center hole — only the symmetry check catches the asymmetry
    ("mirror ignored (asymmetric part built for a mirror spec)",
     Spec(object="symmetric bracket", shape="box", envelope={"length": 80, "width": 40, "height": 20},
          features=[{"type": "through_hole", "diameter": 8, "at": [25, 0]}, {"type": "mirror", "plane": "YZ"}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(80, 40, 20).faces(">Z").workplane().pushPoints([(25, 0)]).hole(8), "selector-binding"),
    # SHELL IGNORED: a solid box built where a thin-wall shell was specified — the thinnest "wall"
    # reads as the min outer dimension (≫ t), so the wall-thickness check catches it
    ("shell ignored (solid box built for a thin-wall spec)",
     Spec(object="open enclosure", shape="box", envelope={"length": 60, "width": 40, "height": 30},
          features=[{"type": "shell", "thickness": 3, "open_face": "top"}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(60, 40, 30), "dimensional"),
    # SWEEP WRONG BORE: a ⌀14 tube built where ⌀10 was specified — the volume-derived ⌀ catches it
    ("sweep wrong bore (⌀14 built for a ⌀10 spec)",
     Spec(object="L pipe", shape="sweep", envelope={"diameter": 10}, path=[(0, 0, 0), (60, 0, 0), (60, 0, 40)], tolerance=0.1),
     lambda: _swept([(0, 0, 0), (60, 0, 0), (60, 0, 40)], 14), "dimensional"),
    # PANEL INSET MIS-PLACED: spec puts the inset at +Y, the solid cuts it at −Y — the pocket
    # position check catches it (footprint + depth still match)
    ("panel inset mis-placed (cut at −Y where +Y was specified)",
     Spec(object="panel", shape="box", envelope={"length": 100, "width": 60, "height": 8},
          features=[{"type": "pocket", "length": 24, "width": 24, "depth": 2, "at": [28, 15]}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(100, 60, 8).faces(">Z").workplane(centerOption="CenterOfBoundBox").center(28, -15).rect(24, 24).cutBlind(-2), "selector-binding"),
    # THREAD WRONG BORE: a ⌀10 hole built where an M12 tapped hole was specified — nominal ⌀ catches it
    ("thread wrong bore (⌀10 built for an M12 spec)",
     Spec(object="nut plate", shape="box", envelope={"length": 40, "width": 40, "height": 12},
          features=[{"type": "thread", "diameter": 12, "pitch": 1.75, "kind": "internal", "at": [0, 0]}], tolerance=0.1),
     lambda: cq.Workplane("XY").box(40, 40, 12).faces(">Z").workplane().hole(10), "missing_feature"),
]


def show_golden(spec: Spec, rep: Report) -> bool:
    print(f"\n■ {spec.object}  [{spec.shape}]  tol ±{spec.tolerance}   valid={rep.valid} solids={rep.solids}")
    golden = rep.passed
    for r in rep.rows:
        meas = "—" if r.measured is None else (f"{r.measured:.3f}" if isinstance(r.measured, float) else str(r.measured))
        d = "" if r.delta is None else f"  Δ{r.delta:+.3f}"
        print(f"   {'✓' if r.within_tol else '✗'} {r.name:<26} exp {r.expected}  meas {meas}{d}  [{r.category}]")
        # heuristic rows (curvature-sampled, marked "≈") are judged by within_tol, not the exact
        # 1e-3 floor the analytic measurements meet.
        if r.delta is not None and abs(r.delta) > GOLD_EPS and "≈" not in r.name:
            golden = False
    print(f"   → {'GOLDEN OK' if golden else 'GOLDEN FAIL'}")
    return golden


def main() -> int:
    print("=" * 60 + "\nGOLDEN — known-good solids must verify exactly\n" + "=" * 60)
    g_fail = sum(0 if show_golden(s, verify(build(s), s)) else 1 for s in GOLDEN)

    print("\n" + "=" * 60 + "\nADVERSARIAL — wrong solids must be CAUGHT (resolve-twice)\n" + "=" * 60)
    a_fail = 0
    for label, spec, wrong, want_cat in ADVERSARIAL:
        rep = verify(wrong(), spec)
        cats = rep.failure_categories()
        caught = (not rep.passed) and (want_cat in cats)
        print(f"\n■ {label}")
        bad = [r for r in rep.rows if not r.within_tol]
        for r in bad:
            print(f"   ✗ {r.name:<26} exp {r.expected}  meas {r.measured}  [{r.category}]")
        print(f"   → {'CAUGHT ✓' if caught else 'MISSED ✗'}  (expected {want_cat}; got {cats or 'PASSED — bad!'})")
        if not caught:
            a_fail += 1

    print("\n" + "=" * 60 + "\nASSEMBLY — fused multi-part frame: connectivity + validity\n" + "=" * 60)
    asm_fail = 0
    connected = verify_assembly(_quad_frame(40))   # arms overlap the hub → one solid
    print(f"\n■ quad frame (connected)   passed={connected['passed']} solids={connected['solids']} "
          f"env={tuple(round(connected['envelope'][k], 0) for k in ('dx', 'dy', 'dz'))}")
    if not connected["passed"]:
        asm_fail += 1
    disconnected = verify_assembly(_quad_frame(80))  # arms float free → must be caught
    caught = (not disconnected["passed"]) and any(r["category"] == "disconnected" for r in disconnected["rows"])
    print(f"■ quad frame (arms too far) → {'CAUGHT ✓' if caught else 'MISSED ✗'} (solids={disconnected['solids']}, expected 1)")
    if not caught:
        asm_fail += 1
    ribbed = verify_assembly(_ribbed_plate())   # ribs/gussets = fused thin-web composition
    print(f"■ ribbed plate (gusset webs)   passed={ribbed['passed']} solids={ribbed['solids']}")
    if not ribbed["passed"]:
        asm_fail += 1

    print("\n" + "=" * 60)
    print(f"GOLDEN {len(GOLDEN) - g_fail}/{len(GOLDEN)} exact   ·   ADVERSARIAL {len(ADVERSARIAL) - a_fail}/{len(ADVERSARIAL)} caught   ·   ASSEMBLY {3 - asm_fail}/3")
    ok = g_fail == 0 and a_fail == 0 and asm_fail == 0
    print("ALL GOOD ✓" if ok else "FAILURES ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
