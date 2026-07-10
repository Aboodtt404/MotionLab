"""Feature-program part representation — schema + executor (build_part).

docs/research/track-a-feature-program-representation.md §3, §9 steps 1–2. Proves:
- backward compatibility: a single-primitive Spec transpiles to a one-step program that builds
  identically to build();
- the multi-step composition single primitives CANNOT represent (the bracket that capped the
  joint-mining keep-rate): plate + boss + drilled hole + slot;
- the CSG + sketch-extrude HYBRID: a sketched-profile body and a primitive solid in one program.

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.test_feature_program
"""
from __future__ import annotations

import math
import sys

from ..builder import build, build_part
from ..spec import Part, SketchExtrude, SketchLoop, Spec, Step, spec_to_part
from ..verifier import verify_part

PASS, FAIL = 0, 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")


def _vol(wp):
    return wp.val().Volume()


def _one_valid_solid(wp):
    s = wp.val()
    return s.isValid() and len(s.Solids()) == 1


def backward_compat():
    spec = Spec(object="plate", shape="box", envelope={"length": 100, "width": 60, "height": 10})
    direct, viaprog = _vol(build(spec)), _vol(build_part(spec_to_part(spec)))
    check("one-step box == build()", math.isclose(direct, viaprog, rel_tol=1e-6),
          f"{direct:.1f} vs {viaprog:.1f}")

    featured = Spec(object="drilled", shape="box",
                    envelope={"length": 40, "width": 40, "height": 10},
                    features=[{"type": "through_hole", "diameter": 8, "axis": "z"}])
    d2, p2 = _vol(build(featured)), _vol(build_part(spec_to_part(featured)))
    check("transpiled operand keeps its hole feature", math.isclose(d2, p2, rel_tol=1e-6),
          f"{d2:.1f} vs {p2:.1f}")


def carve_block():
    # NOTE origin conventions (doc §8): box builds CENTERED (z −10..10); cylinder builds
    # BASE-AT-z=0. So to drill fully through the centered box the ⌀10×40 drill is placed at z=−20
    # (spans −20..20). The executor places operands as built; the program author supplies `at`.
    part = Part(object="block with bore", steps=[
        Step(op="new_body", operand=Spec(object="block", shape="box",
                                         envelope={"length": 40, "width": 40, "height": 20})),
        Step(op="cut", operand=Spec(object="drill", shape="cylinder",
                                    envelope={"diameter": 10, "height": 40}), at=(0, 0, -20)),
    ])
    wp = build_part(part)
    expected = 40 * 40 * 20 - math.pi * 5 ** 2 * 20   # 20 mm of the drill lies inside the box
    check("box − cylinder is one valid solid", _one_valid_solid(wp))
    check("carved volume = box − bore", math.isclose(_vol(wp), expected, rel_tol=1e-3),
          f"{_vol(wp):.1f} vs {expected:.1f}")


def bracket_program():
    """The bracket that single-primitive fitting could not represent."""
    plate = Spec(object="plate", shape="box", envelope={"length": 100, "width": 60, "height": 10})
    boss = Spec(object="boss", shape="cylinder", envelope={"diameter": 24, "height": 25})
    hole = Spec(object="hole", shape="cylinder", envelope={"diameter": 10, "height": 60})
    slot = Spec(object="slot", shape="box", envelope={"length": 30, "width": 8, "height": 40})
    v_plate = 100 * 60 * 10

    # plate centered z −5..5; boss builds base-at-0, placed at z=0 so it OVERLAPS the plate (z 0..5)
    # and rises to z=25 — a real overlap gives a robust single-solid fuse (coincident faces are fragile).
    part = Part(object="bracket", steps=[
        Step(op="new_body", operand=plate),
        Step(op="join", operand=boss, at=(0, 0, 0)),
    ])
    v_boss = _vol(build_part(part))
    check("join grows the solid", v_boss > v_plate, f"{v_plate} → {v_boss:.1f}")

    part.steps.append(Step(op="cut", operand=hole, at=(0, 0, -30)))    # ⌀10 down the boss axis, through
    v_hole = _vol(build_part(part))
    check("cut (hole) shrinks the solid", v_hole < v_boss, f"{v_boss:.1f} → {v_hole:.1f}")

    part.steps.append(Step(op="cut", operand=slot, at=(35, 0, 0)))     # slot box is centered → z −20..20
    v_slot = _vol(build_part(part))
    check("cut (slot) shrinks further", v_slot < v_hole, f"{v_hole:.1f} → {v_slot:.1f}")

    wp = build_part(part)
    check("bracket is a single watertight solid", _one_valid_solid(wp))
    bb = wp.val().BoundingBox()
    check("boss reaches z=25", math.isclose(bb.zmax, 25, abs_tol=0.1), f"zmax={bb.zmax:.2f}")
    check("plate base at z=−5", math.isclose(bb.zmin, -5, abs_tol=0.1), f"zmin={bb.zmin:.2f}")


def hybrid_program():
    """CSG + sketch-extrude hybrid: a sketched profile_extrude body + a revolve boss + a cylinder cut."""
    # profile_extrude builds CENTERED: the L outline (x 0..60, z 0..40) → bbox x −30..30, z −20..20;
    # its riser (profile x 0..20, z 15..40) lands at x −30..−10, z −5..20. Boss (revolve, base-at-0)
    # is placed embedded in the riser top; hole runs vertically through the riser.
    lshape = Spec(object="L-body", shape="profile_extrude", envelope={"width": 20},
                  side_profile=[(0, 0), (60, 0), (60, 15), (20, 15), (20, 40), (0, 40)])
    boss = Spec(object="turned boss", shape="revolve",
                profile=[(0, 0), (10, 0), (10, 6), (5, 6), (5, 20), (0, 20)])
    hole = Spec(object="bore", shape="cylinder", envelope={"diameter": 6, "height": 80})
    part = Part(object="hybrid bracket", steps=[
        Step(op="new_body", operand=lshape),
        Step(op="join", operand=boss, at=(-20, 0, 10)),       # base z10 overlaps riser (z −5..20)
        Step(op="cut", operand=hole, at=(-20, 0, -40)),       # ⌀6 through riser + boss
    ])
    wp = build_part(part)
    check("hybrid (sketched body + primitive) is one valid solid", _one_valid_solid(wp))
    check("hybrid has positive volume", _vol(wp) > 0, f"{_vol(wp):.1f}")


def sketch_extrude_operand():
    """The general SketchExtrude operand (arbitrary-plane sketch): a rect+hole on XY, a rect on a
    tilted plane, and a clean JSON round-trip (corpus serialization via the discriminated union)."""
    rect = SketchLoop(outer=True, pts=[(-20, -10), (20, -10), (20, 10), (-20, 10)], arcs=[0, 0, 0])
    hole = SketchLoop(outer=False, circle=(0, 0, 3))
    se = SketchExtrude(plane=[(0, 0, 0), (1, 0, 0), (0, 0, 1)], loops=[rect, hole], distance=10.0)
    wp = build_part(Part(steps=[Step(op="new_body", operand=se)]))
    expected = 40 * 20 * 10 - math.pi * 9 * 10
    check("sketch_extrude rect+hole volume", math.isclose(_vol(wp), expected, rel_tol=1e-3),
          f"{_vol(wp):.1f} vs {expected:.1f}")
    check("sketch_extrude one valid solid", _one_valid_solid(wp))

    se2 = SketchExtrude(plane=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], loops=[rect], distance=10.0)
    bb = build_part(Part(steps=[Step(op="new_body", operand=se2)])).val().BoundingBox()
    check("tilted plane (normal +Y) bbox", math.isclose(bb.ylen, 10, abs_tol=0.1)
          and math.isclose(bb.zlen, 20, abs_tol=0.1), f"{bb.xlen:.0f}x{bb.ylen:.0f}x{bb.zlen:.0f}")

    part = Part(steps=[Step(op="new_body", operand=se)])
    rt = Part.model_validate(part.model_dump())
    check("discriminated-union JSON round-trip", isinstance(rt.steps[0].operand, SketchExtrude)
          and math.isclose(_vol(build_part(rt)), _vol(wp), rel_tol=1e-9))


def verifier_passes_bracket():
    """The measurement verifier passes a well-formed bracket: watertight, and every boolean step
    moved volume in the right direction."""
    plate = Spec(object="plate", shape="box", envelope={"length": 100, "width": 60, "height": 10})
    boss = Spec(object="boss", shape="cylinder", envelope={"diameter": 24, "height": 25})
    hole = Spec(object="hole", shape="cylinder", envelope={"diameter": 10, "height": 60})
    part = Part(object="bracket", steps=[
        Step(op="new_body", operand=plate),
        Step(op="join", operand=boss, at=(0, 0, 0)),
        Step(op="cut", operand=hole, at=(0, 0, -30)),
    ])
    rep = verify_part(part)
    check("well-formed bracket passes verify_part", rep.passed,
          f"cats={rep.failure_categories()}")


def verifier_catches_noop_cut():
    """The honesty check: a cut whose tool MISSES the body removes nothing → the verifier must flag
    'cut removes material' (this is the half-drilled-hole class of bug, caught at the step level)."""
    plate = Spec(object="plate", shape="box", envelope={"length": 40, "width": 40, "height": 10})
    miss = Spec(object="miss", shape="cylinder", envelope={"diameter": 6, "height": 10})
    part = Part(object="bad", steps=[
        Step(op="new_body", operand=plate),
        Step(op="cut", operand=miss, at=(500, 0, 0)),        # 500 mm away — cuts nothing
    ])
    rep = verify_part(part)
    noop = any(r.category == "boolean-noop" for r in rep.rows)
    check("no-op cut is flagged", noop and not rep.passed,
          f"passed={rep.passed} cats={rep.failure_categories()}")


def verifier_oracle_iou():
    """Oracle mode: a program that reconstructs a known target scores IoU→1; a mismatched one fails.
    Mirrors §5 — the reconstruction go/no-go and corpus-admission gate."""
    target = build(Spec(object="t", shape="box",
                        envelope={"length": 50, "width": 30, "height": 20})).val()
    good = Part(steps=[Step(op="new_body", operand=Spec(object="t", shape="box",
                                                        envelope={"length": 50, "width": 30, "height": 20}))])
    rep_good = verify_part(good, target=target)
    iou_good = next(r.measured for r in rep_good.rows if r.name == "recon · volume IoU")
    check("faithful reconstruction scores IoU≈1", iou_good >= 0.99 and rep_good.passed,
          f"IoU={iou_good}")

    bad = Part(steps=[Step(op="new_body", operand=Spec(object="t", shape="box",
                                                       envelope={"length": 50, "width": 30, "height": 12}))])
    rep_bad = verify_part(bad, target=target)
    iou_bad = next(r.measured for r in rep_bad.rows if r.name == "recon · volume IoU")
    check("wrong reconstruction fails the IoU gate", iou_bad < 0.95 and not rep_bad.passed,
          f"IoU={iou_bad}")


def main() -> int:
    print("=" * 60)
    print("FEATURE PROGRAM — schema + executor (build_part) + verify_part")
    print("=" * 60)
    for fn in (backward_compat, carve_block, bracket_program, hybrid_program, sketch_extrude_operand,
               verifier_passes_bracket, verifier_catches_noop_cut, verifier_oracle_iou):
        print(f"\n■ {fn.__name__}")
        fn()
    print("\n" + "=" * 60)
    print(f"FEATURE PROGRAM {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
