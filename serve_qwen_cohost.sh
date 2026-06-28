#!/bin/bash
# Serve BF16 base + Phase-3 GRPO LoRA on :8002 (OpenAI-compatible) for the frontend test.
# base served as "qwen3.6-27b" (control), adapter as "phase3". eager + offline (tight/flaky box).
export HF_HOME=/workspace/.hf_home
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export VLLM_LOGGING_LEVEL=INFO
exec /home/abdelrahman/MotionLab/serve_venv/bin/vllm serve unsloth/Qwen3.6-27B --revision c7d3d676ae77b6ae969f875aec68ed2daad7118c \
  --served-model-name qwen3.6-27b \
  --enable-lora \
  --max-lora-rank 32 \
  --lora-modules phase3=/workspace/.hf_home/training/phase3/final parser3=/workspace/.hf_home/training/nl_spec_parser_v3/final \
  --port 8002 \
  --max-model-len 12288 \
  --enforce-eager \
  --gpu-memory-utilization 0.65
