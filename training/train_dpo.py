"""DPO stage (fable_run/out/03_training_recipe.md §4: the cheap middle step, SFT→DPO→GRPO).
Continue the Phase-2 NL→code SFT adapter with preference pairs (chosen = verified-correct code,
rejected = same-spec perturbed-wrong code — training/build_dpo_pairs.py). QLoRA, unsloth, trl 0.24.

Run (serve_venv, trl 0.24 — do NOT upgrade trl/torch):
  HF_HUB_OFFLINE=1 serve_venv/bin/python training/train_dpo.py \
    --init /workspace/.hf_home/training/phase2/final \
    --data /workspace/.hf_home/cad_corpus/dpo_pairs.jsonl \
    --out /workspace/.hf_home/training/phase_dpo
"""
import argparse
import os

os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from unsloth import FastLanguageModel, PatchDPOTrainer   # unsloth first, then patch DPO

PatchDPOTrainer()

from datasets import load_dataset   # noqa: E402
from trl import DPOConfig, DPOTrainer   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="/workspace/.hf_home/training/phase2/final")   # the NL→code SFT adapter
    ap.add_argument("--data", default="/workspace/.hf_home/cad_corpus/dpo_pairs.jsonl")
    ap.add_argument("--out", default="/workspace/.hf_home/training/phase_dpo")
    ap.add_argument("--max_seq", type=int, default=4096)
    ap.add_argument("--max_prompt", type=int, default=1024)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=5e-6)
    ap.add_argument("--bsz", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--save_steps", type=int, default=50)
    a = ap.parse_args()

    # base + Phase-2 SFT adapter (QLoRA 4-bit); continue THIS adapter (SFT→DPO ordering)
    model, tok = FastLanguageModel.from_pretrained(a.init, max_seq_length=a.max_seq, load_in_4bit=True)
    FastLanguageModel.for_training(model)
    for n, p in model.named_parameters():
        if "lora" in n.lower():
            p.requires_grad_(True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    ds = load_dataset("json", data_files=a.data, split="train")

    def fmt(r):   # SFT instruct format (train_sft.py): user(NL) → assistant(code); prompt is templated
        prompt = tok.apply_chat_template([{"role": "user", "content": r["prompt"]}],
                                         tokenize=False, add_generation_prompt=True)
        return {"prompt": prompt, "chosen": r["chosen"], "rejected": r["rejected"]}
    ds = ds.map(fmt, remove_columns=[c for c in ds.column_names if c not in ("prompt", "chosen", "rejected")])

    cfg = DPOConfig(
        output_dir=a.out, beta=a.beta, learning_rate=a.lr,
        per_device_train_batch_size=a.bsz, gradient_accumulation_steps=a.grad_accum,
        num_train_epochs=a.epochs, max_length=a.max_seq, max_prompt_length=a.max_prompt,
        logging_steps=10, save_steps=a.save_steps, save_total_limit=3,
        bf16=True, optim="adamw_8bit", lr_scheduler_type="cosine", warmup_ratio=0.05,
        report_to="none",
    )
    trainer = DPOTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok)

    import glob
    resume = bool(glob.glob(f"{a.out}/checkpoint-*"))
    print(f"[dpo] init={a.init} pairs={len(ds)} beta={a.beta} epochs={a.epochs} resume={resume} out={a.out}",
          flush=True)
    trainer.train(resume_from_checkpoint=resume)
    model.save_pretrained(f"{a.out}/final"); tok.save_pretrained(f"{a.out}/final")
    print(f"[dpo] DONE -> {a.out}/final", flush=True)


if __name__ == "__main__":
    main()
