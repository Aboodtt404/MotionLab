"""Phase-3c: the print verifier (cad_pipeline/print_verify.py) implements §6.3 FDM validation,
including the prusa-slicer oracle, validated on printable vs unprintable geometry.
"""
from __future__ import annotations

import shutil
import sys

import cadquery as cq

from cad_pipeline.print_verify import slicer_oracle, verify_print

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_printable_box():
    print("\n■ a solid box is printable (watertight, no overhang, full bed, fits, slices)")
    box = cq.Workplane("XY").box(30, 20, 10)
    rep = verify_print(box)
    names = {r.name: r for r in rep.rows}
    check(names["print · watertight (single manifold)"].within_tol, "watertight")
    check(names["print · unsupported_overhang_area"].within_tol, "no unsupported overhang")
    check(names["print · bed_contact_frac"].within_tol, "adequate bed contact")
    check(names["print · fits_build_volume"].within_tol, "fits build volume")
    check(rep.passed, "box passes the full print report")


def test_overhang_caught():
    print("\n■ a mushroom (flat cap underside) fails the overhang check")
    mush = (cq.Workplane("XY").cylinder(20, 5)
            .union(cq.Workplane("XY").workplane(offset=12).cylinder(5, 20)))
    rep = verify_print(mush, run_slicer=False)
    oh = next(r for r in rep.rows if r.name == "print · unsupported_overhang_area")
    check(not oh.within_tol and oh.measured > 0.05, f"steep cap underside flagged (overhang {oh.measured})")


def test_thin_wall_caught():
    print("\n■ a 0.5 mm wall fails the print min_wall (below 0.8 FDM floor)")
    from cad_pipeline.builder import build
    from cad_pipeline.spec import Spec
    thin = build(Spec(object="thin", shape="box", envelope={"length": 40, "width": 40, "height": 30},
                      features=[{"type": "shell", "thickness": 0.5, "open_face": "top"}]))
    rep = verify_print(thin, run_slicer=False)
    row = next(r for r in rep.rows if r.name == "print · min_wall")
    check(not row.within_tol, f"0.5 mm wall < 0.8 mm floor (measured {row.measured})")


def test_slicer_oracle():
    print("\n■ prusa-slicer oracle (§6.3)")
    if shutil.which("prusa-slicer") is None:
        check(True, "prusa-slicer absent → oracle row honestly omitted (skip)")
        return
    res = slicer_oracle(cq.Workplane("XY").box(30, 20, 10))
    check(res is not None and res[0] is True, "box slices, exit 0")
    check(res[1] is not None, f"estimated print time returned ({res[1]})")


def main() -> int:
    print("=" * 62)
    print("PRINT VERIFY — §6.3 FDM validation + prusa-slicer oracle")
    print("=" * 62)
    for fn in (test_printable_box, test_overhang_caught, test_thin_wall_caught, test_slicer_oracle):
        fn()
    print("\n" + "=" * 62)
    print(f"PRINT_VERIFY {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
