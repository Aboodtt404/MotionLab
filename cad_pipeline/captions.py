"""Deterministic L0–L3 prompt synthesis from a Spec (Text2CAD taxonomy).

Because the targeted layer AUTHORS the spec, we caption from the structured truth directly — no
images, no VLM→LLM chain (CADmium's lesson; docs/research/track-a-targeted-layer.md §5). Four
abstraction levels per part:
  L0 — one abstract phrase, no dims        L1 — beginner: shape + features, no measurements
  L2 — intermediate: geometry + rough mm   L3 — expert: precise relative dimensions + selectors

Light rng-driven synonym choice keeps prompts from being byte-identical across samples (reduces
phrasing overfit). This is the SHIP-SAFE baseline; an optional model paraphrase pass (deferred) can
add linguistic diversity later — CAD-Coder's 160K gated pairs already supply natural-language breadth
at instruct time.
"""
from __future__ import annotations

import random
from typing import Dict

from .spec import Spec


def _pick(rng: random.Random, *opts: str) -> str:
    return rng.choice(opts)


def _edge_phrase(edges: str) -> str:
    """'all_vertical' → 'all vertical edges'; 'top' → 'the top edges'."""
    e = edges.replace("_", " ")
    return f"{e} edges" if e.startswith("all") else f"the {e} edges"


_ORDINAL = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


# ----------------------------------------------------------------- shape noun + dimensions
def _shape_noun(spec: Spec, rng: random.Random) -> str:
    e = spec.envelope
    if spec.shape == "box":
        flat = e.get("height", 0) < 0.4 * max(e.get("length", 1), e.get("width", 1))
        return _pick(rng, "plate", "panel") if flat else _pick(rng, "block", "body", "housing")
    if spec.shape == "cylinder":
        return _pick(rng, "cylindrical body", "round body", "disc")
    if spec.shape == "revolve":
        return _pick(rng, "turned body", "revolved part")
    if spec.shape == "loft":
        return "round-to-rectangular adapter" if spec.loft_top_round() else "tapered body"
    if spec.shape == "profile_extrude":
        return (_pick(rng, "silhouette body (side outline trimmed by a plan outline)",
                      "profiled body with a shaped side view and plan cutout")
                if spec.plan_profile else
                _pick(rng, "silhouette body (extruded side outline)", "profiled slab"))
    if spec.shape == "loft_sections":
        return _pick(rng, "smoothly lofted hull", "multi-station lofted body", "fuselage-like lofted form")
    if spec.shape == "prism":
        poly = {3: "triangular", 4: "square", 5: "pentagonal", 6: "hexagonal",
                8: "octagonal"}.get(spec.sides, f"{spec.sides}-sided")
        return _pick(rng, f"{poly} bar", f"{poly} standoff", f"{poly} prism")
    if spec.shape == "sweep" and {"width", "height"} <= set(spec.envelope):
        return _pick(rng, "box-section beam", "extruded channel", "rail")
    return _pick(rng, "swept tube", "pipe")


def _dims_phrase(spec: Spec, precise: bool) -> str:
    def n(x: float) -> str:
        return f"{x:.1f}".rstrip("0").rstrip(".") if precise else f"{round(x / 5) * 5:g}"
    if spec.shape == "sweep":   # round bore OR a rectangular section, swept along the path
        if {"width", "height"} <= set(spec.envelope):
            return (f"{n(spec.envelope['width'])}×{n(spec.envelope['height'])} mm section, "
                    f"{n(spec.path_length())} mm long")
        return f"{n(spec.envelope['diameter'])} mm bore, {n(spec.path_length())} mm long"
    if spec.shape == "prism":   # regular N-gon bar: circumscribed ⌀ across corners × height
        return f"{n(spec.envelope['diameter'])} mm across, {n(spec.envelope['height'])} mm tall"
    d = spec.envelope_dims()
    if spec.shape in ("profile_extrude", "loft_sections"):   # hero bodies: bbox extents
        return f"{n(d['length'])}×{n(d['width'])}×{n(d['height'])} mm overall"
    if spec.shape in ("box", "loft"):
        return f"{n(d['length'])}×{n(d['width'])}×{n(d['height'])} mm"
    return f"{n(d['diameter'])} mm dia × {n(d['height'])} mm"


# ----------------------------------------------------------------- feature → phrase, per level
def _feat_phrase(f, level: int, rng: random.Random) -> str:
    t = f.type
    # NOTE: feature phrases are DETERMINISTIC (no per-call rng) so identical features in one part
    # read identically and group cleanly ("three recessed pockets"). Lexical variety across SAMPLES
    # comes from the shape noun / L0 / lead, which don't repeat within a part.
    if t == "fillet":
        return "filleted edges" if level <= 1 else f"a {f.radius:g} mm fillet on {_edge_phrase(f.edges)}"
    if t == "chamfer":
        return "chamfered edges" if level <= 1 else f"a {f.distance:g} mm chamfer on {_edge_phrase(f.edges)}"
    if t == "var_fillet":
        return "a variable-radius blend" if level <= 1 else f"a blend tapering from {f.r1:g} to {f.r2:g} mm"
    if t == "through_hole":
        where = "centered" if not f.at or f.at == (0.0, 0.0) else f"at ({f.at[0]:g}, {f.at[1]:g})"
        ax = "" if f.axis == "z" else f" along {f.axis.upper()}"
        return "a through hole" if level <= 1 else f"a {f.diameter:g} mm through-hole {where}{ax}"
    if t == "hole_pattern":
        if f.pattern == "bolt_circle":
            base = f"a {f.count}-hole bolt circle"
            return base if level <= 1 else f"{base} of {f.diameter:g} mm holes on a {f.pitch_diameter:g} mm PCD"
        if f.pattern == "grid":
            base = f"a {f.nx}×{f.ny} grid of holes"
            return base if level <= 1 else f"{base}, {f.diameter:g} mm at {f.spacing:g} mm pitch"
        base = f"a row of {f.count} holes"
        return base if level <= 1 else f"{base}, {f.diameter:g} mm at {f.spacing:g} mm spacing"
    if t == "pocket":
        where = "" if not f.at or f.at == (0.0, 0.0) else f" at ({f.at[0]:g}, {f.at[1]:g})"
        if level <= 1:
            return "a recessed pocket"
        return f"a {f.length:g}×{f.width:g} mm pocket {f.depth:g} mm deep{where}"
    if t == "counterbore":
        return "a counterbored hole" if level <= 1 else \
            f"a counterbored hole ({f.diameter:g} mm pilot, {f.cbore_diameter:g}×{f.cbore_depth:g} mm recess)"
    if t == "countersink":
        return "a countersunk hole" if level <= 1 else \
            f"a {f.diameter:g} mm countersunk hole ({f.csk_angle:g}° × {f.csk_diameter:g} mm)"
    if t == "draft":
        return "draft on the side walls" if level <= 1 else f"{f.angle:g}° draft on the side walls"
    if t == "shell":
        face = {"top": "open top", "bottom": "open bottom", "none": "sealed"}[f.open_face]
        return f"hollowed ({face})" if level <= 1 else f"shelled to a {f.thickness:g} mm wall, {face}"
    if t == "thread":
        return f"an internal M{f.diameter:g} thread" if level <= 1 else \
            f"an internal M{f.diameter:g}×{f.pitch:g} tapped bore"
    if t == "mirror":
        return f"mirror-symmetric about {f.plane}"
    if t == "greeble":
        where = "the top face" if f.face == "top" else "the lateral (side) surface"
        if level <= 1:
            return "a paneled greeble detail pass"
        return (f"a procedural greeble pass on {where} (~{f.panel:g} mm panels, {f.depth:g} mm recesses, "
                f"~{round(f.density * 100):g}% detailed with panel-line grooves)")
    return t


def _pluralize(phrase: str) -> str:
    """'an inset' → 'insets'; 'a recessed pocket' → 'recessed pockets'."""
    if phrase.startswith("an "):
        p = phrase[3:]
    elif phrase.startswith("a "):
        p = phrase[2:]
    else:
        p = phrase
    return p + ("es" if p.endswith(("s", "x", "ch")) else "s")


def _join(parts) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    # collapse runs of identical phrases ("an inset, an inset, an inset" → "three insets")
    grouped = []
    i = 0
    while i < len(parts):
        j = i
        while j < len(parts) and parts[j] == parts[i]:
            j += 1
        cnt = j - i
        grouped.append(parts[i] if cnt == 1 else f"{_ORDINAL.get(cnt, str(cnt))} {_pluralize(parts[i])}")
        i = j
    if len(grouped) == 1:
        return grouped[0]
    return ", ".join(grouped[:-1]) + " and " + grouped[-1]


def describe(spec: Spec, rng: random.Random) -> Dict[str, str]:
    """Spec → {l0, l1, l2, l3}."""
    noun = _shape_noun(spec, rng)
    obj = spec.object

    l0 = _pick(rng, f"a {obj}", obj, f"{obj} part")

    feats_l1 = _join([_feat_phrase(f, 1, rng) for f in spec.features])
    l1 = f"A {noun}" + (f" with {feats_l1}." if feats_l1 else ".")

    feats_l2 = _join([_feat_phrase(f, 2, rng) for f in spec.features])
    lead = _pick(rng, f"A {_dims_phrase(spec, False)} {noun}",
                 f"A {noun}, roughly {_dims_phrase(spec, False)}")
    l2 = lead + (f", with {feats_l2}." if feats_l2 else ".")

    feats_l3 = _join([_feat_phrase(f, 3, rng) for f in spec.features])
    extra = ""
    if spec.shape == "revolve" and spec.profile:
        extra = f" The meridian profile is {[[round(r, 1), round(z, 1)] for r, z in spec.profile]} (radius, z)."
    elif spec.shape == "sweep" and spec.path:
        extra = f" Swept along the path {[[round(c, 1) for c in p] for p in spec.path]}."
    elif spec.shape == "profile_extrude" and spec.side_profile:
        extra = f" The side (X–Z) outline is {[[round(x, 1), round(z, 1)] for x, z in spec.side_profile]}"
        if spec.side_arcs and any(spec.side_arcs):
            extra += f" with per-segment sagitta {list(spec.side_arcs)}"
        extra += "."
        if spec.plan_profile:
            extra += f" The plan (X–Y) outline is {[[round(x, 1), round(y, 1)] for x, y in spec.plan_profile]}."
    elif spec.shape == "loft_sections" and spec.sections:
        st = [{k: (round(v, 1) if isinstance(v, (int, float)) else v) for k, v in s.items()}
              for s in sorted(spec.sections, key=lambda s: s["x"])]
        extra = f" Lofted smoothly through the stations {st} (x along the length)."
    l3 = (f"Model a {obj}: a {noun} measuring {_dims_phrase(spec, True)}"
          + (f", featuring {feats_l3}." if feats_l3 else ".") + extra)

    return {"l0": l0, "l1": l1, "l2": l2, "l3": l3}
