"""Phase-3b: the §2.1 anti-toy / §3.4 plausibility rows and the 46-mistake catalog conform to
fable_run/out/00_manual.md §2.1/§3.4 and 05_mistakes.md.
"""
from __future__ import annotations

import sys

from cad_pipeline.builder import build
from cad_pipeline.mistakes import BY_AREA, CATALOG, feedback_for
from cad_pipeline.plausibility import (DENSITY_G_PER_MM3, fillet_classes, fillet_hierarchy_row,
                                       mass_props_row, min_wall_row, verify_plausibility)
from cad_pipeline.schemas import CHECK_CATEGORY
from cad_pipeline.spec import Spec

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_mass_props():
    print("\n■ mass_props (§3.4): volume × density, sanity band")
    vol = 100_000.0  # mm³ = 100 cm³
    r = mass_props_row(vol, "aluminum")
    check(abs(r.measured - vol * DENSITY_G_PER_MM3["aluminum"]) < 1e-6, f"aluminum mass = {r.measured} g")
    r2 = mass_props_row(vol, "pla", expected_g=124.0)      # 100cm³ PLA ≈ 124 g → in band
    check(r2.within_tol, "mass within 0.5–2× estimate passes")
    r3 = mass_props_row(vol, "pla", expected_g=10.0)       # way off → fail
    check(not r3.within_tol, "mass far outside estimate band fails")


def test_fillet_hierarchy():
    print("\n■ fillet hierarchy (§2.1 rule 3): distinct radius classes")
    toy = Spec(object="toy", shape="box", envelope={"length": 40, "width": 40, "height": 40},
               features=[{"type": "fillet", "radius": 2, "edges": "all_vertical"}])
    check(fillet_classes(toy) == [2.0], "single-radius part → 1 class")
    check(not fillet_hierarchy_row(toy, 3).within_tol, "1 class fails a ≥3 requirement (toy tell)")
    rich = Spec(object="rich", shape="box", envelope={"length": 60, "width": 60, "height": 30},
                features=[{"type": "fillet", "radius": 0.5, "edges": "all_vertical"},
                          {"type": "chamfer", "distance": 2, "edges": "top"},
                          {"type": "var_fillet", "r1": 5, "r2": 12, "edges": "all_vertical"}])
    check(len(fillet_classes(rich)) >= 3, f"multi-radius design → ≥3 classes ({fillet_classes(rich)})")


def test_min_wall_row():
    print("\n■ min_wall row (§3.4 / §2.1 rule 6): inward raycast on a real shell")
    thin = build(Spec(object="thin", shape="box", envelope={"length": 60, "width": 60, "height": 40},
                      features=[{"type": "shell", "thickness": 1.0, "open_face": "top"}]))
    check(not min_wall_row(thin, 1.2).within_tol, "1.0 mm wall fails a 1.2 mm minimum")
    ok = build(Spec(object="ok", shape="box", envelope={"length": 60, "width": 60, "height": 40},
                    features=[{"type": "shell", "thickness": 2.5, "open_face": "top"}]))
    check(min_wall_row(ok, 1.2).within_tol, "2.5 mm wall passes a 1.2 mm minimum")


def test_verify_plausibility_assembles():
    print("\n■ verify_plausibility assembles the applicable rows from opt-in thresholds")
    spec = Spec(object="p", shape="box", envelope={"length": 60, "width": 60, "height": 40},
                features=[{"type": "shell", "thickness": 2.0, "open_face": "top"}])
    solid = build(spec)
    rows = verify_plausibility(solid, spec, material="pla", min_wall_mm=1.2,
                               volume_mm3=50_000.0, min_fillet_classes=3)
    names = {r.name.split(" ·")[0] for r in rows}
    check(any("min_wall" in r.name for r in rows), "min_wall row present")
    check(any("mass" in r.name for r in rows), "mass row present")
    check(any("fillet radius classes" in r.name for r in rows), "fillet-hierarchy row present")


def test_mistakes_catalog():
    print("\n■ 46-mistake catalog (05_mistakes.md) — count, areas, category conformance")
    check(len(CATALOG) == 46, f"46 mistakes catalogued (got {len(CATALOG)})")
    counts = {a: len(v) for a, v in sorted(BY_AREA.items())}
    check(counts == {"assembly": 8, "cad": 14, "mesh": 11, "print": 4, "procedural": 3, "web": 6},
          f"area distribution matches 05_mistakes (got {counts})")
    valid_cat = set(CHECK_CATEGORY) | {"exec"}
    bad = [m.id for m in CATALOG if m.category not in valid_cat]
    check(not bad, f"every mistake category ∈ CHECK_CATEGORY ∪ exec ({bad or 'all ok'})")
    check(len({m.id for m in CATALOG}) == 46, "all mistake ids unique")
    check(feedback_for("A7").startswith("extend legs"), "feedback_for('A7') returns the typed repair string")


def main() -> int:
    print("=" * 62)
    print("PLAUSIBILITY + MISTAKES — §2.1/§3.4 rows + the 46-mistake catalog")
    print("=" * 62)
    for fn in (test_mass_props, test_fillet_hierarchy, test_min_wall_row,
               test_verify_plausibility_assembles, test_mistakes_catalog):
        fn()
    print("\n" + "=" * 62)
    print(f"PLAUSIBILITY {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
