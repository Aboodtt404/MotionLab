"""Step 1 (cad_pipeline/.venv): build all eval prompts (full eval_vocab in+ood, no-RAG and RAG)
and dump to JSONL. Runs where cadquery/rag/eval_vocab import cleanly. The serve_venv generator then
consumes this without importing any cad_pipeline machinery.

Run:  cad_pipeline/.venv/bin/python training/eval_grpo_prompts.py
Out:  /tmp/grpo_ab.prompts.jsonl  (dist,cap,level,rag,spec,messages)
"""
from __future__ import annotations
import sys, json
sys.path.insert(0, ".")
from cad_pipeline.loop import VLLMGenerator
from cad_pipeline.rag import reference_block
from cad_pipeline.tests.eval_vocab import EVAL_IN, EVAL_OOD

CASES = [("in", c) for c in EVAL_IN] + [("ood", c) for c in EVAL_OOD]
SYSTEM = VLLMGenerator.SYSTEM


def build(spec, rag):
    user = f"Build this part as CadQuery, assigning the solid to `result`:\n{spec.model_dump_json(indent=2)}"
    if rag:
        ref = reference_block(spec)
        if ref:
            user += f"\n\n{ref}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


out = "/tmp/grpo_ab.prompts.jsonl"
with open(out, "w") as f:
    for rag in (False, True):
        for dist, c in CASES:
            f.write(json.dumps({"dist": dist, "cap": c.cap, "level": c.level, "rag": rag,
                                "spec": c.spec.model_dump(), "messages": build(c.spec, rag)}) + "\n")
print(f"SAVED {len(CASES)*2} prompts -> {out}")
