"""QLoRA SFT for the Track A CadQuery model (3-phase plan, track-a-corpus-scope §5b).

Resumable by construction: checkpoints every `save_steps`; on restart it auto-resumes from the last
checkpoint against the FIXED local JSONL corpus (so a VPS stop mid-run loses at most `save_steps`).

Modes:
  fluency  — Phase 1: causal-LM on RAW CadQuery code (no prompt). Teaches syntax/vocabulary at scale
             (Zero-to-CAD 1M, already exec/validity-gated by Autodesk).
  instruct — Phase 2: prompt → code (chat-formatted). Teaches text→CadQuery behavior
             (verifier-gated CAD-Coder + our targeted sci-fi/robotics layer).

Run (after the base + data are on disk):
  serve_venv/bin/python training/train_sft.py --mode fluency \
      --data /workspace/.hf_home/cad_corpus/zerocad.jsonl --out /workspace/.hf_home/training/phase1
"""
import argparse
import glob
import os

os.environ.setdefault("HF_HOME", "/workspace/.hf_home")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fluency", "instruct"], required=True)
    ap.add_argument("--data", required=True)                       # fixed local JSONL
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="unsloth/Qwen3.6-27B")
    ap.add_argument("--max_seq", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max_steps", type=int, default=-1)           # -1 = use epochs; >0 for a smoke run
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--bsz", type=int, default=2)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--save_steps", type=int, default=500)
    ap.add_argument("--grad_ckpt", default="unsloth", choices=["unsloth", "true", "false"])  # false = use spare VRAM, skip recompute/offload
    a = ap.parse_args()

    from unsloth import FastLanguageModel
    from datasets import load_dataset
    from trl import SFTTrainer, SFTConfig

    model, tok = FastLanguageModel.from_pretrained(a.base, max_seq_length=a.max_seq, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=32, lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing={"unsloth": "unsloth", "true": True, "false": False}[a.grad_ckpt], random_state=42)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    ds = load_dataset("json", data_files=a.data, split="train")
    if a.mode == "fluency":
        ds = ds.map(lambda r: {"text": r["code"]})                # raw code, causal LM
    else:
        def fmt(r):
            msgs = [{"role": "user", "content": r["prompt"]}, {"role": "assistant", "content": r["code"]}]
            return {"text": tok.apply_chat_template(msgs, tokenize=False)}
        ds = ds.map(fmt)

    cfg = SFTConfig(
        output_dir=a.out, dataset_text_field="text", max_seq_length=a.max_seq,
        per_device_train_batch_size=a.bsz, gradient_accumulation_steps=a.grad_accum,
        num_train_epochs=a.epochs, max_steps=a.max_steps, learning_rate=a.lr, warmup_ratio=0.03,
        logging_steps=20, save_steps=a.save_steps, save_total_limit=3,
        bf16=True, optim="adamw_8bit", lr_scheduler_type="cosine", report_to="none",
        dataset_num_proc=4,
        # pack short CadQuery programs into full-length sequences — ~5× throughput for fluency
        # (a 1M epoch goes from weeks → single-digit hours). Instruct mode keeps per-example loss.
        packing=(a.mode == "fluency"),
    )
    trainer = SFTTrainer(model=model, tokenizer=tok, train_dataset=ds, args=cfg)

    resume = bool(glob.glob(f"{a.out}/checkpoint-*"))             # auto-resume after a crash
    print(f"[train] mode={a.mode} rows={len(ds)} resume={resume} out={a.out}", flush=True)
    trainer.train(resume_from_checkpoint=resume)
    model.save_pretrained(f"{a.out}/final"); tok.save_pretrained(f"{a.out}/final")
    print(f"[train] DONE → {a.out}/final", flush=True)


if __name__ == "__main__":
    main()
