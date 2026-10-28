"""
1536_cascade (MAX DETAIL) full-pipeline base vs fine-tuned vehicle eval — the payoff of the
MeshFleet fine-tune. Production path: FLUX side-view concept -> MV-Adapter 6 views (shared, not
fine-tuned) -> TRELLIS.2 run_multi_image at pipeline_type="1536_cascade".

  BASE = stock ss_flow + shape_slat_512 + shape_slat_1024 (the 1536 cascade uses 512 coarse -> 1024 refine)
  FT   = MeshFleet fine-tuned ALL THREE geometry stages (ema step 4000)

Run under trellis_venv:  ATTN_BACKEND=xformers SPARSE_ATTN_BACKEND=xformers python -m training.eval_vehicle_1536
The CuMesh empty_cache fix is already in trellis2_image_to_3d.py:590 (before decode_latent).
"""
import glob
import os
import subprocess
import sys

os.environ.setdefault("ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, "/workspace/.hf_home/trellis")

import torch
from PIL import Image

MODEL = "microsoft/TRELLIS.2-4B"
OUT = "/home/abdelrahman/MotionLab/eval_vehicle_1536"
CONCEPTS = "/home/abdelrahman/MotionLab/eval_vehicle/concepts"
RENDER = "/home/abdelrahman/MotionLab/training/render_clay.py"
BLENDER = "/tmp/blender-3.0.1-linux-x64/blender"
PIPELINE_TYPE = "1536_cascade"
SEED = 42
CK = "/workspace/.hf_home/training"
# all three geometry stages fine-tuned (the 1536 cascade drives ss_flow -> 512 coarse -> 1024 refine)
FT = {
    "sparse_structure_flow_model": f"{CK}/meshfleet_ss_flow_64/ckpts/denoiser_ema0.9999_step0004000.pt",
    "shape_slat_flow_model_512":   f"{CK}/meshfleet_img2shape_512/ckpts/denoiser_ema0.9999_step0004000.pt",
    "shape_slat_flow_model_1024":  f"{CK}/meshfleet_img2shape_1024/ckpts/denoiser_ema0.9999_step0004000.pt",
}


def _export(mesh, path):
    import o_voxel
    mesh.simplify(16777216)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=50000, texture_size=1024, remesh=False, verbose=False)
    glb.export(path)


def _clay(glb, png):
    subprocess.run([BLENDER, "-b", "-P", RENDER, "--", "--glb", glb, "--out", png],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    concepts = sorted(glob.glob(f"{CONCEPTS}/*.png"))
    names = [os.path.splitext(os.path.basename(c))[0] for c in concepts]
    print("concepts:", names, "| tier:", PIPELINE_TYPE)

    sys.path.insert(0, "/home/abdelrahman/MotionLab")
    from track_b.mvadapter_views import multiview
    from track_b.trellis_multiview import enable_multi_image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    print("\n=== MV-Adapter: 6 views per concept (once, shared base vs FT) ===")
    views = {}
    for n, c in zip(names, concepts):
        os.makedirs(f"{OUT}/{n}", exist_ok=True)
        Image.open(c).convert("RGB").save(f"{OUT}/{n}/input.png")
        views[n] = multiview(c, text="a car, studio product shot", num_views=6, seed=SEED)
        print(f"  {n}: {len(views[n])} views")

    pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL); pipe.cuda()
    pipe = enable_multi_image(pipe)

    def gen(tag):
        for n in names:
            mesh = pipe.run_multi_image(views[n], seed=SEED, pipeline_type=PIPELINE_TYPE, mode="stochastic")[0]
            _export(mesh, f"{OUT}/{n}/{tag}.glb"); _clay(f"{OUT}/{n}/{tag}.glb", f"{OUT}/{n}/{tag}.png")
            print(f"  {tag} {n} done")

    print("\n=== BASE @ 1536_cascade (stock) ===")
    gen("base1536")

    print("\n=== load FT into all 3 geometry stages ===")
    for key, ckpt in FT.items():
        sd = torch.load(ckpt, map_location="cpu", weights_only=True)
        m, u = pipe.models[key].load_state_dict(sd, strict=False)
        print(f"  {key}: loaded (missing {len(m)}, unexpected {len(u)})")

    print("\n=== FINE-TUNED @ 1536_cascade ===")
    gen("ft1536")
    print(f"\nDONE -> {OUT}")


if __name__ == "__main__":
    main()
