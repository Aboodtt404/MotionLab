"""Base-model bake-off on OUR assembly benchmark — is a different base worth an SFT run?

Compares raw bases (no adapters) through the same plan→verify→repair loop the adapters
use, on briefs spanning trained families and OOD. The question is the post-SFT CEILING:
a base that zero-shots our schema better is the one worth spending a retrain on.

  cad_pipeline/.venv/bin/python -m training.bakeoff_base
"""

from __future__ import annotations

import json
import os
import time

OUT_DIR = "/workspace/.hf_home/eval_asm1"

MODELS = [
    ("qwen3.6-27b", "http://localhost:8002/v1"),    # our base (adapters train on this)
    ("thebes-coder", "http://localhost:8001/v1"),   # Qwen3-Coder-30B-A3B base (candidate)
]

BRIEFS = [
    ("stool", "a 4-legged stool, ~120 mm tall, round seat ⌀140, legs splayed 10°"),
    ("quadcopter", "quadcopter frame: central hub, four arms, motor pads with bolt circles"),
    ("enclosure", "PCB enclosure with standoffs, shelled base and lid"),
    ("mast", "a sensor mast: a base plate with a vertical pole and a small sensor head on top"),
    ("pcb", "a PCB mounted on four corner standoffs on a base plate 90x70 mm"),
    ("door", "an enclosure door on two hinges with a handle, door swings on revolute joints"),
    ("workbench", "a workbench: rectangular top on four legs, a lower storage shelf spanning "
     "the legs at mid height"),
    ("rover", "a four-wheeled rover: chassis plate, four wheels on stub axles at the corners, "
     "each spinning on its own revolute"),
]


def main() -> int:
    from cad_pipeline.asm_loop import VLLMAsmGenerator, run_assembly

    stamp = time.strftime("%m%d_%H%M")
    results: dict = {"suite": "bakeoff", "when": stamp, "models": {}}
    for model, base_url in MODELS:
        gen = VLLMAsmGenerator(base_url=base_url, model=model)
        rows = []
        for name, prompt in BRIEFS:
            t0 = time.time()
            try:
                out = run_assembly(prompt, gen, max_attempts=3)
                rep = out.get("best_report") or {}
                npass = sum(1 for r in rep.get("rows", []) if r["within_tol"])
                rows.append({"name": name, "passed": out["passed"], "attempt": out.get("attempt"),
                             "rows": f"{npass}/{len(rep.get('rows', []))}",
                             "seconds": round(time.time() - t0)})
            except Exception as e:  # noqa: BLE001
                rows.append({"name": name, "passed": False,
                             "error": f"{type(e).__name__}: {str(e)[:160]}",
                             "seconds": round(time.time() - t0)})
            r = rows[-1]
            state = (f"PASS@{r['attempt']}" if r.get("passed")
                     else ("ERROR" if r.get("error") else "FAIL"))
            print(f"[{model}] {name}: {state} {r.get('rows', r.get('error', ''))} "
                  f"{r['seconds']}s", flush=True)
        results["models"][model] = rows

    path = f"{OUT_DIR}/bakeoff_{stamp}.json"
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(results, f, indent=2)

    print("\n===== BAKE-OFF =====")
    print(f"{'brief':12s}" + "".join(f"{m:>16s}" for m, _ in MODELS))
    for i, (name, _) in enumerate(BRIEFS):
        cells = []
        for m, _u in MODELS:
            r = results["models"][m][i]
            cells.append(f"PASS@{r['attempt']}" if r.get("passed")
                         else ("ERROR" if r.get("error") else f"F {r.get('rows', '')}"))
        print(f"{name:12s}" + "".join(f"{c:>16s}" for c in cells))
    for m, _u in MODELS:
        n = sum(1 for r in results["models"][m] if r.get("passed"))
        print(f"{m}: {n}/{len(BRIEFS)}")
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
