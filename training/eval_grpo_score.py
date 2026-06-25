"""A/B eval SCORER (cad_pipeline/.venv): score generated completions through the deterministic
verifier (single-shot = run_code once). Reads the generator's JSONL, aggregates by RAG×dist, prints
a comparison table. Numbers are comparable to the decision-gate eval (same verifier).

Run:  cad_pipeline/.venv/bin/python training/eval_grpo_score.py /tmp/grpo_ab_<label>.completions.jsonl <label>
"""
from __future__ import annotations
import sys, json
sys.path.insert(0, ".")
from cad_pipeline.spec import Spec
from cad_pipeline.executor import run_code

PATH = sys.argv[1]
LABEL = sys.argv[2] if len(sys.argv) > 2 else "model"
rows = [json.loads(l) for l in open(PATH)]


def score(r):
    spec = Spec(**r["spec"])
    res = run_code(r["code"], spec, timeout=60.0)
    execok = res.get("status") == "ok"
    passed = execok and res.get("report", {}).get("passed", False)
    return {**{k: r[k] for k in ("dist", "cap", "level", "rag")}, "exec": execok, "passed": passed}


scored = [score(r) for r in rows]


def rate(sub, key):
    return (sum(1 for r in sub if r[key]) / len(sub) * 100) if sub else 0.0


print(f"\n================ {LABEL} ================")
for rag in (False, True):
    g = [r for r in scored if r["rag"] == rag]
    inn = [r for r in g if r["dist"] == "in"]; ood = [r for r in g if r["dist"] == "ood"]
    print(f"\n----- RAG={rag} -----")
    print(f"  OVERALL pass={rate(g,'passed'):5.1f}%  exec={rate(g,'exec'):5.1f}%  (n={len(g)})")
    print(f"  IN      pass={rate(inn,'passed'):5.1f}%  exec={rate(inn,'exec'):5.1f}%  (n={len(inn)})")
    print(f"  OOD     pass={rate(ood,'passed'):5.1f}%  exec={rate(ood,'exec'):5.1f}%  (n={len(ood)})")
    fails = [f"{r['cap']}/{r['level']}/{r['dist']}" for r in g if not r["passed"]]
    print(f"  FAILS:  {', '.join(fails) if fails else 'none'}")

with open(f"/tmp/grpo_ab_{LABEL}.scored.json", "w") as f:
    json.dump(scored, f, indent=2)
print(f"\nSAVED -> /tmp/grpo_ab_{LABEL}.scored.json")
