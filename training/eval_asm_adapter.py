"""Turnkey assembly-adapter eval: hot-load a LoRA checkpoint into the running vLLM serve
(no restart — needs VLLM_ALLOW_RUNTIME_LORA_UPDATING=1 on the serve) and run the banked
baseline battery against it, printing the before/after table.

Sets (pick with --sets, comma-separated):
  live  — the 4 user-run briefs (stool / rover / PCB enclosure / hinged door), ~30-60 min.
          Baselines: stool = phase23 pass@1 356s; the other three FAILED on base/phase23.
  eval  — cad_pipeline.tests.eval_asm 10-brief set. Baseline pass@1 = 1/10 (base).
  bank  — training.bank_asm_repair 10 hard vehicle briefs (transcripts append to the bank,
          so the run also grows the repair corpus). Baseline = 0/20 (base, 2 rounds).

Run (epoch-1 smoke):
  cad_pipeline/.venv/bin/python -m training.eval_asm_adapter --module asm1e1 \
      --ckpt /workspace/.hf_home/training/asm1/checkpoint-276 --sets live
Run (full, after training):
  cad_pipeline/.venv/bin/python -m training.eval_asm_adapter --module asm1 \
      --ckpt /workspace/.hf_home/training/asm1/final --sets live,eval,bank
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8002"
OUT_DIR = "/workspace/.hf_home/eval_asm1"

LIVE_BRIEFS = [
    ("stool", "a 4-legged stool, ~120 mm tall, round seat ⌀140, legs splayed 10°",
     "phase23: PASS@1 356s"),
    ("rover", "A four-wheeled utility rover: a 220×120×16 mm chassis riding at wheel-center "
     "height, four ⌀48×14 mm wheels on stub axles at the corners (wheelbase 140 mm), each wheel "
     "spinning freely on its own revolute across the width; on top of the chassis, a 90×70×40 mm "
     "equipment housing with a 2 mm shell, stacked centrally, and a ⌀60×8 mm sensor turret disc "
     "resting on the housing.",
     "base: FAILED twice (5-6/22 rows; wheel↔axle interference 309-2953mm³)"),
    ("enclosure", "PCB enclosure with standoffs, shelled base and lid",
     "phase23: degenerate 1-box 'pass' / clumped standoffs"),
    ("door", "an enclosure door on two hinges with a handle, door swings on revolute joints",
     "phase23: FAILED (honest feedback, model-side)"),
    # the OOD cliff probe (2026-07-16): a DASHBOARD SUGGESTED PROMPT asm2 failed — arms unmated,
    # raw-coordinate fallback — while the golden drone phrasing passed on the same model. The
    # rung-3 hero family + vocabulary variety exist to flip exactly this brief.
    ("quadcopter", "quadcopter frame: central hub, four arms, motor pads with bolt circles",
     "asm2: FAILED (arms unmated — OOD coordinate fallback)"),
]


def hot_load(module: str, ckpt: str) -> None:
    body = json.dumps({"lora_name": module, "lora_path": ckpt}).encode()
    req = urllib.request.Request(f"{BASE}/v1/load_lora_adapter", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            print(f"[load] {module} ← {ckpt}: {r.read().decode()[:120]}")
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:200]
        if "already" in msg.lower():
            print(f"[load] {module} already loaded — continuing")
        else:
            raise SystemExit(f"[load] FAILED {e.code}: {msg}")


def run_briefs(briefs, gen, run_assembly, max_attempts, tag, bank_path=None, asm_transcript=None,
               gen_meta=None):
    rows = []
    for i, (name, prompt, baseline) in enumerate(briefs, 1):
        print(f"[{tag} {i}/{len(briefs)}] {name}: {prompt[:70]}", flush=True)
        t0 = time.time()
        try:
            out = run_assembly(prompt, gen, max_attempts=max_attempts)
        except Exception as e:  # noqa: BLE001 — one bad episode must not stop the battery
            rows.append({"name": name, "passed": False, "error": str(e)[:200],
                         "seconds": round(time.time() - t0), "baseline": baseline})
            print(f"    ERROR {e}", flush=True)
            continue
        if bank_path and asm_transcript:
            with open(bank_path, "a") as f:
                f.write(asm_transcript(prompt, out, gen_meta).model_dump_json() + "\n")
        rep = out.get("best_report") or {}
        npass = sum(1 for r in rep.get("rows", []) if r["within_tol"])
        ncomp = len(rep.get("components") or (out.get("assembly") or {}).get("components", []) or [])
        rows.append({"name": name, "passed": out["passed"], "attempt": out.get("attempt"),
                     "rows": f"{npass}/{len(rep.get('rows', []))}", "components": ncomp,
                     "seconds": round(time.time() - t0), "baseline": baseline,
                     "categories": [h["category"] for h in out.get("history", [])]})
        state = f"PASS@{out['attempt']}" if out["passed"] else "FAIL"
        print(f"    {state}  rows {npass}/{len(rep.get('rows', []))}  parts={ncomp}  "
              f"{round(time.time() - t0)}s", flush=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True, help="served lora name (= PLAN_MODEL)")
    ap.add_argument("--ckpt", help="adapter path to hot-load (omit if already served)")
    ap.add_argument("--sets", default="live", help="comma of live,eval,bank")
    ap.add_argument("--max-attempts", type=int, default=3)
    a = ap.parse_args()

    if a.ckpt:
        hot_load(a.module, a.ckpt)
    os.environ["PLAN_MODEL"] = a.module  # must precede cad_pipeline imports (bound at import)

    from cad_pipeline.asm_loop import VLLMAsmGenerator, asm_transcript, run_assembly
    gen = VLLMAsmGenerator()
    assert gen.model == a.module, f"generator model {gen.model} != {a.module}"

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%m%d_%H%M")
    results: dict = {"module": a.module, "ckpt": a.ckpt, "sets": a.sets, "when": stamp}

    sets = [s.strip() for s in a.sets.split(",")]
    if "live" in sets:
        results["live"] = run_briefs(LIVE_BRIEFS, gen, run_assembly, a.max_attempts, "live")
    if "eval" in sets:
        from cad_pipeline.tests.eval_asm import evaluate
        summary = evaluate(a.max_attempts, out_path=f"{OUT_DIR}/{a.module}_{stamp}_eval.jsonl")
        summary.pop("results", None)
        results["eval"] = {**summary, "baseline": "base pass@1 = 1/10, repair_gain 0"}
    if "bank" in sets:
        from training.bank_asm_repair import BRIEFS, OUT as BANK_OUT
        bank_briefs = [(f"b{i}", b, "base: 0/20 over 2 rounds") for i, b in enumerate(BRIEFS)]
        gen_meta = {"model": a.module, "provider": "vllm-local", "role": "assembly-planner"}
        rows = run_briefs(bank_briefs, gen, run_assembly, a.max_attempts, "bank",
                          bank_path=BANK_OUT, asm_transcript=asm_transcript, gen_meta=gen_meta)
        results["bank"] = {"passed": sum(1 for r in rows if r.get("passed")),
                           "n": len(rows), "rows": rows, "baseline": "0/20 (base)"}

    out_path = f"{OUT_DIR}/{a.module}_{stamp}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("\n===== SUMMARY vs baselines =====")
    for r in results.get("live", []):
        state = f"PASS@{r['attempt']}" if r.get("passed") else ("ERROR" if r.get("error") else "FAIL")
        print(f"  {r['name']:10s} {state:8s} {r.get('rows', '-'):8s} {r['seconds']}s   "
              f"(was: {r['baseline']})")
    if "eval" in results:
        print(f"  eval_asm   {results['eval']['pass_at']}   (was: pass@1 1/10)")
    if "bank" in results:
        print(f"  bank       {results['bank']['passed']}/{results['bank']['n']}   (was: 0/20)")
    print(f"→ {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
