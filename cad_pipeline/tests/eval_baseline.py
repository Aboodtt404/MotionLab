"""Baseline eval: off-the-shelf model vs the Track A loop (track-a §"model bake-off").

Runs every golden spec through the live generate→execute→verify→retry loop and
aggregates the numbers the design doc wants before committing to a model:
  • pass-rate (specs fully verified within N attempts)
  • per-feature pass-rate (envelope / hole-⌀ / hole-position / fillet-r / fillet-binding / ...)
  • error-category profile (exec-fix vs dimensional vs selector-binding) — WHERE it fails
  • attempts-to-first-valid-geometry — how fast it gets past API errors

This converts anecdotes ("the bracket failed on position") into an evidence-backed
baseline, and localizes the residual gap the fine-tune must close.

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.eval_baseline [max_attempts]
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from ..loop import VLLMGenerator, run
from ..spec import Spec
from .selftest import GOLDEN

# --------------------------------------------------------------------------- L2/L3 eval set
# Harder than GOLDEN (which the verifier was built around and now passes 100%): combined
# features, multi-hole positioning, and pattern expansion (bolt-circle / linear / grid) —
# the spatial-reasoning load the simple goldens don't exercise. Verifiable by construction
# (only feature types the verifier checks); a pre-flight builds+verifies each to confirm the
# verifier handles it before we judge the model on it.
EVAL_HARD = [
    Spec(object="filleted bracket with two bolt holes and a central pocket", shape="box",
         envelope={"length": 120, "width": 70, "height": 12},
         features=[{"type": "fillet", "radius": 6, "edges": "all_vertical"},
                   {"type": "through_hole", "diameter": 8, "at": [-45, 0]},
                   {"type": "through_hole", "diameter": 8, "at": [45, 0]},
                   {"type": "pocket", "length": 50, "width": 30, "depth": 6}], tolerance=0.1),
    Spec(object="8-bolt mounting flange", shape="cylinder", envelope={"diameter": 90, "height": 12},
         features=[{"type": "through_hole", "diameter": 20},
                   {"type": "hole_pattern", "pattern": "bolt_circle", "count": 8, "pitch_diameter": 70, "diameter": 6}], tolerance=0.1),
    Spec(object="grid-perforated plate (3x2)", shape="box", envelope={"length": 100, "width": 60, "height": 5},
         features=[{"type": "hole_pattern", "pattern": "grid", "nx": 3, "ny": 2, "spacing": 25, "diameter": 5}], tolerance=0.1),
    Spec(object="filleted vent panel with 7-hole row", shape="box", envelope={"length": 140, "width": 40, "height": 6},
         features=[{"type": "fillet", "radius": 4, "edges": "all_vertical"},
                   {"type": "hole_pattern", "pattern": "linear_x", "count": 7, "spacing": 18, "diameter": 6}], tolerance=0.1),
    Spec(object="recessed mounting plate (4 corner holes + pocket)", shape="box", envelope={"length": 110, "width": 80, "height": 10},
         features=[{"type": "through_hole", "diameter": 6, "at": [-48, -33]}, {"type": "through_hole", "diameter": 6, "at": [48, -33]},
                   {"type": "through_hole", "diameter": 6, "at": [-48, 33]}, {"type": "through_hole", "diameter": 6, "at": [48, 33]},
                   {"type": "pocket", "length": 60, "width": 40, "depth": 5}], tolerance=0.1),
    Spec(object="asymmetric link plate (3 holes, mixed ⌀)", shape="box", envelope={"length": 90, "width": 50, "height": 8},
         features=[{"type": "fillet", "radius": 5, "edges": "all_vertical"},
                   {"type": "through_hole", "diameter": 10, "at": [-30, 0]},
                   {"type": "through_hole", "diameter": 6, "at": [20, 12]},
                   {"type": "through_hole", "diameter": 6, "at": [20, -12]}], tolerance=0.1),
    Spec(object="12-bolt ring flange", shape="cylinder", envelope={"diameter": 120, "height": 10},
         features=[{"type": "through_hole", "diameter": 40},
                   {"type": "hole_pattern", "pattern": "bolt_circle", "count": 12, "pitch_diameter": 95, "diameter": 7}], tolerance=0.1),
    Spec(object="chamfered terminal block with two holes", shape="box", envelope={"length": 70, "width": 45, "height": 18},
         features=[{"type": "chamfer", "distance": 4, "edges": "all_vertical"},
                   {"type": "through_hole", "diameter": 8, "at": [-20, 0]},
                   {"type": "through_hole", "diameter": 8, "at": [20, 0]}], tolerance=0.1),
    Spec(object="cable comb (9-hole row)", shape="box", envelope={"length": 160, "width": 25, "height": 5},
         features=[{"type": "hole_pattern", "pattern": "linear_x", "count": 9, "spacing": 16, "diameter": 5}], tolerance=0.1),
    Spec(object="instrument faceplate (fillet + 2x2 holes + pocket)", shape="box", envelope={"length": 130, "width": 90, "height": 8},
         features=[{"type": "fillet", "radius": 6, "edges": "all_vertical"},
                   {"type": "hole_pattern", "pattern": "grid", "nx": 2, "ny": 2, "spacing": 40, "diameter": 6},
                   {"type": "pocket", "length": 50, "width": 30, "depth": 4}], tolerance=0.1),
]

from .bench_specs import EVAL_BENCH  # the benchmark's parametric-CAD slice (fable_run §C)

SETS = {"golden": GOLDEN, "hard": EVAL_HARD, "bench": EVAL_BENCH}


def _first_valid_attempt(history: list[dict]) -> int | None:
    for h in history:
        if h["status"] == "ok":
            return h["attempt"]
    return None


def evaluate(specs: list, max_attempts: int = 3, transcripts_out: str | None = None,
             model: str = "qwen3.6-27b") -> dict:
    """`transcripts_out`: append every episode as a schema-valid RepairTranscript JSONL —
    eval runs double as repair-pair harvest (03_training_recipe §3c: repair pairs at ~15% of
    the SFT mixture teach 'minimum-change correction from typed feedback', the highest-value
    skill). Costs nothing: the loop already records attempt_log.
    `model`: the served model/adapter name to evaluate (e.g. 'sft', 'dpo' as vLLM --lora-modules)."""
    gen = VLLMGenerator(model=model)
    gen_meta = {"model": gen.model, "base_url": gen.base_url, "rag": gen.rag,
                "loop": "loop.run", "max_attempts": max_attempts}
    tfh = open(transcripts_out, "a") if transcripts_out else None
    results = []
    feature_pass = Counter()   # feature name → # specs where its BEST build was within tolerance
    feature_seen = Counter()   # feature name → # specs where it was checked
    cat_profile = Counter()    # failure category → occurrences across best-build reports
    exec_attempts = 0

    for spec in specs:
        out = run(spec, gen, max_attempts=max_attempts)
        if tfh is not None and out.get("attempt_log"):
            from ..corpus import transcript_from_run
            tfh.write(transcript_from_run(spec, out, gen_meta).model_dump_json() + "\n")
            tfh.flush()
        # aggregate the BEST valid build per spec, not the final attempt — else a spec that
        # reached valid-but-wrong then regressed to an exec error contributes no feature data,
        # hiding real failures (e.g. the bracket's wrong hole position).
        rep = out.get("best_report") or out.get("report")
        fv = _first_valid_attempt(out["history"])
        exec_attempts += sum(1 for h in out["history"] if h["status"] in ("error", "timeout"))
        if rep:
            for r in rep["rows"]:
                feature_seen[r["name"]] += 1
                if r["within_tol"]:
                    feature_pass[r["name"]] += 1
                else:
                    cat_profile[r["category"]] += 1
        results.append({
            "object": spec.object, "shape": spec.shape,
            "passed": out["passed"],
            "attempts_used": out.get("attempt", out.get("attempts")),
            "first_valid_attempt": fv,
            "ever_valid": fv is not None,
            "trace": [f"{h['attempt']}:{h['status']}/{h['category']}"
                      + ("↻" if h.get("repeated_error") else "") + ("↓" if h.get("regressed") else "")
                      for h in out["history"]],
            "final_fail_rows": [r["name"] for r in (rep["rows"] if rep else []) if not r["within_tol"]],
        })

    if tfh is not None:
        tfh.close()
    n = len(specs)
    # capability_score (02_benchmark §scoring): 100·Σ(weight·passed)/Σ(weight), weights
    # L1=1…L4=4, at pass@1 (passed on the first attempt) and pass@N (this run's budget).
    # Computed over the SLICE actually run — comparable run-to-run on the same set; the
    # /263 full-benchmark score and capability bands need all 100 tasks (8 categories).
    from .bench_specs import BENCH_LEVELS
    weights = [BENCH_LEVELS.get(s.object.split()[0], 2) for s in specs]
    wtot = sum(weights)
    w_p1 = sum(w for w, r in zip(weights, results)
               if r["passed"] and r["attempts_used"] == 1)
    w_pn = sum(w for w, r in zip(weights, results) if r["passed"])
    return {
        "max_attempts": max_attempts,
        "n_specs": n,
        "capability_score": {f"pass@1": round(100 * w_p1 / wtot, 1),
                             f"pass@{max_attempts}": round(100 * w_pn / wtot, 1),
                             "weight_total": wtot},
        "pass_rate": round(sum(r["passed"] for r in results) / n, 3),
        "ever_valid_rate": round(sum(r["ever_valid"] for r in results) / n, 3),
        "total_exec_errors": exec_attempts,
        "feature_pass_rate": {k: f"{feature_pass[k]}/{feature_seen[k]}" for k in feature_seen},
        "failure_category_profile": dict(cat_profile),
        "results": results,
    }


def preflight(specs: list) -> None:
    """Verifier-first guard: build each spec with the golden builder and verify it — confirms
    the verifier correctly handles every spec BEFORE we judge the model on it. Aborts on a gap."""
    from ..builder import build
    from ..verifier import verify
    bad = []
    for s in specs:
        try:
            rep = verify(build(s), s)
            if not rep.passed:
                bad.append((s.object, [r.name for r in rep.rows if not r.within_tol]))
        except Exception as e:  # noqa: BLE001 — surface any build/verify gap
            bad.append((s.object, [f"EXC {type(e).__name__}: {e}"]))
    if bad:
        print("PRE-FLIGHT FAILED — verifier cannot cleanly check these specs (fix before eval):")
        for obj, rows in bad:
            print(f"  ✗ {obj}: {rows}")
        raise SystemExit(1)
    print(f"pre-flight ok: all {len(specs)} specs build + verify to spec (verifier trustworthy on them)\n")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    set_name = next((a for a in args if a in SETS), "golden")
    max_attempts = next((int(a) for a in args if a.isdigit()), 3)
    tout = next((a.split("=", 1)[1] for a in args if a.startswith("--transcripts=")), None)
    model = next((a.split("=", 1)[1] for a in args if a.startswith("--model=")), "qwen3.6-27b")
    specs = SETS[set_name]
    print(f"Eval set='{set_name}' — {len(specs)} specs, max_attempts={max_attempts}, model={model} (live)\n")
    preflight(specs)
    summary = evaluate(specs, max_attempts, transcripts_out=tout, model=model)

    print("=" * 66)
    for r in summary["results"]:
        flag = "PASS" if r["passed"] else ("valid-but-wrong" if r["ever_valid"] else "never-valid")
        print(f"■ {r['object']:<48} [{r['shape']:<8}] {flag}")
        print(f"    {' → '.join(r['trace'])}")
        if r["final_fail_rows"]:
            print(f"    unresolved: {', '.join(r['final_fail_rows'])}")
    print("=" * 66)
    print(f"PASS RATE          {summary['pass_rate']*100:.0f}%  ({sum(x['passed'] for x in summary['results'])}/{summary['n_specs']} fully verified)")
    print(f"EVER-VALID RATE    {summary['ever_valid_rate']*100:.0f}%  (produced executable, valid geometry)")
    print(f"TOTAL EXEC ERRORS  {summary['total_exec_errors']}")
    print(f"FEATURE PASS-RATE  {summary['feature_pass_rate']}")
    print(f"FAILURE PROFILE    {summary['failure_category_profile']}")
    print("\nJSON:")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
