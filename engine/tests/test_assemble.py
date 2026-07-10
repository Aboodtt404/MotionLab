"""Phase-5b: the hybrid assembly merge — parts of different representations (brep + library + mesh)
placed via the mate graph into one common-frame scene and verified (fable_run §1.1 ASSEMBLE / §1.4).
"""
from __future__ import annotations

import sys

import trimesh

from cad_pipeline.schemas import AssemblyBrief, BriefComponent, BriefMate, ModelBrief
from engine.assemble import assemble
from engine.builders import BuiltPart

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def _drone_brief() -> AssemblyBrief:
    frame = ModelBrief(brief_id="f", name="quad frame plate", target_use="cad", representation="brep",
                       units="mm", up_axis="z", shape="box",
                       envelope_mm={"length": 120, "width": 120, "height": 4})
    bearing = ModelBrief(brief_id="b", name="608 bearing", target_use="cad", representation="brep",
                         units="mm", up_axis="z", envelope_mm={"diameter": 22, "height": 7})
    canopy = ModelBrief(brief_id="c", name="canopy", target_use="film", representation="mesh",
                        units="mm", up_axis="z", envelope_mm={"length": 80, "width": 40, "height": 30},
                        prompt="organic sculpted canopy shell")
    return AssemblyBrief(brief_id="ab", name="drone", units="mm", components=[
        BriefComponent(component_id="frame", role="base", brief=frame),
        BriefComponent(component_id="brg", role="hub", brief=bearing),
        BriefComponent(component_id="canopy", role="panel", brief=canopy)],
        mates=[BriefMate(kind="stack", a="canopy", b="frame", overlap_mm=2),
               BriefMate(kind="coaxial", a="brg", b="frame")])


def test_hybrid_merge():
    print("\n■ hybrid drone: brep frame + library bearing + (injected) mesh canopy → one scene")
    brief = _drone_brief()
    # :8770 is offline here, so inject the organic canopy as a mesh BuiltPart (what TRELLIS would return)
    canopy_mesh = trimesh.creation.icosphere(subdivisions=2, radius=0.5)   # ~1 m blob, glTF-ish
    injected = {"canopy": BuiltPart("canopy", "mesh", True, {"passed": True}, canopy_mesh)}
    asset = assemble(brief, built=injected)

    check(asset.reps.get("frame") == "brep", "frame routed to brep")
    check(asset.reps.get("brg") == "library", "bearing routed to library")
    check(asset.reps.get("canopy") == "mesh", "canopy is mesh")
    check(len(asset.scene.geometry) == 3, f"all 3 parts placed in the scene (got {len(asset.scene.geometry)})")
    placed = next(r for r in asset.rows if r["name"] == "assembly · parts placed")
    check(placed["within_tol"], "parts-placed row passes")
    interf = next(r for r in asset.rows if "interference" in r["name"])
    check(interf["within_tol"], f"no gross interference (worst bbox overlap {interf['measured']})")
    env = next(r for r in asset.rows if "envelope" in r["name"])
    check(env["measured"] > 100, f"combined envelope is sane ({env['measured']} mm diag)")
    check(asset.passed, "hybrid asset passes the combined-scene verify")


def test_canopy_scaled_to_envelope():
    print("\n■ §1.4 unit fit: the mesh canopy is scaled to its brief envelope (not left at ~1 m)")
    brief = _drone_brief()
    canopy_mesh = trimesh.creation.icosphere(subdivisions=2, radius=0.5)   # 1 m across
    asset = assemble(brief, built={"canopy": BuiltPart("canopy", "mesh", True, {"passed": True}, canopy_mesh)})
    cg = asset.scene.geometry["canopy"]
    ext = cg.extents
    check(max(ext) <= 120 and max(ext) >= 20, f"canopy fitted to ~80×40×30 mm envelope (extents {ext.round(1)})")


def main() -> int:
    print("=" * 62)
    print("HYBRID ASSEMBLY — cross-representation merge via the mate graph")
    print("=" * 62)
    for fn in (test_hybrid_merge, test_canopy_scaled_to_envelope):
        fn()
    print("\n" + "=" * 62)
    print(f"ASSEMBLE {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
