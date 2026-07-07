"""Assemble the Phase-2.1 curriculum SFT set from the verifier-gated corpus batches.

The bench A/B localized the fine-tune target: no-RAG fails exactly 7 convention families
(revolve, loft, sweep, shell, countersink, draft, var_fillet) while box-family survives.
Batches 1–3 were produced against that curriculum (batch 3 hint-forced toward the starved
families), every sample gated on the SHIPPED artifact (exec(emit_code) + verify). This script
turns them into train_sft.py --mode instruct pairs:

  1. HOLDOUT dedup (03_training_recipe §5): drop any sample whose spec signature (shape +
     feature-type multiset + envelope dims rounded to 5 mm) matches an eval spec — GOLDEN,
     EVAL_HARD, and the benchmark set are never trained on.
  2. prompt→code pairs from l1/l2/l3 (l0 is too sparse to pin to a specific part — build_phase2's
     finding), same code under several phrasings = free augmentation.
  3. spec→code pairs (the recipe's mixed-task row): prompt = the spec JSON itself — the exact
     input the live loop sends, so the adapter learns the production task too.
  4. repair pairs (recipe §3c, capped at ~15% of the mixture) from RepairTranscript JSONLs
     (harvest with `eval_baseline <set> --transcripts=FILE`): prompt = spec JSON + the loop's
     exact failure preamble + the typed feedback the generator actually saw; target = the first
     LATER attempt of that episode that fully passed (the model's own verified fix), else the
     golden emit_code (always verified). Matches loop.VLLMGenerator.generate() byte-for-byte.

Run:
  cad_pipeline/.venv/bin/python training/build_curriculum.py \
      --corpus corpus_out/batch1_clean.jsonl corpus_out/batch2_w*.jsonl corpus_out/batch3_w*.jsonl \
      --repair corpus_out/repair_transcripts*.jsonl \
      --out /workspace/.hf_home/cad_corpus/phase21_curriculum.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sys
from collections import Counter

sys.path.insert(0, ".")


def _sig(spec: dict) -> tuple:
    """Cheap near-duplicate signature: shape + feature-type multiset + envelope dims @5mm."""
    env = spec.get("envelope") or {}
    dims = tuple(sorted((k, round(float(v) / 5.0) * 5) for k, v in env.items()
                        if isinstance(v, (int, float))))
    feats = tuple(sorted(f["type"] for f in spec.get("features", [])))
    return (spec.get("shape"), feats, dims)


def _holdout_sigs() -> set:
    from cad_pipeline.tests.bench_specs import EVAL_BENCH
    from cad_pipeline.tests.eval_baseline import EVAL_HARD
    from cad_pipeline.tests.selftest import GOLDEN
    sigs = set()
    for s in [*GOLDEN, *EVAL_HARD, *EVAL_BENCH]:
        sigs.add(_sig(json.loads(s.model_dump_json())))
    return sigs


def _repair_pairs(paths: list) -> list:
    """RepairTranscript JSONLs → (spec+feedback → verified code) pairs, mirroring the exact
    user message loop.VLLMGenerator.generate() builds on a retry. Assembly transcripts
    (spec.kind == assembly_brief) are a different task and are skipped here."""
    from cad_pipeline.builder import emit_code
    from cad_pipeline.spec import Spec
    pairs = []
    for p in paths:
        for line in open(p):
            t = json.loads(line)
            if (t.get("spec") or {}).get("kind") == "assembly_brief":
                continue
            spec = Spec(**t["spec"])
            spec_json = spec.model_dump_json(indent=2)
            attempts = t.get("attempts", [])
            for i, a in enumerate(attempts[:-1]):
                fb = a.get("feedback_to_next")
                if not fb:
                    continue
                target = next((b["code"] for b in attempts[i + 1:]
                               if (b.get("verifier_report") or {}).get("passed") and b.get("code")),
                              None)
                src = "repair" if target else "repair-golden"
                target = target or emit_code(spec)
                prompt = (f"Build this part as CadQuery, assigning the solid to `result`:\n{spec_json}"
                          f"\n\nThe previous attempt failed verification — fix ONLY these issues, "
                          f"keep the rest:\n{fb}")
                pairs.append({"prompt": prompt, "code": target, "source": src,
                              "level": "repair", "category": "repair", "prompt_level": "repair"})
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", nargs="+", required=True, help="TrainingSample JSONL files/globs")
    ap.add_argument("--repair", nargs="*", default=[], help="RepairTranscript JSONL files/globs")
    ap.add_argument("--repair-frac", type=float, default=0.15, help="max repair share of the mixture")
    ap.add_argument("--general", default=None,
                    help="general-code {prompt,code} JSONL — recipe §4: keep 10–20%% general code "
                         "in every SFT mixture to avoid catastrophic forgetting")
    ap.add_argument("--general-frac", type=float, default=0.15, help="general-code share of the mixture")
    ap.add_argument("--out", required=True)
    ap.add_argument("--levels", default="l1,l2,l3")
    ap.add_argument("--spec-pairs", action="store_true", default=True,
                    help="include spec→code pairs (one per sample)")
    ap.add_argument("--val-frac", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    paths = sorted({p for pat in a.corpus for p in glob.glob(pat)} )
    paths = [p for p in paths if not p.endswith(".rejects.jsonl")]
    recs, seen = [], set()
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            sid = r.get("sample_id") or json.dumps(r["spec"], sort_keys=True)
            if sid in seen:
                continue
            seen.add(sid)
            recs.append(r)

    holdout = _holdout_sigs()
    kept = [r for r in recs if _sig(r["spec"]) not in holdout]
    n_held = len(recs) - len(kept)

    pairs = []
    levels = a.levels.split(",")
    for r in kept:
        for lv in levels:
            p = (r.get("prompts") or {}).get(lv)
            if p:
                pairs.append({"prompt": p, "code": r["code"], "source": "curriculum",
                              "level": r["tags"]["level"], "category": r["category"],
                              "prompt_level": lv})
        if a.spec_pairs:
            pairs.append({"prompt": json.dumps(r["spec"], separators=(",", ":")),
                          "code": r["code"], "source": "curriculum-spec",
                          "level": r["tags"]["level"], "category": r["category"],
                          "prompt_level": "spec"})

    rpaths = sorted({p for pat in a.repair for p in glob.glob(pat)})
    repair = _repair_pairs(rpaths) if rpaths else []
    rng.shuffle(repair)
    cap = int(len(pairs) * a.repair_frac / (1 - a.repair_frac))   # repair ≤ repair_frac of TOTAL
    if len(repair) > cap:
        repair = repair[:cap]
    pairs += repair

    general = []
    if a.general:
        pool = [json.loads(line) for line in open(a.general)]
        rng.shuffle(pool)
        general = pool[:int(len(pairs) * a.general_frac / (1 - a.general_frac))]
        pairs += general
    rng.shuffle(pairs)

    n_val = max(1, int(len(pairs) * a.val_frac))
    val, train = pairs[:n_val], pairs[n_val:]
    val_out = a.out.replace(".jsonl", ".val.jsonl")
    with open(a.out, "w") as f:
        for r in train:
            f.write(json.dumps(r) + "\n")
    with open(val_out, "w") as f:
        for r in val:
            f.write(json.dumps(r) + "\n")

    caps = Counter()
    for r in kept:
        for c in r["tags"]["capabilities"]:
            caps[c] += 1
    print(json.dumps({
        "files": paths, "repair_files": rpaths, "samples_in": len(recs), "holdout_dropped": n_held,
        "samples_used": len(kept), "repair_pairs": len(repair), "general_pairs": len(general),
        "train_pairs": len(train), "val_pairs": len(val),
        "by_prompt_level": dict(Counter(p["prompt_level"] for p in pairs)),
        "capability_coverage": dict(caps.most_common()),
        "out": a.out, "val_out": val_out,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
