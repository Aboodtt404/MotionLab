"""Phase-3d: web/GLB (§6.5) + game (§6.4) verifiers — gltf-validator + trimesh introspection +
Blender render smoke, validated on good/bad GLBs.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import trimesh

from cad_pipeline.glb_verify import gltf_validate, render_smoke, verify_game, verify_web

PASS = FAIL = 0
_TMP = tempfile.mkdtemp()


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def _glb(mesh, name):
    p = os.path.join(_TMP, name)
    mesh.export(p)
    return p


def test_gltf_validator():
    print("\n■ gltf-validator (Khronos, node) — clean GLB reports 0 errors")
    p = _glb(trimesh.creation.box((0.3, 0.2, 0.1)), "clean.glb")
    val = gltf_validate(p)
    if val is None:
        check(True, "node/validator absent → skip")
        return
    check(val["numErrors"] == 0, f"clean GLB → 0 errors (got {val['numErrors']})")
    check("materialCount" in val["info"], "info carries materialCount")


def test_web_budgets():
    print("\n■ verify_web §6.5: size / tris / scale / height")
    small = _glb(trimesh.creation.icosphere(subdivisions=2, radius=0.1), "w01.glb")
    rep = verify_web(small, max_tris=10_000, max_file_mb=2.0)
    check(rep.passed, "small in-scale GLB passes web budgets")
    huge = verify_web(small, max_tris=100)      # 320 > 100 → tri budget fails
    check(not huge.passed, "tri-budget overflow caught")
    fig = _glb(trimesh.creation.box((0.4, 1.8, 0.3)), "w02.glb")   # 1.8 m along Y (glTF up)
    r2 = verify_web(fig, height_range=(1.78, 1.82))
    check(any(x.name.endswith("height (m)") and x.within_tol for x in r2.rows), "1.8 m Y-height passes W02")


def test_scale_sanity_caught():
    print("\n■ scale sanity: a 500 m bbox (unit bug) is caught")
    big = _glb(trimesh.creation.box((500, 500, 500)), "big.glb")
    rep = verify_web(big)
    check(not any(x.name.startswith("web · bbox diag") and x.within_tol for x in rep.rows),
          "500 m diag flagged (outside [0.01,100] m)")


def test_game_budgets():
    print("\n■ verify_game §6.4: tri budget / material slots / base pivot")
    crate = trimesh.creation.box((0.5, 0.5, 0.5)); crate.apply_translation([0, 0.25, 0])  # base at Y=0
    rep = verify_game(_glb(crate, "g01.glb"), tri_budget=500)
    check(rep.passed, "crate ≤500 tris, ≤2 materials, base pivot → passes")
    over = verify_game(_glb(crate, "g01b.glb"), tri_budget=6)   # 12 > 6
    check(not over.passed, "tri-budget overflow caught")


def test_render_smoke():
    print("\n■ Blender render smoke (§6.5 non-empty framebuffer)")
    if shutil.which("blender") is None:
        check(True, "blender absent → skip")
        return
    sd = render_smoke(_glb(trimesh.creation.box((0.3, 0.2, 0.1)), "r.glb"))
    check(sd is not None and sd > 10, f"box renders non-empty (std-dev {round(sd, 1) if sd else None})")


def main() -> int:
    print("=" * 62)
    print("GLB VERIFY — web §6.5 + game §6.4 (gltf-validator + trimesh + Blender)")
    print("=" * 62)
    try:
        for fn in (test_gltf_validator, test_web_budgets, test_scale_sanity_caught,
                   test_game_budgets, test_render_smoke):
            fn()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("\n" + "=" * 62)
    print(f"GLB_VERIFY {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
