"""Assembly tests (non-gated, no model): the mate-graph layout solver, the bounded connectivity
repair, the structural-support check, and the edit-patch apply that back the planner.

Run:  python -m cad_pipeline.tests.test_assembly
"""
from __future__ import annotations

import sys

from ..assembly import (Assembly, AsmPatch, Component, Mate, apply_patch, repair_connectivity,
                        solve_layout, verify_assembly)
from ..spec import Spec


def _box(name, l, w, h, at=(0, 0, 0), role="other"):
    return Component(name=name, role=role, part=Spec(object=name, shape="box",
                     envelope={"length": l, "width": w, "height": h}), at=at)


def _cyl(name, d, h, role="other"):
    return Component(name=name, role=role, part=Spec(object=name, shape="cylinder",
                     envelope={"diameter": d, "height": h}))


def _row(rep, key):
    return next(r["within_tol"] for r in rep["rows"] if key in r["name"])


def t_solve_stool() -> bool:
    # the headline case: 4-legged stool via MATES → legs splayed at the rim, grounded, seat on top,
    # one connected solid, structurally supported (not a central clump).
    legs = [_box(f"leg{i+1}", 16, 16, 110, role="leg") for i in range(4)]
    asm = Assembly(object="stool", components=[_cyl("seat", 140, 16, role="seat")] + legs, mates=[
        Mate(kind="radial", parts=[f"leg{i+1}" for i in range(4)], around="seat", count=4, radius=52, splay_deg=10),
        Mate(kind="stack", a="seat", b="leg1", overlap=4)])
    asm = repair_connectivity(solve_layout(asm))
    rep = verify_assembly(asm)
    legxy = [(c.at[0], c.at[1]) for c in asm.components if c.role == "leg"]
    spread = max(x for x, _ in legxy) - min(x for x, _ in legxy)   # legs span in X (not clumped)
    seat_z = next(c.at[2] for c in asm.components if c.role == "seat")
    ok = (rep["solids"] == 1 and _row(rep, "structurally supported") and _row(rep, "valid")
          and spread > 80 and seat_z > 90)
    print(f"  [{'ok ' if ok else 'FAIL'}] stool: solids={rep['solids']} supported={_row(rep,'structurally supported')} "
          f"leg-spreadX={spread:.0f} seat_z={seat_z:.0f}")
    return ok


def t_solve_bracket_flush() -> bool:
    # an L-bracket: a horizontal top flush against the +z face of a vertical support → one solid.
    asm = Assembly(object="bracket", components=[
        _box("post", 16, 16, 80, role="support"), _box("shelf", 80, 16, 12, role="top")], mates=[
        Mate(kind="ground", a="post"), Mate(kind="flush", a="shelf", b="post", side="+z", overlap=4)])
    asm = repair_connectivity(solve_layout(asm))
    rep = verify_assembly(asm)
    ok = rep["solids"] == 1 and _row(rep, "valid")
    print(f"  [{'ok ' if ok else 'FAIL'}] bracket flush: solids={rep['solids']}")
    return ok


def t_repair_small_gap() -> bool:
    # bounded fallback: a SMALL joint gap (≤ cap) is still closed to one solid.
    asm = Assembly(object="t", fuse=True, components=[
        _box("hub", 40, 40, 10), _box("arm", 50, 10, 8, at=(50, 0, 0))])   # hub ends x=20, arm starts x=25 → 5mm gap
    before = verify_assembly(asm)["solids"]
    rep = verify_assembly(repair_connectivity(asm))
    ok = before >= 2 and rep["solids"] == 1 and _row(rep, "valid")
    print(f"  [{'ok ' if ok else 'FAIL'}] repair small gap: {before} -> {rep['solids']} solids")
    return ok


def t_repair_no_collapse() -> bool:
    # the anti-regression: parts placed FAR apart (a legitimate spread) must NOT be dragged together.
    asm = Assembly(object="t", fuse=True, components=[
        _box("core", 30, 30, 10), _box("far", 20, 20, 10, at=(120, 0, 0))])   # ~75mm gap ≫ cap
    asm2 = repair_connectivity(asm)
    moved = asm2.components[1].at[0] != 120
    ok = not moved   # left where it was (verifier will flag it disconnected) — no center-collapse
    print(f"  [{'ok ' if ok else 'FAIL'}] repair no-collapse: far part still at x={asm2.components[1].at[0]} (unmoved={not moved})")
    return ok


def t_patch_mates() -> bool:
    # edit patch can replace a component AND swap the mate graph.
    asm = Assembly(object="t", components=[_box("a", 10, 10, 10), _box("b", 10, 10, 10)],
                   mates=[Mate(kind="ground", a="a")])
    out = apply_patch(asm, AsmPatch(upsert=[_box("a", 20, 10, 10), _box("c", 8, 8, 20)], remove=["nope"],
                                    mates=[Mate(kind="ground", a="a"), Mate(kind="stack", a="c", b="a")]))
    names = [c.name for c in out.components]
    a = next(c for c in out.components if c.name == "a")
    ok = names == ["a", "b", "c"] and a.part.envelope["length"] == 20 and len(out.mates) == 2
    print(f"  [{'ok ' if ok else 'FAIL'}] patch+mates: names={names} a.len={a.part.envelope['length']} mates={len(out.mates)}")
    return ok


def main() -> int:
    print("ASSEMBLY — mate layout solver + bounded repair + structural check + edit patch:")
    checks = [t_solve_stool, t_solve_bracket_flush, t_repair_small_gap, t_repair_no_collapse, t_patch_mates]
    ok = sum(bool(c()) for c in checks)
    print(f"\nASSEMBLY {ok}/{len(checks)}")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
