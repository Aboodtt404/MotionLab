#!/bin/bash
# Track A serving, ONLINE-FP8 + LoRA adapters (recipe of record 2026-07-07).
# ASSEMBLY LANE (2026-07-15): PLAN_MODEL=asm2 (1-epoch champion, eval 5/10 + first repair
#   rescue + honest enclosure pass; served from the PROTECTED copy in adapters/ — never point
#   at a trainer output dir, rotation deletes checkpoints and a dead adapter path crashes the
#   engine). asm1 (2-epoch, 4/10) kept as fallback.
# ~44GB (28G weights via Fp8OnlineLinearMethod + KV) — leaves Track B's 42G beside it.
# 0.38 util OOMs the KV cache; 0.45 is the floor at 12k ctx.
export HF_HOME=/workspace/.hf_home
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export VLLM_LOGGING_LEVEL=INFO
# hot-load LoRA checkpoints without a restart (asm1 mid-training evals):
#   POST :8002/v1/load_lora_adapter {"lora_name": "...", "lora_path": "..."}
export VLLM_ALLOW_RUNTIME_LORA_UPDATING=1
exec /home/abdelrahman/MotionLab/serve_venv/bin/vllm serve unsloth/Qwen3.6-27B --revision c7d3d676ae77b6ae969f875aec68ed2daad7118c \
  --served-model-name qwen3.6-27b \
  --quantization fp8 \
  --enable-lora --max-lora-rank 32 \
  --lora-modules phase23=/workspace/.hf_home/training/phase23/final phase21b=/workspace/.hf_home/training/phase21b/final parser3=/workspace/.hf_home/training/nl_spec_parser_v3/final asm1=/workspace/.hf_home/training/asm1/final asm2=/workspace/.hf_home/adapters/asm2 asm3=/workspace/.hf_home/adapters/asm3 \
  --port 8002 \
  --max-model-len 12288 \
  --enforce-eager \
  --gpu-memory-utilization 0.42
