"""Step 2 (serve_venv): batch-generate one single-shot completion per prompt. NO cad_pipeline
imports (serve_venv has no cadquery) — _extract_code is inlined. Thinking OFF + greedy.

Run:  serve_venv/bin/python training/eval_grpo_gen.py <adapter_path> <label>
In:   /tmp/grpo_ab.prompts.jsonl     Out: /tmp/grpo_ab_<label>.completions.jsonl
"""
from __future__ import annotations
import os, sys, json, re
os.environ.setdefault("HF_HUB_OFFLINE", "1"); os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

ADAPTER = sys.argv[1]
LABEL = sys.argv[2] if len(sys.argv) > 2 else "model"
PROMPTS = "/tmp/grpo_ab.prompts.jsonl"


def extract_code(txt):  # mirrors cad_pipeline.loop.VLLMGenerator._extract_code
    if "</think>" in txt:
        txt = txt.rsplit("</think>", 1)[1]
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    closed = re.findall(r"```(?:python)?\s*(.*?)```", txt, re.S)
    if closed:
        return closed[-1].strip()
    op = re.search(r"```(?:python)?\s*(.*)$", txt, re.S)
    if op:
        return op.group(1).strip()
    i = txt.find("import cadquery")
    return (txt[i:] if i != -1 else txt).strip()


rows = [json.loads(l) for l in open(PROMPTS)]

from unsloth import FastLanguageModel
import torch
model, tok = FastLanguageModel.from_pretrained(ADAPTER, max_seq_length=4096, load_in_4bit=True)
FastLanguageModel.for_inference(model)
tk = getattr(tok, "tokenizer", tok)
if tk.pad_token_id is None:
    tk.pad_token = tk.eos_token
tk.padding_side = "left"


def gen_batch(messages_list, chunk=8, max_new=1024):
    outs = []
    for i in range(0, len(messages_list), chunk):
        texts = [tok.apply_chat_template(m, tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False) for m in messages_list[i:i + chunk]]
        ids = tk(texts, return_tensors="pt", padding=True).to(model.device)
        with torch.no_grad():
            g = model.generate(**ids, max_new_tokens=max_new, do_sample=False,
                               pad_token_id=tk.pad_token_id)
        g = g[:, ids["input_ids"].shape[1]:]
        outs += [extract_code(tk.decode(x, skip_special_tokens=True)) for x in g]
        print(f"  ...{min(i+chunk,len(messages_list))}/{len(messages_list)}", flush=True)
    return outs


print(f"[{LABEL}] generating {len(rows)} completions...", flush=True)
codes = gen_batch([r["messages"] for r in rows])
out = f"/tmp/grpo_ab_{LABEL}.completions.jsonl"
with open(out, "w") as f:
    for r, code in zip(rows, codes):
        f.write(json.dumps({"dist": r["dist"], "cap": r["cap"], "level": r["level"],
                            "rag": r["rag"], "spec": r["spec"], "code": code}) + "\n")
print(f"SAVED -> {out}")
