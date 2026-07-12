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

import os
import shutil
import tempfile

import trimesh

from ...assembly import Assembly, Component, Mate, repair_connectivity, solve_layout, verify_assembly
from ...builder import build
from ...glb_verify import verify_game, verify_web
from ...mesh_verify import mesh_report
from ...partlib_solids import involute_gear, tooth_count
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


def _mesh_oracle(mesh_factory: Callable[[], "trimesh.Trimesh"], **report_kw) -> Callable[[], dict]:
    """M-category (mesh modeling): the artifact IS a mesh — build it with trimesh.creation and gate it
    through the §6.1 mesh verifier."""
    def run() -> dict:
        return mesh_report(mesh_factory(), **report_kw).to_dict()
    return run


# M-category mesh artifacts (mesh primitives are watertight; OCCT UV-spheres are not — pole degeneracy)
def _m01_sphere() -> "trimesh.Trimesh":       # sphere r=25, ≤2000 tris, vol ∈ [62000,65500]
    return trimesh.creation.icosphere(subdivisions=3, radius=25)


def _m02_torus() -> "trimesh.Trimesh":        # torus R=30 r=8, ≤5000 tris, vol ≈ 37899 ±5%, genus-1
    return trimesh.creation.torus(major_radius=30, minor_radius=8)


# W/G-category GLB artifacts (meters, glTF Y-up). The oracle writes a temp GLB and gates it.
def _glb_oracle(mesh_fn, verify_fn) -> Callable[[], dict]:
    def run() -> dict:
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "a.glb")
            mesh_fn().export(p)
            return verify_fn(p).to_dict()
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return run


def _w01_asset() -> "trimesh.Trimesh":        # ≤10k-tri GLB ≤2 MB
    return trimesh.creation.icosphere(subdivisions=2, radius=0.1)


def _w02_figure() -> "trimesh.Trimesh":       # human-scale 1.80 m Y-up, min-Y = 0
    b = trimesh.creation.box((0.4, 1.8, 0.3)); b.apply_translation([0, 0.9, 0]); return b


def _g01_crate() -> "trimesh.Trimesh":        # crate ≤500 tris, pivot base center (min-Y=0)
    b = trimesh.creation.box((0.5, 0.5, 0.5)); b.apply_translation([0, 0.25, 0]); return b


import json
import subprocess

_BPY_GEN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                        "engine", "tools", "bpy_generate.py"))


def _bpy_oracle(kind: str, params: dict, checks) -> Callable[[], dict]:
    """B-category procedural tasks: run the Blender bpy generator → GLB → trimesh [BPY]-equivalent
    checks. glTF is Y-up, so a Blender Z-up 'height' reads as the exported Y extent."""
    def run() -> dict:
        import shutil as _sh
        if _sh.which("blender") is None:
            return {"passed": False, "valid": False, "solids": 0, "rows": [], "failure_categories": ["validity"]}
        d = tempfile.mkdtemp()
        try:
            glb = os.path.join(d, "o.glb")
            subprocess.run(["blender", "--background", "--python", _BPY_GEN, "--",
                            kind, json.dumps(params), glb], capture_output=True, text=True, timeout=180)
            m = trimesh.load(glb, force="mesh")
            rows = checks(m)
            ok = all(r["within_tol"] for r in rows)
            return {"passed": ok, "valid": True, "solids": 1, "rows": rows,
                    "failure_categories": [] if ok else sorted({r["category"] for r in rows if not r["within_tol"]})}
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return run


def _row(name, exp, meas, ok, cat="dimensional"):
    return {"name": name, "expected": exp, "measured": meas, "within_tol": bool(ok),
            "category": "ok" if ok else cat}


def _b01_checks(m):   # 5-step staircase: height (glTF Y) 0.75, depth (glTF Z) 1.5
    e = m.extents
    return [_row("stair · height", 0.75, round(float(e[1]), 3), abs(e[1] - 0.75) < 0.02),
            _row("stair · depth", 1.5, round(float(e[2]), 3), abs(e[2] - 1.5) < 0.02)]


def _b02_checks(m):   # 10 columns spaced 2.0 → x-extent 18.3
    e = m.extents
    return [_row("array · x-extent", 18.3, round(float(e[0]), 2), abs(e[0] - 18.3) < 0.05)]


def _b05_checks(m):   # boolean window: volume = wall(2.4) − window(0.24) = 2.16
    return [_row("window · volume (wall−window)", 2.16, round(float(m.volume), 3), abs(m.volume - 2.16) < 0.05, "integrity")]


def _b06_checks(m):   # 200 seeded scatter instances → 200×12 tris
    n = len(m.faces)
    return [_row("scatter · instance tris (200×12)", 2400, n, abs(n - 2400) <= 24, "missing_feature")]


def _g03_uv_oracle() -> Callable[[], dict]:
    """G03: single clean UV set (§6.4) — xatlas unwrap → UVs in [0,1], one set, covered."""
    def run() -> dict:
        from cad_pipeline.uv import uv_report
        return uv_report(trimesh.creation.box((0.5, 0.5, 0.5))).to_dict()
    return run


def _w03_draco_oracle() -> Callable[[], dict]:
    """W03: Draco-compress a mesh (§5/§6.5) — gltf-transform optimize → size ≤ 40% of source."""
    def run() -> dict:
        from cad_pipeline.glb_verify import optimize_glb
        d = tempfile.mkdtemp()
        try:
            src, opt = os.path.join(d, "s.glb"), os.path.join(d, "o.glb")
            trimesh.creation.icosphere(subdivisions=5).export(src)
            res = optimize_glb(src, opt, draco=True)
            if res is None:
                return {"passed": False, "valid": False, "solids": 0, "rows": [], "failure_categories": ["validity"]}
            ok = res["ratio"] <= 0.40
            return {"passed": ok, "valid": True, "solids": 1,
                    "rows": [{"name": "web · draco size ≤40% source", "expected": "≤0.40",
                              "measured": res["ratio"], "within_tol": ok, "category": "ok" if ok else "dfm"}],
                    "failure_categories": [] if ok else ["dfm"]}
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return run


def _g09_trim_oracle() -> Callable[[], dict]:
    """G09: UV islands in 4 declared V-bands (§4) — cad_pipeline.art.verify_trim_sheet."""
    def run() -> dict:
        from cad_pipeline.art import verify_trim_sheet
        return verify_trim_sheet(trimesh.creation.box((1, 1, 0.5)), n_bands=4).to_dict()
    return run


def _g07_lod_oracle() -> Callable[[], dict]:
    """G07: LOD chain 6000/1500/400 tris + §4.2 silhouette-IoU acceptance (cad_pipeline.lod)."""
    def run() -> dict:
        from cad_pipeline.lod import generate_lods, verify_lod_chain
        src = trimesh.creation.icosphere(subdivisions=5)
        budgets = [6000, 1500, 400]
        rep = verify_lod_chain(src, generate_lods(src, budgets), budgets)
        return rep.to_dict()
    return run


def _gear_oracle(module: float, teeth: int) -> Callable[[], dict]:
    """P05/A05 gear tasks: involute gear from the library, checked on tip ⌀ = m(z+2) and the polar
    tooth count (FFT) = z (fable_run §8.5 / P05)."""
    def run() -> dict:
        g, _ = involute_gear(module, teeth)
        s = g.val(); bb = s.BoundingBox()
        tip = max(bb.xlen, bb.ylen)
        tc = tooth_count(g)
        tip_ok = abs(tip - module * (teeth + 2)) <= 0.2
        cnt_ok = tc == teeth
        rows = [{"name": "gear · tip ⌀", "expected": module * (teeth + 2), "measured": round(tip, 3),
                 "within_tol": tip_ok, "category": "ok" if tip_ok else "dimensional"},
                {"name": "gear · tooth count (polar FFT)", "expected": teeth, "measured": tc,
                 "within_tol": cnt_ok, "category": "ok" if cnt_ok else "missing_feature"}]
        return {"passed": bool(s.isValid() and tip_ok and cnt_ok), "valid": bool(s.isValid()),
                "solids": 1, "volume": None, "rows": rows,
                "failure_categories": [] if (tip_ok and cnt_ok) else ["dimensional"]}
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
def _hex_standoff_c04() -> Spec:                            # C04: hex standoff ⌀14 (across corners) ×25, ⌀3.2 bore
    return Spec(object="C04 hex standoff", shape="prism", sides=6,
                envelope={"diameter": 14, "height": 25},
                features=[{"type": "through_hole", "diameter": 3.2}], tolerance=0.1)


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
    "M01": "sphere r=25 mm, ≤2000 tris, watertight, vol ∈ [62000,65500]",
    "M02": "torus R=30 r=8, ≤5000 tris, watertight, vol ≈ 37899 ±5% (genus-1)",
    "M06": "any closed mesh with all normals outward (winding consistent, signed vol > 0)",
    "M07": "closed mesh, clean topology: every edge shared by exactly 2 faces",
    "W01": "export a ≤10k-tri asset as GLB ≤ 2 MB (gltf-validator clean, in-scale)",
    "W02": "human-scale figure, correct web scale: Y-up height 1.80 ±0.02 m, min-Y = 0",
    "G01": "crate prop ≤500 tris, ≤2 materials, pivot at base center",
    "P05": "spur gear m=2, z=24 → tip ⌀ 52±0.2, 24 polar maxima (library involute gear)",
    "B01": "script a 5-step staircase: rise 0.15, tread 0.30, width 1.0 (bpy)",
    "B02": "array modifier: 10 columns ⌀0.3×3 spaced 2.0 in X → x-extent 18.3 (bpy)",
    "B05": "boolean-cut a 1×1.2 window through a 4×3×0.2 wall (bpy)",
    "B06": "geometry-nodes scatter: exactly 200 seeded instances on a 10×10 plane (bpy)",
    "G07": "LOD chain 6000/1500/400 tris, silhouette IoU ≥0.97/0.92 (§4.2)",
    "G03": "single clean UV set: 0 overlaps, all inside [0,1] (§6.4)",
    "W03": "Draco-compress a 50k-tri mesh → ≤40% of source (§5)",
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
    "C04": _spec_oracle(_hex_standoff_c04()),               # unblocked by the Phase-1 prism shape
    "C05": _spec_oracle(_flange_c05()), "C15": _spec_oracle(_linear_bar_c15()),
    "C16": _spec_oracle(_grid_plate_c16()),
    "M01": _mesh_oracle(_m01_sphere, max_triangles=2000),
    "M02": _mesh_oracle(_m02_torus, max_triangles=5000, expected_euler=0),
    "M06": _mesh_oracle(_m01_sphere),                 # closed mesh, all normals outward
    "M07": _mesh_oracle(_m01_sphere),                 # clean topology: every edge shared by 2 faces
    "W01": _glb_oracle(_w01_asset, lambda p: verify_web(p, max_tris=10_000, max_file_mb=2.0)),
    "W02": _glb_oracle(_w02_figure, lambda p: verify_web(p, height_range=(1.78, 1.82))),
    "G01": _glb_oracle(_g01_crate, lambda p: verify_game(p, tri_budget=500)),
    "P05": _gear_oracle(2, 24),                       # spur gear m=2 z=24 (library involute gear)
    "B01": _bpy_oracle("staircase", {"steps": 5, "rise": 0.15, "tread": 0.30, "width": 1.0}, _b01_checks),
    "B02": _bpy_oracle("array", {"count": 10, "spacing": 2.0}, _b02_checks),
    "B05": _bpy_oracle("window", {"wall": [4, 0.2, 3], "window": [1, 1.2]}, _b05_checks),
    "B06": _bpy_oracle("scatter", {"count": 200, "seed": 42}, _b06_checks),
    "G07": _g07_lod_oracle(),                          # LOD chain 6000/1500/400 + silhouette IoU (§4.2)
    "G03": _g03_uv_oracle(),                            # single clean UV set (xatlas §6.4)
    "W03": _w03_draco_oracle(),                         # Draco compression ≤40% (gltf-transform §5)
    "G09": _g09_trim_oracle(),                          # trim-sheet UV in 4 V-bands (§4)
}

# extra task-specific assertions on the golden report (Fable's per-task numeric criteria)
_CRITERIA: Dict[str, Callable[[dict], bool]] = {
    "M01": lambda r: 62000 <= (r.get("volume") or 0) <= 65500,
    "M02": lambda r: abs((r.get("volume") or 0) - 37899) <= 0.05 * 37899,
}

# why each not-yet-runnable task is blocked (so the scorecard names the missing capability, not a silent gap)
_BLOCKED: Dict[str, str] = {
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
        tasks.append(Task(id=tid, level=level, category=cat, prompt=prompt, oracle=oracle,
                          blocked_on=None if oracle else _BLOCKED.get(tid, "unencoded"),
                          criteria=_CRITERIA.get(tid)))
    return tasks


REGISTRY: List[Task] = _build_registry()
