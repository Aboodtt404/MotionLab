"""Phase-5 close-out: §1.3 part-tree decomposition — a prompt decomposes into a part tree with a
representation per part, and the engine builds every routed part.
"""
from __future__ import annotations

import sys

from cad_pipeline.schemas import AssemblyBrief, ModelBrief
from engine.decompose import decompose
from engine.engine import build_asset

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_drone_multi_rep():
    print("\n■ 'quadcopter drone' → part tree with per-part representation")
    brief = decompose("a quadcopter drone with a camera canopy")
    check(isinstance(brief, AssemblyBrief) and len(brief.components) == 6, "6 parts (frame+4 motors+canopy)")
    res = build_asset(brief)
    reps = {p.name: p.representation for p in res.parts}
    check(reps.get("quad frame plate") == "brep", "frame → brep")
    check(sum(1 for r in reps.values() if r == "library") == 4, "4 motors → library (catalog instances)")
    check(any(r == "mesh" for r in reps.values()), "organic canopy → mesh")
    inproc = [p for p in res.parts if p.representation in ("brep", "library")]
    check(all(p.passed for p in inproc), "all in-process (brep+library) parts verify")


def test_stool_and_gimbal():
    print("\n■ stool + gimbal templates")
    st = decompose("a 4-legged stool")
    check(len(st.components) == 5 and {m.kind for m in st.mates} == {"radial", "stack"}, "stool: 5 parts, radial+stack")
    gm = decompose("a 2-axis camera gimbal")
    check(isinstance(gm, AssemblyBrief) and len(gm.components) == 3, "gimbal: 3 parts")


def test_atomic_fallback():
    print("\n■ atomic prompt → single model_brief")
    sp = decompose("a 60 mm cylinder with a 20 mm bore")
    check(isinstance(sp, ModelBrief) and sp.shape == "cylinder", "cylinder atomic part")
    bx = decompose("a mounting bracket")
    check(isinstance(bx, ModelBrief) and bx.shape == "box", "bracket → box atomic part")


def main() -> int:
    print("=" * 60)
    print("DECOMPOSE — §1.3 part-tree decomposition → routed build")
    print("=" * 60)
    for fn in (test_drone_multi_rep, test_stool_and_gimbal, test_atomic_fallback):
        fn()
    print("\n" + "=" * 60)
    print(f"DECOMPOSE {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
