"""Build the NL→spec SFT corpus for the dedicated parser fine-tune (research Stage 2).

Source = targeted_pilot.jsonl, which already carries multi-level NL prompts (l0 terse → l3 detailed)
paired with the canonical Spec (Text2CAD-style multi-level annotation). We emit one {prompt, code}
row per (spec × level) so train_sft.py --mode instruct can consume it unchanged (user=prompt,
assistant=the compact spec JSON). A concise schema hint is prepended so the model has the shape
vocabulary without the giant few-shot block — the fine-tune internalizes the mapping (the latency win).

Run:  cad_pipeline/.venv/bin/python training/build_nl_spec.py
Out:  /workspace/.hf_home/cad_corpus/nl_spec_sft.jsonl
"""
import json
import os

SRC = "/workspace/.hf_home/cad_corpus/targeted_pilot.jsonl"
OUT = "/workspace/.hf_home/cad_corpus/nl_spec_sft.jsonl"

# concise schema hint — single source of truth in cad_pipeline.nl_spec (training == inference).
import sys as _sys
_sys.path.insert(0, "/home/abdelrahman/MotionLab")
from cad_pipeline.nl_spec import PARSER_HINT as HINT

KEEP = ("object", "shape", "envelope", "profile", "path", "features", "tolerance")

def compact(spec: dict) -> dict:
    """Drop always-default/derived fields so the target JSON is clean and minimal."""
    out = {k: spec[k] for k in KEEP if k in spec and spec[k] not in (None, [], {})}
    out.setdefault("features", spec.get("features", []))
    out.setdefault("tolerance", spec.get("tolerance", 0.1))
    return out

def main():
    n = 0
    with open(OUT, "w") as w:
        for line in open(SRC):
            r = json.loads(line)
            spec_json = json.dumps(compact(r["spec"]), separators=(",", ":"))
            for level, nl in sorted(r.get("prompts", {}).items()):   # l1..l3 (skip l0)
                if not nl or level == "l0":   # l0 is a 2-word object name — too sparse to fix a spec
                    continue
                w.write(json.dumps({"prompt": HINT + nl.strip(), "code": spec_json,
                                    "level": level, "shape": r["spec"]["shape"]}) + "\n")
                n += 1
    print(f"wrote {n} NL→spec pairs -> {OUT}")
    # report shape balance
    from collections import Counter
    c = Counter(json.loads(l)["shape"] for l in open(OUT))
    print("shape balance:", dict(c))

if __name__ == "__main__":
    main()
