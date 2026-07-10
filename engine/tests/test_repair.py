"""Phase-5b: the repair loop over routed builds — typed feedback (46-mistake catalog) for every
failing row, and deterministic assembly-level repair (A3 interference → clearance) that closes the loop.
"""
from __future__ import annotations

import sys

import trimesh

from cad_pipeline.schemas import AssemblyBrief, BriefComponent, ModelBrief
from engine.builders import BuiltPart
from engine.repair import repair_asset, typed_feedback

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_typed_feedback():
    print("\n■ typed feedback maps failing rows → the 46-mistake catalog repair strings")
    rows = [{"name": "assembly · pairwise interference (bbox)", "within_tol": False, "category": "integrity"},
            {"name": "holes · position (worst)", "within_tol": False, "category": "selector_binding"}]
    fb = typed_feedback(rows)
    check(any("clearance" in f for f in fb), "interference → A3 'add clearance' feedback")
    check(any("selector" in f for f in fb), "selector_binding → C4 'fix the selector' feedback")


def test_interference_repair_closes():
    print("\n■ A3 interference repair: two overlapping parts → declump → passes")
    # two parts, NO mate → solve_layout leaves both at the origin → they interfere
    a = ModelBrief(brief_id="a", name="block a", target_use="cad", representation="mesh",
                   units="mm", up_axis="z", envelope_mm={"length": 40, "width": 40, "height": 40})
    b = ModelBrief(brief_id="b", name="block b", target_use="cad", representation="mesh",
                   units="mm", up_axis="z", envelope_mm={"length": 40, "width": 40, "height": 40})
    brief = AssemblyBrief(brief_id="ab", name="two blocks", units="mm", components=[
        BriefComponent(component_id="a", role="body", brief=a),
        BriefComponent(component_id="b", role="body", brief=b)], mates=[])
    injected = {"a": BuiltPart("a", "mesh", True, {"passed": True}, trimesh.creation.box((40, 40, 40))),
                "b": BuiltPart("b", "mesh", True, {"passed": True}, trimesh.creation.box((40, 40, 40)))}

    # before repair: interference present
    from engine.assemble import assemble
    pre = assemble(brief, built=injected)
    pre_int = next(r for r in pre.rows if "interference" in r["name"])
    check(not pre_int["within_tol"], f"parts overlap before repair (overlap {pre_int['measured']})")

    injected2 = {"a": BuiltPart("a", "mesh", True, {"passed": True}, trimesh.creation.box((40, 40, 40))),
                 "b": BuiltPart("b", "mesh", True, {"passed": True}, trimesh.creation.box((40, 40, 40)))}
    res = repair_asset(brief, built=injected2, max_rounds=2)
    check(res.rounds >= 2, f"repair ran a second round ({res.rounds})")
    post_int = next(r for r in res.asset.rows if "interference" in r["name"])
    check(post_int["within_tol"], f"interference cleared after declump (overlap {post_int['measured']})")
    check(res.passed, "asset passes after repair")


def main() -> int:
    print("=" * 62)
    print("REPAIR LOOP — typed feedback + deterministic assembly repair")
    print("=" * 62)
    for fn in (test_typed_feedback, test_interference_repair_closes):
        fn()
    print("\n" + "=" * 62)
    print(f"REPAIR {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
