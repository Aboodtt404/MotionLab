"""profile_extrude — silhouette bodies (side X-Z extrude, optional ∩ plan X-Y).
Verifier-first: extents match the arc-aware profile math, the built solid is valid + single, the
2D simple-polygon gate rejects self-intersecting outlines, and — critically — emit_code() rebuilds
the SAME geometry (the corpus gates on the emitted artifact, so a builder↔emit divergence would
silently poison training data; see docs/research/track-a-silhouette-cutout-wheel.md §4).

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.test_profile_extrude
"""
from __future__ import annotations

import sys

import cadquery as cq

from ..builder import build, emit_code
from ..spec import Spec, profile_is_simple
from ..verifier import verify

PASS, FAIL = 0, 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")


def _bbox(wp):
    b = (wp.val() if isinstance(wp, cq.Workplane) else wp).BoundingBox()
    return b.xlen, b.ylen, b.zlen


def _exec_emit(spec):
    ns = {}
    exec(emit_code(spec), ns)                       # noqa: S102 — trusted, our own emitter
    return ns["result"]


# a crude but recognizable car SIDE silhouette (hood → windshield → roof → trunk), XZ
CAR_SIDE = [[0, 0], [4200, 0], [4200, 600], [3400, 700], [2600, 1200], [1200, 1250], [400, 900], [0, 700]]
CAR_PLAN = [[0, -500], [3600, -650], [4200, 0], [3600, 650], [0, 500]]   # top view, XY


def side_only():
    spec = Spec(object="car body", shape="profile_extrude", side_profile=CAR_SIDE, envelope={"width": 1400})
    wp = build(spec)
    dx, dy, dz = _bbox(wp)
    xl, yl, zl = spec.profile_extrude_extents()
    check("side-only builds one solid", len(wp.val().Solids()) == 1)
    rep = verify(wp, spec)
    check("side-only verify passes", rep.passed, f"solids={rep.solids} valid={rep.valid}")
    check("side-only extents match spec", abs(dx - xl) < 0.5 and abs(dy - yl) < 0.5 and abs(dz - zl) < 0.5,
          f"built=({dx:.0f},{dy:.0f},{dz:.0f}) spec=({xl:.0f},{yl:.0f},{zl:.0f})")
    check("side-only centered on origin (Y)", abs(wp.val().BoundingBox().center.y) < 0.5)
    # emit parity — the shipped artifact must reproduce the same envelope
    edx, edy, edz = _bbox(_exec_emit(spec))
    check("side-only emit_code geometry parity", abs(edx - dx) < 0.5 and abs(edy - dy) < 0.5 and abs(edz - dz) < 0.5,
          f"emit=({edx:.0f},{edy:.0f},{edz:.0f})")


def side_and_plan():
    spec = Spec(object="car body", shape="profile_extrude", side_profile=CAR_SIDE, plan_profile=CAR_PLAN, envelope={})
    wp = build(spec)
    dx, dy, dz = _bbox(wp)
    xl, yl, zl = spec.profile_extrude_extents()
    rep = verify(wp, spec)
    check("side∩plan verify passes", rep.passed, f"solids={rep.solids} valid={rep.valid}")
    check("side∩plan extents match spec (y trimmed to plan)", abs(dy - yl) < 0.5 and abs(dy - 1300) < 0.5,
          f"y built={dy:.0f} spec={yl:.0f}")
    check("side∩plan single solid", rep.solids == 1, f"solids={rep.solids}")
    edx, edy, edz = _bbox(_exec_emit(spec))
    check("side∩plan emit_code geometry parity", abs(edx - dx) < 0.5 and abs(edy - dy) < 0.5 and abs(edz - dz) < 0.5,
          f"emit=({edx:.0f},{edy:.0f},{edz:.0f}) build=({dx:.0f},{dy:.0f},{dz:.0f})")


def arc_roof():
    # a sagitta on the windshield→roof segment bows the roofline up past its chord
    side = [[0, 0], [4200, 0], [4200, 600], [3400, 700]]
    spec = Spec(object="fastback", shape="profile_extrude",
                side_profile=side + [[1200, 1250], [0, 700]],
                side_arcs=[0, 0, 0, -140, 0], envelope={"width": 1200})
    wp = build(spec)
    _, _, dz = _bbox(wp)
    _, _, zl = spec.profile_extrude_extents()
    check("arc'd roofline: extents count the bulge", abs(dz - zl) < 0.5 and dz > 1250,
          f"z built={dz:.1f} spec={zl:.1f}")
    check("arc'd roofline valid", verify(wp, spec).passed)


def rejects_self_intersection():
    bowtie = [[0, 0], [4200, 1200], [4200, 0], [0, 1200]]      # a crossed (bow-tie) outline
    check("bow-tie outline is NOT simple", not profile_is_simple(bowtie))
    spec = Spec(object="bad", shape="profile_extrude", side_profile=bowtie, envelope={"width": 1000})
    try:
        build(spec)
        check("self-intersecting side_profile rejected at build", False, "build did not raise")
    except ValueError as e:
        check("self-intersecting side_profile rejected at build", True, str(e)[:50])


def rejects_empty_intersection():
    # plan whose X range (5000..6000) doesn't overlap the side (0..4200) ⇒ empty ∩
    spec = Spec(object="bad", shape="profile_extrude", side_profile=CAR_SIDE,
                plan_profile=[[5000, -500], [6000, -500], [6000, 500], [5000, 500]], envelope={})
    try:
        build(spec)
        check("empty side∩plan rejected at build", False, "build did not raise")
    except ValueError as e:
        check("empty side∩plan rejected at build", True, str(e)[:50])


def main() -> int:
    print("=" * 60)
    print("PROFILE_EXTRUDE — silhouette bodies (side ∩ optional plan)")
    print("=" * 60)
    for fn in (side_only, side_and_plan, arc_roof, rejects_self_intersection, rejects_empty_intersection):
        print(f"\n■ {fn.__name__}")
        fn()
    print("\n" + "=" * 60)
    print(f"PROFILE_EXTRUDE {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
