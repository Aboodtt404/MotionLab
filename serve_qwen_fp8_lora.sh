#!/bin/bash
# Track A serving, ONLINE-FP8 + LoRA adapters (recipe of record 2026-07-07).
# ~44GB (28G weights via Fp8OnlineLinearMethod + KV) — leaves Track B's 42G beside it.
# 0.38 util OOMs the KV cache; 0.45 is the floor at 12k ctx.
export HF_HOME=/workspace/.hf_home
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export VLLM_LOGGING_LEVEL=INFO
exec /home/abdelrahman/MotionLab/serve_venv/bin/vllm serve unsloth/Qwen3.6-27B --revision c7d3d676ae77b6ae969f875aec68ed2daad7118c \
  --served-model-name qwen3.6-27b \
  --quantization fp8 \
  --enable-lora --max-lora-rank 32 \
  --lora-modules phase23=/workspace/.hf_home/training/phase23/final phase21b=/workspace/.hf_home/training/phase21b/final parser3=/workspace/.hf_home/training/nl_spec_parser_v3/final \
  --port 8002 \
  --max-model-len 12288 \
  --enforce-eager \
  --gpu-memory-utilization 0.42
