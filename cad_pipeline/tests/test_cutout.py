"""cutout mate — associative part-to-part carve (wheel arches, pockets, openings).
The cut is a POST-PLACEMENT modeling op (SolidWorks-Cavity pattern, research doc §2.2): the tool's
clearance-grown primitive is subtracted from the target after the solver places everything; the
tool stays a live movable part. Verifier-first: material removed, target NOT severed (an over-deep
carve splits it into pieces that are each individually valid — only the count catches it), and the
well genuinely admits the tool with its clearance as a MEASURED gap.

The main fixture is a ride-height mini-car: suspended chassis, 4 corner axles poking out of its
flanks, 4 grounded wheels tangent to the axle tips, a wide body whose flanks the wheels overlap —
UNTIL the arches carve them clear. Pre-cut this assembly fails interference; post-cut it passes
end-to-end. That is the whole point of the mate.

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.test_cutout
"""
from __future__ import annotations

import sys

from ..assembly import (Assembly, Component, Joint, Mate, build_assembly, solve_layout,
                        verify_assembly)
from ..spec import Spec

PASS, FAIL = 0, 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")


def _row(rep: dict, frag: str, frag2: str = "") -> dict:
    for r in rep["rows"]:
        if frag in r["name"] and frag2 in r["name"]:
            return r
    return {"within_tol": None, "measured": None, "expected": None}


def _mini_car() -> Assembly:
    chassis = Spec(object="chassis", shape="box", envelope={"length": 2000, "width": 700, "height": 80})
    body = Spec(object="body", shape="box", envelope={"length": 2000, "width": 1300, "height": 500})
    axle = Spec(object="axle", shape="cylinder", envelope={"diameter": 60, "height": 160})
    wheel = Spec(object="wheel", shape="cylinder", envelope={"diameter": 600, "height": 200})
    comps = [Component(name="chassis", role="base", part=chassis, at=(0, 0, 300)),
             Component(name="body", role="body", part=body)]
    axles = [f"{p}_axle" for p in ("front_left", "front_right", "rear_left", "rear_right")]
    wheels = [f"{p}_wheel" for p in ("front_left", "front_right", "rear_left", "rear_right")]
    comps += [Component(name=n, role="support", part=axle) for n in axles]
    comps += [Component(name=n, role="other", part=wheel) for n in wheels]
    mates = [Mate(kind="stack", a="body", b="chassis", overlap=3),
             Mate(kind="corners", parts=axles, around="chassis", dx=600, dy=420, axis="y", z=300),
             Mate(kind="corners", parts=wheels, around="chassis", dx=600, dy=600, axis="y"),
             *[Mate(kind="cutout", a=w, b="body", clearance=40) for w in wheels]]
    joints = [Joint(kind="revolute", a=w, b="chassis", axis="y", limits=(0, 360)) for w in wheels]
    return Assembly(object="mini car", components=comps, mates=mates, joints=joints)


def wheel_arches():
    asm = solve_layout(_mini_car())
    check("cutout mates survive the joint sanitizer",
          sum(1 for m in asm.mates if m.kind == "cutout") == 4)
    rep = verify_assembly(asm)
    for w in ("front_left_wheel", "rear_right_wheel"):
        check(f"arch carved for {w}", _row(rep, "cutout (", w)["within_tol"] is True,
              str(_row(rep, "cutout (", w)["measured"]))
    check("body intact after 4 arches (one solid)",
          _row(rep, "cutout target intact")["within_tol"] is True,
          f"solids={_row(rep, 'cutout target intact')['measured']}")
    gaps = [r for r in rep["rows"] if "cutout clearance" in r["name"]]
    check("all 4 arch gaps ≥ clearance (measured)", len(gaps) == 4 and all(r["within_tol"] for r in gaps),
          f"gaps={[r['measured'] for r in gaps]}")
    check("interference clean (wheels no longer inside the body)",
          _row(rep, "interference")["within_tol"] is True,
          f"worst={_row(rep, 'interference')['measured']}")
    check("pose sweep clean through the arches", _row(rep, "pose sweep")["within_tol"] is True)
    check("wheels still attached (tangent to axle tips)",
          all(r["within_tol"] for r in rep["rows"] if "joint attachment" in r["name"]))
    check("END-TO-END mini ride-height car passes", rep["passed"],
          str([r["name"] for r in rep["rows"] if not r["within_tol"]]))


def arch_actually_needed():
    """The same car WITHOUT the cutouts must FAIL interference — proving the arches (not a
    sanction) are what clear the wheels, i.e. the row can't be gamed by deleting the mate."""
    asm = _mini_car()
    asm.mates = [m for m in asm.mates if m.kind != "cutout"]
    rep = verify_assembly(solve_layout(asm))
    r = _row(rep, "interference")
    check("without arches the wheels collide with the body", r["within_tol"] is False,
          f"worst={r['measured']}")


def severed_target_caught():
    plate = Spec(object="plate", shape="box", envelope={"length": 400, "width": 100, "height": 20})
    post = Spec(object="post", shape="cylinder", envelope={"diameter": 60, "height": 200})
    asm = Assembly(components=[Component(name="plate", role="base", part=plate, at=(0, 0, 10)),
                               Component(name="post", role="other", part=post, at=(0, 0, -90))],
                   mates=[Mate(kind="ground", a="plate"),
                          Mate(kind="cutout", a="post", b="plate", clearance=60)])
    rep = verify_assembly(asm)
    r = _row(rep, "cutout target intact")
    check("over-deep carve SEVERS the plate — caught by solid count", r["within_tol"] is False,
          f"solids={r['measured']} (expected {r['expected']})")


def useless_cut_caught():
    plate = Spec(object="plate", shape="box", envelope={"length": 400, "width": 100, "height": 20})
    post = Spec(object="post", shape="cylinder", envelope={"diameter": 60, "height": 200})
    asm = Assembly(components=[Component(name="plate", role="base", part=plate, at=(0, 0, 10)),
                               Component(name="post", role="other", part=post, at=(1000, 0, 0))],
                   mates=[Mate(kind="ground", a="plate"),
                          Mate(kind="cutout", a="post", b="plate", clearance=5)])
    rep = verify_assembly(asm)
    r = _row(rep, "cutout (")
    check("carve that removes nothing FAILS honestly", r["within_tol"] is False,
          str(r["measured"])[:60])


def export_reflects_carve():
    asm = solve_layout(_mini_car())
    w = build_assembly(asm)
    vol_arched = w.val().Volume()
    asm2 = _mini_car()
    asm2.mates = [m for m in asm2.mates if m.kind != "cutout"]
    vol_plain = build_assembly(solve_layout(asm2)).val().Volume()
    check("exported geometry carries the arches (volume dropped)",
          vol_plain - vol_arched > 4 * 1e6,   # 4 real wheel wells, > 1 litre each
          f"Δ={(vol_plain - vol_arched) / 1e6:.1f}e6 mm³")


def main() -> int:
    print("=" * 60)
    print("CUTOUT — associative part-to-part carve (arches/pockets)")
    print("=" * 60)
    for fn in (wheel_arches, arch_actually_needed, severed_target_caught,
               useless_cut_caught, export_reflects_carve):
        print(f"\n■ {fn.__name__}")
        fn()
    print("\n" + "=" * 60)
    print(f"CUTOUT {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
