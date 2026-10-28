"""Leg-2 pairs: captioned REAL Fusion assemblies → SFT pairs in the planner's EXACT serving formats
(identical record shape to build_asm_pairs leg 1: {"system","prompt","code",...}).

Per captioned keep (fusion_joint_assemblies.captioned.jsonl):
  • plan pairs   — _SYSTEM + "input: <caption>" → compact assembly JSON, across the gated ladder
                   (l1 simple / l2 rough / l3 metric) + the bare VLM name (terse casual persona)
  • two-stage    — the Stage-2 listing form (parts list → realized assembly)
  • outline pair — _OUTLINE_SYSTEM + "object: <name>" → {"parts":[{name,role,shape}]}

The captions were generated and PER-LEVEL GATED at caption time (caption_fusion_keeps), so no
re-gating here — but every target assembly re-validates through the Assembly model as a cheap
schema check before it becomes training data (corpus lesson: gate on the shipped artifact).

Out: /workspace/.hf_home/cad_corpus/fusion_pairs.jsonl
Run: cad_pipeline/.venv/bin/python -m training.build_fusion_pairs
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cad_pipeline.assembly import Assembly  # noqa: E402
from cad_pipeline.planner import (_OUTLINE_SCHEMA, _OUTLINE_SYSTEM, _SYSTEM,  # noqa: E402
                                  _asm_schema, dump_for_grammar)

IN = "/workspace/.hf_home/cad_corpus/fusion_joint_assemblies.captioned.jsonl"
# sets promoted to precise PORT exemplars (build_port_pairs) — excluded here so one mechanism
# never teaches both `attach`+raw-coords AND its port rewrite
PORT_SETS = "/workspace/.hf_home/cad_corpus/port_pairs.sets.json"
OUT = "/workspace/.hf_home/cad_corpus/fusion_pairs.jsonl"


def pairs_for(rec: dict) -> list:
    asm = rec["assembly"]
    Assembly(**asm)                                      # schema gate on the shipped artifact
    target = dump_for_grammar(asm, _asm_schema())   # decoder-producible or it is dead weight
    cat = "fusion-" + rec["joint"].replace("JointType", "").lower()
    out = []
    prompts = [("l1", rec["captions"]["l1"]), ("l2", rec["captions"]["l2"]),
               ("l3", rec["captions"]["l3"]), ("name", rec["name"].lower())]
    for lv, cap in prompts:
        out.append({"system": _SYSTEM, "prompt": "input: " + cap, "code": target,
                    "source": "asm-plan-fusion", "category": cat, "prompt_level": lv,
                    "set": rec["set"]})
    listing = "; ".join(
        f"{c['name']} (role {c.get('role', 'other')}, {c['part'].get('shape', 'box')})"
        for c in asm["components"])
    two_stage_user = (f"input: {rec['name'].lower()}\nRealize THIS parts list as the assembly — one component "
                      f"per part with its role, dimensions, and the functional features it needs; "
                      f"connect every part with `mates` (radial/stack/ground/coaxial/flush/mirror), "
                      f"NOT coordinates:\n{listing}")
    out.append({"system": _SYSTEM, "prompt": two_stage_user, "code": target,
                "source": "asm-plan-fusion", "category": cat, "prompt_level": "two_stage"})
    parts = [{"name": c["name"], "role": c.get("role", "other"), "shape": c["part"].get("shape", "box")}
             for c in asm["components"]]
    out.append({"system": _OUTLINE_SYSTEM, "prompt": "object: " + rec["name"].lower(),
                "code": json.dumps({"parts": parts}, separators=(",", ":")),
                "set": rec["set"], "source": "asm-outline-fusion", "category": cat, "prompt_level": "outline"})
    return out


def main() -> int:
    recs = [json.loads(l) for l in open(IN)]
    promoted = set()
    if os.path.exists(PORT_SETS):
        d = json.load(open(PORT_SETS))
        promoted = set(d.get("train", [])) | set(d.get("eval", []))
        before = len(recs)
        recs = [r for r in recs if r["set"] not in promoted]
        print(f"[fusion-pairs] skipped {before - len(recs)} sets promoted to PORT exemplars "
              f"(one mechanism must not teach both attach+coords and its port rewrite)")
    n_ok = n_bad = 0
    with open(OUT, "w") as f:
        for rec in recs:
            try:
                for p in pairs_for(rec):
                    f.write(json.dumps(p) + "\n")
                n_ok += 1
            except Exception as e:  # noqa: BLE001 — one bad record must not poison the set
                n_bad += 1
                print(f"{rec.get('set')}: DROP {type(e).__name__}: {str(e)[:90]}")
    total = sum(1 for _ in open(OUT))
    print(f"\n{n_ok} assemblies → {total} pairs ({n_bad} dropped) → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
