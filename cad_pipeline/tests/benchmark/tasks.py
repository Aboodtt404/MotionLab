"""The 100-task benchmark registry — fable_run/out/02_benchmark.md, transcribed.

Every one of the 100 tasks is registered with its (id, level, category, prompt) so the /263 weight
denominator, the category floors, and the bands are HONEST from day one. Tasks whose verifier or
representation isn't built yet carry `blocked_on` and count as not-passed (they light up as Phase-3
verifiers / the Phase-5 router land). Runnable tasks carry a golden `oracle` — a callable that builds
our by-construction artifact and returns its verifier report; the oracle preflight asserts the task is
encodable + passes our deterministic verifier (Fable's preflight discipline: the task is valid only if
the golden path is green).

Ordering of the build-out (02_benchmark categories): C (parametric CAD) and A/D (assembly/drone) are
checkable with the B-rep + assembly verifier we already have; M/B/W/G/P land with their verifiers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ...assembly import Assembly, Component, Mate, repair_connectivity, solve_layout, verify_assembly
from ...builder import build
from ...spec import Spec
from ...verifier import verify
from ..bench_specs import EVAL_BENCH

# C-id → golden Spec (bench_specs objects are named "C01 …", "C02 …", …)
EVAL_BENCH_BY_ID: Dict[str, Spec] = {s.object.split()[0]: s for s in EVAL_BENCH}


# ─────────────────────────────────────────────────────────────────────────── task model
@dataclass
class Task:
    id: str
    level: int
    category: str          # one of C M B W G P D A
    prompt: str
    oracle: Optional[Callable[[], dict]] = None   # golden build+verify → report dict; None = blocked
    blocked_on: Optional[str] = None              # capability/verifier this task waits on
    criteria: Optional[Callable[[dict], bool]] = None   # extra task-specific assertions on the report

    @property
    def runnable(self) -> bool:
        return self.oracle is not None


# ─────────────────────────────────────────────────────────────── oracle helpers
def _spec_oracle(spec: Spec) -> Callable[[], dict]:
    def run() -> dict:
        rep = verify(build(spec), spec)
        return rep.to_dict()
    return run


def _asm_oracle(asm_factory: Callable[[], Assembly]) -> Callable[[], dict]:
    def run() -> dict:
        asm = repair_connectivity(solve_layout(asm_factory()))
        return verify_assembly(asm)
    return run


# ─────────────────────────────────────────────────────────────── A — assemblies (golden)
def _stool() -> Assembly:                                   # A01
    seat = Component(name="seat", role="seat", part=Spec(
        object="seat", shape="cylinder", envelope={"diameter": 140, "height": 16}))
    legs = [Component(name=f"leg{i}", role="leg", part=Spec(
        object="leg", shape="box", envelope={"length": 16, "width": 16, "height": 110})) for i in range(4)]
    return Assembly(object="four-leg stool", components=[seat, *legs], mates=[
        Mate(kind="radial", parts=[f"leg{i}" for i in range(4)], around="seat", count=4,
             radius=55, splay_deg=10),
        Mate(kind="stack", a="seat", b="leg0", overlap=4),
    ], fuse=True)


def _shelf_bracket() -> Assembly:                           # A02
    shelf = Component(name="shelf", role="top", part=Spec(
        object="shelf", shape="box", envelope={"length": 200, "width": 120, "height": 12}))
    bracket = Component(name="bracket", role="support", part=Spec(
        object="bracket", shape="box", envelope={"length": 60, "width": 120, "height": 60}))
    return Assembly(object="shelf on L-bracket", components=[bracket, shelf], mates=[
        Mate(kind="stack", a="shelf", b="bracket", overlap=3)], fuse=True)


def _bolt_stack() -> Assembly:                              # A04
    p1 = Component(name="plate1", role="panel", part=Spec(
        object="plate", shape="box", envelope={"length": 40, "width": 40, "height": 6},
        features=[{"type": "through_hole", "diameter": 6.6}]))
    p2 = Component(name="plate2", role="panel", part=Spec(
        object="plate", shape="box", envelope={"length": 40, "width": 40, "height": 6},
        features=[{"type": "through_hole", "diameter": 6.6}]))
    return Assembly(object="two clamped plates", components=[p1, p2], mates=[
        Mate(kind="stack", a="plate2", b="plate1", overlap=0.1)], fuse=True)


def _shaft_bearings() -> Assembly:                          # A08 — bearings at ±20 (shoulder spacing 40)
    shaft = Component(name="shaft", role="body", part=Spec(
        object="shaft", shape="cylinder", envelope={"diameter": 8, "height": 60}))
    b1 = Component(name="bearing1", role="hub", at=(0.0, 0.0, 20.0), part=Spec(
        object="bearing", shape="cylinder", envelope={"diameter": 22, "height": 7},
        features=[{"type": "through_hole", "diameter": 8.05}]))
    b2 = Component(name="bearing2", role="hub", at=(0.0, 0.0, -20.0), part=Spec(
        object="bearing", shape="cylinder", envelope={"diameter": 22, "height": 7},
        features=[{"type": "through_hole", "diameter": 8.05}]))
    # no mates: bearings sit on the shaft by their explicit z; the ⌀8.05 bores clear the ⌀8 shaft
    # within contact tol → connected but not interfering (a seated running fit).
    return Assembly(object="shaft with two bearing seats", components=[shaft, b1, b2], fuse=False)


# ─────────────────────────────────────────────────────────────── D — drone plates (golden)
def _quad_frame() -> Spec:                                  # D01 (250 mm wheelbase → motors at ±88.4)
    return Spec(object="250mm quad frame plate", shape="box",
                envelope={"length": 200, "width": 200, "height": 4},
                features=[{"type": "through_hole", "diameter": 3, "at": [sx * 88.4, sy * 88.4]}
                          for sx in (-1, 1) for sy in (-1, 1)]
                + [{"type": "hole_pattern", "pattern": "grid", "diameter": 3, "nx": 2, "ny": 2,
                    "spacing": 30.5}], tolerance=0.2)


def _motor_mount() -> Spec:                                 # D02 (2207 cross pattern 16/19 + ⌀8 bore)
    return Spec(object="2207 motor mount plate", shape="cylinder",
                envelope={"diameter": 40, "height": 4},
                features=[{"type": "through_hole", "diameter": 8},
                          {"type": "through_hole", "diameter": 3, "at": [9.5, 0]},
                          {"type": "through_hole", "diameter": 3, "at": [-9.5, 0]},
                          {"type": "through_hole", "diameter": 3, "at": [0, 8]},
                          {"type": "through_hole", "diameter": 3, "at": [0, -8]}], tolerance=0.1)


def _bottom_plate() -> Spec:                                # D04 (2 mm plate + FC/AIO patterns + pocket)
    return Spec(object="2mm frame bottom plate", shape="box",
                envelope={"length": 100, "width": 100, "height": 2},
                features=[{"type": "hole_pattern", "pattern": "grid", "diameter": 3, "nx": 2, "ny": 2, "spacing": 30.5},
                          {"type": "pocket", "length": 30, "width": 30, "depth": 1.0}], tolerance=0.05)


# ─────────────────────────────────────────── C tasks not in bench_specs (eval-only, buildable)
def _flange_c05() -> Spec:                                  # C05: ⌀90×12, ⌀20 bore, 8×⌀6 on PCD 70
    return Spec(object="C05 bolt-circle flange", shape="cylinder",
                envelope={"diameter": 90, "height": 12},
                features=[{"type": "through_hole", "diameter": 20},
                          {"type": "hole_pattern", "pattern": "bolt_circle", "count": 8,
                           "pitch_diameter": 70, "diameter": 6}], tolerance=0.1)


def _linear_bar_c15() -> Spec:                              # C15: 7×⌀6 pitch 18 on 140×40×6
    return Spec(object="C15 linear-hole bar", shape="box",
                envelope={"length": 140, "width": 40, "height": 6},
                features=[{"type": "hole_pattern", "pattern": "linear_x", "count": 7,
                           "spacing": 18, "diameter": 6}], tolerance=0.1)


def _grid_plate_c16() -> Spec:                              # C16: 3×2 ⌀5 spacing 25 on 100×60×5
    return Spec(object="C16 grid-hole plate", shape="box",
                envelope={"length": 100, "width": 60, "height": 5},
                features=[{"type": "hole_pattern", "pattern": "grid", "nx": 3, "ny": 2,
                           "spacing": 25, "diameter": 5}], tolerance=0.1)


# ───────────────────────────────────────────────────────────── level/category table (all 100)
# (fable_run/out/02_benchmark.md — the L column of every category table). Weights: L1=1…L4=4, Σ=263.
_LEVELS: Dict[str, int] = {
    # C — Parametric CAD
    "C01": 1, "C02": 1, "C03": 1, "C04": 1, "C05": 2, "C06": 2, "C07": 2, "C08": 2, "C09": 2, "C10": 2,
    "C11": 3, "C12": 3, "C13": 3, "C14": 3, "C15": 3, "C16": 3, "C17": 4, "C18": 4, "C19": 4, "C20": 4,
    # M — Mesh modeling
    "M01": 1, "M02": 1, "M03": 1, "M04": 2, "M05": 2, "M06": 2, "M07": 2, "M08": 2, "M09": 3, "M10": 3,
    "M11": 3, "M12": 3, "M13": 4, "M14": 4, "M15": 4,
    # B — Blender scripted/procedural
    "B01": 1, "B02": 1, "B03": 2, "B04": 2, "B05": 2, "B06": 2, "B07": 3, "B08": 3, "B09": 3, "B10": 3,
    "B11": 4, "B12": 4,
    # W — Three.js / web GLB
    "W01": 1, "W02": 1, "W03": 2, "W04": 2, "W05": 2, "W06": 3, "W07": 3, "W08": 3, "W09": 4, "W10": 4,
    # G — Game assets
    "G01": 1, "G02": 1, "G03": 2, "G04": 2, "G05": 2, "G06": 2, "G07": 3, "G08": 3, "G09": 3, "G10": 3,
    "G11": 4, "G12": 4,
    # P — Product models
    "P01": 2, "P02": 2, "P03": 2, "P04": 2, "P05": 3, "P06": 3, "P07": 3, "P08": 3, "P09": 4, "P10": 4,
    # D — Drones / robotics
    "D01": 2, "D02": 2, "D03": 2, "D04": 3, "D05": 3, "D06": 3, "D07": 4, "D08": 4,
    # A — Assemblies, mates & joints
    "A01": 2, "A02": 2, "A03": 2, "A04": 3, "A05": 3, "A06": 3, "A07": 3, "A08": 3, "A09": 3, "A10": 4,
    "A11": 4, "A12": 4, "A13": 4,
}

# short prompts (full pass/fail criteria live in 02_benchmark.md; these are the human-readable task line)
_PROMPTS: Dict[str, str] = {
    "C05": "flange ⌀90×12, center bore ⌀20, 8×⌀6 on PCD 70",
    "C15": "linear pattern: 7×⌀6 holes, pitch 18, on a 140×40×6 bar",
    "C16": "grid pattern: 3×2 ⌀5 holes, spacing 25, on a 100×60×5 plate",
    "A01": "4-legged stool: seat ⌀140×16, height 120, legs 90° apart, splayed 10°",
    "A02": "shelf on an L-bracket, flush-mounted, fused single solid",
    "A04": "bolt + nut clamping 2 plates, coaxial holes, grip = Σ thickness",
    "A08": "shaft with two ⌀8 bearing seats, bores ⌀8.05, shoulder spacing 40",
    "D01": "250 mm-wheelbase quad frame plate, motors at (±88.4,±88.4), FC 30.5 pattern",
    "D02": "2207 motor mount plate: 4×⌀3 on 16/19 cross, ⌀8 center bore, 4 mm thick",
    "D04": "2 mm frame bottom plate: 30.5 + 20 mm hole patterns, lightening cutouts",
}

# runnable oracles (golden by construction)
_ORACLES: Dict[str, Callable[[], dict]] = {
    "A01": _asm_oracle(_stool), "A02": _asm_oracle(_shelf_bracket),
    "A04": _asm_oracle(_bolt_stack), "A08": _asm_oracle(_shaft_bearings),
    "D01": _spec_oracle(_quad_frame()), "D02": _spec_oracle(_motor_mount()),
    "D04": _spec_oracle(_bottom_plate()),
    "C05": _spec_oracle(_flange_c05()), "C15": _spec_oracle(_linear_bar_c15()),
    "C16": _spec_oracle(_grid_plate_c16()),
}

# why each not-yet-runnable task is blocked (so the scorecard names the missing capability, not a silent gap)
_BLOCKED: Dict[str, str] = {
    "C04": "hex-prism shape (Phase-3 vocab)",
    "C18": "harness re-exec-with-overridden-params", "C20": "STEP AP214 round-trip harness",
    **{f"M{i:02d}": "mesh verifier (Phase-3 §6.1)" for i in range(1, 16)},
    **{f"B{i:02d}": "Blender bpy verifier (Phase-3/5 §6 [BPY])" for i in range(1, 13)},
    **{f"W{i:02d}": "web/GLB verifier (Phase-3 §6.5 [WEB])" for i in range(1, 11)},
    **{f"G{i:02d}": "game-asset verifier (Phase-3 §6.4)" for i in range(1, 13)},
    **{f"P{i:02d}": "product verifier (mesh cavity / DFM — Phase-3)" for i in range(1, 11)},
    "D03": "airfoil propeller (loft) verifier", "D05": "landing-gear layout", "D06": "angled mount plate",
    "D07": "full 13-part quad assembly + prop-clearance sweep", "D08": "ducted fan (duct+struts+hub)",
    "A03": "revolute hinge pose-sweep task criteria", "A05": "involute gear pair (Phase-4)",
    "A06": "4-bar linkage Grashof", "A07": "prismatic drawer slide", "A09": "enclosure + PCB standoffs",
    "A10": "3R arm chained joints", "A11": "screw-clamp travel", "A12": "swivel caster",
    "A13": "planetary gear set (Phase-4)",
}


def _build_registry() -> List[Task]:
    tasks: List[Task] = []
    for tid, level in _LEVELS.items():
        cat = tid[0]
        oracle = _ORACLES.get(tid)
        # C tasks: wire the by-construction Spec from bench_specs (its own oracle) where present
        if oracle is None and tid in EVAL_BENCH_BY_ID:
            oracle = _spec_oracle(EVAL_BENCH_BY_ID[tid])
        prompt = _PROMPTS.get(tid, f"{tid} — see 02_benchmark.md")
        tasks.append(Task(id=tid, level=level, category=cat, prompt=prompt,
                          oracle=oracle, blocked_on=None if oracle else _BLOCKED.get(tid, "unencoded")))
    return tasks


REGISTRY: List[Task] = _build_registry()
