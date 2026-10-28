"""
Full-pipeline base vs fine-tuned eval, the way the product actually runs:
FLUX concept image -> TRELLIS.2 image->3D, comparing
  BASE  = stock sparse_structure_flow_model + shape_slat_flow_model_512
  FT    = MeshFleet fine-tuned BOTH stages (ss_flow + shape_slat)

Inputs are FLUX concepts (eval_vehicle_ft2/concepts/*.png), not dataset renders.
Run under trellis_venv with ATTN_BACKEND=xformers.
"""
import os, sys, glob, subprocess
os.environ.setdefault("ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, "/workspace/.hf_home/trellis")

import torch
from PIL import Image

MODEL = "microsoft/TRELLIS.2-4B"
OUT = "/home/abdelrahman/MotionLab/eval_vehicle"
CONCEPTS = f"{OUT}/concepts"
RENDER = "/home/abdelrahman/MotionLab/training/render_clay.py"
SEED = 42
# stage -> (pipeline model key, fine-tuned EMA checkpoint)
FT = {
    "sparse_structure_flow_model": "/workspace/.hf_home/training/meshfleet_ss_flow_64/ckpts/denoiser_ema0.9999_step0004000.pt",
    "shape_slat_flow_model_512":   "/workspace/.hf_home/training/meshfleet_img2shape_512/ckpts/denoiser_ema0.9999_step0004000.pt",
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
    subprocess.run(["/tmp/blender-3.0.1-linux-x64/blender", "-b", "-P", RENDER,
                    "--", "--glb", glb, "--out", png],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    concepts = sorted(glob.glob(f"{CONCEPTS}/*.png"))
    names = [os.path.splitext(os.path.basename(c))[0] for c in concepts]
    print("concepts:", names)

    # PRODUCTION PATH = multi-view: MV-Adapter makes 6 consistent views per concept,
    # then multi-view TRELLIS (reference-cycling) reconstructs. MV-Adapter is NOT fine-tuned,
    # so generate the views ONCE per concept and reuse for base vs FT (isolates the TRELLIS change).
    sys.path.insert(0, "/home/abdelrahman/MotionLab")
    from track_b.mvadapter_views import multiview
    from track_b.trellis_multiview import enable_multi_image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    print("\n=== MV-Adapter: 6 views per concept (once, shared) ===")
    views = {}
    for n, c in zip(names, concepts):
        os.makedirs(f"{OUT}/{n}", exist_ok=True)
        Image.open(c).convert("RGB").save(f"{OUT}/{n}/input.png")
        vs = multiview(c, text="a car, studio product shot", num_views=6, seed=SEED)
        views[n] = vs
        # save a strip of the generated views for inspection
        strip = Image.new("RGB", (256*len(vs), 256), (20,20,22))
        for i,v in enumerate(vs): strip.paste(v.convert("RGB").resize((256,256)), (i*256,0))
        strip.save(f"{OUT}/{n}/mvviews.png")
        print(f"  {n}: {len(vs)} views")

    pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL); pipe.cuda()
    pipe = enable_multi_image(pipe)

    def gen(tag):
        for n in names:
            mesh = pipe.run_multi_image(views[n], seed=SEED, pipeline_type="512", mode="stochastic")[0]
            _export(mesh, f"{OUT}/{n}/{tag}.glb"); _clay(f"{OUT}/{n}/{tag}.glb", f"{OUT}/{n}/{tag}.png")
            print(f"  {tag} {n} done")

    print("\n=== BASE (both stages stock) ===")
    gen("base")

    print("\n=== load FT into BOTH stages ===")
    for key, ckpt in FT.items():
        sd = torch.load(ckpt, map_location="cpu", weights_only=True)
        m, u = pipe.models[key].load_state_dict(sd, strict=False)
        print(f"  {key}: loaded (missing {len(m)}, unexpected {len(u)})")

    print("\n=== FINE-TUNED (both stages) ===")
    gen("ft")
    print(f"\nDONE -> {OUT}")

if __name__ == "__main__":
    main()
