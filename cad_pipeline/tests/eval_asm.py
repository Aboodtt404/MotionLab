"""Assembly-repair eval: pass@attempt baseline for the assembly retry loop (asm_loop).

The part-loop analog of eval_baseline, over natural-language ASSEMBLY briefs: every brief
runs through plan → verify → typed feedback → minimal patch → re-verify, and we aggregate
what the fine-tune must close:
  • pass@1 (planner alone) vs pass@N (does feedback-repair ADD anything live?)
  • per-category failure profile (disconnected / integrity / kinematic / structure / ...)
  • regression rate (patches that broke working parts — the live failure mode we observed)
Every episode also serializes to a schema-valid RepairTranscript JSONL — the assembly-repair
training data comes free with the baseline run.

Briefs span the verifier's row families: mate-only structures (radial legs, stacks),
frame-hierarchy sub-assemblies (PCB-on-standoffs), and revolute-jointed mechanisms
(hinged lid, door, 2R arm) — the pose-sweep/DOF rows only fire on jointed briefs.

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.eval_asm [max_attempts] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from ..asm_loop import VLLMAsmGenerator, asm_transcript, run_assembly

# ------------------------------------------------------------------ the assembly eval set
# 10 briefs, ~evenly split mate-only vs jointed; sized/worded like the studio's real inputs.
EVAL_ASM = [
    # mate-only structural (solve_layout + statics + integrity rows)
    "a 4-legged stool, about 120 mm tall, round seat 140 mm across, legs splayed outward",
    "a rectangular equipment stand: flat top plate 160x100 mm on four corner legs, 90 mm tall",
    "a two-tier electronics rack: two shelves stacked on four corner posts, 120 mm tall",
    "a camera tripod: three legs spread around a central hub with a flat mounting plate on top",
    # frame hierarchy (parented sub-assembly)
    "a PCB mounted on four corner standoffs on a base plate 90x70 mm",
    "a sensor mast: a base plate with a vertical pole and a small sensor head box parented on top",
    # revolute-jointed mechanisms (DOF + pose-sweep rows)
    "a small hinged storage box, 80x60x40 mm, with a lid that opens on a hinge along the back edge",
    "a door on a frame: a 60x100 mm door panel hinged to a post so it can swing open 90 degrees",
    "a laptop-style clamshell: base slab and screen slab joined by a hinge along one edge",
    "a simple 2-link robot arm: base, upper arm and forearm connected by two revolute joints",
]


def evaluate(max_attempts: int = 3, out_path: str = "eval_asm_transcripts.jsonl") -> dict:
    gen = VLLMAsmGenerator()
    gen_meta = {"model": gen.model, "base_url": gen.base_url, "loop": "asm_loop.run_assembly",
                "max_attempts": max_attempts}
    results, cats, regressions = [], Counter(), 0
    pass_at = Counter()
    with open(out_path, "w") as fh:
        for i, prompt in enumerate(EVAL_ASM, 1):
            print(f"[{i}/{len(EVAL_ASM)}] {prompt[:70]}", flush=True)
            out = run_assembly(prompt, gen, max_attempts=max_attempts)
            fh.write(asm_transcript(prompt, out, gen_meta).model_dump_json() + "\n")
            fh.flush()
            for h in out["history"]:
                if h["regressed"]:
                    regressions += 1
                if h["category"] not in ("ok",):
                    cats[h["category"]] += 1
            if out["passed"]:
                for k in range(out["attempt"], max_attempts + 1):
                    pass_at[k] += 1
            npass_best = sum(1 for r in (out.get("best_report") or {}).get("rows", [])
                             if r["within_tol"])
            nrows = len((out.get("best_report") or {}).get("rows", []))
            results.append({"prompt": prompt, "passed": out["passed"],
                            "attempt": out.get("attempt"),
                            "history": out["history"],
                            "best_rows": f"{npass_best}/{nrows}"})
            state = f"PASS@{out['attempt']}" if out["passed"] else f"FAIL ({out.get('category')})"
            print(f"    {state}  rows {npass_best}/{nrows}  "
                  f"{[h['category'] for h in out['history']]}", flush=True)
    n = len(EVAL_ASM)
    return {
        "n": n, "max_attempts": max_attempts,
        "pass_at": {f"pass@{k}": f"{pass_at[k]}/{n}" for k in range(1, max_attempts + 1)},
        "repair_gain": pass_at[max_attempts] - pass_at[1],   # what the loop adds over the planner
        "regressions": regressions,
        "failure_categories": dict(cats.most_common()),
        "transcripts": out_path,
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("max_attempts", nargs="?", type=int, default=3)
    ap.add_argument("--out", default="eval_asm_transcripts.jsonl")
    a = ap.parse_args()
    print(f"Assembly-repair baseline — {len(EVAL_ASM)} briefs, max_attempts={a.max_attempts}\n")
    summary = evaluate(a.max_attempts, a.out)
    results = summary.pop("results")
    print("\n" + json.dumps(summary, indent=2))
    with open("eval_asm_summary.json", "w") as fh:
        json.dump({**summary, "results": results}, fh, indent=2)
    print("\nsummary → eval_asm_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
