"""Track A — controlled selector grammar + verifier-side resolution (the core IP, §3).

The generator emits a feature *and* a selector predicate naming the entities it binds to
("all_vertical edges", "top rim"); the verifier independently re-resolves that predicate
against the built BRep and checks the feature landed on EXACTLY that entity set
(resolve-twice). This catches "right radius, wrong edges".

v2 vocabulary — orientation + location over a base box:
    all_vertical    edges ‖ Z              (the 4 corner edges)
    top             top-rim edges ‖ X/Y    (the 4 edges of the top face)
    bottom          bottom-rim edges       (the 4 edges of the bottom face)
    all_horizontal  every X/Y edge         (top 4 + bottom 4)
Each resolves to (edge_kind, location, count); a fillet/chamfer must bind to exactly that set.
"""
from __future__ import annotations

from typing import Tuple

# selector → (edge_kind, location).  edge_kind: "vertical" (‖Z) | "horizontal" (‖X or ‖Y)
_SELECTORS = {
    "all_vertical":   ("vertical", "any"),
    "top":            ("horizontal", "top"),
    "bottom":         ("horizontal", "bottom"),
    "all_horizontal": ("horizontal", "any"),
}

# selector → CadQuery edge-selector string (what the builder/generator applies it with)
CQ_EDGE = {
    "all_vertical":   "|Z",
    "top":            ">Z",
    "bottom":         "<Z",
    "all_horizontal": "|X or |Y",
}


def resolve(selector: str) -> Tuple[str, str]:
    """(edge_kind, location) the selector denotes. Default = vertical/any."""
    return _SELECTORS.get(selector, ("vertical", "any"))


def orientation_of(selector: str) -> str:
    """Back-compat: the axis vertical-edge features bind to ('z'); horizontal ⇒ 'xy'."""
    kind, _ = resolve(selector)
    return "z" if kind == "vertical" else "xy"


def expected_edge_count(shape_kind: str, selector: str, sides: int = 4) -> int:
    """Set-valued resolution: how many edges the selector denotes on the base envelope.
    A box has 4 collinear vertical edges, and 4 horizontal edges per (top/bottom) face.
    A regular N-gon PRISM generalizes the box: N vertical edges, N horizontal edges per rim.
    An axisymmetric body (cylinder / revolve) has no straight edges, so a straight-edge
    selector is the empty set — but its TOP/BOTTOM circular rim IS a single filletable/
    chamferable edge, so `top`/`bottom` denote exactly one rim edge there."""
    if shape_kind in ("box", "prism"):
        n = 4 if shape_kind == "box" else sides
        kind, loc = resolve(selector)
        if kind == "vertical":
            return n
        return 2 * n if loc == "any" else n
    if shape_kind in ("cylinder", "revolve"):
        kind, loc = resolve(selector)
        # only the top/bottom circular rim is a rim-break target on a turned body
        return 1 if kind == "horizontal" and loc in ("top", "bottom") else 0
    return 0
