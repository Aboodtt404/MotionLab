"""Merge the Phase-2 QLoRA adapter into the BF16 base via peft merge_and_unload.

Uses peft (NOT unsloth save_pretrained_merged) on purpose: unsloth's 16-bit merge silently
drops the LoRA for VISION models (unsloth #1352) and re-downloads the base (#3633). peft's
merge is transparent and works on VLMs. Includes a HARD CHECK that the merge actually applied
(language q_proj weights must change) — aborts if not, so we never serve a base-only "merge".

Run:  HF_HOME=/workspace/.hf_home serve_venv/bin/python training/merge_lora.py
Output: /workspace/.hf_home/phase2_merged  (standalone — serve in vLLM with NO --enable-lora)
"""
import os
import shutil
import sys

os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import torch  # noqa: E402
from peft import PeftModel  # noqa: E402

BASE = "unsloth/Qwen3.6-27B"
ADAPTER = "/workspace/.hf_home/training/phase2/final"
OUT = "/workspace/.hf_home/phase2_merged"


def load_base():
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText
    last = None
    for cls in (AutoModelForImageTextToText, AutoModelForCausalLM):
        try:
            print(f"[merge] loading base via {cls.__name__} (bf16) ...", flush=True)
            return cls.from_pretrained(BASE, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {cls.__name__} failed: {type(e).__name__}: {str(e)[:140]}", flush=True)
            last = e
    raise last


base = load_base()

# snapshot a few LANGUAGE-tower q_proj weights (LoRA target) to prove the merge applied
snap = {}
for n, p in base.named_parameters():
    if n.endswith("q_proj.weight") and not any(k in n.lower() for k in ("visual", "vision", "vit")):
        snap[n] = p.detach().to(torch.float32).clone()
        if len(snap) >= 5:
            break
assert snap, "no language q_proj weights found — naming assumption wrong, inspect model"
print(f"[merge] snapshotted {len(snap)} language q_proj weights for the merge-applied check", flush=True)

print("[merge] attaching adapter + merge_and_unload ...", flush=True)
merged = PeftModel.from_pretrained(base, ADAPTER).merge_and_unload()

post = dict(merged.named_parameters())
maxd = max((post[n].detach().to(torch.float32) - w).abs().max().item() for n, w in snap.items())
print(f"[merge] MERGE CHECK: max|delta| over {len(snap)} target weights = {maxd:.6e}", flush=True)
if maxd < 1e-6:
    print("[merge] FAIL — LoRA did NOT merge (weights unchanged). Aborting, NOT saving a base-only model.", flush=True)
    sys.exit(1)
print("[merge] APPLIED ✓ (the fine-tune is in the merged weights)", flush=True)

print(f"[merge] saving merged model → {OUT} ...", flush=True)
os.makedirs(OUT, exist_ok=True)
merged.save_pretrained(OUT, safe_serialization=True)
# tokenizer / processor / chat template come from the adapter dir (identical to base, already local)
for f in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "processor_config.json",
          "special_tokens_map.json", "vocab.json", "merges.txt", "preprocessor_config.json"):
    src = os.path.join(ADAPTER, f)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(OUT, f))
print(f"[merge] DONE → {OUT}", flush=True)
