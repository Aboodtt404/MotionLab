"""Track A — the typed structured spec (the contract).

Both Track-A entry points target this: text→spec and (Track C) image→spec.
The generator builds CadQuery *from* it; the verifier checks the built solid
*against* it, field by field. Kept deliberately small for the L1–L2 scope.
"""
from __future__ import annotations

import math
from typing import Annotated, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field


class ThroughHole(BaseModel):
    type: Literal["through_hole"] = "through_hole"
    diameter: float
    # Position (top-face XY, origin = part center). Precedence: `at` > `from_edge` > centered.
    at: Optional[Tuple[float, float]] = None       # explicit [x, y]
    from_edge: Optional[float] = None              # mm from the -X face (box only); y = 0
    axis: Literal["x", "y", "z"] = "z"


class HolePattern(BaseModel):
    """A set of equal through-holes in a regular arrangement (L2–L3: tests pattern
    reasoning, not just single placement). Expanded to points by `.points()` — the
    builder places them and the verifier re-derives the same expected set."""
    type: Literal["hole_pattern"] = "hole_pattern"
    diameter: float
    pattern: Literal["bolt_circle", "linear_x", "grid"]
    count: int = 4                  # bolt_circle / linear_x: total holes
    pitch_diameter: Optional[float] = None   # bolt_circle: PCD (centered at origin)
    spacing: Optional[float] = None          # linear_x / grid: hole-to-hole spacing
    nx: Optional[int] = None                 # grid: holes in X
    ny: Optional[int] = None                 # grid: holes in Y

    def points(self) -> List[Tuple[float, float]]:
        if self.pattern == "bolt_circle":
            r = (self.pitch_diameter or 0.0) / 2.0
            return [(round(r * math.cos(2 * math.pi * k / self.count), 6),
                     round(r * math.sin(2 * math.pi * k / self.count), 6)) for k in range(self.count)]
        if self.pattern == "linear_x":
            s = self.spacing or 0.0
            return [((k - (self.count - 1) / 2.0) * s, 0.0) for k in range(self.count)]
        # grid (centered): nx × ny at `spacing`
        nx, ny, s = self.nx or 1, self.ny or 1, self.spacing or 0.0
        return [((i - (nx - 1) / 2.0) * s, (j - (ny - 1) / 2.0) * s)
                for i in range(nx) for j in range(ny)]


class Fillet(BaseModel):
    type: Literal["fillet"] = "fillet"
    radius: float
    edges: str = "all_vertical"  # controlled selector (resolved by generator AND verifier)


class Chamfer(BaseModel):
    type: Literal["chamfer"] = "chamfer"
    distance: float
    edges: str = "all_vertical"


class VarFillet(BaseModel):
    """A VARIABLE-radius fillet (frontier — flowing sci-fi-prop blends): the radius sweeps from
    `r1` at one end of each selected edge to `r2` at the other. Box only. Built via raw OCCT (the
    fluent API is constant-radius only); the blend faces are BSplines, so verification is HEURISTIC
    — count + a curvature-sampled radius range, not the exact analytic check the constant fillet gets."""
    type: Literal["var_fillet"] = "var_fillet"
    r1: float
    r2: float
    edges: str = "all_vertical"


class Pocket(BaseModel):
    """A rectangular recess in the top face. With `at` it can be positioned anywhere — several
    positioned pockets give panel insets / panel-line grooves / greeble detail (the hard-surface
    look). Subtractive, so the envelope is unchanged."""
    type: Literal["pocket"] = "pocket"
    length: float
    width: float
    depth: float
    face: str = "top"
    at: Optional[Tuple[float, float]] = None   # top-face XY (origin = face center); None = centered


class CounterboreHole(BaseModel):
    """A counterbored hole (recess for a socket-head screw): a pilot bore of `diameter` with a
    larger flat-bottomed recess (`cbore_diameter` × `cbore_depth`) at the top face. Drilled along
    -Z from the top. BRep signature = two coaxial Z cylinders + an annular shoulder."""
    type: Literal["counterbore"] = "counterbore"
    diameter: float
    cbore_diameter: float
    cbore_depth: float
    at: Optional[Tuple[float, float]] = None   # top-face XY (origin = part center); None = centered


class CountersinkHole(BaseModel):
    """A countersunk hole (recess for a flat-head screw): a pilot bore of `diameter` with a conical
    seat of `csk_diameter` at the top, `csk_angle`° INCLUDED. BRep = pilot cylinder + a cone whose
    semi-angle = csk_angle/2."""
    type: Literal["countersink"] = "countersink"
    diameter: float
    csk_diameter: float
    csk_angle: float = 90.0       # included angle (82/90/100 standard)
    at: Optional[Tuple[float, float]] = None


class Draft(BaseModel):
    """A draft angle on a box's side walls (DFM for molding/casting): the walls tilt inward from
    the base (z−) up to the top (z+) by `angle`°, so the part releases from a mold. Box only — a
    tapered ROUND body is a `revolve` with a slanted profile (a verified cone)."""
    type: Literal["draft"] = "draft"
    angle: float  # degrees


class Shell(BaseModel):
    """Hollow a box to a thin wall of `thickness` (enclosures/housings — the biggest 'looks
    machined' upgrade after solid blocks). `open_face` leaves one face open ('top'=+Z, 'bottom'=−Z)
    or 'none' for a sealed hollow. Box only — a hollow ROUND body (cup/can) is a `revolve` with a
    U-profile. BRep: walls of thickness t separated by a cavity; verified by the min wall gap."""
    type: Literal["shell"] = "shell"
    thickness: float
    open_face: Literal["top", "bottom", "none"] = "top"


class Thread(BaseModel):
    """A COSMETIC thread (the production-standard representation — track-a-vocabulary §3.11): a
    cylindrical bore (internal) or the part's cylindrical surface (external) of nominal `diameter`,
    tagged with the thread callout (`pitch`). Real swept-helix geometry is deferred (needs a thread
    plugin like bd_warehouse; raw-OCCT helix sweeps are fragile). The verifier checks the nominal ⌀
    and records the callout — it does NOT BRep-verify a helix, which is correct: a cosmetic thread
    carries no helical geometry (it's PMI), so there is nothing helical to measure."""
    type: Literal["thread"] = "thread"
    diameter: float
    pitch: float = 1.0
    kind: Literal["internal", "external"] = "internal"
    at: Optional[Tuple[float, float]] = None   # internal bore position (z-axis), None = centered


class Mirror(BaseModel):
    """Make a part SYMMETRIC about a plane through the origin (L/R brackets, clamshells): the built
    part is reflected across `plane` and unioned, so any off-center feature is duplicated to the
    other side. The base shape is centered on the plane (envelope unchanged); the contract the
    verifier checks is symmetry itself — vol(part ∪ mirror(part)) == vol(part)."""
    type: Literal["mirror"] = "mirror"
    plane: Literal["XY", "XZ", "YZ"] = "YZ"


class Greeble(BaseModel):
    """A procedural hard-surface DETAIL PASS on a face (the sci-fi/filmic look): subdivide the face into
    a grid of panels, cut panel-line grooves along the grid, and recess a seeded `density` fraction of
    panels (greeble-detail-research.md). Cosmetic + purely SUBTRACTIVE, so the envelope is unchanged.
    Deterministic via `seed`. Recesses are inset `margin` from the grooves so cutters stay disjoint
    (no near-coincident booleans → robust). Density < 1 gives the non-uniform, focal look ('detail
    everywhere = no detail'). The builder dispatches on `spec.shape`: a BOX greebles its top (+Z) face
    (Stage A/B); a CYLINDER greebles its lateral (+R) face via the unrolled arc-length×height grid with
    radial cutters + fuzzy-boolean tolerance (Stage C, greeble-detail-research.md's deferred robustness
    case). focal `center`→busy mid-height band, `edges`→busy top/bottom rings."""
    type: Literal["greeble"] = "greeble"
    face: Literal["top", "side"] = "top"   # box top (+Z) face; cylinder lateral (+R) face = "side"
    panel: float = 20.0               # nominal panel cell size (mm) — sets the subdivision granularity
    depth: float = 2.0                # recessed-panel depth
    density: float = 0.5              # fraction of panels DETAILED (0..1); <1 ⇒ focal points + rest areas
    groove: float = 1.0               # panel-line groove width AND depth (shallow)
    margin: float = 3.0               # element inset within a cell (keeps detail off the grooves)
    seed: int = 0                     # determinism: same seed ⇒ same layout (builder == emit_code == verifier)
    # --- Stage B: hierarchy + raised panels + focal mask (defaults give the richer "filmic" look) ---
    levels: int = 2                   # 1 = flat cells; ≥2 = some cells subdivide into 2×2 finer sub-recesses
    subdiv: float = 0.35              # fraction of detailed cells that subdivide (when levels≥2)
    raised: float = 0.3               # fraction of detailed cells that RAISE a panel (additive) vs recess
    raise_h: float = 1.5              # raised-panel protrusion off the face (mm) — grows box height / cyl ⌀ by this
    focal: Literal["none", "center", "edges"] = "center"  # density weighting → non-uniform, focal points


Feature = Annotated[
    Union[ThroughHole, HolePattern, Fillet, Chamfer, Pocket, Draft, CounterboreHole, CountersinkHole,
          Mirror, Shell, VarFillet, Thread, Greeble],
    Field(discriminator="type")]


class Spec(BaseModel):
    object: str = "part"
    asset_class: Literal["hard_surface"] = "hard_surface"
    fabrication: Literal["render", "fabricate"] = "render"
    shape: Literal["box", "cylinder", "loft", "revolve", "sweep"]
    # box: length/width/height · cylinder: diameter/height
    # loft (a TAPERED bar — engineered arm/strut): tapers along its length (local X) from a base
    # profile at the −X end to a tip profile at the +X end. envelope = length (taper axis) +
    # width/height (base, wide/hub end) + width_top/height_top (tip, narrow/motor end).
    # revolve (a TURNED body — shaft/hub/nozzle/flange): a meridian `profile` of (radius, z) points
    # spun about the Z axis by `envelope["angle"]`° (default 360). Straight axis-parallel runs become
    # cylinders, tapers become cones, arcs become spheres/tori — all sharing the Z axis.
    # sweep (a TUBE/CHANNEL/spar): a round profile of envelope["diameter"] swept along `path`
    # (3D points), e.g. a coolant line, handle, or curved strut. vol = π·r²·(path length).
    envelope: Dict[str, float] = Field(default_factory=dict)  # box/cylinder/loft dims; revolve uses `profile`
    profile: Optional[List[Tuple[float, float]]] = None  # revolve meridian: [(radius, z), …]
    path: Optional[List[Tuple[float, float, float]]] = None  # sweep path: [(x, y, z), …]
    features: List[Feature] = Field(default_factory=list)
    tolerance: float = 0.1  # ± mm on directly-specified dimensions
    # DFM gates (advisory; each off at its zero/false default so plain specs are unaffected)
    min_wall: float = 0.0            # min manufacturable wall (mm); 0 = only flag actual overlaps
    min_internal_radius: float = 0.0  # tool radius; sharp internal pocket corners below it are flagged
    max_pocket_aspect: float = 0.0    # max pocket depth / width (tool reach); 0 = off
    draft_required: bool = False      # flag vertical walls (0° draft) for injection molding

    def loft_top_round(self) -> bool:
        """A loft whose tip profile is a CIRCLE (envelope has `diameter_top`) ⇒ a round↔rectangular
        transition/adapter, not just a tapered bar."""
        return "diameter_top" in self.envelope

    def loft_profiles(self) -> Tuple[float, float, float, float, float]:
        """(length, base_width, base_height, tip_width, tip_height) for a loft; tip defaults to
        base (⇒ a plain bar). A round tip (`diameter_top`) reports tip width = height = diameter, so
        the end-face check measures the circle's bbox."""
        e = self.envelope
        w, h = e["width"], e["height"]
        if self.loft_top_round():
            dt = e["diameter_top"]
            return e["length"], w, h, dt, dt
        return e["length"], w, h, e.get("width_top", w), e.get("height_top", h)

    def envelope_dims(self) -> Dict[str, float]:
        """Canonical (x, y, z) extents the bounding box should report."""
        e = self.envelope
        if self.shape == "box":
            return {"length": e["length"], "width": e["width"], "height": e["height"]}
        if self.shape == "loft":
            L, w, h, wt, ht = self.loft_profiles()
            return {"length": L, "width": max(w, wt), "height": max(h, ht)}
        if self.shape == "revolve":
            d, h = self.revolve_extents()
            return {"diameter": d, "height": h}
        return {"diameter": e["diameter"], "height": e["height"]}

    def path_length(self) -> float:
        """Total length of the sweep `path` polyline."""
        p = self.path or []
        return sum(sum((p[i + 1][k] - p[i][k]) ** 2 for k in range(3)) ** 0.5 for i in range(len(p) - 1))

    def revolve_extents(self) -> Tuple[float, float]:
        """(diameter, height) of a revolve from its meridian: ⌀ = 2·max(radius), height = z-span."""
        p = self.profile or []
        rs = [r for r, _ in p]
        zs = [z for _, z in p]
        return (2 * max(rs) if rs else 0.0, (max(zs) - min(zs)) if zs else 0.0)


def expected_holes(spec: "Spec") -> List[Tuple[float, float, float, float, str]]:
    """Every through-hole as a 3D centerline anchor (px, py, pz, diameter, axis): the point
    the hole axis passes through, with the free (along-axis) coord at the part center.
    `at` is the 2D position in the plane PERPENDICULAR to the axis — z→(x,y), x→(y,z),
    y→(x,z). Single source of truth shared by the builder (drills them) and verifier
    (re-resolves them), so a pattern/axis is specified in exactly one place."""
    out: List[Tuple[float, float, float, float, str]] = []
    L = spec.envelope.get("length", spec.envelope.get("diameter", 0.0))
    for f in spec.features:
        if isinstance(f, ThroughHole):
            ax = f.axis
            if f.at is not None:
                a, b = f.at
                px, py, pz = ({"z": (a, b, 0.0), "x": (0.0, a, b), "y": (a, 0.0, b)})[ax]
            elif f.from_edge is not None and spec.shape == "box" and ax == "z":
                px, py, pz = -L / 2 + f.from_edge, 0.0, 0.0
            else:
                px, py, pz = 0.0, 0.0, 0.0
            out.append((px, py, pz, f.diameter, ax))
        elif isinstance(f, HolePattern):
            out.extend((px, py, 0.0, f.diameter, "z") for px, py in f.points())
    return out
