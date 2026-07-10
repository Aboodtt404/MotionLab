"""Plausibility & manufacturability rows — fable_run/out/00_manual.md §2.1 (anti-toy realism) + the
§3.4 CAD-verifier gaps (min_wall, mass_props). These are TARGET-SPECIFIC (product / fabricate / print),
NOT universal — Fable frames §2.1 as hard rules for *realistic product modeling*, so they run on demand
(the benchmark P-category, the print verifier, a fabricate target), never on every corpus-gate verify().

Every function returns rows in the standard verifier Row envelope so they compose into any Report.
"""
from __future__ import annotations

from typing import List, Optional

from .spec import Spec
from .verifier import Row

# Material densities, g/mm³ (= g/cm³ × 1e-3). The mass oracle (§3.4 mass_props) is only as good as the
# declared material; default to PLA (the common print material) when unspecified.
DENSITY_G_PER_MM3 = {
    "pla": 1.24e-3, "abs": 1.04e-3, "petg": 1.27e-3, "nylon": 1.14e-3, "resin": 1.15e-3,
    "aluminum": 2.70e-3, "steel": 7.85e-3, "brass": 8.50e-3, "titanium": 4.51e-3,
}


def mass_props_row(volume_mm3: float, material: str = "pla",
                   expected_g: Optional[float] = None) -> Row:
    """§3.4 mass_props: mass = volume × density. If an estimate is given, pass iff 0.5×–2× it
    (Fable's band); otherwise informational (report the mass, pass)."""
    rho = DENSITY_G_PER_MM3.get(material.lower(), DENSITY_G_PER_MM3["pla"])
    mass = volume_mm3 * rho
    if expected_g is not None and expected_g > 0:
        ok = 0.5 * expected_g <= mass <= 2.0 * expected_g
        return Row(f"mass · {material} (0.5–2× est)", round(expected_g, 2), round(mass, 2), ok,
                   "ok" if ok else "dfm")
    return Row(f"mass · {material} (g, informational)", None, round(mass, 3), True, "ok")


def fillet_classes(spec: Spec) -> List[float]:
    """Distinct rounding radii the DESIGN uses (fillet r, chamfer distance, var-fillet extremes),
    rounded to 0.1 mm. §2.1 rule 3: a real product uses ≥3 radius classes; uniform radii read as toy."""
    radii = set()
    for f in getattr(spec, "features", []):
        t = getattr(f, "type", None)
        if t == "fillet":
            radii.add(round(f.radius, 1))
        elif t == "chamfer":
            radii.add(round(f.distance, 1))
        elif t == "var_fillet":
            radii.add(round(f.r1, 1)); radii.add(round(f.r2, 1))
    return sorted(radii)


def fillet_hierarchy_row(spec: Spec, min_classes: int = 3) -> Row:
    """§2.1 anti-toy: report the number of distinct radius classes; fail only when a plausibility
    target explicitly demands ≥min_classes (a plain bracket legitimately has one)."""
    n = len(fillet_classes(spec))
    ok = n >= min_classes
    return Row(f"plausibility · fillet radius classes (≥{min_classes})", f"≥{min_classes}", n, ok,
               "ok" if ok else "dfm")


def min_wall_row(solid, min_mm: float, samples: int = 6000) -> Row:
    """§3.4 / §2.1 rule 6: minimum wall thickness by inward surface raycast (see mesh_verify.min_wall).
    Fails if any wall is thinner than min_mm (a zero/near-zero wall is the classic 'fake' geometry)."""
    from .mesh_verify import min_wall, tri_from_solid
    mesh = tri_from_solid(solid)
    mw = min_wall(mesh, samples)
    ok = mw is not None and mw >= min_mm - 1e-3
    return Row("min_wall (inward raycast)", f"≥{min_mm}", round(mw, 3) if mw is not None else None,
               ok, "ok" if ok else "dfm")


def verify_plausibility(solid, spec: Spec, *, material: str = "pla",
                        expected_mass_g: Optional[float] = None,
                        min_wall_mm: Optional[float] = None,
                        min_fillet_classes: Optional[int] = None,
                        volume_mm3: Optional[float] = None) -> List[Row]:
    """Assemble the applicable §2.1/§3.4 plausibility rows for a part. Thresholds are opt-in: pass
    min_wall_mm (or rely on spec.min_wall) for the wall check, expected_mass_g for the mass band,
    min_fillet_classes for the anti-toy radius-hierarchy gate."""
    rows: List[Row] = []
    mw = min_wall_mm if min_wall_mm is not None else (spec.min_wall if getattr(spec, "min_wall", 0) else None)
    if mw:
        rows.append(min_wall_row(solid, mw))
    if volume_mm3 is not None:
        rows.append(mass_props_row(volume_mm3, material, expected_mass_g))
    if min_fillet_classes is not None:
        rows.append(fillet_hierarchy_row(spec, min_fillet_classes))
    return rows
