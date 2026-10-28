"""Adversarial stress suite for the assembly planner — where does generalization break?

Complements eval_asm_adapter.py (near-distribution battery) with off-distribution briefs
across failure axes, scored by the SAME verifier loop so numbers are comparable:

  compositional   families the model knows, combined in unseen ways
  count_scale     part counts / dimensions beyond the training envelope
  underspecified  vague product-speak — must decompose sensibly, not hallucinate
  contradiction   impossible or degenerate asks — graceful structure beats a lying pass
  variance        N independent draws on fixed briefs — skill vs dice (pass@1 spread)

Repair stress is read out of the attempt histories (rescue categories) rather than a
separate lane — every non-@1 pass documents the repair loop earning its keep.

  cad_pipeline/.venv/bin/python -m training.stress_asm --module asm3
  cad_pipeline/.venv/bin/python -m training.stress_asm --module asm2   # the baseline flip
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

OUT_DIR = "/workspace/.hf_home/eval_asm1"

STRESS_BRIEFS: dict[str, list[tuple[str, str]]] = {
    "compositional": [
        ("workbench_shelf", "a workbench: rectangular top on four legs, a lower storage shelf "
         "spanning the legs at mid height, and a vice mounting plate on one end of the top"),
        ("rack_fan", "a two-tier equipment rack with four corner posts, and a cooling fan "
         "mounted on a bracket on the top tier"),
        ("stool_footring", "a bar stool: round seat on four splayed legs with a circular "
         "footring connecting the legs at one-third height"),
        ("table_drawer", "a side table with a rectangular top on four legs and a shallow "
         "drawer box mounted under the top"),
        ("mast_dish", "an antenna mast: base plate, vertical pole, a dish bracket near the top, "
         "and two diagonal support braces from the pole to the base"),
        ("quad_gimbal", "a quadcopter frame: central hub, four arms with motor pads, and a "
         "camera gimbal bracket hanging under the hub"),
    ],
    "count_scale": [
        ("octo_stool", "an 8-legged round stool, legs evenly spaced and splayed"),
        ("rack_3x5", "a three-post rack with five shelves evenly spaced up the posts"),
        ("rover_6x6", "a six-wheeled rover: chassis plate with three wheels per side on stub "
         "axles, each spinning on its own revolute"),
        ("hexacopter", "a hexacopter frame: central hub, six arms, motor pads with bolt circles"),
        ("micro_stool", "a miniature 4-legged stool only 9 mm tall with a 12 mm round seat"),
        ("giant_table", "a large dining table 1800x900 mm top on four 730 mm legs"),
        ("pcb_12so", "a PCB mounted on twelve standoffs arranged around its perimeter on a "
         "base plate"),
    ],
    "underspecified": [
        ("drone_holder", "something to hold my drone on a shelf"),
        ("cable_organizer", "a thing to organize the cables on my desk"),
        ("phone_stand", "a stand for my phone"),
        ("parts_storage", "storage for small workshop parts"),
        ("camera_mount", "a mount for a small camera"),
    ],
    "contradiction": [
        ("floating_shelf", "a floating shelf with no visible supports"),
        ("one_leg_table", "a table with a single central leg"),
        ("solid_hinge", "a box with a lid that is welded shut but also opens on a hinge"),
        ("thin_plate", "a plate 100x100 mm and 0.05 mm thick on four legs"),
    ],
}

VARIANCE_BRIEFS = [
    ("stool", "a 4-legged stool, ~120 mm tall, round seat ⌀140, legs splayed 10°"),
    ("quadcopter", "quadcopter frame: central hub, four arms, motor pads with bolt circles"),
    ("rack", "a two-tier parts rack: four corner posts, two shelves"),
    ("rover", "a four-wheeled rover: chassis plate, four wheels on stub axles at the corners, "
     "each spinning on its own revolute"),
    ("enclosure", "PCB enclosure with standoffs, shelled base and lid"),
]
VARIANCE_RUNS = 5


def _episode(prompt: str, gen, run_assembly, max_attempts: int) -> dict:
    t0 = time.time()
    try:
        out = run_assembly(prompt, gen, max_attempts=max_attempts)
    except Exception as e:  # noqa: BLE001 — a crashed episode is a data point, not a stop
        return {"passed": False, "error": f"{type(e).__name__}: {str(e)[:200]}",
                "seconds": round(time.time() - t0)}
    rep = out.get("best_report") or {}
    npass = sum(1 for r in rep.get("rows", []) if r["within_tol"])
    return {"passed": out["passed"], "attempt": out.get("attempt"),
            "rows": f"{npass}/{len(rep.get('rows', []))}",
            "components": len(rep.get("components")
                              or (out.get("assembly") or {}).get("components", []) or []),
            "categories": [h["category"] for h in out.get("history", [])],
            "seconds": round(time.time() - t0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True, help="served lora name (= PLAN_MODEL)")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--skip-variance", action="store_true")
    ap.add_argument("--categories", default="", help="comma subset; default all")
    a = ap.parse_args()

    os.environ["PLAN_MODEL"] = a.module  # must precede cad_pipeline imports (bound at import)
    from cad_pipeline.asm_loop import VLLMAsmGenerator, run_assembly
    gen = VLLMAsmGenerator()
    assert gen.model == a.module, f"generator model {gen.model} != {a.module}"

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%m%d_%H%M")
    results: dict = {"module": a.module, "when": stamp, "suite": "stress", "cats": {}}

    wanted = [c.strip() for c in a.categories.split(",") if c.strip()] or list(STRESS_BRIEFS)
    for cat in wanted:
        briefs = STRESS_BRIEFS[cat]
        rows = []
        for i, (name, prompt) in enumerate(briefs, 1):
            print(f"[{cat} {i}/{len(briefs)}] {name}: {prompt[:70]}", flush=True)
            r = {"name": name, **_episode(prompt, gen, run_assembly, a.max_attempts)}
            rows.append(r)
            state = (f"PASS@{r['attempt']}" if r.get("passed")
                     else ("ERROR" if r.get("error") else "FAIL"))
            print(f"    {state}  rows {r.get('rows', '-')}  parts={r.get('components', '?')}  "
                  f"{r['seconds']}s", flush=True)
        results["cats"][cat] = rows

    if not a.skip_variance:
        var: dict = {}
        for name, prompt in VARIANCE_BRIEFS:
            outs = []
            for k in range(VARIANCE_RUNS):
                r = _episode(prompt, gen, run_assembly, 1)   # pass@1 only — measure the dice
                outs.append(bool(r.get("passed")))
                print(f"[variance {name} {k + 1}/{VARIANCE_RUNS}] "
                      f"{'PASS' if outs[-1] else 'FAIL'} ({r['seconds']}s)", flush=True)
            var[name] = {"pass1": sum(outs), "n": VARIANCE_RUNS, "draws": outs}
        results["variance"] = var

    out_path = f"{OUT_DIR}/{a.module}_{stamp}_stress.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n===== STRESS SCORECARD =====")
    rescued = attempts_gt1 = 0
    for cat, rows in results["cats"].items():
        npass = sum(1 for r in rows if r.get("passed"))
        print(f"  {cat:15s} {npass}/{len(rows)}")
        for r in rows:
            if r.get("passed") and (r.get("attempt") or 1) > 1:
                attempts_gt1 += 1
                if any("fix" in c or "repair" in c for c in r.get("categories", [])):
                    rescued += 1
    if "variance" in results:
        spread = {k: f"{v['pass1']}/{v['n']}" for k, v in results["variance"].items()}
        print(f"  variance        {spread}")
    print(f"  repair rescues  {rescued} (of {attempts_gt1} multi-attempt passes)")
    print(f"→ {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
