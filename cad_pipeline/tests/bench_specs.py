"""EVAL_BENCH — the parametric-CAD slice of the 100-task benchmark, as verifiable Specs.

Source: fable_run/out/02_benchmark.md §C (Parametric CAD, C01–C20) — the Fable-5-authored
benchmark. Each task below is transcribed into our Spec schema so the EXISTING golden
builder + deterministic verifier are the pass/fail oracle (same by-construction guarantee
as EVAL_HARD: eval_baseline.preflight() builds+verifies every spec before any model is
judged on it).

Coverage vs EVAL_HARD: this set adds the feature axes EVAL_HARD never exercises —
counterbore, countersink, shell, draft, positioned pocket, revolve, loft(+round tip),
sweep, mirror, and var_fillet.

Not transcribed (with reasons):
  C04  hex standoff        — hexagonal prism isn't in the shape vocabulary (box/cyl/loft/revolve/sweep)
  C05  8-bolt flange       — EXACT duplicate of EVAL_HARD "8-bolt mounting flange"
  C15  7-hole linear bar   — near-duplicate of EVAL_HARD "filleted vent panel" (same bar/pattern)
  C16  3×2 grid plate      — exact duplicate of EVAL_HARD "grid-perforated plate (3x2)"
  C18  params re-run       — harness-level check (re-execute with overridden dict), not a Spec
  C20  STEP export/reimport— round-trip check outside the generate→verify loop
"""
from __future__ import annotations

from ..spec import Spec

EVAL_BENCH = [
    # C01 (L1): bracket 80×50×30, fillet the 4 vertical edges r=4
    Spec(object="C01 filleted bracket", shape="box",
         envelope={"length": 80, "width": 50, "height": 30},
         features=[{"type": "fillet", "radius": 4, "edges": "all_vertical"}], tolerance=0.1),
    # C02 (L1): cylinder ⌀60×20 with a ⌀20 through-bore
    Spec(object="C02 bored disc", shape="cylinder", envelope={"diameter": 60, "height": 20},
         features=[{"type": "through_hole", "diameter": 20}], tolerance=0.1),
    # C03 (L1): plate 100×60×5 with 4 corner holes ⌀5.5 at (±42, ±22)
    Spec(object="C03 corner-hole plate", shape="box",
         envelope={"length": 100, "width": 60, "height": 5},
         features=[{"type": "through_hole", "diameter": 5.5, "at": [-42, -22]},
                   {"type": "through_hole", "diameter": 5.5, "at": [42, -22]},
                   {"type": "through_hole", "diameter": 5.5, "at": [-42, 22]},
                   {"type": "through_hole", "diameter": 5.5, "at": [42, 22]}], tolerance=0.1),
    # C06 (L2): plate 70×40×10 with 2 counterbores (⌀5 pilot, ⌀9×5 recess) at (±20, 0)
    Spec(object="C06 counterbored plate", shape="box",
         envelope={"length": 70, "width": 40, "height": 10},
         features=[{"type": "counterbore", "diameter": 5, "cbore_diameter": 9, "cbore_depth": 5, "at": [-20, 0]},
                   {"type": "counterbore", "diameter": 5, "cbore_diameter": 9, "cbore_depth": 5, "at": [20, 0]}],
         tolerance=0.1),
    # C07 (L2): countersunk hole (pilot ⌀4, csk ⌀8, 90° included) centered in a 50×50×8 plate
    Spec(object="C07 countersunk plate", shape="box",
         envelope={"length": 50, "width": 50, "height": 8},
         features=[{"type": "countersink", "diameter": 4, "csk_diameter": 8, "csk_angle": 90}], tolerance=0.1),
    # C08 (L2): shell a 60×60×40 box to 2.5 mm walls, open top
    Spec(object="C08 open-top shell", shape="box",
         envelope={"length": 60, "width": 60, "height": 40},
         features=[{"type": "shell", "thickness": 2.5, "open_face": "top"}], tolerance=0.1),
    # C09 (L2): box 80×50×30 with 3° draft on all side walls
    Spec(object="C09 drafted box", shape="box",
         envelope={"length": 80, "width": 50, "height": 30},
         features=[{"type": "draft", "angle": 3}], tolerance=0.1),
    # C10 (L2): pocket 40×25 depth 6 centered at (10, 5) in a 100×60×12 plate
    Spec(object="C10 offset-pocket plate", shape="box",
         envelope={"length": 100, "width": 60, "height": 12},
         features=[{"type": "pocket", "length": 40, "width": 25, "depth": 6, "at": [10, 5]}], tolerance=0.1),
    # C11 (L3): revolved stepped shaft ⌀20×15 / ⌀32×20 / ⌀20×15 (z-span 50, radius set {10, 16})
    Spec(object="C11 stepped shaft", shape="revolve",
         profile=[(0, 0), (10, 0), (10, 15), (16, 15), (16, 35), (10, 35), (10, 50), (0, 50)],
         tolerance=0.1),
    # C12 (L3): loft adapter — 60×40 rect base → ⌀30 round tip, length 80 along X
    Spec(object="C12 rect-to-round adapter", shape="loft",
         envelope={"length": 80, "width": 60, "height": 40, "diameter_top": 30}, tolerance=0.1),
    # C13 (L3): tube ⌀12 swept along an L-path (60 along X, then 40 up Z) — vol = π·36·100
    Spec(object="C13 L-tube", shape="sweep", envelope={"diameter": 12},
         path=[(0, 0, 0), (60, 0, 0), (60, 0, 40)], tolerance=0.1),
    # C14 (L3): mirror-symmetric bracket about YZ (off-center hole duplicated by the mirror)
    Spec(object="C14 mirrored bracket", shape="box",
         envelope={"length": 80, "width": 40, "height": 10},
         features=[{"type": "through_hole", "diameter": 6, "at": [20, 10]},
                   {"type": "mirror", "plane": "YZ"}], tolerance=0.1),
    # C17 (L4): combo part 90×60×20 — vertical fillet r5, 4×⌀5 corner holes inset 10 (→ ±35, ±20),
    # centered pocket 40×24×8, 2 mm top-rim chamfer. Feature order matters: chamfer the rim
    # BEFORE the pocket is cut so the pocket rim isn't chamfered too.
    Spec(object="C17 combo plate", shape="box",
         envelope={"length": 90, "width": 60, "height": 20},
         features=[{"type": "fillet", "radius": 5, "edges": "all_vertical"},
                   {"type": "chamfer", "distance": 2, "edges": "top"},
                   {"type": "through_hole", "diameter": 5, "at": [-35, -20]},
                   {"type": "through_hole", "diameter": 5, "at": [35, -20]},
                   {"type": "through_hole", "diameter": 5, "at": [-35, 20]},
                   {"type": "through_hole", "diameter": 5, "at": [35, 20]},
                   {"type": "pocket", "length": 40, "width": 24, "depth": 8}], tolerance=0.1),
    # C19 (L4): variable-radius fillet r 2→6 on the 4 vertical edges of a 60×60×30 box
    Spec(object="C19 variable-fillet block", shape="box",
         envelope={"length": 60, "width": 60, "height": 30},
         features=[{"type": "var_fillet", "r1": 2, "r2": 6, "edges": "all_vertical"}], tolerance=0.1),
]


# Benchmark difficulty levels (02_benchmark §C column 2; weights L1=1…L4=4 per the scoring
# spec: capability_score = 100·Σ(weight·passed)/Σ(weight), computed at pass@1 and pass@3).
BENCH_LEVELS = {"C01": 1, "C02": 1, "C03": 1,
                "C06": 2, "C07": 2, "C08": 2, "C09": 2, "C10": 2,
                "C11": 3, "C12": 3, "C13": 3, "C14": 3,
                "C17": 4, "C19": 4}
