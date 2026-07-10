"""Phase-5: the representation router + unified engine (the Track A+B merge). The router picks a
representation per part (§1.2); brep + library build+verify in-process; mesh (TRELLIS :8770) and
procedural (Blender) degrade gracefully when the service/tooling is down.
"""
from __future__ import annotations

import sys

from cad_pipeline.schemas import AssemblyBrief, ModelBrief
from engine.builders import build_brep, build_library
from engine.engine import build_asset, build_part
from engine.router import choose_representation

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_router_decision_table():
    print("\n■ §1.2 decision table — representation chosen per part")
    cases = [
        ("brep", dict(name="mounting bracket", prompt="CNC aluminum bracket, ±0.1 tolerance")),
        ("library", dict(name="608 bearing", prompt="a deep-groove ball bearing")),
        ("library", dict(name="M3 hex nut", prompt="fastener")),
        ("mesh", dict(name="dragon head", prompt="an organic sculpted creature head")),
        ("procedural", dict(name="rock field", prompt="a family of scattered greebles on terrain")),
        ("brep", dict(name="flange", prompt="⌀90 flange with bolt circle")),
    ]
    for exp, kw in cases:
        got = choose_representation(**kw)
        check(got == exp, f"{kw['name']!r} → {got} (expect {exp})")
    # explicit representation on the brief wins (unless it names a catalog part)
    check(choose_representation(representation="mesh", name="statue") == "mesh", "explicit mesh honored")


def test_brep_path():
    print("\n■ brep path builds + verifies a CAD part end-to-end")
    b = ModelBrief(brief_id="mb1", name="bored disc", target_use="cad", representation="brep",
                   units="mm", up_axis="z", shape="cylinder", envelope_mm={"diameter": 60, "height": 20},
                   features=[{"type": "through_hole", "params": {"diameter": 20}}])
    part = build_part(b)
    check(part.representation == "brep", "routed to brep")
    check(part.passed, f"builds + verifies (report passed={part.report.get('passed')})")


def test_library_path():
    print("\n■ library path instantiates a golden catalog part")
    b = ModelBrief(brief_id="mb2", name="608 bearing", target_use="cad", representation="brep",
                   units="mm", up_axis="z", envelope_mm={"diameter": 22, "height": 7})
    part = build_part(b)
    check(part.representation == "library", "routed to library (named catalog part)")
    check(part.passed, "golden bearing instantiates + validates")
    g = ModelBrief(brief_id="mb3", name="involute gear m=2 z=24", target_use="cad", representation="brep",
                   units="mm", up_axis="z", envelope_mm={"diameter": 52, "height": 10})
    gp = build_part(g)
    check(gp.representation == "library" and gp.passed, "involute gear m2z24 via library")


def test_graceful_degradation():
    print("\n■ mesh / procedural degrade gracefully when service/tooling absent")
    b = ModelBrief(brief_id="mb4", name="dragon", target_use="film", representation="mesh",
                   units="m", up_axis="y", envelope_mm={"x": 1, "y": 1, "z": 1}, prompt="organic creature")
    part = build_part(b)   # :8770 is down in CI → ok=False with a clear reason, never a crash
    check(part.representation == "mesh", "routed to mesh")
    check((not part.ok) and "TRELLIS" in part.reason or part.ok,
          f"mesh path handled (ok={part.ok}, reason={part.reason!r})")


def test_hybrid_assembly_routing():
    print("\n■ hybrid assembly — each component routed to its own representation")
    frame = ModelBrief(brief_id="f", name="quad frame plate", target_use="cad", representation="brep",
                       units="mm", up_axis="z", shape="box", envelope_mm={"length": 120, "width": 120, "height": 4})
    bearing = ModelBrief(brief_id="b", name="608 bearing", target_use="cad", representation="brep",
                         units="mm", up_axis="z", envelope_mm={"diameter": 22, "height": 7})
    canopy = ModelBrief(brief_id="c", name="canopy", target_use="film", representation="mesh",
                        units="mm", up_axis="z", envelope_mm={"length": 80, "width": 40, "height": 30},
                        prompt="organic sculpted canopy shell")
    from cad_pipeline.schemas import BriefComponent
    asm = AssemblyBrief(brief_id="ab", name="drone", units="mm", components=[
        BriefComponent(component_id="frame", role="body", brief=frame),
        BriefComponent(component_id="brg", role="hub", brief=bearing),
        BriefComponent(component_id="canopy", role="panel", brief=canopy)])
    res = build_asset(asm)
    reps = {p.name: p.representation for p in res.parts}
    check(reps.get("quad frame plate") == "brep", "frame → brep")
    check(reps.get("608 bearing") == "library", "bearing → library")
    check(reps.get("canopy") == "mesh", "organic canopy → mesh")
    # the two in-process parts must actually pass; the mesh part is service-gated
    inproc = [p for p in res.parts if p.representation in ("brep", "library")]
    check(all(p.passed for p in inproc), "all in-process (brep+library) parts verify")
    print("    asset summary:", res.summary()["by_rep"])


def main() -> int:
    print("=" * 62)
    print("ENGINE — representation router + unified build (Track A+B merge)")
    print("=" * 62)
    for fn in (test_router_decision_table, test_brep_path, test_library_path,
               test_graceful_degradation, test_hybrid_assembly_routing):
        fn()
    print("\n" + "=" * 62)
    print(f"ENGINE {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
