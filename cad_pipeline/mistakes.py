"""The 46 weak-model failure modes — fable_run/out/05_mistakes.md, as a structured catalog.

Fable: "each DETECTION column is written to be implemented directly as a verifier row, and each
REPAIR as the typed feedback string handed back on retry — rows of this table ARE the error→fix
table of a repair loop." This module makes that table explicit: each Mistake carries its detection
summary, the typed repair feedback, and the verifier check_category (schemas.CHECK_CATEGORY) or
"exec" that routes it. The repair loop / feedback builders can look up precise guidance by category.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Mistake:
    id: str
    area: str            # cad | mesh | assembly | print | web | procedural
    summary: str
    detection: str
    repair: str          # the typed feedback string to hand back on retry
    category: str        # a schemas.CHECK_CATEGORY value, or "exec" for code-never-ran failures


CATALOG: List[Mistake] = [
    # ── CAD parametric code (C1–C14) ─────────────────────────────────────────────────────────
    Mistake("C1", "cad", "relative .center() per hole accumulates offsets",
            "worst hole-center offset > tol AND drift grows with hole index",
            "place ALL holes with one absolute pushPoints([...]).hole(d) (origin = part center)", "selector_binding"),
    Mistake("C2", "cad", "plane name passed to .workplane() (wants a float offset)",
            "traceback ~ Multiplied()/offsetVector; no geometry",
            "start with cq.Workplane('XY'); face planes via .faces('>Z').workplane()", "exec"),
    Mistake("C3", "cad", "fillet/chamfer radius ≥ adjacent face half-width",
            "BRep_API command-not-done, or vanished face; r ≥ min(adjacent dim)/2",
            "clamp r below the adjacent-dim bound, or select fewer edges", "dimensional"),
    Mistake("C4", "cad", "right radius, wrong edge set (selector binding)",
            "count of blend faces matching the selector ≠ expected count",
            "fix the selector ('>Z' vs '|Z'), not the dimension", "selector_binding"),
    Mistake("C5", "cad", "hole drilled along the wrong axis",
            "hole cylinder axis label ≠ spec axis",
            "sketch on the face ⊥ to the spec axis, or cut with the correct direction vector", "selector_binding"),
    Mistake("C6", "cad", "position measured from the wrong datum (edge vs center)",
            "|measured − expected| ∈ {L/2, W/2} ± tol",
            "recompute anchor in the stated frame (origin = part center): x = −L/2 + from_edge", "selector_binding"),
    Mistake("C7", "cad", "unit mixup (cm/inch treated as mm)",
            "bbox_measured/bbox_expected ≈ 10, 0.1, 25.4, or 0.03937",
            "multiply all dims by the single detected factor; parameterize a UNIT constant", "dimensional"),
    Mistake("C8", "cad", "radius/diameter confusion",
            "measured ⌀ / expected ⌀ ≈ 2.0 or 0.5",
            "pass diameter/2 to radius args (circle(d/2)), d to .hole(d)", "dimensional"),
    Mistake("C9", "cad", "overlapping features (holes merge into a slot)",
            "hole↔hole clearance = center_dist − r₁ − r₂ < 0",
            "reposition per spec; enforce pitch ≥ r₁+r₂+min_wall", "integrity"),
    Mistake("C10", "cad", "boolean between exactly-tangent/coincident faces",
            "BRepCheck invalid, or post-cut volume delta ≈ 0",
            "over-cut: extend cutters 0.5–1 mm past the surface; avoid zero-gap tangency", "integrity"),
    Mistake("C11", "cad", "unclosed sketch before extrude",
            "traceback ~ 'No pending wires'",
            "close the profile: polyline(...).close() before extrude/cutBlind", "exec"),
    Mistake("C12", "cad", "final solid never bound to the output contract",
            "NameError: 'result' is not defined",
            "assign the final Workplane/solid to `result` as the last statement", "exec"),
    Mistake("C13", "cad", "feature order wrong (holes cut before shell)",
            "shell wall row fails while hole rows pass, or shell throws",
            "reorder: base → draft → shell → then cut holes/pockets", "structure"),
    Mistake("C14", "cad", "taper/loft ignored — straight prism emitted",
            "end-face census: −X face dims == +X face dims but spec says base ≠ tip",
            "loft between the two profiles, don't extrude", "dimensional"),
    # ── Mesh (M1–M11) ────────────────────────────────────────────────────────────────────────
    Mistake("M1", "mesh", "non-manifold edges (>2 faces share an edge)",
            "count(edges with face-degree ≠ 2) > 0", "delete duplicate faces, merge-by-distance, or voxel-remesh", "validity"),
    Mistake("M2", "mesh", "leaky mesh (boundary edges / holes)",
            "is_watertight == False; boundary-edge count > 0", "fill_holes / cap boundary loops; last resort Poisson rebuild", "validity"),
    Mistake("M3", "mesh", "flipped normals on a subset of faces",
            "signed volume < 0 or ray-parity disagrees with orientation", "flood-fill coherent orientation; recompute outward normals", "validity"),
    Mistake("M4", "mesh", "inconsistent winding between islands",
            "is_winding_consistent == False", "unify winding per connected component (seed = largest face)", "validity"),
    Mistake("M5", "mesh", "self-intersecting surface",
            "triangle-triangle intersection count > 0 (pymeshlab)", "voxel-remesh self-union, or push apart + re-stitch", "integrity"),
    Mistake("M6", "mesh", "degenerate faces (zero area / slivers)",
            "face area < 1e-8 mm² or min angle < 0.5°", "collapse short edges; delete degenerates; re-triangulate", "validity"),
    Mistake("M7", "mesh", "duplicate vertices along seams",
            "unique(position)/vertex_count < 0.7", "weld by distance 1e-4; rebuild split normals by angle", "validity"),
    Mistake("M8", "mesh", "over-tessellation (10⁶ tris for a crate)",
            "tri_count > budget; density ≫ category norm", "quadric edge-collapse to budget, volume ±2%", "dfm"),
    Mistake("M9", "mesh", "under-tessellation (visible facets on curves)",
            "max dihedral step on curved regions > 15°", "re-export at angular deflection ≤ 5° / chord ≤ 0.1 mm", "dfm"),
    Mistake("M10", "mesh", "wrong pivot/origin (rotates around a corner)",
            "|centroid_xy| > 5% of bbox, or base ≠ 0", "bake transform: origin = base-center (min-z=0, centroid xy=0)", "structure"),
    Mistake("M11", "mesh", "unbaked node transforms (FBX unit-scale 0.01)",
            "node scale ≠ 1.0 or rotation ≠ identity on mesh nodes", "apply/bake all transforms pre-export; unit scale 1.0", "structure"),
    # ── Assembly (A1–A8) ─────────────────────────────────────────────────────────────────────
    Mistake("A1", "assembly", "floating/disconnected parts",
            "fused solid count > 1, or contact-graph components > 1", "add the missing mate; translate along min-gap by gap + 1–4 mm overlap", "disconnected"),
    Mistake("A2", "assembly", "all parts clumped at origin (no placement solved)",
            "pairwise centroid distances ≈ 0; total ∩ ≫ 0", "solve the mate graph (ground/stack/radial/flush); never emit raw coordinates", "structure"),
    Mistake("A3", "assembly", "interference between mated parts",
            "pairwise ∩ > 1 mm³", "add clearance along the mate normal (0.2–0.5 mm); shrink the inner part", "integrity"),
    Mistake("A4", "assembly", "missing constraint — part unreachable in the mate graph",
            "graph reachability: unmated component count > 0", "add an attach/ground mate for every unreached component", "disconnected"),
    Mistake("A5", "assembly", "impossible joint motion (hinge bores misaligned)",
            "knuckle-axis colinearity > 0.05, or pose-sweep ∩ > 0", "re-place knuckles on one common axis; re-run the pose sweep", "structure"),
    Mistake("A6", "assembly", "zero-clearance running fit (pin ⌀ == bore ⌀)",
            "bore ⌀ − pin ⌀ < 0.1 (need 0.1–0.3)", "size pin = bore − 0.2; keep the tolerance note in the brief", "dfm"),
    Mistake("A7", "assembly", "legs/supports hover above the ground plane",
            "min-z(leg parts) > 2 mm", "extend legs / set leg z so feet reach z=0; re-check seat height", "structure"),
    Mistake("A8", "assembly", "fastener mismatch (pattern vs standard)",
            "hole ⌀/pitch vs the fastener standard table mismatch", "regenerate the pattern from the standard's dims, not remembered numbers", "dfm"),
    # ── Print (P1–P4) ────────────────────────────────────────────────────────────────────────
    Mistake("P1", "print", "wall below printable minimum",
            "min ray-sampled thickness < 0.8 mm FDM / 0.4 SLA", "thicken to ≥ 2× nozzle (0.8–1.2); offset inner surface, keep outer dims", "dfm"),
    Mistake("P2", "print", "unsupported overhang",
            "down-facing normal steeper than 55° from vertical (above first 1 mm)", "45° chamfer under features; reorient; add support/draft", "dfm"),
    Mistake("P3", "print", "trapped volume with no drain",
            "voxel flood-fill leaves an unreachable interior void with 0 openings", "add ≥ 2 drain holes ⌀ ≥ 3 mm at the lowest cavity points", "dfm"),
    Mistake("P4", "print", "zero-thickness internal walls / embedded faces",
            "faces not on the volume boundary > 0", "delete interior faces; re-solidify; re-check M1/M2", "validity"),
    # ── Web / real-time / game (W1–W6) ───────────────────────────────────────────────────────
    Mistake("W1", "web", "Z-up exported into a Y-up format",
            "GLB: largest extent of a standing object along Z not Y", "rotate −90° about X and bake; assert min-Y = 0", "structure"),
    Mistake("W2", "web", "wrong absolute scale for web/AR",
            "GLB bbox vs class prior off by ≥ 10×", "convert units at export (mm→m ×0.001); assert height in class range", "dimensional"),
    Mistake("W3", "web", "normal maps without tangents",
            "primitive has normalTexture but no TANGENT accessor", "generate MikkTSpace tangents; re-export; validator clean", "validity"),
    Mistake("W4", "web", "overlapping lightmap UVs (UV2)",
            "UV2 island intersection area > 0; gap < 2/res", "re-unwrap UV2 with ≥ 2 px padding; keep UV0", "validity"),
    Mistake("W5", "web", "non-power-of-two or oversized textures",
            "image dims ∉ {2ⁿ} or > 2048", "resize/atlas to POT ≤ 2048; re-reference in material", "dfm"),
    Mistake("W6", "web", "n-gons shipped to a triangle renderer",
            "face vertex count > 4 anywhere", "triangulate on export; verify silhouette Hausdorff ≤ 0.5%", "validity"),
    # ── Procedural (R1–R3) ───────────────────────────────────────────────────────────────────
    Mistake("R1", "procedural", "unseeded randomness — output unreproducible",
            "two runs with the same brief hash to different geometry", "seed every RNG from the brief seed; assert run-to-run hash equality", "validity"),
    Mistake("R2", "procedural", "compound boolean cutter inverts or hangs",
            "post-cut volume > pre-cut volume, or wall-clock > N·t̄", "cut sequentially; fuzzy tolerance for near-tangent; defer clean()", "integrity"),
    Mistake("R3", "procedural", "operation order (mirror after asymmetric edit)",
            "vol(part ∪ mirror(part)) − vol(part) > 1%", "move mirror before the asymmetric ops, or re-apply edits to both sides", "structure"),
]

BY_ID: Dict[str, Mistake] = {m.id: m for m in CATALOG}
BY_AREA: Dict[str, List[Mistake]] = {}
for _m in CATALOG:
    BY_AREA.setdefault(_m.area, []).append(_m)


def feedback_for(mistake_id: str) -> str:
    """The typed repair feedback for a mistake id — what the loop hands back on retry."""
    return BY_ID[mistake_id].repair
