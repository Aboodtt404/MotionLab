"""GRPO for the ASSEMBLY planner — shaped verifier reward (cad_pipeline.asm_reward).

The measured warning this file exists to heed (assembly-placement research, arXiv:2606.31252):
GRPO with a BINARY solver reward stalled (93.1→93.2%) — 68.3% of groups had identical rewards.
The shaped reward grades severity (verifier-row fraction + island count + interference decay),
so a group of 8 rollouts with different flaws carries gradient. Reward masking still applies:
non-JSON → 0.

Prompts: briefs from the SFT mix (production format), but the SYSTEM prompt comes from
--system_file — export the CURRENT deployed grammar first so RL optimizes the policy the
server actually runs (including the port/fraction dialects the SFT never saw):

  cad_pipeline/.venv/bin/python -c "from cad_pipeline.planner import _SYSTEM; print(_SYSTEM)" \
      > /workspace/.hf_home/cad_corpus/asm_system_current.txt

Run (trainer python is serve_venv/bin/python — the GRPO shims target ITS trl/vllm stack):
  serve_venv/bin/python training/train_grpo_asm.py \
      --init /workspace/.hf_home/adapters/asm3 \
      --data /workspace/.hf_home/cad_corpus/asm_sft_mix_v2.jsonl \
      --system_file /workspace/.hf_home/cad_corpus/asm_system_current.txt \
      --out /workspace/.hf_home/training/asm3_grpo
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

# env-overridable so the SAME script runs on rented boxes (vast offload): ASM_REPO = repo root
# (cwd for the bridge), REWARD_PY = the cadquery venv's python there.
REPO = os.environ.get("ASM_REPO", "/home/abdelrahman/MotionLab")
REWARD_BRIDGE = [os.environ.get("REWARD_PY", f"{REPO}/cad_pipeline/.venv/bin/python"),
                 "-m", "cad_pipeline.asm_reward"]


def _reward_one(output: str) -> float:
    try:
        p = subprocess.run(REWARD_BRIDGE, input=json.dumps({"output": output}),
                           capture_output=True, text=True, timeout=180, cwd=REPO)
        return float(json.loads(p.stdout.strip().splitlines()[-1])["reward"])
    except Exception:  # noqa: BLE001 — a failed reward call must not kill the step
        return 0.0


def _as_text(c):
    return c if isinstance(c, str) else c[-1]["content"]


def make_reward_fn(workers: int):
    def asm_reward(completions, **_):
        outs = [_as_text(c) for c in completions]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_reward_one, outs))
    asm_reward.__name__ = "shaped_assembly_reward"
    return asm_reward


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", required=True, help="asm SFT adapter dir (continue its LoRA)")
    ap.add_argument("--data", required=True, help="asm SFT mix JSONL (prompts reused; completions ignored)")
    ap.add_argument("--system_file", required=True, help="CURRENT deployed grammar (see module docstring)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max_seq", type=int, default=4608)
    ap.add_argument("--max_completion", type=int, default=2048)   # assemblies are long JSON
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-6)
    ap.add_argument("--beta", type=float, default=0.001)
    ap.add_argument("--bsz", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--max_steps", type=int, default=-1)
    ap.add_argument("--save_steps", type=int, default=50)
    ap.add_argument("--reward_workers", type=int, default=8)
    ap.add_argument("--log_every", type=int, default=10)   # smoke sets 1 so the reward gate has data
    # colocated-vLLM rollouts (unsloth fast_inference): the model is loaded ONCE, shared by
    # trainer and engine — the single-GPU fit for a 32 GB card AND the fix for the 407 s/it
    # HF-generate rollouts measured in the local smoke. Off by default: the local banked
    # command ran (and smoked green) without it.
    ap.add_argument("--fast_inference", action="store_true")
    ap.add_argument("--gpu_mem_util", type=float, default=0.55, help="vLLM share w/ --fast_inference")
    # multi-GPU fallback (vast 2x32GB lesson): unsloth is single-GPU and its VLM generate patch
    # REQUIRES the compiled path, whose fused-CE kernel preallocates a fixed ~2.4GB workspace --
    # a 27B QLoRA GRPO step cannot fit one 32GB card. Plain transformers shards the 4-bit model
    # across every visible GPU (device_map) with peft on top; slower per token, but the full
    # science config (k=8, 2048-token completions) fits with room to spare.
    ap.add_argument("--plain_hf", action="store_true")
    a = ap.parse_args()

    # --- shim trl 0.24 ↔ vLLM 0.19.1 (identical to train_grpo.py; see [[grpo-runtime-shims]]) ---
    import vllm.sampling_params as _sp
    if not hasattr(_sp, "GuidedDecodingParams") and hasattr(_sp, "StructuredOutputsParams"):
        _sp.GuidedDecodingParams = _sp.StructuredOutputsParams
    import trl.import_utils as _iu
    for _n in dir(_iu):
        if _n.endswith("_available") and isinstance(getattr(_iu, _n), tuple):
            setattr(_iu, _n, getattr(_iu, _n)[0])
    # ---------------------------------------------------------------------------------------------
    from datasets import load_dataset
    from trl import GRPOConfig, GRPOTrainer

    if a.plain_hf:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from peft import PeftModel
        base = json.load(open(f"{a.init}/adapter_config.json"))["base_model_name_or_path"]
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=torch.bfloat16,
                                 bnb_4bit_use_double_quant=True)
        tok = AutoTokenizer.from_pretrained(a.init)
        try:
            model = AutoModelForCausalLM.from_pretrained(
                base, quantization_config=bnb, device_map="balanced",
                dtype=torch.bfloat16, attn_implementation="sdpa")
        except ValueError:   # VLM checkpoint -- the causal-LM auto class refuses the architecture
            from transformers import AutoModelForImageTextToText
            model = AutoModelForImageTextToText.from_pretrained(
                base, quantization_config=bnb, device_map="balanced",
                dtype=torch.bfloat16, attn_implementation="sdpa")
        model = PeftModel.from_pretrained(model, a.init, is_trainable=True)
        model.enable_input_require_grads()
        model.config.use_cache = False
        # trl's Trainer pokes PreTrainedModel bookkeeping attrs the peft delegation chain
        # can't find on this arch — provide them (observed live: warnings_issued)
        for _attr, _default in (("warnings_issued", {}), ("model_tags", [])):
            try:
                getattr(model, _attr)
            except AttributeError:
                setattr(model, _attr, _default)
        if not hasattr(model, "add_model_tags"):
            model.add_model_tags = lambda *args, **kw: None
    else:
        from unsloth import FastLanguageModel
        kw = dict(fast_inference=True, gpu_memory_utilization=a.gpu_mem_util) if a.fast_inference else {}
        model, tok = FastLanguageModel.from_pretrained(
            a.init, max_seq_length=a.max_seq, load_in_4bit=True, **kw)
        FastLanguageModel.for_training(model)
    for _n, _p in model.named_parameters():
        if "lora" in _n.lower():
            _p.requires_grad_(True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    system = open(a.system_file).read().strip()
    ds = load_dataset("json", data_files=a.data, split="train")
    # assembly rows only — the general-code anti-forgetting slice has non-assembly completions,
    # and the shaped reward would mask them all to 0 (an all-tie group teaches nothing).
    ds = ds.filter(lambda r: str(r.get("code", "")).lstrip().startswith("{"))

    def to_prompt(r):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": r["prompt"]}]
        # PRE-TEMPLATE with thinking OFF (train_grpo.py lesson: default template leaves reasoning
        # ON → rollouts ramble the whole budget → nothing parses → all-zero reward groups).
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)
        return {"prompt": prompt}
    ds = ds.map(to_prompt, remove_columns=[c for c in ds.column_names if c != "prompt"])

    cfg = GRPOConfig(
        output_dir=a.out, num_generations=a.k, learning_rate=a.lr, beta=a.beta,
        per_device_train_batch_size=a.bsz, gradient_accumulation_steps=a.grad_accum,
        max_prompt_length=a.max_seq - a.max_completion, max_completion_length=a.max_completion,
        temperature=0.7, top_p=0.95, max_steps=a.max_steps, save_steps=a.save_steps,
        save_total_limit=3, logging_steps=a.log_every, bf16=True, optim="adamw_8bit",
        lr_scheduler_type="cosine", warmup_ratio=0.03, report_to="none",
        use_vllm=a.fast_inference, vllm_mode="colocate")   # mode ignored when use_vllm=False
    trainer = GRPOTrainer(model=model, processing_class=tok, args=cfg,
                          reward_funcs=[make_reward_fn(a.reward_workers)], train_dataset=ds)

    import glob
    resume = bool(glob.glob(f"{a.out}/checkpoint-*"))
    print(f"[grpo-asm] init={a.init} rows={len(ds)} k={a.k} resume={resume} out={a.out}", flush=True)
    trainer.train(resume_from_checkpoint=resume)
    model.save_pretrained(f"{a.out}/final"); tok.save_pretrained(f"{a.out}/final")
    print(f"[grpo-asm] DONE -> {a.out}/final", flush=True)


if __name__ == "__main__":
    main()
