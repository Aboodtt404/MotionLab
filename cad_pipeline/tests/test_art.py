"""§4 art-production: style card, retopo, trim-sheet, texture bake."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import trimesh

from cad_pipeline.art import (StyleCard, bake_maps, retopo, verify_retopo, verify_style,
                              verify_trim_sheet)

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def main() -> int:
    print("=" * 58)
    print("ART — §4 style card / retopo / trim-sheet / texture bake")
    print("=" * 58)
    card = StyleCard()

    print("\n■ §4.3 style card — palette adherence")
    check(verify_style([[43, 46, 51], [199, 82, 30]], card).passed, "on-palette colors pass")
    check(not verify_style([[255, 0, 255]], card).passed, "off-palette (magenta) fails")

    print("\n■ §4.1 retopo — high-poly → clean low-poly, silhouette preserved")
    hi = trimesh.creation.icosphere(subdivisions=5)      # ~20k faces
    lo = retopo(hi, 800)
    rr = verify_retopo(hi, lo, 800)
    check(len(lo.faces) <= 840, f"decimated to budget ({len(lo.faces)})")
    check(lo.is_watertight and lo.is_winding_consistent, "manifold + coherent winding")
    check(rr.passed, "retopo report passes (incl. silhouette IoU ≥0.95)")

    print("\n■ §4 trim-sheet — UVs in declared V-bands")
    check(verify_trim_sheet(trimesh.creation.box((1, 1, 1)), n_bands=4).passed, "box UVs fit 4 V-bands")

    print("\n■ §4 texture bake (Blender) — AO + tangent normal")
    if shutil.which("blender") is None:
        check(True, "blender absent → bake skipped")
    else:
        d = tempfile.mkdtemp()
        try:
            hi.export(os.path.join(d, "in.glb"))
            maps = bake_maps(os.path.join(d, "in.glb"), os.path.join(d, "bake"), res=256)
            check(maps is not None and "normal" in maps, f"bake wrote maps {list(maps) if maps else None}")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    print("\n" + "=" * 58)
    print(f"ART {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
