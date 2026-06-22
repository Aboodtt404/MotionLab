"""Class-1 robustness stress suite — feature-interaction, boolean/topology, parameter
extremes, and numerical precision (the cases that break naive generators).

Verifier-FIRST: this does NOT test the model. It tests whether our deterministic
infrastructure (emit→sandbox→gates→verifier) gives the RIGHT verdict on hard geometry,
because a generator can only be trusted if the verifier underneath it is. Each case has an
expected verdict:

  valid    — should build & verify clean (a feasible hard case).
  caught   — should be REJECTED (exec error / gate fail / feature mismatch) — never a
             silent pass, never a harness crash. Graceful failure is success here.
  measured — should build clean AND the verifier must MEASURE it correctly (envelope Δ≈0)
             despite the stress (extreme scale / thin wall) — tests precision, not rejection.

The valuable output is the SURPRISES: a silent pass of bad geometry (dangerous), a harness
crash (bug), or a mis-measurement at scale (precision bug).

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.stress
"""
from __future__ import annotations

import sys

from ..builder import emit_code
from ..executor import run_code
from ..spec import Spec

# (label, category, spec, expected_verdict)
STRESS = [
    # --- feature interaction & fillet feasibility ---
    ("fillet feasible (r24 on 50-wide box)", "fillet", Spec(object="x", shape="box",
        envelope={"length": 80, "width": 50, "height": 30},
        features=[{"type": "fillet", "radius": 24, "edges": "all_vertical"}], tolerance=0.1), "valid"),
    ("fillet INFEASIBLE (r30 > half-width 25)", "fillet", Spec(object="x", shape="box",
        envelope={"length": 80, "width": 50, "height": 30},
        features=[{"type": "fillet", "radius": 30, "edges": "all_vertical"}], tolerance=0.1), "caught"),
    ("fillet AND chamfer on the SAME vertical edges (conflict)", "interaction", Spec(object="x", shape="box",
        envelope={"length": 80, "width": 50, "height": 30},
        features=[{"type": "fillet", "radius": 6, "edges": "all_vertical"},
                  {"type": "chamfer", "distance": 6, "edges": "all_vertical"}], tolerance=0.1), "caught"),
    ("fillet radius ~ hole proximity (r10 fillet, ⌀12 hole near corner)", "interaction", Spec(object="x", shape="box",
        envelope={"length": 60, "width": 40, "height": 20},
        features=[{"type": "fillet", "radius": 10, "edges": "all_vertical"},
                  {"type": "through_hole", "diameter": 12, "at": [-22, 0]}], tolerance=0.1), "valid"),

    # --- boolean / topology stress ---
    ("bolt-circle so dense the holes OVERLAP (24× ⌀6 on ⌀30 PCD)", "boolean", Spec(object="x", shape="cylinder",
        envelope={"diameter": 50, "height": 10},
        features=[{"type": "hole_pattern", "pattern": "bolt_circle", "count": 24, "pitch_diameter": 30, "diameter": 6}], tolerance=0.1), "caught"),
    ("two NEARLY-COINCIDENT holes (⌀6 at 0,0 and 0.4,0)", "boolean", Spec(object="x", shape="box",
        envelope={"length": 60, "width": 40, "height": 15},
        features=[{"type": "through_hole", "diameter": 6, "at": [0, 0]},
                  {"type": "through_hole", "diameter": 6, "at": [0.4, 0]}], tolerance=0.1), "caught"),
    ("pocket DEEPER than the part (depth 15 > height 10 → cuts through)", "boolean", Spec(object="x", shape="box",
        envelope={"length": 80, "width": 60, "height": 10},
        features=[{"type": "pocket", "length": 40, "width": 24, "depth": 15}], tolerance=0.1), "caught"),

    # --- numerical precision / thin walls / scale ---
    ("near-zero wall (⌀49.9 hole in a 50-wide box → 0.05mm wall, min_wall 0.8)", "precision", Spec(object="x", shape="box",
        envelope={"length": 80, "width": 50, "height": 20},
        features=[{"type": "through_hole", "diameter": 49.9}], tolerance=0.1, min_wall=0.8), "caught"),
    ("concentric tiny gap (⌀39.8 bore in ⌀40 cylinder → 0.1mm wall)", "precision", Spec(object="x", shape="cylinder",
        envelope={"diameter": 40, "height": 25},
        features=[{"type": "through_hole", "diameter": 39.8}], tolerance=0.1), "valid"),
    ("EXTREME small scale (0.5×0.3×0.2 mm box, ⌀0.1 hole)", "scale", Spec(object="x", shape="box",
        envelope={"length": 0.5, "width": 0.3, "height": 0.2},
        features=[{"type": "through_hole", "diameter": 0.1}], tolerance=0.01), "measured"),
    ("EXTREME large scale (5000×3000×2000 mm box, ⌀500 hole)", "scale", Spec(object="x", shape="box",
        envelope={"length": 5000, "width": 3000, "height": 2000},
        features=[{"type": "through_hole", "diameter": 500}], tolerance=0.1), "measured"),

    # --- DFM gates (manufacturing-constraint awareness) ---
    ("deep narrow pocket — tool reach (depth30/width10=3.0 > max 2.0)", "dfm", Spec(object="x", shape="box",
        envelope={"length": 70, "width": 50, "height": 35},
        features=[{"type": "pocket", "length": 40, "width": 10, "depth": 30}], tolerance=0.1, max_pocket_aspect=2.0), "caught"),
    ("shallow pocket — tool reach OK (depth5/width24=0.2 < max 2.0)", "dfm", Spec(object="x", shape="box",
        envelope={"length": 100, "width": 60, "height": 10},
        features=[{"type": "pocket", "length": 40, "width": 24, "depth": 5}], tolerance=0.1, max_pocket_aspect=2.0), "valid"),
    ("injection-molded box, NO draft on vertical walls", "dfm", Spec(object="x", shape="box",
        envelope={"length": 60, "width": 40, "height": 20}, features=[], tolerance=0.1, draft_required=True), "caught"),
    ("milled pocket with sharp internal corners (tool r2 required)", "dfm", Spec(object="x", shape="box",
        envelope={"length": 80, "width": 60, "height": 15},
        features=[{"type": "pocket", "length": 40, "width": 24, "depth": 6}], tolerance=0.1, min_internal_radius=2.0), "caught"),
    ("injection-molded part with a SIDE hole (undercut)", "dfm", Spec(object="x", shape="box",
        envelope={"length": 60, "width": 40, "height": 30},
        features=[{"type": "through_hole", "diameter": 8, "axis": "x", "at": [0, 0]}], tolerance=0.1, draft_required=True), "caught"),

    # --- multi-axis / Swiss-cheese ---
    ("cross-drilled block (z⌀10 + x⌀8 intersecting)", "multiaxis", Spec(object="x", shape="box",
        envelope={"length": 80, "width": 50, "height": 40},
        features=[{"type": "through_hole", "diameter": 10, "axis": "z", "at": [0, 0]},
                  {"type": "through_hole", "diameter": 8, "axis": "x", "at": [0, 0]}], tolerance=0.1), "valid"),
    ("Swiss-cheese — many intersecting holes on 3 axes", "multiaxis", Spec(object="x", shape="box",
        envelope={"length": 60, "width": 60, "height": 60},
        features=[{"type": "through_hole", "diameter": 8, "axis": "x", "at": [0, 0]},
                  {"type": "through_hole", "diameter": 8, "axis": "y", "at": [0, 0]},
                  {"type": "through_hole", "diameter": 8, "axis": "z", "at": [0, 0]},
                  {"type": "through_hole", "diameter": 6, "axis": "z", "at": [20, 20]},
                  {"type": "through_hole", "diameter": 6, "axis": "z", "at": [-20, -20]}], tolerance=0.1), "valid"),
]


def _verdict(res: dict, spec: Spec):
    """Map a run_code result → (verdict, detail)."""
    st = res["status"]
    if st in ("error", "timeout"):
        return "caught", "exec:" + str(res.get("error", st)).strip().splitlines()[-1][:70]
    if st == "gate_fail":
        return "caught", "gate:" + ",".join(res.get("failed", [])) + (" " + res.get("error", "")[:50] if res.get("error") else "")
    rep = res["report"]
    if not rep["passed"]:
        cats = rep["failure_categories"]
        return "caught", "verify:" + ",".join(cats)
    # passed — but for precision/scale, did it MEASURE the envelope correctly?
    env_rows = [r for r in rep["rows"] if r["name"].startswith("envelope")]
    bad = [r for r in env_rows if r["delta"] is not None and abs(r["delta"]) > spec.tolerance + 1e-9]
    if bad:
        return "mismeasured", "env Δ " + ", ".join(f"{r['name'].split('·')[-1].strip()}:{r['delta']}" for r in bad)
    return "valid", "clean"


def main() -> int:
    print("=" * 72 + "\nClass-1 robustness stress suite (deterministic pipeline; no model)\n" + "=" * 72)
    surprises = 0
    by_cat: dict = {}
    for label, cat, spec, expect in STRESS:
        try:
            res = run_code(emit_code(spec), spec, timeout=90)
            verdict, detail = _verdict(res, spec)
        except Exception as e:  # a crash in OUR harness is the worst outcome
            verdict, detail = "HARNESS-CRASH", f"{type(e).__name__}: {e}"[:80]
        # "measured" expectation is satisfied by a clean, correctly-measured build
        ok = (verdict == expect) or (expect == "measured" and verdict == "valid")
        by_cat.setdefault(cat, []).append(ok)
        if not ok:
            surprises += 1
        mark = "✓" if ok else "⚠ SURPRISE"
        print(f"\n[{cat}] {label}")
        print(f"   expect {expect:<9} got {verdict:<13} {mark}   ({detail})")

    print("\n" + "=" * 72)
    for cat, oks in sorted(by_cat.items()):
        print(f"  {cat:<12} {sum(oks)}/{len(oks)} as-expected")
    print(f"\n{len(STRESS) - surprises}/{len(STRESS)} matched expectation · {surprises} SURPRISE(S)"
          + ("  ← investigate" if surprises else "  ✓"))
    return 0 if surprises == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
