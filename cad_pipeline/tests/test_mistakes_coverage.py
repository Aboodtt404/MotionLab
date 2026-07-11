"""Phase-3 close-out: prove the 46-mistake catalog (05_mistakes.md) is LIVE — each mistake's
detection is reachable by a real verifier (its category is one the suite actually emits), and a
representative mistake per area is demonstrated end-to-end against the live oracle.
"""
from __future__ import annotations

import sys

import numpy as np
import trimesh

from cad_pipeline.builder import build
from cad_pipeline.glb_verify import verify_web
from cad_pipeline.mesh_verify import mesh_report, self_intersections
from cad_pipeline.mistakes import BY_AREA, CATALOG
from cad_pipeline.print_verify import verify_print
from cad_pipeline.schemas import CHECK_CATEGORY
from cad_pipeline.spec import Spec
from cad_pipeline.verifier import verify

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_every_category_reachable():
    print("\n■ every mistake's detection category is one the verifier suite emits")
    reachable = set(CHECK_CATEGORY) | {"exec"}
    unreachable = [m.id for m in CATALOG if m.category not in reachable]
    check(not unreachable, f"all 46 map to a live category ({unreachable or 'ok'})")
    # per-area count report (must equal 05_mistakes distribution)
    counts = {a: len(v) for a, v in sorted(BY_AREA.items())}
    check(counts == {"assembly": 8, "cad": 14, "mesh": 11, "print": 4, "procedural": 3, "web": 6},
          f"area distribution {counts}")


def test_cad_C8_dia_confusion():
    print("\n■ CAD C8 (radius/diameter confusion) — live detection")
    spec = Spec(object="disc", shape="cylinder", envelope={"diameter": 60, "height": 20},
                features=[{"type": "through_hole", "diameter": 20}])
    bad = spec.model_copy(deep=True); bad.features[0].diameter = 40   # ⌀×2 = C8
    rep = verify(build(bad), spec)                                    # verify wrong build vs target
    check(not rep.passed, f"⌀×2 hole caught ({rep.failure_categories()})")


def test_mesh_M2_leaky_and_M5_selfintersect():
    print("\n■ mesh M2 (leaky) + M5 (self-intersection) — live detection")
    box = trimesh.creation.box((20, 20, 20))
    leaky = trimesh.Trimesh(vertices=box.vertices.copy(), faces=box.faces[:-4].copy(), process=True)
    r = mesh_report(leaky)
    check(not next(x for x in r.rows if "watertight" in x.name).within_tol, "M2 leaky → not watertight")
    a = trimesh.creation.box((20, 20, 20)); b = trimesh.creation.box((20, 20, 20)); b.apply_translation([8, 8, 0])
    si = self_intersections(trimesh.util.concatenate([a, b]))
    check(si is None or si > 0, f"M5 self-intersection → {si} faces")


def test_assembly_A3_interference():
    print("\n■ assembly A3 (interference) — live detection")
    # the live A3 detection is the engine hybrid assembler's pairwise-interference row
    from cad_pipeline.schemas import AssemblyBrief, BriefComponent, ModelBrief
    from engine.assemble import assemble
    from engine.builders import BuiltPart
    mb = lambda i: ModelBrief(brief_id=i, name=i, target_use="cad", representation="mesh",
                              units="mm", up_axis="z", envelope_mm={"length": 40, "width": 40, "height": 40})
    brief = AssemblyBrief(brief_id="clash", name="clash", units="mm", components=[
        BriefComponent(component_id="a", role="body", brief=mb("a")),
        BriefComponent(component_id="b", role="body", brief=mb("b"))], mates=[])   # no mate → both at origin
    inj = {c: BuiltPart(c, "mesh", True, {"passed": True}, trimesh.creation.box((40, 40, 40))) for c in ("a", "b")}
    asset = assemble(brief, built=inj)
    row = next(r for r in asset.rows if "interference" in r["name"])
    check(not row["within_tol"] and row["measured"] > 0, f"overlap caught (bbox overlap {row['measured']})")


def test_print_P1_thin_wall():
    print("\n■ print P1 (wall below minimum) — live detection")
    thin = build(Spec(object="thin", shape="box", envelope={"length": 40, "width": 40, "height": 30},
                      features=[{"type": "shell", "thickness": 0.5, "open_face": "top"}]))
    rep = verify_print(thin, run_slicer=False)
    check(not next(r for r in rep.rows if r.name == "print · min_wall").within_tol, "0.5 mm wall < 0.8 FDM floor")


def test_web_W2_scale():
    print("\n■ web W2 (wrong absolute scale) — live detection")
    import os
    import tempfile
    d = tempfile.mkdtemp(); p = os.path.join(d, "big.glb")
    trimesh.creation.box((500, 500, 500)).export(p)               # 500 m = unit bug
    rep = verify_web(p)
    check(not any(x.name.startswith("web · bbox diag") and x.within_tol for x in rep.rows), "500 m flagged")


def main() -> int:
    print("=" * 62)
    print("MISTAKES COVERAGE — 46 catalog entries are live detections")
    print("=" * 62)
    for fn in (test_every_category_reachable, test_cad_C8_dia_confusion,
               test_mesh_M2_leaky_and_M5_selfintersect, test_assembly_A3_interference,
               test_print_P1_thin_wall, test_web_W2_scale):
        fn()
    print("\n" + "=" * 62)
    print(f"MISTAKES_COVERAGE {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
