"""Kinematic assembly tests (non-gated, no model) — benchmark §A transcribed onto the new
verifier rows (DOF accounting, pose sweep, interference, statics, frame hierarchy).

Source: fable_run/out/02_benchmark.md §A (Assemblies, mates & joints, A01–A13). Transcribed
here: A03-lite (hinge: 1 revolute DOF + swept clearance), A09 (PCB standoffs via parent
frames), A10-lite (2R arm: rest-pose reach + DOF bookkeeping), + joint auto-placement and
the arc-meridian continuity fixtures, and A6 (pin/bore running-fit rows — joint_fit_a6).
Not transcribable in v1 (documented gaps): A05/A13 (gear teeth not in the shape vocabulary),
A07 (prismatic joint), full A10 sweep (chained-joint posing — v1 poses each joint independently).

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.test_kinematic
"""
from __future__ import annotations

import sys

from ..assembly import (Assembly, AsmPatch, Component, Joint, Mate, apply_patch,
                        _place_world, _bare_solid, _solid_gap, build_assembly,
                        solve_layout, verify_assembly)
from ..builder import build
from ..spec import Spec
from ..verifier import verify

PASS, FAIL = 0, 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")


def _row(rep: dict, key: str) -> dict:
    return next(r for r in rep["rows"] if key in r["name"])


def _post() -> Component:
    return Component(name="post", role="support",
                     part=Spec(object="post", shape="box", envelope={"length": 10, "width": 10, "height": 100}),
                     at=(0, 0, 50))


def _door(x: float = 85.0) -> Component:
    return Component(name="door", role="panel",
                     part=Spec(object="door", shape="box", envelope={"length": 80, "width": 6, "height": 90}),
                     at=(x, 0, 50))


def hinge_golden() -> None:
    """A03-lite: hinge = 2 rigid groups sharing an axis, exactly 1 DOF, clearance holds over
    the whole motion range (gap(θ) > 0 ∀θ), bodies stay separate in the built compound."""
    # door edge 0.3 mm off the post face — physically HUNG, not hovering (the attachment row
    # rightly failed the old 40 mm-away door; a hinge's sides must meet)
    asm = Assembly(object="hinged door", components=[_post(), _door(x=45.3)], fuse=True,
                   joints=[Joint(a="door", b="post", axis="z", at=(5.3, 10, 50), limits=(0, 90))])
    rep = verify_assembly(asm)
    check("hinge passes end-to-end", rep["passed"],
          str([r["name"] for r in rep["rows"] if not r["within_tol"]]))
    check("2 rigid groups (not welded across the joint)",
          _row(rep, "connectivity")["expected"] == 2 and _row(rep, "connectivity")["measured"] == 2)
    check("DOF row: 1 movable / 1 joint", _row(rep, "DOF")["measured"] == 1 and _row(rep, "DOF")["within_tol"])
    check("pose sweep clean over (0°, 45°, 90°)", _row(rep, "pose sweep")["measured"] <= 1.0)
    n = len(build_assembly(asm).val().Solids())
    check("build_assembly emits posed separate bodies", n == 2, f"solids={n}")


def hinge_smash() -> None:
    """Adversarial A03: an obstacle inside the swing range — invisible at rest pose, caught by
    the configuration-space sweep (the concentric-circles lesson: clearance ∀θ, not at θ=0)."""
    wall = Component(name="wall", role="panel",
                     part=Spec(object="wall", shape="box", envelope={"length": 80, "width": 10, "height": 100}),
                     at=(45, 60, 50))
    asm = Assembly(object="door into wall", components=[_post(), _door(), wall], fuse=True,
                   mates=[Mate(kind="flush", a="wall", b="post", side="+y", overlap=2)],
                   joints=[Joint(a="door", b="post", axis="z", at=(45, 10, 50), limits=(0, 180))])
    rep = verify_assembly(asm)
    sweep = _row(rep, "pose sweep")
    check("swing collision CAUGHT by sweep", not sweep["within_tol"] and sweep["measured"] > 100,
          f"∩ {sweep['measured']} mm³")
    check("rest-pose interference alone would MISS it", _row(rep, "interference")["within_tol"])


def hinge_welded() -> None:
    """Adversarial: a joint whose sides a mate already welded — over-constrained (0 DOF)."""
    body = Component(name="body", role="body",
                     part=Spec(object="body", shape="box", envelope={"length": 40, "width": 40, "height": 50}), at=(0, 0, 25))
    lid = Component(name="lid", role="top",
                    part=Spec(object="lid", shape="box", envelope={"length": 40, "width": 40, "height": 6}), at=(0, 0, 53))
    asm = Assembly(object="welded hinge", components=[body, lid], fuse=True,
                   mates=[Mate(kind="stack", a="lid", b="body", overlap=2)],
                   joints=[Joint(a="lid", b="body", axis="y", limits=(0, 90))])
    dof = _row(verify_assembly(asm), "DOF")
    check("over-constraint CAUGHT (welded hinge = 0 DOF)",
          not dof["within_tol"] and dof["measured"] == 0 and "over-constrained" in dof["name"])


def joint_autoplacement() -> None:
    """solve_layout must pull a joint's moving side to a RUNNING CLEARANCE (~0.3 mm, fit band
    A6), never a weld — derived adjacency, not a guessed coordinate."""
    asm = Assembly(object="autoplaced hinge", components=[_post(), _door(x=120.0)], fuse=True,
                   joints=[Joint(a="door", b="post", axis="z", limits=(0, 90))])
    asm = solve_layout(asm)
    comps = {c.name: c for c in asm.components}
    d, _ = _solid_gap(_place_world(_bare_solid(comps["door"].part), comps["door"], comps),
                      _place_world(_bare_solid(comps["post"].part), comps["post"], comps))
    check("moving side landed at the fit-band gap", 0.2 <= d <= 0.4, f"gap {d:.3f} mm")


def pcb_standoffs() -> None:
    """A09: enclosure floor + 4 standoffs (PARENTED — placed once in the enclosure frame) + PCB
    stacked on them. Frame hierarchy + statics + non-mated clearance all in one fixture."""
    # standoff `at` is LOCAL to enc's frame (enc center sits at world z=2, so local z=2 puts the
    # standoff base exactly on the enclosure top at world z=4) — the frame-hierarchy contract.
    standoffs = [Component(name=f"so{i}", role="support", parent="enc",
                           part=Spec(object="standoff", shape="cylinder", envelope={"diameter": 6, "height": 5}),
                           at=(x, y, 2))
                 for i, (x, y) in enumerate([(-35, -25), (35, -25), (-35, 25), (35, 25)])]
    asm = Assembly(object="pcb on standoffs", components=[
        Component(name="enc", role="base",
                  part=Spec(object="enclosure floor", shape="box", envelope={"length": 90, "width": 70, "height": 4}), at=(0, 0, 2)),
        *standoffs,
        Component(name="pcb", role="panel",
                  part=Spec(object="pcb", shape="box", envelope={"length": 80, "width": 60, "height": 1.6})),
    ], mates=[Mate(kind="ground", a="enc"),
              # stack onto a corner standoff, offset back to the board center so it rests on all 4
              Mate(kind="stack", a="pcb", b="so0", overlap=0.1, offset=(35, 25))])
    asm = solve_layout(asm)
    rep = verify_assembly(asm)
    check("A09 assembly verifies", rep["passed"])
    comps = {c.name: c for c in asm.components}
    w = _place_world(_bare_solid(comps["so3"].part), comps["so3"], comps).BoundingBox().center
    check("standoff placed through the parent frame", abs(w.x - 35) < 1e-6 and abs(w.y - 25) < 1e-6,
          f"so3 world ({w.x:.1f}, {w.y:.1f})")


def arm_2r() -> None:
    """A10-lite: base + 2 links on two revolutes — DOF bookkeeping (2/2) + straight-pose reach.
    (Full chained sweep is the documented v1 gap: joints pose independently.)"""
    base = Component(name="base", role="base",
                     part=Spec(object="base", shape="cylinder", envelope={"diameter": 40, "height": 20}))
    l1 = Component(name="l1", role="arm",
                   part=Spec(object="link1", shape="box", envelope={"length": 120, "width": 16, "height": 12}),
                   at=(80.3, 0, 26))
    l2 = Component(name="l2", role="arm",
                   part=Spec(object="link2", shape="box", envelope={"length": 90, "width": 16, "height": 12}),
                   at=(185.6, 0, 26))
    asm = Assembly(object="2R arm", components=[base, l1, l2], fuse=True,
                   mates=[Mate(kind="ground", a="base")],
                   joints=[Joint(a="l1", b="base", axis="z", limits=(0, 0)),
                           Joint(a="l2", b="l1", axis="z", limits=(0, 0))])
    rep = verify_assembly(asm)
    dof = _row(rep, "DOF")
    check("2R arm: DOF 2/2", dof["measured"] == 2 and dof["within_tol"])
    check("3 rigid groups", _row(rep, "connectivity")["measured"] == 3)
    reach = rep["envelope"]["dx"]
    # dx spans the base's LEFT radius too: −20 … (20 + 0.3 + 120 + 0.3 + 90) = 250.6
    check("straight-pose reach = base ⌀/2 + links + fit gaps", 250 <= reach <= 251.5, f"dx {reach:.1f}")


def arc_meridians() -> None:
    """Continuity vocabulary (§5): arcs revolve to analytic spheres/tori and verify exactly."""
    barrel = Spec(object="barrel", shape="revolve",
                  profile=[(0, 0), (20, 0), (20, 40), (0, 40)], profile_arcs=[0, -5.0, 0])
    rep = verify(build(barrel), barrel)
    check("barrel (torus bulge) verifies, ⌀ includes apex",
          rep.passed and any(r.name == "envelope · ⌀" and r.expected == 50.0 for r in rep.rows))
    dome = Spec(object="dome", shape="revolve",
                profile=[(0, 0), (30, 0), (0, 30)], profile_arcs=[0, -8.7868])
    check("dome (sphere cap) verifies", verify(build(dome), dome).passed)


def joints_patch() -> None:
    """The edit loop can now change moving connections: AsmPatch.joints replaces the joint list."""
    asm = Assembly(object="hinged door", components=[_post(), _door()], fuse=True,
                   joints=[Joint(a="door", b="post", axis="z", at=(45, 10, 50), limits=(0, 90))])
    out = apply_patch(asm, AsmPatch(joints=[Joint(a="door", b="post", axis="z", at=(45, 10, 50), limits=(0, 120))]))
    check("patch replaced joint limits", out.joints[0].limits == (0, 120))
    out2 = apply_patch(asm, AsmPatch(remove=["door"]))
    check("patch without joints leaves them untouched", len(out2.joints) == 1)


def joint_fit_a6() -> None:
    """Mistakes catalog A6: pin ⌀ == bore ⌀ models a seized joint. The fit row measures the
    diametral clearance at the revolute's concentric pin/bore interface (manual §3.2 running
    band 0.1–0.8 mm) — seized and sloppy both fail, a proper running fit passes."""
    def hinge(bore_d: float) -> Assembly:
        return Assembly(object="pin hinge", fuse=True, components=[
            Component(name="bracket", role="base",
                      part=Spec(object="bracket", shape="box",
                                envelope={"length": 40, "width": 30, "height": 20},
                                features=[{"type": "through_hole", "diameter": bore_d, "axis": "z"}]),
                      at=(0, 0, 0)),
            Component(name="pin_arm", role="arm",
                      part=Spec(object="pin", shape="cylinder",
                                envelope={"diameter": 6.0, "height": 40}, features=[]),
                      at=(0, 0, -10)),
        ], joints=[Joint(a="pin_arm", b="bracket", axis="z")])

    def fit_row(bore_d: float):
        rep = verify_assembly(hinge(bore_d))
        return next((r for r in rep["rows"] if "joint fit" in r["name"]), None)

    seized = fit_row(6.0)
    check("seized fit (bore == pin) caught", seized is not None and not seized["within_tol"]
          and seized["category"] == "fit" and seized["measured"] == 0.0)
    running = fit_row(6.2)
    check("running fit 0.2 mm passes", running is not None and running["within_tol"])
    sloppy = fit_row(7.5)
    check("sloppy fit 1.5 mm caught", sloppy is not None and not sloppy["within_tol"])


def car_corners() -> None:
    """The vehicle pattern: `corners` mates (wheelbase×track rectangle, NOT a radial circle) —
    axles welded into the chassis sides + sideways wheels (axis 'y') whose inner faces MEET the
    axle tips, one revolute per wheel. Geometry is derived in the fixture (dy_wheel = dy_axle +
    axle_len/2 + wheel_w/2; ≥ body_w/2 + wheel_w/2) so the whole car passes by construction,
    including the joint-ATTACHMENT row — and name-aware corner assignment puts front_left at
    (+x, +y) regardless of list order."""
    wheels = ["rear_right_wheel", "front_left_wheel", "rear_left_wheel", "front_right_wheel"]  # shuffled on purpose
    axles = ["front_left_axle", "front_right_axle", "rear_left_axle", "rear_right_axle"]
    asm = Assembly(object="test car", fuse=True, components=[
        Component(name="chassis", role="base",
                  part=Spec(object="chassis", shape="box",
                            envelope={"length": 4200, "width": 1400, "height": 60}), at=(0, 0, 30)),
        Component(name="body", role="body",
                  part=Spec(object="body", shape="box",
                            envelope={"length": 4200, "width": 1400, "height": 1100}), at=(0, 0, 0)),
        *[Component(name=a, role="support",
                    part=Spec(object="axle", shape="cylinder",
                              envelope={"diameter": 80, "height": 160}), at=(0, 0, 0))
          for a in axles],
        *[Component(name=w, role="other",
                    part=Spec(object="wheel", shape="cylinder",
                              envelope={"diameter": 620, "height": 240}), at=(0, 0, 0))
          for w in wheels],
    ], mates=[
        Mate(kind="ground", a="chassis"),
        Mate(kind="stack", a="body", b="chassis", overlap=3),
        # axle centers at ±780: span 700..860 → 20 mm welded into the chassis, tip at 860
        Mate(kind="corners", parts=axles, around="chassis", dx=1300, dy=780, axis="y", z=310),
        # wheel centers at ±980: inner face at 860 = exactly the axle tip (attachment gap 0)
        Mate(kind="corners", parts=wheels, around="chassis", dx=1300, dy=980, axis="y"),
    ], joints=[Joint(a=w, b="chassis", axis="y", limits=(0, 360)) for w in wheels])
    asm = solve_layout(asm)
    comps = {c.name: c for c in asm.components}
    fl = comps["front_left_wheel"]
    rr = comps["rear_right_wheel"]

    def center(c: Component):
        b = _place_world(_bare_solid(c.part), c, comps).BoundingBox()
        return (b.center.x, b.center.y, b.zmin)

    flc, rrc = center(fl), center(rr)
    check("front_left CENTERED at (+1300,+980) by name",
          abs(flc[0] - 1300) < 0.5 and abs(flc[1] - 980) < 0.5, f"center={flc}")
    check("rear_right CENTERED at (−1300,−980) by name",
          abs(rrc[0] + 1300) < 0.5 and abs(rrc[1] + 980) < 0.5, f"center={rrc}")
    check("wheels lie sideways (axis y)", fl.rotate == (90.0, 0.0, 0.0), f"rot={fl.rotate}")
    check("wheels rest on the floor", abs(flc[2]) < 0.5, f"zmin={flc[2]}")
    rep = verify_assembly(asm)
    check("assembly passes end-to-end", rep["passed"],
          str([r["name"] for r in rep["rows"] if not r["within_tol"]]))
    dof = _row(rep, "DOF")
    check("DOF 4/4, nothing floating", dof["within_tol"] and dof["measured"] == 4)
    inter = _row(rep, "interference")
    check("wheels clear the body (derived dy)", inter["within_tol"], f"worst={inter['measured']}")
    sweep = _row(rep, "pose sweep")
    check("full 360° sweep clean", sweep["within_tol"], f"worst={sweep['measured']}")
    att = _row(rep, "joint attachment")
    check("wheels physically MEET their axles (attachment row)", att["within_tol"],
          f"gap={att['measured']}")
    # the adversarial side: strip the axles → the same car passes DOF/sweep but the attachment
    # row must catch the 60 mm air gap the eye sees instantly
    naked = asm.model_copy(deep=True)
    naked.components = [c for c in naked.components if "axle" not in c.name]
    naked.mates = [m for m in naked.mates if not (m.kind == "corners" and "axle" in (m.parts or [""])[0])]
    nrep = verify_assembly(naked)
    natt = _row(nrep, "joint attachment")
    check("floating wheels (no axles) CAUGHT by attachment row",
          not natt["within_tol"], f"gap={natt['measured']}")


def main() -> int:
    print("=" * 60)
    print("KINEMATIC — benchmark §A on the DOF/sweep/hierarchy rows")
    print("=" * 60)
    for fn in (hinge_golden, hinge_smash, hinge_welded, joint_autoplacement,
               pcb_standoffs, arm_2r, arc_meridians, joints_patch, joint_fit_a6, car_corners):
        print(f"\n■ {fn.__name__}")
        fn()
    print("\n" + "=" * 60)
    print(f"KINEMATIC {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
