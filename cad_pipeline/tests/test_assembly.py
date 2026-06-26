"""Assembly-reliability tests (non-gated, no model): the deterministic connectivity repair and the
edit-patch apply that back the planner upgrade.

Run:  python -m cad_pipeline.tests.test_assembly
"""
from __future__ import annotations

import sys

from ..assembly import Assembly, AsmPatch, Component, apply_patch, repair_connectivity, verify_assembly
from ..spec import Spec


def _box(name, l, w, h, at=(0, 0, 0)):
    return Component(name=name, part=Spec(object=name, shape="box",
                     envelope={"length": l, "width": w, "height": h}), at=at)


def t_repair_gap() -> bool:
    # hub + an arm placed with a 15mm GAP → 2 solids; repair must snap it to 1 connected valid solid.
    asm = Assembly(object="t", fuse=True, components=[
        _box("hub", 40, 40, 10), _box("arm", 50, 10, 8, at=(60, 0, 0))])   # hub ends x=20, arm starts x=35
    before = verify_assembly(asm)["solids"]
    asm = repair_connectivity(asm)
    rep = verify_assembly(asm)
    ok = before >= 2 and rep["solids"] == 1 and next(r["within_tol"] for r in rep["rows"] if "valid" in r["name"])
    print(f"  [{'ok ' if ok else 'FAIL'}] repair: {before} solids -> {rep['solids']} (valid)")
    return ok


def t_repair_multi() -> bool:
    # three boxes, two of them floating away → repair must pull both into one solid.
    asm = Assembly(object="t", fuse=True, components=[
        _box("core", 40, 40, 10), _box("a", 30, 10, 8, at=(70, 0, 0)), _box("b", 10, 30, 8, at=(0, 70, 0))])
    asm = repair_connectivity(asm)
    rep = verify_assembly(asm)
    ok = rep["solids"] == 1
    print(f"  [{'ok ' if ok else 'FAIL'}] repair multi: solids={rep['solids']}")
    return ok


def t_patch() -> bool:
    asm = Assembly(object="t", fuse=True, components=[_box("hub", 40, 40, 10), _box("arm", 50, 10, 8)])
    # replace 'arm' (by name), add 'fin', remove 'nope' (absent → no-op)
    patch = AsmPatch(upsert=[_box("arm", 60, 12, 8), _box("fin", 8, 8, 20)], remove=["nope"])
    out = apply_patch(asm, patch)
    names = [c.name for c in out.components]
    arm = next(c for c in out.components if c.name == "arm")
    ok = names == ["hub", "arm", "fin"] and arm.part.envelope["length"] == 60   # replaced, not duplicated
    print(f"  [{'ok ' if ok else 'FAIL'}] patch: names={names} arm.len={arm.part.envelope['length']}")
    return ok


def t_patch_remove() -> bool:
    asm = Assembly(object="t", fuse=True, components=[_box("a", 10, 10, 10), _box("b", 10, 10, 10)])
    out = apply_patch(asm, AsmPatch(remove=["a"]))
    ok = [c.name for c in out.components] == ["b"]
    print(f"  [{'ok ' if ok else 'FAIL'}] patch remove: {[c.name for c in out.components]}")
    return ok


def main() -> int:
    print("ASSEMBLY reliability — connectivity repair + edit patch:")
    checks = [t_repair_gap, t_repair_multi, t_patch, t_patch_remove]
    ok = sum(bool(c()) for c in checks)
    print(f"\nASSEMBLY {ok}/{len(checks)}")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
