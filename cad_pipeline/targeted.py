"""Targeted-layer driver — generate the Phase-2 sci-fi/robotics clean-room corpus.

Spec-first, deterministic, verifier-gated (docs/research/track-a-targeted-layer.md §6). Pipeline per
sample: pick a weighted category → templates.sample → emit_idiomatic (idiomatic target code) →
ACCEPT GATE = run_code (sandboxed exec → feature-level verify) → captions.describe (L0–L3) →
write the 6-tuple. Spec-hash dedup; a soft L1 cap pulls the level mix toward the 15/45/40 target
(under-weight RAG-covered basics — corpus-scope §2). 100% clean by construction (the rare sampled
edge case is gate-rejected, not shipped).

Run:
  cad_pipeline/.venv/bin/python -m cad_pipeline.targeted --n 3000 \
      --out /workspace/.hf_home/cad_corpus/targeted_pilot.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter

from .captions import describe
from .emit_idiomatic import emit_idiomatic
from .executor import run_code
from .spec import Spec
from .templates import level, sample, weighted_categories


def _spec_hash(spec: Spec) -> str:
    return spec.model_dump_json()


def _sample_record(category: str, spec: Spec, code: str, rep: dict, rng: random.Random) -> dict:
    """The 6-tuple (corpus-scope §1): prompts · code · spec · verifier report · tags."""
    caps = sorted({spec.shape, *[f.type for f in spec.features]})
    return {
        "source": "targeted",
        "category": category,
        "tags": {"capabilities": caps, "level": level(spec), "dist": "in"},
        "prompts": describe(spec, rng),               # L0–L3
        "code": code,                                  # idiomatic target (gated, verify-passing)
        "spec": json.loads(spec.model_dump_json()),
        "verifier": {"passed": True, "rows": [r["name"] for r in rep["report"]["rows"]]},
    }


def generate(total: int, out_path: str, seed: int = 0, l1_cap: float = 0.18, l2_cap: float = 0.50) -> dict:
    cats = weighted_categories()
    master = random.Random(seed)
    seen: set = set()
    by_level: Counter = Counter()
    by_cat: Counter = Counter()
    caps_cov: Counter = Counter()
    fail: Counter = Counter()
    kept = attempts = dup = capped = 0
    budget = total * 8 + 200

    with open(out_path, "w") as fh:
        while kept < total and attempts < budget:
            attempts += 1
            category = cats[master.randrange(len(cats))]
            rng = random.Random(master.getrandbits(64))
            try:
                spec = sample(category, rng)
            except Exception as ex:  # noqa: BLE001
                fail[f"sample:{type(ex).__name__}"] += 1
                continue
            h = _spec_hash(spec)
            if h in seen:
                dup += 1
                continue
            code = emit_idiomatic(spec)
            rep = run_code(code, spec, timeout=60)
            if not (rep.get("status") == "ok" and rep.get("report", {}).get("passed", False)):
                fail[rep.get("status", "?")] += 1
                continue
            lvl = level(spec)
            # soft level caps → pull the mix toward 15/45/40 (L3 uncapped — it's the OOD moat)
            if lvl == "L1" and by_level["L1"] >= l1_cap * total:
                capped += 1
                continue
            if lvl == "L2" and by_level["L2"] >= l2_cap * total:
                capped += 1
                continue
            seen.add(h)
            fh.write(json.dumps(_sample_record(category, spec, code, rep, rng)) + "\n")
            kept += 1
            by_level[lvl] += 1
            by_cat[category] += 1
            for c in {spec.shape, *[f.type for f in spec.features]}:
                caps_cov[c] += 1
            if kept % 250 == 0:
                print(f"  [{kept}/{total}] attempts={attempts} levels={dict(by_level)}", flush=True)

    pct = {k: round(100 * v / max(kept, 1), 1) for k, v in by_level.items()}
    return {
        "kept": kept, "attempts": attempts, "dup": dup, "capped": capped,
        "accept_rate": round(kept / max(attempts, 1), 3),
        "levels": dict(by_level), "levels_pct": pct,
        "by_category": dict(by_cat.most_common()),
        "capability_coverage": dict(caps_cov.most_common()),
        "gate_rejects": dict(fail.most_common()),
        "out": out_path,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default="/tmp/targeted_pilot.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--l1-cap", type=float, default=0.18)
    ap.add_argument("--l2-cap", type=float, default=0.50)
    a = ap.parse_args()
    print(f"Targeted-layer generation → {a.out}  (target N={a.n})\n")
    summary = generate(a.n, a.out, seed=a.seed, l1_cap=a.l1_cap, l2_cap=a.l2_cap)
    print("\n" + json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
