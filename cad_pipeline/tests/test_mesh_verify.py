"""Phase-3: the mesh verifier (cad_pipeline/mesh_verify.py) implements §6.1 mesh validation + the
§2.3 min-wall raycast, validated against ground-truth good/bad meshes.
"""
from __future__ import annotations

import sys

import numpy as np
import trimesh

from cad_pipeline.builder import build
from cad_pipeline.mesh_verify import mesh_report, min_wall, tri_from_solid
from cad_pipeline.spec import Spec

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_clean_solid_passes():
    print("\n■ a clean OCCT box tessellates to a valid mesh (all §6.1 rows pass)")
    box = build(Spec(object="box", shape="box", envelope={"length": 30, "width": 20, "height": 10}))
    rep = mesh_report(box)
    check(rep.passed, "watertight, manifold, single-component box passes")
    check(rep.solids == 1, f"isolated_components == 1 (got {rep.solids})")
    names = {r.name: r for r in rep.rows}
    check(names["mesh · watertight"].measured is True, "watertight True")
    check(names["mesh · non_manifold_edges"].measured == 0, "0 non-manifold edges")
    check(names["mesh · winding_consistent (normals)"].measured is True, "winding consistent")


def test_min_wall_accuracy():
    print("\n■ min-wall raycast matches a known 2.5 mm shell")
    shell = build(Spec(object="shell", shape="box", envelope={"length": 60, "width": 60, "height": 40},
                       features=[{"type": "shell", "thickness": 2.5, "open_face": "top"}]))
    mw = min_wall(tri_from_solid(shell, 0.2))
    check(mw is not None and abs(mw - 2.5) < 0.1, f"min wall ≈ 2.5 (got {round(mw, 3)})")
    # a solid box's 'min wall' is its smallest full dimension (10)
    box = tri_from_solid(build(Spec(object="box", shape="box",
                                    envelope={"length": 40, "width": 30, "height": 10})), 0.2)
    mwb = min_wall(box)
    check(mwb is not None and abs(mwb - 10) < 0.3, f"solid box min-wall ≈ 10 (got {round(mwb, 3)})")


def test_min_wall_row_gates():
    print("\n■ min_wall row gates a thin wall below the budget")
    shell = build(Spec(object="thin", shape="box", envelope={"length": 60, "width": 60, "height": 40},
                       features=[{"type": "shell", "thickness": 1.0, "open_face": "top"}]))
    rep = mesh_report(shell, min_wall_mm=1.2)      # 1.0 wall vs 1.2 required → fail
    row = next(r for r in rep.rows if r.name == "mesh · min_wall")
    check(not row.within_tol, f"1.0 mm wall fails a 1.2 mm min_wall budget (measured {row.measured})")


def test_broken_mesh_caught():
    print("\n■ a leaky mesh (faces removed) fails watertight + non-manifold")
    box = tri_from_solid(build(Spec(object="box", shape="box",
                                    envelope={"length": 20, "width": 20, "height": 20})), 0.5)
    holed = trimesh.Trimesh(vertices=box.vertices.copy(), faces=box.faces[:-4].copy(), process=True)
    rep = mesh_report(holed)
    names = {r.name: r for r in rep.rows}
    check(not names["mesh · watertight"].within_tol, "removed faces → not watertight (caught)")
    check(names["mesh · non_manifold_edges"].measured > 0, "boundary edges → non-manifold count > 0")
    check(not rep.passed, "broken mesh does not pass")


def test_component_count():
    print("\n■ isolated_components catches an unintended second body")
    a = tri_from_solid(build(Spec(object="a", shape="box", envelope={"length": 10, "width": 10, "height": 10})), 0.5)
    b = a.copy(); b.apply_translation([50, 0, 0])
    two = trimesh.util.concatenate([a, b])
    rep = mesh_report(two, expected_components=1)   # expect 1 but there are 2
    row = next(r for r in rep.rows if r.name == "mesh · isolated_components")
    check(not row.within_tol and row.measured == 2, f"two disjoint boxes → 2 components (got {row.measured})")


def test_self_intersection():
    print("\n■ self-intersection (§6.1, pymeshlab) — clean passes, overlapping faces caught")
    from cad_pipeline.mesh_verify import _HAVE_PYMESHLAB, self_intersections
    if not _HAVE_PYMESHLAB:
        check(True, "pymeshlab absent → self-intersection row honestly omitted (skip)")
        return
    clean = trimesh.creation.icosphere(subdivisions=3, radius=25)
    check(self_intersections(clean) == 0, "clean icosphere → 0 self-intersecting faces")
    a = trimesh.creation.box((20, 20, 20)); b = trimesh.creation.box((20, 20, 20)); b.apply_translation([8, 8, 0])
    bad = trimesh.util.concatenate([a, b])
    check(self_intersections(bad) > 0, "overlapping boxes → self-intersections caught")
    rep = mesh_report(clean)
    check(any(r.name == "mesh · self_intersections" for r in rep.rows), "self_intersections row present in report")


def main() -> int:
    print("=" * 62)
    print("MESH VERIFY — §6.1 mesh validation + §2.3 min-wall raycast")
    print("=" * 62)
    for fn in (test_clean_solid_passes, test_min_wall_accuracy, test_min_wall_row_gates,
               test_broken_mesh_caught, test_component_count, test_self_intersection):
        fn()
    print("\n" + "=" * 62)
    print(f"MESH_VERIFY {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
