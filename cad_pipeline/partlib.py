"""Standard-part library — build once, reuse forever (manual §2.4), with the exact fastener
and fit numbers from manual §3.2 as the single source of truth (mistakes catalog A8: regenerate
patterns FROM the standard's dims, never from remembered numbers).

Factories return ordinary Specs, so every standard part flows through the same build → verify
path as generated geometry, and the planner/robotics code can compose them into assemblies
by name instead of re-inventing (and mis-drilling) them.
"""
from __future__ import annotations

from .spec import Spec

# ---------------------------------------------------------------- standards (manual §3.2, exact)
ISO273_CLEARANCE = {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5}   # medium series, mm
TAP_DRILL = {"M2": 1.6, "M2.5": 2.05, "M3": 2.5, "M4": 3.3, "M5": 4.2}          # metric coarse, mm
RUNNING_FIT_DIAMETRAL = (0.1, 0.3)      # machined rotating shaft in plain bore, mm on ⌀
FDM_RUNNING_PER_SIDE = 0.25             # printed running fit, mm per side
PRESS_FIT_PRINTED = -0.05               # printed press fit: bore = OD − 0.05
HINGE_PIN_BORE = {"printed": 3.15, "machined": 3.05}   # for a ⌀3 pin
HEATSET_M3 = {"boss_bore": 4.0, "boss_od": 8.0, "extra_depth": 1.0}
BEARING_608 = {"od": 22.0, "id": 8.0, "width": 7.0}
NEMA17 = {"body": 42.3, "hole_square": 31.0, "pilot_d": 22.0, "screw": "M3"}


def nema17_mount_plate(thickness: float = 5.0, margin: float = 6.0) -> Spec:
    """Face-mount plate for a NEMA17 stepper: 31 mm hole square in M3 clearance (⌀3.4,
    ISO 273) + the ⌀22 register pilot (+0.5 locational clearance)."""
    side = NEMA17["body"] + 2 * margin
    half = NEMA17["hole_square"] / 2
    return Spec(object="NEMA17 mount plate", shape="box",
                envelope={"length": side, "width": side, "height": thickness},
                features=[{"type": "through_hole", "diameter": NEMA17["pilot_d"] + 0.5},
                          *({"type": "through_hole", "diameter": ISO273_CLEARANCE["M3"],
                             "at": [sx * half, sy * half]}
                            for sx in (-1, 1) for sy in (-1, 1))],
                tolerance=0.1)


def bearing_housing_608(wall: float = 5.0, printed: bool = True) -> Spec:
    """Press-fit pocket for a 608 bearing (⌀22×7): printed bore = OD − 0.05 (manual §3.2);
    through-bore ⌀10 clears the ⌀8 shaft with margin."""
    bore = BEARING_608["od"] + (PRESS_FIT_PRINTED if printed else 0.0)
    od = BEARING_608["od"] + 2 * wall
    h = BEARING_608["width"] + 3.0
    return Spec(object="608 bearing housing", shape="cylinder",
                envelope={"diameter": od, "height": h},
                features=[{"type": "counterbore", "diameter": 10.0, "cbore_diameter": bore,
                           "cbore_depth": BEARING_608["width"]}],
                tolerance=0.05)


def standoff(size: str = "M3", length: float = 12.0, od: float = 6.0, tapped: bool = True) -> Spec:
    """Cylindrical standoff/spacer: tapped (tap-drill bore) or clearance through."""
    bore = TAP_DRILL[size] if tapped else ISO273_CLEARANCE[size]
    return Spec(object=f"{size} standoff {length:g}mm", shape="cylinder",
                envelope={"diameter": od, "height": length},
                features=[{"type": "through_hole", "diameter": bore}], tolerance=0.05)


def heatset_boss_m3(height: float = 8.0) -> Spec:
    """Heat-set insert boss (M3): OD ⌀8, bore ⌀4.0 (manual §3.2; depth = insert + 1 handled
    by making the boss at least insert-length + 1 tall)."""
    return Spec(object="M3 heat-set boss", shape="cylinder",
                envelope={"diameter": HEATSET_M3["boss_od"], "height": height},
                features=[{"type": "through_hole", "diameter": HEATSET_M3["boss_bore"]}],
                tolerance=0.05)


def hinge_knuckle(pin_d: float = 3.0, od: float = 8.0, length: float = 12.0,
                  process: str = "printed") -> Spec:
    """Hinge knuckle for a ⌀3 pin: bore 3.15 printed / 3.05 machined (manual §3.2) — a
    running fit the assembly verifier's A6 joint-fit row will accept."""
    bore = HINGE_PIN_BORE[process] if pin_d == 3.0 else pin_d + 2 * FDM_RUNNING_PER_SIDE * (process == "printed") + 0.05 * (process != "printed")
    return Spec(object=f"hinge knuckle ⌀{pin_d:g} pin", shape="cylinder",
                envelope={"diameter": od, "height": length},
                features=[{"type": "through_hole", "diameter": bore}], tolerance=0.05)


PARTS = {"nema17_mount_plate": nema17_mount_plate, "bearing_housing_608": bearing_housing_608,
         "standoff": standoff, "heatset_boss_m3": heatset_boss_m3, "hinge_knuckle": hinge_knuckle}

# Prompt-injectable rendering of the standards (planner._SYSTEM) — generated FROM the tables
# above so the prompt can never drift from the data the factories and verifier use (A8's rule).
_STANDARDS_LINE = (
    "STANDARD DIMENSIONS (use these, never guess): bolt clearance holes "
    + " ".join(f"{k}→⌀{v}" for k, v in ISO273_CLEARANCE.items())
    + "; tap drill " + " ".join(f"{k}→⌀{v}" for k, v in TAP_DRILL.items())
    + f"; rotating pin in bore: bore ⌀ = pin ⌀ + {RUNNING_FIT_DIAMETRAL[0]}–{RUNNING_FIT_DIAMETRAL[1]} "
    f"(0.2 nominal — NEVER equal, that's a seized joint); printed press fit: bore = insert OD − 0.05; "
    f"heat-set M3 boss: OD ⌀{HEATSET_M3['boss_od']:g}, bore ⌀{HEATSET_M3['boss_bore']:g}; "
    f"NEMA17 mount: {NEMA17['hole_square']:g} mm square of M3 clearance holes + ⌀{NEMA17['pilot_d']:g} pilot; "
    f"608 bearing: ⌀{BEARING_608['od']:g}×{BEARING_608['width']:g}, pocket ⌀21.95 printed."
)


def selftest() -> int:
    """Every factory's Spec must build AND verify — the library is golden by construction."""
    from .builder import build
    from .verifier import verify
    bad = []
    for name, fn in PARTS.items():
        spec = fn()
        rep = verify(build(spec), spec)
        print(f"  [{'ok ' if rep.passed else 'FAIL'}] {name}: {spec.object}")
        if not rep.passed:
            bad.append((name, [r.name for r in rep.rows if not r.within_tol]))
    print(f"PARTLIB {len(PARTS) - len(bad)}/{len(PARTS)}")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
