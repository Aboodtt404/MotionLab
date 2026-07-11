"""Phase-8/§4: LOD generation + silhouette-IoU acceptance (§4.2)."""
from __future__ import annotations

import sys

import trimesh

from cad_pipeline.lod import generate_lods, silhouette_iou, verify_lod_chain

PASS = FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def main() -> int:
    print("=" * 58)
    print("LOD — decimation chain + §4.2 silhouette-IoU acceptance")
    print("=" * 58)
    src = trimesh.creation.icosphere(subdivisions=5)     # ~20k faces
    budgets = [6000, 1500, 400]                          # G07 game LOD chain
    lods = generate_lods(src, budgets)
    print("\n■ generation hits the face budgets")
    check([len(l.faces) for l in lods] == [min(len(src.faces), b) for b in budgets] or
          all(len(l.faces) <= int(b * 1.05) for l, b in zip(lods, budgets)), f"faces {[len(l.faces) for l in lods]}")
    print("\n■ silhouette IoU stays above the §4.2 thresholds")
    check(silhouette_iou(src, lods[0]) >= 0.97, "LOD0 IoU ≥ 0.97")
    check(silhouette_iou(src, lods[2]) >= 0.92, "LOD2 IoU ≥ 0.92")
    print("\n■ verify_lod_chain passes a good chain")
    check(verify_lod_chain(src, lods, budgets).passed, "chain report passes")
    print("\n■ silhouette IoU discriminates a wrong shape")
    check(silhouette_iou(src, trimesh.creation.box((2, 2, 2))) < 0.9, "sphere vs box < 0.9")
    print("\n" + "=" * 58)
    print(f"LOD {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
