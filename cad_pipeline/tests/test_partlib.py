"""Phase-4: the standard-part library is golden by construction — every Spec part builds+verifies
and every solid part builds valid + re-measures to its catalog dimension (fable_run §2.4).
"""
from __future__ import annotations

import sys

from cad_pipeline import partlib, partlib_solids
from cad_pipeline.partlib_solids import involute_gear, tooth_count


def main() -> int:
    print("=" * 60)
    print("PARTLIB — Spec factories (build+verify) + solid factories (valid+dims)")
    print("=" * 60)
    print("\n■ Spec parts (partlib.py)")
    rc_spec = partlib.selftest()
    print("\n■ Solid parts (partlib_solids.py)")
    rc_solid = partlib_solids.selftest()

    print("\n■ involute-gear mesh criteria (P05/A05): tip ⌀ + polar tooth count")
    ok = True
    for m, z in [(2, 24), (2, 12), (1, 16)]:
        g, _ = involute_gear(m, z)
        bb = g.val().BoundingBox()
        tip = max(bb.xlen, bb.ylen)
        tc = tooth_count(g)
        good = abs(tip - m * (z + 2)) <= 0.2 and tc == z
        ok = ok and good
        print(f"  [{'ok ' if good else 'FAIL'}] m={m} z={z}: tip⌀={round(tip, 2)} teeth={tc}")

    bad = rc_spec or rc_solid or (0 if ok else 1)
    print("\n" + "=" * 60)
    print("PARTLIB ALL GOOD ✓" if not bad else "PARTLIB FAILURES ✗")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
