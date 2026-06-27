"""Track B backbone — TRELLIS.2-4B image-to-3D → GLB with PBR (the organic branch's generator).

Thin, reusable wrapper around the TRELLIS.2 pipeline (Slice 1 of docs/research/track-b-implementation.md).
Runs in `trellis_venv` (torch 2.11.0+cu128 + the 5 sm_120 CUDA extensions); the trellis2 package is loaded
from the cloned repo via sys.path so this stays OFF cad_pipeline's venv (strict two-venv discipline).

  from track_b.backbone import generate, inspect_glb
  generate("creature.png", "out.glb")                 # 512³ by default (fast); pipeline_type bumps quality
  python -m track_b.backbone <image> [out.glb] [pipeline_type]

GATED/LICENSE NOTES (see the research doc): the image encoder is Meta DINOv3 (commercial-OK, "Built with
DINOv3" attribution required); background removal currently uses Bria RMBG-2.0 (gated + commercially
RESTRICTIVE → swap to a permissive remover or pre-masked input before shipping); the GLB/PBR render path
uses nvdiffrast/nvdiffrec (NON-commercial NVIDIA license) → audit/replace before shipping. Fine for
research/eval now.
"""
from __future__ import annotations

import os
import sys
import time

# --- environment MUST be set before importing trellis2 / torch-heavy deps ---
os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("ATTN_BACKEND", "xformers")          # xformers 0.0.35 — works on Blackwell + torch 2.11
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")   # sparse attn only allows xformers/flash_attn (no sdpa)
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
if "HF_TOKEN" not in os.environ:                            # DINOv3 + RMBG are gated; HF_HOME hides ~/.cache token
    _tok = os.path.expanduser("~/.cache/huggingface/token")
    if os.path.exists(_tok):
        os.environ["HF_TOKEN"] = open(_tok).read().strip()

TRELLIS_REPO = os.environ.get("TRELLIS_REPO", "/workspace/.hf_home/trellis")
if TRELLIS_REPO not in sys.path:
    sys.path.insert(0, TRELLIS_REPO)

MODEL = os.environ.get("TRELLIS_MODEL", "microsoft/TRELLIS.2-4B")
_pipe = None


def _pipeline():
    """Load the pipeline once (it's ~16 GB; keep it resident across calls)."""
    global _pipe
    if _pipe is None:
        from trellis2.pipelines import Trellis2ImageTo3DPipeline
        _pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL)
        _pipe.cuda()
    return _pipe


def generate(image, out_glb: str, *, seed: int = 42, pipeline_type: str = "512",
             texture_size: int | None = None, decimation: int = 1_000_000) -> str:
    """image (path or PIL.Image) → a GLB with PBR at `out_glb`. pipeline_type ∈ {'512','1024',
    '1024_cascade','1536_cascade'} trades speed for fidelity ('512' fast eval; '1536_cascade' = hero).
    texture_size defaults by tier: hero (cascade) tiers bake 4K PBR maps, fast tiers stay 2K (keeps
    Preview light); pass an explicit value to override."""
    from PIL import Image
    import o_voxel
    if texture_size is None:
        texture_size = 4096 if "cascade" in pipeline_type else 2048   # hero tiers → sharper 4K PBR
    img = Image.open(image) if isinstance(image, str) else image
    mesh = _pipeline().run(img, seed=seed, pipeline_type=pipeline_type)[0]
    mesh.simplify(16777216)   # nvdiffrast index limit
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=decimation, texture_size=texture_size, remesh=True, remesh_band=1,
        remesh_project=0, verbose=False)
    os.makedirs(os.path.dirname(out_glb) or ".", exist_ok=True)
    glb.export(out_glb, extension_webp=True)
    return out_glb


def inspect_glb(glb_path: str) -> dict:
    """Quick structural read of a GLB (no GPU): faces/verts, watertight, which PBR maps are present."""
    import trimesh
    s = trimesh.load(glb_path)
    g = next(iter(s.geometry.values())) if getattr(s, "geometry", None) else s
    mat = getattr(getattr(g, "visual", None), "material", None)
    pbr = [a for a in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture", "emissiveTexture")
           if getattr(mat, a, None) is not None] if mat is not None else []
    return {"faces": int(len(g.faces)), "verts": int(len(g.vertices)),
            "watertight": bool(g.is_watertight), "pbr": pbr,
            "size_mb": round(os.path.getsize(glb_path) / 1e6, 1)}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m track_b.backbone <image> [out.glb] [pipeline_type]"); return 2
    image = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "out.glb"
    ptype = sys.argv[3] if len(sys.argv) > 3 else "512"
    t = time.time(); generate(image, out, pipeline_type=ptype); dt = time.time() - t
    print(f"[{dt:.0f}s @ {ptype}] {image} -> {out}  {inspect_glb(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
