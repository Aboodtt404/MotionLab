"""Phase-3 GRPO — verifier-gated RL for the Track A CadQuery model (track-a-finetuning.md §3-4).

Init from the Phase-2 SFT checkpoint (SFT→CoT→RL ordering is non-negotiable per CAD-Coder).
The reward is OUR deterministic feature-level verifier via the subprocess bridge
(`cad_pipeline.reward`) — a STRONGER signal than the Chamfer/IoU proxies the field uses, and the
documented edge. Trains WITHOUT RAG on purpose: the verifier reward teaches the conventions into
the weights (attacking the no-RAG 44% gap), and prompt-building then needs no cadquery in serve_venv.

NOT runnable on the current box — gated on the throughput rework (see track-a-phase3-grpo-plan.md
§2a: GRPO does k=8 rollouts × thousands of steps; at ~28 tok/s that's ~1-2 weeks). Author now, run
after the kernel/torch fix. Reward is a subprocess so it runs in cad_pipeline/.venv (cadquery).

Run (AFTER the throughput rework):
  serve_venv/bin/python training/train_grpo.py --init /workspace/.hf_home/training/phase2/final \
      --data /workspace/.hf_home/cad_corpus/targeted_pilot.jsonl --out /workspace/.hf_home/training/phase3
"""
import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("HF_HUB_OFFLINE", "1")          # the box's HF is flaky (telemetry-crash guard)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

REPO = "/home/abdelrahman/MotionLab"
REWARD_BRIDGE = [f"{REPO}/cad_pipeline/.venv/bin/python", "-m", "cad_pipeline.reward"]

# Mirrors cad_pipeline.loop.VLLMGenerator.SYSTEM minus the "retrieved reference" clause (we train
# no-RAG). Inlined because cad_pipeline imports cadquery, absent in serve_venv.
SYSTEM = (
    "You are a CAD engineer who writes CadQuery (Python). Think through the 6-stage method "
    "(decompose -> workplane/frame -> base profile -> features -> operation order -> units) INSIDE a "
    "<think>...</think> block. After </think>, output ONLY the final program as a single ```python "
    "code block - NO prose outside the block. The program must `import cadquery as cq` and assign the "
    "final solid to a variable named `result`. `.box(L,W,H)` is centered at the origin; Z-hole via "
    "`.faces('>Z').workplane().hole(d)`; MULTIPLE holes via one "
    "`.faces('>Z').workplane().pushPoints([(x1,y1),...]).hole(d)` (absolute, origin=part center); "
    "fillet/chamfer vertical edges via `.edges('|Z').fillet(r)` / `.chamfer(d)`."
)


def _reward_one(output: str, spec: dict) -> float:
    """One reward via the cad_pipeline subprocess bridge (exec + deterministic verify)."""
    try:
        p = subprocess.run(REWARD_BRIDGE, input=json.dumps({"output": output, "spec": spec}),
                           capture_output=True, text=True, timeout=120, cwd=REPO)
        return float(json.loads(p.stdout.strip().splitlines()[-1])["reward"])
    except Exception:  # noqa: BLE001 — a failed reward call must not kill the step
        return 0.0


def _as_text(c):
    return c if isinstance(c, str) else (c[-1]["content"] if isinstance(c, list) else str(c))


def make_reward_fn(workers: int):
    def cad_reward(completions, spec, **_):
        outs = [_as_text(c) for c in completions]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(lambda a: _reward_one(*a), zip(outs, spec)))
    cad_reward.__name__ = "verifier_reward"
    return cad_reward


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", required=True, help="Phase-2 SFT checkpoint dir (continue its LoRA)")
    ap.add_argument("--data", required=True, help="JSONL prompt pool; each line needs a 'spec' dict")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max_seq", type=int, default=4096)
    ap.add_argument("--max_completion", type=int, default=1024)  # no-think terminates ~270 tok; headroom
    ap.add_argument("--k", type=int, default=8)              # num generations / group (CAD-Coder)
    ap.add_argument("--lr", type=float, default=1e-6)        # RL-LR (§4)
    ap.add_argument("--beta", type=float, default=0.001)     # KL coeff (§4); GSPO fallback => 0
    ap.add_argument("--bsz", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--max_steps", type=int, default=-1)
    ap.add_argument("--save_steps", type=int, default=100)
    ap.add_argument("--reward_workers", type=int, default=8)
    a = ap.parse_args()

    # --- shim trl 0.24 ↔ vLLM 0.19.1 (lets the unsloth-blessed stack run GRPO on Blackwell) ---
    # (1) vLLM renamed GuidedDecodingParams -> StructuredOutputsParams; trl 0.24 still imports the
    #     old name (only in RLOO/DPO/serve paths — GRPO doesn't use guided decoding).
    # (2) trl 0.24's is_*_available() return truthy (avail, version) TUPLES, so it eagerly imports
    #     every optional dep (vllm_ascend, mergekit, ...) and crashes. Coerce the flags to bools.
    import vllm.sampling_params as _sp
    if not hasattr(_sp, "GuidedDecodingParams") and hasattr(_sp, "StructuredOutputsParams"):
        _sp.GuidedDecodingParams = _sp.StructuredOutputsParams
    import trl.import_utils as _iu
    for _n in dir(_iu):
        if _n.endswith("_available") and isinstance(getattr(_iu, _n), tuple):
            setattr(_iu, _n, getattr(_iu, _n)[0])
    # ---------------------------------------------------------------------------------------------
    from unsloth import FastLanguageModel
    from datasets import load_dataset
    from trl import GRPOConfig, GRPOTrainer

    # init from the Phase-2 adapter (unsloth loads base+adapter). NOTE: unsloth fast_inference does
    # NOT support this VLM (siglip+qwen3_5), so rollouts use HF-generate (use_vllm=False below).
    # vLLM-accelerated rollouts = a later optimization via trl server-mode against an external
    # vLLM 0.19.1 (which DOES serve this model at ~180 tok/s batched).
    model, tok = FastLanguageModel.from_pretrained(
        a.init, max_seq_length=a.max_seq, load_in_4bit=True)
    # --init is the Phase-2 LoRA adapter → from_pretrained already attached it. Don't re-add a LoRA;
    # just continue training THIS adapter (the SFT→RL ordering). Ensure it's in trainable mode.
    FastLanguageModel.for_training(model)
    for _n, _p in model.named_parameters():
        if "lora" in _n.lower():
            _p.requires_grad_(True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    ds = load_dataset("json", data_files=a.data, split="train")

    def to_prompt(r):
        spec = r["spec"]
        user = ("Build this part as CadQuery, assigning the solid to `result`:\n"
                + json.dumps(spec, indent=2))
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        # PRE-TEMPLATE with thinking OFF. Default qwen3.6 template leaves reasoning ON → rollouts
        # ramble for the whole budget, never terminate, never parse → exec-gate → reward 0 on every
        # rollout (smoke: frac_reward_zero_std=1). no-think drops completions ~1024→~270 tok and
        # lifts the in-group pass rate ~5%→~33% (the variance GRPO needs). Passing a STRING prompt
        # makes trl skip its own templating, so this enable_thinking=False is preserved.
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)
        return {"prompt": prompt, "spec": spec}
    ds = ds.map(to_prompt, remove_columns=[c for c in ds.column_names if c not in ("spec",)])

    cfg = GRPOConfig(
        output_dir=a.out, num_generations=a.k, learning_rate=a.lr, beta=a.beta,
        per_device_train_batch_size=a.bsz, gradient_accumulation_steps=a.grad_accum,
        max_prompt_length=a.max_seq - a.max_completion, max_completion_length=a.max_completion,
        temperature=0.7, top_p=0.95, max_steps=a.max_steps, save_steps=a.save_steps, save_total_limit=3,
        logging_steps=10, bf16=True, optim="adamw_8bit", lr_scheduler_type="cosine", warmup_ratio=0.03,
        report_to="none", use_vllm=False,   # HF-generate rollouts (pilot); vLLM server-mode = later speed-up
        # §4 add-ons to wire when stable: DAPO Dynamic-Sampling (drop all-tie groups) + Clip-Higher;
        # GSPO fallback (sequence-level, clip ~3e-4/4e-4, beta=0) if GRPO is unstable at 27B;
        # Precision-Token-Loss (up-weight dim/selector tokens). Track IR (reward 'exec' rate) every
        # checkpoint for the CAD-Coder ~200-step executability-collapse signature.
    )
    trainer = GRPOTrainer(model=model, processing_class=tok, args=cfg,
                          reward_funcs=[make_reward_fn(a.reward_workers)], train_dataset=ds)

    import glob
    resume = bool(glob.glob(f"{a.out}/checkpoint-*"))
    print(f"[grpo] init={a.init} rows={len(ds)} k={a.k} resume={resume} out={a.out}", flush=True)
    trainer.train(resume_from_checkpoint=resume)
    model.save_pretrained(f"{a.out}/final"); tok.save_pretrained(f"{a.out}/final")
    print(f"[grpo] DONE -> {a.out}/final", flush=True)


if __name__ == "__main__":
    main()
