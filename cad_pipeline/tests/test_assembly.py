"""Assembly tests (non-gated, no model): the mate-graph layout solver, the bounded connectivity
repair, the structural-support check, and the edit-patch apply that back the planner.

Run:  python -m cad_pipeline.tests.test_assembly
"""
from __future__ import annotations

import sys

from ..assembly import (Assembly, AsmPatch, Component, Mate, _bare_solid, _placed_bb, apply_patch,
                        repair_connectivity, solve_layout, verify_assembly)
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


def t_rack_mid_shelf() -> bool:
    # rung-2 dialect: stack+fraction fixes a shelf PARTWAY UP a corner-post group (two-tier rack).
    # The mid shelf's center must land at fraction×post-height, the top shelf on the post tops,
    # interference through the posts sanctioned, and the whole thing one supported solid.
    posts = [_box(f"post{i}", 16, 16, 180, role="leg") for i in range(4)]
    asm = Assembly(object="two-tier rack", components=posts + [
        _box("top_shelf", 200, 120, 10, role="top"), _box("mid_shelf", 200, 120, 10, role="top")], mates=[
        Mate(kind="corners", parts=[f"post{i}" for i in range(4)], around="top_shelf", dx=87, dy=47),
        Mate(kind="stack", a="top_shelf", b="post0", overlap=3),
        Mate(kind="stack", a="mid_shelf", b="post0", fraction=0.5)])
    asm = repair_connectivity(solve_layout(asm))
    rep = verify_assembly(asm)
    comps = {c.name: c for c in asm.components}
    mid_bb = _placed_bb(_bare_solid(comps["mid_shelf"].part), comps["mid_shelf"], comps)
    top_bb = _placed_bb(_bare_solid(comps["top_shelf"].part), comps["top_shelf"], comps)
    mid_ok = abs(mid_bb.center.z - 90) <= 3          # center at 0.5 × 180 mm posts
    top_ok = abs(top_bb.zmin - 177) <= 1             # classic stack: bottom = post top − overlap
    ok = (rep["solids"] == 1 and _row(rep, "structurally supported") and _row(rep, "interference")
          and _row(rep, "valid") and mid_ok and top_ok)
    print(f"  [{'ok ' if ok else 'FAIL'}] rack mid-shelf: solids={rep['solids']} mid_z={mid_bb.center.z:.1f} "
          f"top_zmin={top_bb.zmin:.1f} interference={_row(rep, 'interference')}")
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


def t_flush_fraction_height() -> bool:
    # the quad's cam-mount fix: a small pod flush on the +x face of a plate, fraction pins its
    # CENTER at 60% of the plate's height instead of leaving raw z (which buried it in an arm).
    asm = Assembly(object="pod", components=[
        _box("plate", 100, 100, 40, role="body"), _box("pod", 12, 20, 10)], mates=[
        Mate(kind="flush", a="pod", b="plate", side="+x", overlap=2, fraction=0.6)])
    asm = solve_layout(asm)
    plate = next(c for c in asm.components if c.name == "plate")
    pod = next(c for c in asm.components if c.name == "pod")
    bb = _placed_bb(_bare_solid(plate.part), plate, {c.name: c for c in asm.components})
    want_z = bb.zmin + 0.6 * (bb.zmax - bb.zmin)
    ok = abs(pod.at[2] - want_z) < 1.0 and pod.at[0] > 40   # centered box pod: at z == center
    print(f"  [{'ok ' if ok else 'FAIL'}] flush+fraction: pod_z={pod.at[2]:.1f} want≈{want_z:.1f} pod_x={pod.at[0]:.1f}")
    return ok


def t_flying_frame_not_grounded_exempt() -> bool:
    # the quadcopter false positive: role='base' plate with arms hanging BELOW it, no ground mate
    # → grounding must NOT be demanded (a drone floats); before the fix this row failed.
    arms = [_box(f"arm{i+1}", 80, 12, 5, role="arm") for i in range(4)]
    asm = Assembly(object="frame", components=[_box("plate", 100, 100, 4, at=(0, 0, 30), role="base")] + arms,
                   mates=[Mate(kind="radial", parts=[f"arm{i+1}" for i in range(4)], around="plate",
                               count=4, radius=60, z=26)])
    asm = repair_connectivity(solve_layout(asm))
    rep = verify_assembly(asm)
    ok = _row(rep, "structurally supported")
    print(f"  [{'ok ' if ok else 'FAIL'}] flying frame exempt: supported={ok}")
    return ok


def t_pedestal_still_needs_ground() -> bool:
    # the counter-case the exemption must NOT break: a pedestal (base IS the lowest member)
    # floating 50 mm up must still FAIL grounding.
    asm = Assembly(object="pedestal", components=[
        _box("base", 100, 100, 10, at=(0, 0, 55), role="base"),
        _box("column", 20, 20, 80, at=(0, 0, 100), role="support")],
        mates=[Mate(kind="stack", a="column", b="base", overlap=2)])
    asm = solve_layout(asm)
    rep = verify_assembly(asm)
    row = next(r for r in rep["rows"] if "structurally supported" in r["name"])
    ok = not row["within_tol"] and "not grounded" in str(row["measured"])
    print(f"  [{'ok ' if ok else 'FAIL'}] floating pedestal flagged: measured={row['measured']}")
    return ok


def t_islands_not_judged_supported() -> bool:
    # the gaming-desk contradiction: disconnected islands must not be graded 'supported ok'.
    asm = Assembly(object="scatter", components=[
        _box("a", 30, 30, 10, role="base"), _box("b", 30, 30, 10, at=(200, 200, 0))], mates=[
        Mate(kind="ground", a="a")])
    asm = solve_layout(asm)   # no repair — keep them apart deliberately
    rep = verify_assembly(asm)
    row = next(r for r in rep["rows"] if "structurally supported" in r["name"])
    ok = not row["within_tol"] and "disconnected" in str(row["measured"])
    print(f"  [{'ok ' if ok else 'FAIL'}] islands not judgeable: measured={row['measured']}")
    return ok


def t_port_suspend_below() -> bool:
    # THE desk killer: a tray hung UNDER the desktop — a's top port on b's bottom port, shifted
    # toward the rear with offset. The old vocabulary could not say this at all.
    asm = Assembly(object="desk", components=[
        _box("top", 1600, 700, 25, at=(0, 0, 738), role="top"),
        _box("tray", 1200, 120, 60, at=(999, 999, 999))], mates=[   # garbage raw coords must not matter
        Mate(kind="port", a="tray", b="top", a_port="top", b_port="bottom", overlap=2, offset=(0, -250))])
    asm = solve_layout(asm)
    tray = next(c for c in asm.components if c.name == "tray")
    cm = {c.name: c for c in asm.components}
    tb = _placed_bb(_bare_solid(tray.part), tray, cm)
    top = next(c for c in asm.components if c.name == "top")
    ob = _placed_bb(_bare_solid(top.part), top, cm)
    ok = abs(tb.zmax - 2 - ob.zmin) < 0.5 and abs(tb.center.y - (ob.center.y - 250)) < 0.5 \
        and abs(tb.center.x - ob.center.x) < 0.5
    print(f"  [{'ok ' if ok else 'FAIL'}] port suspend-below: tray_zmax={tb.zmax:.1f} top_zmin={ob.zmin:.1f} "
          f"tray_y={tb.center.y:.0f}")
    return ok


def t_port_side_at_height() -> bool:
    # side attachment at a height share: pod's back face onto plate's front face, 60% up.
    asm = Assembly(object="pod", components=[
        _box("plate", 100, 100, 40, role="body"), _box("pod", 12, 20, 10, at=(500, 500, 500))], mates=[
        Mate(kind="port", a="pod", b="plate", a_port="back", b_port="front", overlap=2, fraction=0.6)])
    asm = solve_layout(asm)
    cm = {c.name: c for c in asm.components}
    pod = next(c for c in asm.components if c.name == "pod")
    pb = _placed_bb(_bare_solid(pod.part), pod, cm)
    plate = next(c for c in asm.components if c.name == "plate")
    ob = _placed_bb(_bare_solid(plate.part), plate, cm)
    want_z = ob.zmin + 0.6 * (ob.zmax - ob.zmin)
    ok = abs(pb.xmin + 2 - ob.xmax) < 0.5 and abs(pb.center.z - want_z) < 0.5 and abs(pb.center.y) < 0.5
    print(f"  [{'ok ' if ok else 'FAIL'}] port side@height: pod_xmin={pb.xmin:.1f} plate_xmax={ob.xmax:.1f} "
          f"pod_z={pb.center.z:.1f} want={want_z:.1f}")
    return ok


def t_port_full_assembly() -> bool:
    # the desk pattern end-to-end: legs + suspended tray + under-shelf all port/mate placed →
    # ONE connected solid, verifier clean (the regression brief's failure signature reversed).
    legs = [_box(f"leg{i+1}", 60, 60, 725, role="leg") for i in range(4)]
    asm = Assembly(object="desk", components=[
        _box("top", 1600, 700, 25, role="top"),
        _box("tray", 1200, 120, 60, at=(9, 9, 9))] + legs, mates=[
        Mate(kind="corners", parts=[f"leg{i+1}" for i in range(4)], around="top", dx=740, dy=290),
        Mate(kind="stack", a="top", b="leg1", overlap=3),
        Mate(kind="port", a="tray", b="top", a_port="top", b_port="bottom", overlap=2, offset=(0, -250))])
    asm = repair_connectivity(solve_layout(asm))
    rep = verify_assembly(asm)
    ok = rep["solids"] == 1 and _row(rep, "structurally supported") and _row(rep, "interference")
    print(f"  [{'ok ' if ok else 'FAIL'}] port desk e2e: solids={rep['solids']} "
          f"supported={_row(rep, 'structurally supported')} interference={_row(rep, 'interference')}")
    return ok


def t_route_disconnected_mates_only() -> bool:
    # targeted repair (ArtiCAD routing): an islanded assembly must route to MATE-ADD — a patch
    # grammar in which geometry edits are unrepresentable (upsert/remove/joints locked).
    from ..asm_loop import _route_for
    from ..planner import _patch_schema_scoped
    asm = Assembly(object="scatter", components=[
        _box("a", 30, 30, 10, role="base"), _box("b", 30, 30, 10, at=(300, 300, 0))],
        mates=[Mate(kind="ground", a="a")])
    rep = verify_assembly(asm)
    route = _route_for(rep)
    ok = route is not None and route["category"] == "disconnected" and route["fields"] == {"mates"}
    if ok:
        s = _patch_schema_scoped(route["fields"], route["must"], route["parts"])
        p = s["properties"]
        ok = (p["upsert"].get("maxItems") == 0 and p["joints"] == {"type": "null"}
              and p["mates"].get("minItems") == 1 and s["required"] == ["mates"])
    print(f"  [{'ok ' if ok else 'FAIL'}] route disconnected→mate-add: "
          f"{route['category'] if route else None} fields={route['fields'] if route else None}")
    return ok


def t_route_integrity_scoped_names() -> bool:
    # interference routes to MATE-PARAM with upsert/remove pinned BY NAME to the colliding pair
    # (the structured `parts` field on the row, not regex on the row title).
    from ..asm_loop import _route_for
    from ..planner import _patch_schema_scoped
    # b and c are each mated to the BASE (sanctioned pairs b-a, c-a) but both stack at its
    # center → they interpenetrate EACH OTHER, an unsanctioned pair. Different dims so the
    # duplicate-coincident row stays quiet and integrity is the sole failing class.
    asm = Assembly(object="clash", components=[
        _box("a", 80, 80, 10, role="base"), _box("b", 40, 40, 20, at=(5, 0, 5)),
        _box("c", 30, 30, 24, at=(60, 0, 0))],
        mates=[Mate(kind="ground", a="a"), Mate(kind="stack", a="b", b="a", overlap=2),
               Mate(kind="stack", a="c", b="a", overlap=2)])
    asm = solve_layout(asm)
    rep = verify_assembly(asm)   # b↔c interpenetrate and are NOT mated to each other
    route = _route_for(rep)
    ok = (route is not None and route["category"] == "integrity"
          and route["parts"] is not None and set(route["parts"]) >= {"b", "c"})
    if ok:
        s = _patch_schema_scoped(route["fields"], route["must"], route["parts"])
        name_enum = s["$defs"]["Component"]["properties"]["name"]
        ok = "enum" in name_enum and set(name_enum["enum"]) == set(route["parts"]) \
            and s["properties"]["remove"]["items"]["enum"] == sorted(route["parts"])
    print(f"  [{'ok ' if ok else 'FAIL'}] route integrity→scoped names: "
          f"parts={route['parts'] if route else None}")
    return ok


def t_routed_feedback_locks_other_rows() -> bool:
    # routed feedback: the focused class's rows lead with FIX prescriptions; every other failing
    # row is listed under LOCKED (one failure class per patch, downstream rows deferred).
    from ..asm_loop import _asm_feedback, _route_for
    asm = Assembly(object="scatter", components=[
        _box("a", 30, 30, 10, role="base"), _box("b", 30, 30, 10, at=(300, 300, 0)),
        _box("c", 30, 30, 10, at=(2, 2, 2))], mates=[Mate(kind="ground", a="a")])
    rep = verify_assembly(asm)   # disconnected (b) AND interference (a↔c) at once
    route = _route_for(rep)
    fb = _asm_feedback(rep, route["category"])
    head = fb.split("ALSO failing")[0]
    ok = (route["category"] == "disconnected" and "LOCKED" in fb
          and "connectivity" in head and "interference" not in head and "interference" in fb)
    print(f"  [{'ok ' if ok else 'FAIL'}] routed feedback locks others: focus={route['category']} "
          f"locked_section={'LOCKED' in fb}")
    return ok


def t_patch_fillet_joints() -> bool:
    # the blend route's only knob: AsmPatch.fillet_joints must actually apply (it was
    # unexpressable before — the 'reduce fillet_joints' prescription had no patch field).
    asm = Assembly(object="x", components=[_box("a", 30, 30, 10)], fillet_joints=2.5)
    out = apply_patch(asm, AsmPatch(fillet_joints=0.0))
    ok = out.fillet_joints == 0.0 and apply_patch(asm, AsmPatch()).fillet_joints == 2.5
    print(f"  [{'ok ' if ok else 'FAIL'}] patch fillet_joints: {asm.fillet_joints} → {out.fillet_joints}")
    return ok


def main() -> int:
    print("ASSEMBLY — mate layout solver + bounded repair + structural check + edit patch:")
    checks = [t_solve_stool, t_solve_bracket_flush, t_repair_small_gap, t_repair_no_collapse,
              t_rack_mid_shelf, t_patch_mates, t_flush_fraction_height,
              t_flying_frame_not_grounded_exempt, t_pedestal_still_needs_ground,
              t_islands_not_judged_supported, t_port_suspend_below, t_port_side_at_height,
              t_port_full_assembly, t_route_disconnected_mates_only, t_route_integrity_scoped_names,
              t_routed_feedback_locks_other_rows, t_patch_fillet_joints]
    ok = sum(bool(c()) for c in checks)
    print(f"\nASSEMBLY {ok}/{len(checks)}")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
