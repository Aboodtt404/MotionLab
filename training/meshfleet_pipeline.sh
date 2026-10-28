#!/usr/bin/env bash
# MeshFleet -> TRELLIS.2 fine-tune data pipeline (full 1,620 curated cars).
# Validated end-to-end on a 5-car smoke first (see memory: trellis-vehicle-finetune).
#
# Two venvs: mf_prep_venv (CPU stages, has objaverse/open3d/blender deps) and
# trellis_venv (GPU + o_voxel + built CUDA exts). trellis_venv is pip-less.
#
# Usage:  bash training/meshfleet_pipeline.sh <stage>
#   stages: download | dump | voxelize | encode | render | all_cpu
# Stages are resumable (each skips already-processed sha256).
set -euo pipefail

TRELLIS=/workspace/.hf_home/trellis
ROOT=/workspace/.hf_home/datasets/meshfleet
RES=512
PV=/workspace/.hf_home/mf_prep_venv/bin/python      # CPU stages
TV=/workspace/.hf_home/trellis_venv/bin/python       # GPU / o-voxel stages
export HF_HOME=/workspace/.hf_home
export MESHFLEET_CSV=$ROOT/meshfleet.csv
export HF_HUB_OFFLINE=1
NW=${NW:-8}
cd "$TRELLIS"

merge() { $PV data_toolkit/build_metadata.py MeshFleet --root "$ROOT" 2>&1 | grep -A6 Statistics || true; }

case "${1:-all_cpu}" in
  download)
    $PV data_toolkit/download.py MeshFleet --root "$ROOT"; merge ;;
  dump)
    $PV data_toolkit/dump_mesh.py MeshFleet --root "$ROOT" --max_workers "$NW"; merge
    $PV data_toolkit/dump_pbr.py  MeshFleet --root "$ROOT" --max_workers "$NW"; merge ;;
  voxelize)
    $TV data_toolkit/dual_grid.py    MeshFleet --root "$ROOT" --resolution "$RES" --max_workers "$NW"; merge
    $TV data_toolkit/voxelize_pbr.py MeshFleet --root "$ROOT" --resolution "$RES" --max_workers "$NW"; merge ;;
  encode)
    $TV data_toolkit/encode_shape_latent.py --root "$ROOT" --resolution "$RES"; merge
    $TV data_toolkit/encode_pbr_latent.py   --root "$ROOT" --resolution "$RES"; merge
    $TV data_toolkit/encode_ss_latent.py    --root "$ROOT" \
        --shape_latent_name shape_enc_next_dc_f16c32_fp16_${RES} --resolution 64; merge ;;
  render)
    $PV data_toolkit/render_cond.py MeshFleet --root "$ROOT" --max_workers "$NW"; merge ;;
  all_cpu)
    bash "$0" dump
    bash "$0" voxelize
    echo "CPU+voxelize done. Next: bash $0 encode  (GPU)  then  bash $0 render" ;;
  *) echo "unknown stage: $1"; exit 1 ;;
esac
