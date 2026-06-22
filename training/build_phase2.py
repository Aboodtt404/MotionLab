"""Assemble the Phase-2 instruct SFT dataset = flatten(targeted) + curate(CAD-Coder), blended.

Phase-2 teaches prompt→code (track-a-corpus-scope.md §5b). Two sources, both already exec/verify-gated:
  - targeted_pilot.jsonl  — OUR clean-room sci-fi/robotics 6-tuples (carry L0–L3 prompts + 1 code each)
  - cadcoder_gated.jsonl  — 160K borrowed (prompt→code) pairs, license = research/dev-only

This script:
  1. FLATTENS each targeted record into one (prompt, code) pair per chosen prompt level (default
     l1/l2/l3 — l0 is a 2-word object name, too sparse to map to a specific part). Same code, several
     phrasings = free augmentation (Text2CAD style).
  2. CURATES CAD-Coder: it is ~57% trivial (≤8-face boxes); a `--simple-frac` cap down-weights those
     so the instruct set isn't basics-heavy (corpus-scope §0: under-weight RAG-covered basics).
  3. BLENDS + shuffles → JSONL of {prompt, code, ...meta}. `train_sft.py --mode instruct` reads
     `prompt` + `code`; the extra fields are ignored by training, kept for inspection.

PILOT-FIRST (corpus-scope §6.1): default caps make a ~40K pilot blend — enough to measure the SFT
delta vs RAG before committing to a bigger targeted corpus + full run. Scale via --cadcoder-n -1.

Run:
  cad_pipeline/.venv/bin/python training/build_phase2.py \
      --targeted /workspace/.hf_home/cad_corpus/targeted_pilot.jsonl \
      --cadcoder /workspace/.hf_home/cad_corpus/cadcoder_gated.jsonl \
      --out      /workspace/.hf_home/cad_corpus/phase2_instruct.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter


def _load(path: str) -> list:
    with open(path) as f:
        return [json.loads(line) for line in f]


def flatten_targeted(recs: list, levels: list) -> list:
    out = []
    for r in recs:
        for lv in levels:
            p = r["prompts"].get(lv)
            if not p:
                continue
            out.append({"prompt": p, "code": r["code"], "source": "targeted",
                        "level": r["tags"]["level"], "category": r["category"], "prompt_level": lv})
    return out


def curate_cadcoder(recs: list, n: int, simple_frac: float, face_thr: int, rng: random.Random) -> list:
    """Keep `n` pairs, with at most `simple_frac` of them ≤`face_thr` faces (trivial primitives)."""
    simple = [r for r in recs if (r.get("meta", {}).get("faces") or 0) <= face_thr]
    complex_ = [r for r in recs if (r.get("meta", {}).get("faces") or 0) > face_thr]
    rng.shuffle(simple)
    rng.shuffle(complex_)
    if n < 0:                                   # keep everything, cap only the simple share
        n = len(recs)
    n_simple = min(len(simple), int(n * simple_frac))
    n_complex = min(len(complex_), n - n_simple)
    if n_complex < n - n_simple:                # not enough composites → backfill from simple
        n_simple = min(len(simple), n - n_complex)
    keep = complex_[:n_complex] + simple[:n_simple]
    out = []
    for r in keep:
        faces = r.get("meta", {}).get("faces")
        out.append({"prompt": r["prompt"], "code": r["code"], "source": "cad-coder",
                    "level": "simple" if (faces or 0) <= face_thr else "composite",
                    "category": "cad-coder", "faces": faces})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targeted", required=True)
    ap.add_argument("--cadcoder", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--levels", default="l1,l2,l3", help="targeted prompt levels to flatten")
    ap.add_argument("--cadcoder-n", type=int, default=30000, help="CAD-Coder pairs to keep (-1 = all)")
    ap.add_argument("--simple-frac", type=float, default=0.30, help="max ≤face-thr share of CAD-Coder")
    ap.add_argument("--face-thr", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    tgt = flatten_targeted(_load(a.targeted), a.levels.split(","))
    cc = curate_cadcoder(_load(a.cadcoder), a.cadcoder_n, a.simple_frac, a.face_thr, rng)
    blend = tgt + cc
    rng.shuffle(blend)

    with open(a.out, "w") as f:
        for r in blend:
            f.write(json.dumps(r) + "\n")

    by_src = Counter(r["source"] for r in blend)
    by_lvl = Counter(r["level"] for r in blend)
    summary = {
        "out": a.out, "total_pairs": len(blend),
        "targeted_pairs": len(tgt), "cadcoder_pairs": len(cc),
        "by_source": dict(by_src), "by_level": dict(by_lvl),
        "targeted_levels": a.levels, "cadcoder_simple_frac_cap": a.simple_frac,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
