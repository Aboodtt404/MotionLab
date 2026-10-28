#!/usr/bin/env bash
# Overnight feature-program SFT (scheduled for ~23:00 UTC). Sequence:
#   kill OUR vLLM (:8002, frees ~42 GB) → re-filter the day's grown textcad corpus (≤4k tokens)
#   → QLoRA train (fresh out dir — the corpus changed since the aborted daytime run)
#   → restart vLLM so the morning box is back to serving.
# Never touches other users' GPU processes (pgrep is user- and command-scoped).
set -u
cd /home/abdelrahman/MotionLab
mkdir -p /workspace/.hf_home/training
LOG=/workspace/.hf_home/training/overnight_sft.log
exec >> "$LOG" 2>&1
echo "=== overnight SFT start $(date -u) ==="

# 1) stop OUR vLLM by exact PID (launcher + engine). Pattern can't match this script's own cmdline.
for pid in $(pgrep -u "$(whoami)" -f "vllm serve unsloth/Qwen3.6-27B" || true); do
  echo "killing vllm pid $pid"
  kill -9 "$pid" 2>/dev/null || true
done
sleep 20
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

# 2) re-filter the (grown) captioned corpus to <=4000 tokens — truncated JSON targets teach garbage
HF_HUB_OFFLINE=1 serve_venv/bin/python - <<'EOF'
import json
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("unsloth/Qwen3.6-27B")
kept = 0
with open('/workspace/.hf_home/cad_corpus/textcad_sft_4k.jsonl', 'w') as out:
    for l in open('/workspace/.hf_home/cad_corpus/textcad_sft.jsonl'):
        r = json.loads(l)
        t = tok.apply_chat_template([{"role": "user", "content": r["prompt"]},
                                     {"role": "assistant", "content": r["code"]}], tokenize=False)
        if len(tok(t)["input_ids"]) <= 4000:
            out.write(l); kept += 1
print("filtered corpus:", kept, "pairs")
EOF

# 3) train (resumable within the night via checkpoints; fresh dir vs the aborted daytime run)
HF_HUB_OFFLINE=1 serve_venv/bin/python training/train_sft.py --mode instruct \
  --data /workspace/.hf_home/cad_corpus/textcad_sft_4k.jsonl \
  --out /workspace/.hf_home/training/featprog_sft_v2 \
  --max_seq 4096 --epochs 3 --save_steps 100
echo "=== training exited rc=$? at $(date -u) ==="

# 4) bring serving back for the morning
setsid nohup bash serve_qwen_fp8_lora.sh > /tmp/vllm_8002.log 2>&1 < /dev/null &
echo "=== vllm relaunched $(date -u) — done ==="
