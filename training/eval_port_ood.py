"""Real-mechanism OOD eval — held-out Fusion attachments, scored on PORT SELECTION.

Why this exists: every assembly eval we have is synthetic-family or hand-written briefs. The port
corpus (build_port_pairs) teaches placement from ~319 real engineer-authored mechanisms; without a
held-out real-mechanism probe we'd be back to shipping an unmeasured change — the exact mistake
that cost a 19-hour GRPO run (its reward was never checked against the gate it claimed to proxy).

The sets here are the hash-stable `eval` split from filter_fusion_joints — they were EXCLUDED from
training pairs by build_port_pairs, so no leakage. Two numbers, both harder than "did it build":

  pass_rate  — the full verifier on the model's assembly (fragment-waived, like the translator)
  port_face  — of the briefs whose GROUND TRUTH is a port mate, how often did the model emit a
               port mate with the SAME b_port face? This is the metric FIX 2 actually targets:
               placement as a discrete CHOICE. A model that ignores ports scores 0 here while
               still passing the verifier by luck, so it separates vocabulary from geometry.

Run: PLAN_MODEL=<module> cad_pipeline/.venv/bin/python -m training.eval_port_ood [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cad_pipeline.asm_captions import asm_describe  # noqa: E402
from cad_pipeline.assembly import Assembly, verify_assembly  # noqa: E402
from training.build_port_pairs import CAPTIONED, rewrite  # noqa: E402

SETS = "/workspace/.hf_home/cad_corpus/port_pairs.sets.json"
OUT_DIR = "/workspace/.hf_home/eval_asm1"


def load_cases(limit: int = 0) -> list:
    want = set(json.load(open(SETS))["eval"])
    caps = {}
    for line in open(CAPTIONED):
        r = json.loads(line)
        if r["set"] in want:
            caps[r["set"]] = r
    cases = []
    for name, rec in sorted(caps.items()):
        rw = rewrite(rec)                      # deterministic; same transform the corpus used
        if rw is None:
            continue
        gt = Assembly(**rw["assembly"])
        # fresh phrasing (rng seeded per set): tests the VOCABULARY, not caption memorisation
        caps_l = asm_describe(gt, random.Random(hash(name) % (2 ** 31)))
        brief = caps_l.get("l2") or caps_l.get("l1")
        if not brief:
            continue
        gt_port = next((m for m in gt.mates if m.kind == "port"), None)
        cases.append({"set": name, "brief": brief, "gt_b_port": gt_port.b_port if gt_port else None,
                      "gt_a_port": gt_port.a_port if gt_port else None,
                      "n_parts": len(gt.components)})
        if limit and len(cases) >= limit:
            break
    return cases


def score(asm: Assembly, case: dict) -> dict:
    out = {"set": case["set"], "parts": len(asm.components)}
    try:
        rep = verify_assembly(asm)
    except Exception as e:  # noqa: BLE001
        return {**out, "passed": False, "rows": "0/0", "port": None, "err": type(e).__name__}
    fails = [r for r in rep["rows"] if not r["within_tol"] and "statics" not in r["name"]]
    out["passed"] = not fails
    out["rows"] = f"{sum(1 for r in rep['rows'] if r['within_tol'])}/{len(rep['rows'])}"
    got = next((m for m in asm.mates if m.kind == "port"), None)
    out["port"] = got.b_port if got else None
    out["port_match"] = bool(got and case["gt_b_port"] and got.b_port == case["gt_b_port"])
    out["emitted_port"] = got is not None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-attempts", type=int, default=1)   # pass@1 by default: measure the DICE
    ap.add_argument("--module", default=os.environ.get("PLAN_MODEL", "asm3"))
    a = ap.parse_args()
    os.environ["PLAN_MODEL"] = a.module

    from cad_pipeline.asm_loop import VLLMAsmGenerator, run_assembly
    gen = VLLMAsmGenerator()
    assert gen.model == a.module, f"generator {gen.model} != {a.module}"

    cases = load_cases(a.limit)
    print(f"[port-ood] {len(cases)} held-out real mechanisms · module={a.module}", flush=True)
    rows, t0 = [], time.time()
    for i, c in enumerate(cases, 1):
        try:
            out = run_assembly(c["brief"], gen, max_attempts=a.max_attempts)
            asm = Assembly(**out["attempt_log"][-1]["assembly"])
            r = score(asm, c)
        except Exception as e:  # noqa: BLE001 — a dead plan is a data point
            r = {"set": c["set"], "passed": False, "rows": "0/0", "port": None,
                 "port_match": False, "emitted_port": False, "err": f"{type(e).__name__}"}
        r["gt_port"] = c["gt_b_port"]
        rows.append(r)
        print(f"  [{i}/{len(cases)}] {r['set']}: passed={r['passed']} rows={r['rows']} "
              f"port={r['port']} vs gt={r['gt_port']} match={r.get('port_match')}", flush=True)

    n = len(rows)
    npass = sum(1 for r in rows if r["passed"])
    with_gt = [r for r in rows if r["gt_port"]]
    nmatch = sum(1 for r in with_gt if r.get("port_match"))
    nemit = sum(1 for r in rows if r.get("emitted_port"))
    print(f"\n===== PORT-OOD ({a.module}) =====")
    print(f"  pass_rate  {npass}/{n} ({100*npass/max(n,1):.0f}%)")
    print(f"  port_face  {nmatch}/{len(with_gt)} ({100*nmatch/max(len(with_gt),1):.0f}%) — "
          f"correct b_port among ground-truth port briefs")
    print(f"  emitted a port mate at all: {nemit}/{n} ({100*nemit/max(n,1):.0f}%)")
    print(f"  wall {time.time()-t0:.0f}s")
    os.makedirs(OUT_DIR, exist_ok=True)
    path = f"{OUT_DIR}/{a.module}_port_ood_{time.strftime('%m%d_%H%M')}.json"
    json.dump({"module": a.module, "n": n, "pass": npass, "port_match": nmatch,
               "n_with_gt": len(with_gt), "emitted": nemit, "rows": rows}, open(path, "w"), indent=1)
    print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
