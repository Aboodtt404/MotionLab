"""Merge the assembly-SFT legs into the final training mixture (recipe-conformant doses).

  leg 1  asm_pairs.jsonl        (corpus_out/) — synthetic golden families + REAL repair pairs
  leg 2  fusion_pairs.jsonl     — REAL Fusion designs, VLM-captioned          (CAPPED — see below)
  leg 3  leg3_pairs.jsonl       — model's own verifier-passing plans (diversity)
  general_code_18k.jsonl        — anti-forgetting slice (recipe §4: 10–20% general in EVERY SFT mix;
                                  the asm1/asm2 mixes dropped it — restored here at ~12%)

Balance rationale: leg 2 is 61% of raw pairs but is ALL 2-part fragments — uncapped it teaches the
model that assemblies have two parts. Cap fusion at ~45% of leg 1's volume, keeping EVERY revolute/
cylindrical record (the articulation vocabulary is the scarce asset) and sampling the rigid rest.

Dose report: prints the REPAIR and GENERAL shares of the FINAL mix — the fable recipe's ~15% repair
target applies to the final mixture (the asm1/asm2 lesson: 137 repair pairs looked like 15% of leg1
but diluted to 3% after the merge, and repair skill never emerged).

Out: /workspace/.hf_home/cad_corpus/asm_sft_mix.jsonl   (shuffled, ready for train_sft --mode instruct)
Run: cad_pipeline/.venv/bin/python -m training.build_asm_sft_mix
"""
from __future__ import annotations

import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LEG1 = "/home/abdelrahman/MotionLab/corpus_out/asm_pairs_v3.jsonl"   # batch8: rack + hero quad + 1,150 repair
LEG2 = "/workspace/.hf_home/cad_corpus/fusion_pairs.jsonl"
LEG3 = "/workspace/.hf_home/cad_corpus/leg3_pairs.jsonl"
# leg 4 (2026-08-02): PORT exemplars — the same real Fusion mechanisms as leg 2 but re-expressed
# as the precise typed `port` mate, each PROVEN to reproduce the real placement (median 0.000 mm).
# build_fusion_pairs excludes these sets, so a mechanism is taught exactly once, the precise way.
LEG4 = "/workspace/.hf_home/cad_corpus/port_pairs.jsonl"
GENERAL = "/workspace/.hf_home/cad_corpus/general_code_18k.jsonl"
GENERAL_FRAC = 0.12
OUT = "/workspace/.hf_home/cad_corpus/asm_sft_mix_v3.jsonl"          # v3 — never clobber asm3's training data


def load(path: str) -> list:
    if not os.path.exists(path):
        print(f"  (missing: {path})")
        return []
    return [json.loads(l) for l in open(path)]


def main() -> int:
    rng = random.Random(42)
    leg1, leg2, leg3, leg4 = load(LEG1), load(LEG2), load(LEG3), load(LEG4)
    print(f"raw: leg1={len(leg1)}  leg2={len(leg2)}  leg3={len(leg3)}  leg4(port)={len(leg4)}")

    cap = int(len(leg1) * 0.45) if leg1 else len(leg2)
    art = [p for p in leg2 if "revolute" in p["category"] or "cylindrical" in p["category"]]
    rig = [p for p in leg2 if "rigid" in p["category"]]
    rng.shuffle(rig)
    leg2_mix = art + rig[:max(0, cap - len(art))]
    print(f"leg2 capped: {len(leg2_mix)} (all {len(art)} articulated + {len(leg2_mix) - len(art)} rigid sample)")

    # leg 4 is 2-part fragments like leg 2, so it carries the same "assemblies have two parts"
    # hazard — capped against leg 1 rather than taken whole. It is the ONLY source of worked port
    # examples, so it gets a real dose (the zero-shot desk got 2/3 of its ports semantically wrong).
    cap4 = int(len(leg1) * 0.25) if leg1 else len(leg4)
    rng.shuffle(leg4)
    leg4_mix = leg4[:cap4]
    print(f"leg4 capped: {len(leg4_mix)}/{len(leg4)} port pairs (<= 25% of leg1)")

    mix = leg1 + leg2_mix + leg3 + leg4_mix

    # anti-forgetting slice — sized against the assembly pairs so it lands at GENERAL_FRAC of final
    gen_pool = load(GENERAL)
    rng.shuffle(gen_pool)
    general = gen_pool[:int(len(mix) * GENERAL_FRAC / (1 - GENERAL_FRAC))]
    for g in general:
        g.setdefault("source", "general")
        g.setdefault("prompt_level", "general")
    mix += general

    # ---- PRODUCIBILITY GATE (the 2026-08-02 audit's blocker: 0/1,217 port targets and only ~25%
    # of the whole plan lane were emittable under the SERVED guided-decoding grammar — pydantic
    # defaults, key ORDER, and -0.0. Training on tokens the decoder masks to zero probability is
    # pure waste). Every plan/outline target must validate against the schema the server compiles.
    try:
        import jsonschema
        from cad_pipeline.planner import _OUTLINE_SCHEMA, _asm_schema
        v_asm = jsonschema.Draft202012Validator(_asm_schema())
        v_out = jsonschema.Draft202012Validator(_OUTLINE_SCHEMA)
        from cad_pipeline.planner import dump_for_grammar
        bad, healed = collections.Counter(), collections.Counter()
        for p in mix:
            src = p.get("source", "")
            if p.get("prompt_level") in ("repair", "general"):
                continue                      # repair uses the per-route scoped patch schema
            try:
                data = json.loads(p["code"])
            except Exception:  # noqa: BLE001
                bad[src + ":unparseable"] += 1
                continue
            val, sch = (v_out, _OUTLINE_SCHEMA) if "outline" in src else (v_asm, _asm_schema())
            if not val.is_valid(data):
                # LAST-GATE HEAL: conform here too, so a leg whose builder predates
                # dump_for_grammar (e.g. leg3-synth) can never ship dead tokens.
                fixed = dump_for_grammar(data, sch)
                if val.is_valid(json.loads(fixed)):
                    p["code"] = fixed
                    healed[src] += 1
                else:
                    bad[src] += 1
        if healed:
            print(f"  producibility gate HEALED {sum(healed.values())} legacy targets: {dict(healed)}")
        n_checked = sum(1 for p in mix if p.get("prompt_level") not in ("repair", "general"))
        if bad:
            print(f"  !! PRODUCIBILITY GATE: {sum(bad.values())}/{n_checked} targets are NOT emittable "
                  f"under the served grammar: {dict(bad)}")
            print("     (fix the builder to use planner.dump_for_grammar — do NOT train on these)")
        else:
            print(f"  producibility gate: {n_checked}/{n_checked} plan+outline targets are decoder-emittable")
    except ImportError:
        print("  (jsonschema not installed — producibility gate SKIPPED)")

    rng.shuffle(mix)
    with open(OUT, "w") as f:
        for p in mix:
            f.write(json.dumps(p) + "\n")
    srcs = collections.Counter(p.get("source", "?") for p in mix)
    lvls = collections.Counter(p.get("prompt_level", "?") for p in mix)
    n = len(mix)
    n_rep = sum(1 for p in mix if p.get("prompt_level") == "repair")
    n_port = sum(1 for p in mix if p.get("source", "").endswith("-port"))
    n_routed = sum(1 for p in mix if p.get("route") and p.get("route") != "flat")
    print(f"final mix: {n} pairs → {OUT}")
    print("  by source:", dict(srcs))
    print("  by level: ", dict(lvls))
    print(f"  DOSES: repair {n_rep}/{n} = {100 * n_rep / max(1, n):.1f}%  (recipe target ~15%)  |  "
          f"general {len(general)}/{n} = {100 * len(general) / max(1, n):.1f}%  (recipe 10–20%)")
    print(f"  NEW: port {n_port}/{n} = {100 * n_port / max(1, n):.1f}%  |  "
          f"routed repair {n_routed}/{max(1, n_rep)} = {100 * n_routed / max(1, n_rep):.0f}% of repair pairs")
    fams = collections.Counter(p.get("category", "?") for p in mix if p.get("source", "").startswith("asm"))
    top = fams.most_common(1)[0] if fams else ("-", 0)
    print(f"  top family: {top[0]} = {100 * top[1] / max(1, sum(fams.values())):.1f}% of asm pairs (quota ≤ ~25%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
