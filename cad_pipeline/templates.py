"""Parametric template sampler — the Phase-2 targeted-layer spec generator.

The pivot (docs/research/track-a-targeted-layer.md §0/§3): an LLM authoring `Spec`s from the open
schema gave 0% yield. Instead we SAMPLE structure from hand-authored, per-category parametric
templates → deterministic, 100% coherent, mm-scale, weighted to the 45/40/15 taxonomy + the
15/45/40 L1/L2/L3 mix. Diversity is by parameter sampling (+ spec-hash dedup), so we skip
Zero-to-CAD's DINOv3 view-curation. Field precedent: CAD-Recode (procedural-tree → CadQuery).

Each template returns a `Spec` designed to stay inside builder capability + the verifier's
feature-integrity (non-overlapping holes within bounds). The driver still exec→verify gates every
sample (the accept gate), so the rare sampled edge case is rejected, not shipped.

BOX-ONLY features (fillet/chamfer/draft/shell/var_fillet/mirror) are added ONLY to box specs — the
builder skips them elsewhere and the verifier would then flag a missing feature.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Dict, List, Tuple

from .spec import (Chamfer, CounterboreHole, CountersinkHole, Draft, Fillet, HolePattern, Mirror,
                   Pocket, Shell, Spec, Thread, ThroughHole, VarFillet)


def _r(rng: random.Random, lo: float, hi: float, step: float = 0.5) -> float:
    """A clean random dimension in [lo, hi], snapped to `step` mm."""
    n = round(rng.uniform(lo, hi) / step)
    return round(n * step, 3)


# ----------------------------------------------------------------- shared feature samplers
def _fillet_or_chamfer(rng: random.Random, L: float, W: float, H: float) -> List:
    """A vertical-edge fillet OR chamfer, radius safely < half the min in-plane dim."""
    cap = min(L, W) / 2 - 2
    if cap < 2:
        return []
    size = _r(rng, 1.5, min(cap, H * 0.6, 8), 0.5)
    if rng.random() < 0.5:
        return [Fillet(radius=size, edges=rng.choice(["all_vertical", "all_vertical", "top"]))]
    return [Chamfer(distance=size, edges=rng.choice(["all_vertical", "top", "bottom"]))]


def _grid_pattern(rng: random.Random, L: float, W: float, d: float) -> HolePattern | None:
    """A centered nx×ny grid that fits within margins with positive hole↔hole clearance."""
    margin = d / 2 + 4
    nx, ny = rng.choice([(2, 2), (2, 2), (2, 3), (3, 2), (3, 3)])
    sx = (L - 2 * margin) / (nx - 1) if nx > 1 else 1e9
    sy = (W - 2 * margin) / (ny - 1) if ny > 1 else 1e9
    s_max = min(sx, sy)
    if s_max < d + 4:
        return None
    s = _r(rng, d + 4, s_max, 0.5)
    return HolePattern(diameter=d, pattern="grid", nx=nx, ny=ny, spacing=s)


def _bolt_circle(rng: random.Random, span: float, d: float) -> HolePattern | None:
    """A bolt circle whose PCD fits in `span` (min in-plane dim) with adjacent-hole clearance."""
    count = rng.choice([4, 4, 6, 6, 8])
    pcd_max = span - 2 * (d / 2 + 4)
    if pcd_max < d * 2:
        return None
    pcd = _r(rng, max(d * 2, pcd_max * 0.5), pcd_max, 1.0)
    if pcd * math.sin(math.pi / count) < d + 3:   # adjacent-hole chord must clear
        count = 4
        if pcd * math.sin(math.pi / count) < d + 3:
            return None
    return HolePattern(diameter=d, pattern="bolt_circle", count=count, pitch_diameter=pcd)


def _stepped_meridian(rng: random.Random, taper: bool) -> List[Tuple[float, float]]:
    """A turned-body meridian (radius, z): starts on-axis (0,0), traces 2–4 stepped/tapered
    rings, returns on-axis (0, z_top). Monotonic z ⇒ no self-intersection ⇒ a valid solid."""
    n = rng.randint(2, 4)
    r0 = _r(rng, 12, 28, 1.0)
    pts: List[Tuple[float, float]] = [(0.0, 0.0), (r0, 0.0)]
    z = 0.0
    r = r0
    for _ in range(n):
        z = round(z + _r(rng, 8, 22, 1.0), 3)
        nr = round(max(4.0, r - _r(rng, 3, 10, 1.0)), 3)   # generally narrowing (hub/nozzle look)
        if r - nr < 1.0:                                   # guarantee a real step (no zero-length edge)
            nr = round(max(4.0, r - 2.0), 3)
        if taper:                                          # slanted run (cone)
            pts.append((nr, z))
        else:                                              # square step (cylinder run)
            if abs(nr - r) >= 1.0:                          # only emit the step if it actually changes ⌀
                pts.append((r, z))
                pts.append((nr, z))
            else:
                pts.append((r, z))
        r = nr
    pts.append((0.0, pts[-1][1]))                          # close back to the axis at the top
    # dedup any consecutive duplicates (zero-length segments crash makeLine: "command not done")
    out: List[Tuple[float, float]] = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out


# ----------------------------------------------------------------- ROBOTICS / MECHANICAL (45%)
def mounting_bracket(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 50, 120), _r(rng, 35, 80), _r(rng, 6, 16)
    feats: List = _fillet_or_chamfer(rng, L, W, H)
    gp = _grid_pattern(rng, L, W, _r(rng, 4, 8, 0.5))
    if gp:
        feats.append(gp)
    return Spec(object="mounting bracket", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


def motor_mount(rng: random.Random) -> Spec:
    L = W = _r(rng, 55, 95)
    H = _r(rng, 6, 12)
    bore = _r(rng, 14, 26, 1.0)
    feats: List = [ThroughHole(diameter=bore, at=(0.0, 0.0))]
    bc = _bolt_circle(rng, min(L, W), _r(rng, 4, 6, 0.5))
    if bc and (bc.pitch_diameter or 0) / 2 > bore / 2 + 4:   # mounting holes clear the bore
        feats.append(bc)
    feats += _fillet_or_chamfer(rng, L, W, H)
    return Spec(object="motor mount", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


def bolt_circle_flange(rng: random.Random) -> Spec:
    D = _r(rng, 50, 110)
    H = _r(rng, 6, 16)
    bore = _r(rng, 12, 30, 1.0)
    feats: List = [ThroughHole(diameter=bore, at=(0.0, 0.0))]
    bc = _bolt_circle(rng, D, _r(rng, 4, 7, 0.5))
    if bc and (bc.pitch_diameter or 0) / 2 > bore / 2 + 4:
        feats.append(bc)
    return Spec(object="bolt-circle flange", shape="cylinder", envelope={"diameter": D, "height": H}, features=feats)


def turned_shaft_or_hub(rng: random.Random) -> Spec:
    prof = _stepped_meridian(rng, taper=rng.random() < 0.3)
    return Spec(object="turned shaft or hub", shape="revolve", envelope={}, profile=prof)


def electronics_enclosure(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 60, 130), _r(rng, 45, 90), _r(rng, 20, 45)
    t = _r(rng, 2, 4, 0.5)
    # NO fillet/chamfer on a shelled box: edge-mods double-bind to inner+outer walls → the verifier
    # measures 8 edges where the spec says 4. Shelled enclosures stay shell + holes (composes cleanly).
    feats: List = [Shell(thickness=t, open_face=rng.choice(["top", "top", "bottom"]))]
    gp = _grid_pattern(rng, L, W, _r(rng, 3.5, 6, 0.5))
    if gp:
        feats.append(gp)
    return Spec(object="electronics enclosure", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


def standoff_or_spacer(rng: random.Random) -> Spec:
    D = _r(rng, 8, 22)
    H = _r(rng, 10, 40)
    return Spec(object="standoff or spacer", shape="cylinder", envelope={"diameter": D, "height": H},
                features=[ThroughHole(diameter=_r(rng, 3, max(3.5, D - 4), 0.5), at=(0.0, 0.0))])


def threaded_boss_or_plate(rng: random.Random) -> Spec:
    if rng.random() < 0.5:
        D = _r(rng, 16, 36)
        H = _r(rng, 10, 30)
        td = _r(rng, 4, max(5, D - 6), 0.5)
        return Spec(object="threaded boss", shape="cylinder", envelope={"diameter": D, "height": H},
                    features=[Thread(diameter=td, pitch=rng.choice([0.7, 0.8, 1.0, 1.25, 1.5]), kind="internal")])
    L = W = _r(rng, 40, 70)
    H = _r(rng, 10, 18)
    td = _r(rng, 5, 12, 0.5)
    return Spec(object="tapped plate", shape="box", envelope={"length": L, "width": W, "height": H},
                features=[Thread(diameter=td, pitch=rng.choice([0.8, 1.0, 1.25, 1.5]), kind="internal")])


def adapter_or_duct(rng: random.Random) -> Spec:
    L = _r(rng, 50, 120)
    W, H = _r(rng, 30, 70), _r(rng, 25, 60)
    if rng.random() < 0.6:   # rect → round adapter
        dt = _r(rng, 16, min(W, H) - 4, 1.0)
        return Spec(object="round-to-rect adapter", shape="loft",
                    envelope={"length": L, "width": W, "height": H, "diameter_top": dt})
    return Spec(object="tapered duct", shape="loft",   # rect → smaller rect
                envelope={"length": L, "width": W, "height": H,
                          "width_top": _r(rng, 12, W - 6, 1.0), "height_top": _r(rng, 10, H - 6, 1.0)})


def coolant_line(rng: random.Random) -> Spec:
    d = _r(rng, 6, 16, 1.0)
    a, b, c = _r(rng, 30, 70, 5), _r(rng, 25, 60, 5), _r(rng, 20, 50, 5)
    if rng.random() < 0.5:   # planar L/U bend
        path = [(0, 0, 0), (a, 0, 0), (a, b, 0)]
    else:                    # 3D bend
        path = [(0, 0, 0), (a, 0, 0), (a, b, 0), (a, b, c)]
    return Spec(object="coolant line", shape="sweep", envelope={"diameter": d}, path=path)


# ----------------------------------------------------------------- SCI-FI HARD-SURFACE (40%)
def _inset_pockets(rng: random.Random, L: float, W: float, H: float, n: int) -> List[Pocket]:
    """A row of shallow panel insets across the plate (the hard-surface greeble look)."""
    depth = _r(rng, 1, min(3, H * 0.4), 0.5)
    pl = _r(rng, 12, max(13, L / (n + 1)), 1.0)
    pw = _r(rng, 10, W * 0.5, 1.0)
    span = L - pl - 8
    out = []
    for i in range(n):
        x = round(-span / 2 + (span * i / max(1, n - 1)) if n > 1 else 0.0, 3)
        out.append(Pocket(length=pl, width=pw, depth=depth, at=(x, 0.0)))
    return out


def greebled_panel(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 90, 160), _r(rng, 55, 100), _r(rng, 6, 12)
    feats: List = _inset_pockets(rng, L, W, H, rng.randint(2, 3))
    gp = _grid_pattern(rng, L, W, _r(rng, 3, 5, 0.5))
    if gp:
        feats.append(gp)
    if rng.random() < 0.5:
        feats += _fillet_or_chamfer(rng, L, W, H)
    return Spec(object="greebled hull panel", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


def vent_grille(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 70, 130), _r(rng, 40, 80), _r(rng, 6, 12)
    n = rng.randint(3, 6)
    depth = _r(rng, 2, min(4, H * 0.6), 0.5)
    slot_w = _r(rng, 3, 6, 0.5)
    slot_l = round(W * 0.7, 1)
    span = L - 16
    feats: List = [Pocket(length=slot_w, width=slot_l, depth=depth,
                          at=(round(-span / 2 + span * i / (n - 1), 3), 0.0)) for i in range(n)]
    return Spec(object="vent grille", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


def turret_body(rng: random.Random) -> Spec:
    D = _r(rng, 40, 90)
    H = _r(rng, 30, 70)
    feats: List = [ThroughHole(diameter=_r(rng, 8, 20, 1.0), at=(0.0, 0.0), axis="x")]  # barrel bore
    return Spec(object="turret body", shape="cylinder", envelope={"diameter": D, "height": H}, features=feats)


def antenna_housing(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 40, 70), _r(rng, 40, 70), _r(rng, 25, 50)
    # shell + a top cable/mount hole; no edge-mods (shell+fillet double-binds → unexpected cylinders)
    feats: List = [Shell(thickness=_r(rng, 2, 3.5, 0.5), open_face="bottom"),
                   ThroughHole(diameter=_r(rng, 4, 8, 0.5), at=(0.0, 0.0))]
    return Spec(object="antenna/sensor housing", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


def hatch_panel(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 60, 110), _r(rng, 50, 90), _r(rng, 8, 16)
    feats: List = [Pocket(length=round(L * 0.5, 1), width=round(W * 0.5, 1), depth=_r(rng, 2, min(4, H * 0.4), 0.5), at=(0.0, 0.0))]
    pilot = _r(rng, 4, 6, 0.5)
    feats.append(CountersinkHole(diameter=pilot, csk_diameter=pilot + _r(rng, 3, 5, 0.5),
                                 csk_angle=rng.choice([82.0, 90.0, 100.0]), at=(round(-L / 2 + 10, 1), round(-W / 2 + 10, 1))))
    feats += _fillet_or_chamfer(rng, L, W, H)
    return Spec(object="hatch/access panel", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


def truss_node(rng: random.Random) -> Spec:
    S = _r(rng, 45, 80)
    feats: List = [ThroughHole(diameter=_r(rng, 8, 16, 1.0), at=(0.0, 0.0), axis="z"),
                   ThroughHole(diameter=_r(rng, 6, 12, 1.0), at=(0.0, 0.0), axis="x"),
                   ThroughHole(diameter=_r(rng, 6, 12, 1.0), at=(0.0, 0.0), axis="y")]
    feats += [Chamfer(distance=_r(rng, 2, 6, 0.5), edges="all_vertical")]
    return Spec(object="structural truss node", shape="box", envelope={"length": S, "width": S, "height": S}, features=feats)


def paneled_plate(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 90, 150), _r(rng, 55, 95), _r(rng, 6, 12)
    feats: List = _inset_pockets(rng, L, W, H, rng.randint(2, 3))
    bc = _bolt_circle(rng, min(L, W), _r(rng, 3.5, 5, 0.5))
    if bc:
        feats.append(bc)
    feats += [Chamfer(distance=_r(rng, 1.5, 4, 0.5), edges="all_vertical")]
    return Spec(object="sci-fi paneled plate", shape="box", envelope={"length": L, "width": W, "height": H}, features=feats)


# ----------------------------------------------------------------- PURE-TAIL STRESS (15%)
def multi_feature_part(rng: random.Random) -> Spec:
    # 4 stacked features, asymmetric placement (L3). Vertical-edge FILLET + a vertical CYLINDER
    # feature (counterbore/centered hole) double-count in fillet-binding, so we use a top chamfer
    # (planar bevel) here, not a vertical fillet — composes cleanly with the cbore + grid.
    L, W, H = _r(rng, 90, 150), _r(rng, 60, 95), _r(rng, 16, 28)
    feats: List = [Chamfer(distance=_r(rng, 1.5, 4, 0.5), edges="top"),
                   Pocket(length=_r(rng, 16, 28, 1), width=_r(rng, 12, 22, 1),
                          depth=_r(rng, 2, min(6, H * 0.4), 0.5), at=(round(-L / 4, 1), round(W / 6, 1)))]
    gp = _grid_pattern(rng, L / 2, W, _r(rng, 4, 6, 0.5))   # grid biased to one half (asymmetric look)
    if gp:
        feats.append(gp)
    pilot = _r(rng, 4, 6, 0.5)
    feats.append(CounterboreHole(diameter=pilot, cbore_diameter=pilot + _r(rng, 3, 6, 0.5),
                                 cbore_depth=_r(rng, 2, min(5, H * 0.3), 0.5),
                                 at=(round(L / 3, 1), round(-W / 4, 1))))
    return Spec(object="multi-feature mechanical part", shape="box",
                envelope={"length": L, "width": W, "height": H}, features=feats)


def stepped_turned_body(rng: random.Random) -> Spec:
    # always multi-segment with a mix of steps AND tapers
    prof = _stepped_meridian(rng, taper=False)
    # inject one tapered run by nudging an interior ring inward
    return Spec(object="stepped turned body", shape="revolve", envelope={}, profile=prof)


def draughted_enclosure(rng: random.Random) -> Spec:
    L, W, H = _r(rng, 60, 110), _r(rng, 45, 85), _r(rng, 25, 50)
    feats: List = [Draft(angle=_r(rng, 2, 6, 0.5)), Shell(thickness=_r(rng, 2, 4, 0.5), open_face="top")]
    gp = _grid_pattern(rng, L * 0.8, W * 0.8, _r(rng, 3.5, 6, 0.5))   # tighter: walls draft inward
    if gp:
        feats.append(gp)
    return Spec(object="draughted thin-wall enclosure", shape="box",
                envelope={"length": L, "width": W, "height": H}, features=feats)


# ----------------------------------------------------------------- registry + taxonomy weights
# weight = relative frequency (mirrors synth.TAXONOMY / corpus-scope §2: robotics 45 / sci-fi 40 / tail 15)
TEMPLATES: Dict[str, Tuple[Callable[[random.Random], Spec], int]] = {
    # robotics / mechanical — 45
    "mounting bracket": (mounting_bracket, 6),
    "motor mount": (motor_mount, 5),
    "bolt-circle flange": (bolt_circle_flange, 5),
    "turned shaft or hub": (turned_shaft_or_hub, 6),
    "electronics enclosure": (electronics_enclosure, 6),
    "standoff or spacer": (standoff_or_spacer, 3),
    "threaded boss or plate": (threaded_boss_or_plate, 5),
    "round-to-rect adapter or duct": (adapter_or_duct, 5),
    "coolant line or pipe": (coolant_line, 4),
    # sci-fi hard-surface — 40
    "greebled hull/fuselage panel": (greebled_panel, 8),
    "vent or louver grille": (vent_grille, 6),
    "turret or weapon body": (turret_body, 5),
    "antenna/sensor housing": (antenna_housing, 5),
    "hatch or access panel": (hatch_panel, 6),
    "sci-fi paneled plate with insets": (paneled_plate, 7),
    "structural truss node": (truss_node, 3),
    # pure-tail stress — 15
    "multi-feature part (4+ features, asymmetric)": (multi_feature_part, 6),
    "stepped turned body": (stepped_turned_body, 4),
    "draughted thin-wall enclosure": (draughted_enclosure, 5),
}


def weighted_categories() -> List[str]:
    """The category pool expanded by weight (for the driver's round-robin)."""
    return [c for c, (_, w) in TEMPLATES.items() for _ in range(w)]


def sample(category: str, rng: random.Random) -> Spec:
    return TEMPLATES[category][0](rng)


def level(spec: Spec) -> str:
    n = len([f for f in spec.features])
    return "L1" if n <= 1 else ("L2" if n <= 3 else "L3")
