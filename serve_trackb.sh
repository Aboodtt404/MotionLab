#!/usr/bin/env bash
# Track B (organic image/text→3D) HTTP service — the TRELLIS.2 + FLUX backbone behind /api/trackb.
# Launches track_b.server on :8770 in its own venv. Detached; not under supervisor (kill to stop).
#
#   PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True — the hero tier (1536_cascade) allocates a large
#   contiguous block in CuMesh; without this the long-lived process fragments the caching allocator and
#   CuMesh CUDA-OOMs even with the card mostly free. This is the documented fix (and what the OOM hint says).
set -u
cd "$(dirname "$0")"
PORT="${1:-8770}"
PY=/workspace/.hf_home/trellis_venv/bin/python

export HF_HOME=/workspace/.hf_home
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1     # HF is flaky on this box; models are cached
export CAD_BIND=0.0.0.0                                 # reachable for the Caddy proxy
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
[ -f "$HOME/.cache/huggingface/token" ] && export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token")"

exec "$PY" -m track_b.server "$PORT"
