"""8-view multi-view (6 orbit + top + bottom) → fine-tuned TRELLIS.2. FT-only.
Dumps GLBs + the 8-view strips to eval_vehicle_8view/ for manual inspection.
Run under trellis_venv with ATTN_BACKEND=xformers."""
import os, sys, glob
os.environ.setdefault("ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, "/workspace/.hf_home/trellis")
sys.path.insert(0, "/home/abdelrahman/MotionLab")
import torch
from PIL import Image

MODEL = "microsoft/TRELLIS.2-4B"
CONCEPTS = "/home/abdelrahman/MotionLab/eval_vehicle/concepts"   # side-profile FLUX heroes
OUT = "/home/abdelrahman/MotionLab/eval_vehicle_8view"
SEED = 42
# 6 orbit (elev 0, the proven layout) + top(+80) + bottom(-80)
AZIMUTH   = [0, 45, 90, 180, 270, 315,  0,   0]
ELEVATION = [0,  0,  0,   0,   0,   0, 80, -80]
FT = {
    "sparse_structure_flow_model": "/workspace/.hf_home/training/meshfleet_ss_flow_64/ckpts/denoiser_ema0.9999_step0004000.pt",
    "shape_slat_flow_model_512":   "/workspace/.hf_home/training/meshfleet_img2shape_512/ckpts/denoiser_ema0.9999_step0004000.pt",
}

def _export(mesh, path):
    import o_voxel
    mesh.simplify(16777216)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size, aabb=[[-0.5,-0.5,-0.5],[0.5,0.5,0.5]],
        decimation_target=50000, texture_size=1024, remesh=False, verbose=False)
    glb.export(path)

def _strip(views, path, S=256):
    g = Image.new("RGB", (S*len(views), S), (20,20,22))
    for i,v in enumerate(views): g.paste(v.convert("RGB").resize((S,S)), (i*S,0))
    g.save(path)

def main():
    os.makedirs(f"{OUT}/glb", exist_ok=True)
    concepts = sorted(glob.glob(f"{CONCEPTS}/*.png"))
    names = [os.path.splitext(os.path.basename(c))[0] for c in concepts]
    print("concepts:", names)

    from track_b.mvadapter_views import multiview
    from track_b.trellis_multiview import enable_multi_image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    print("\n=== 8-view MV (6 orbit + top + bottom) ===")
    views = {}
    for n, c in zip(names, concepts):
        vs = multiview(c, text="a car", num_views=8, seed=SEED,
                       azimuth_deg=AZIMUTH, elevation_deg=ELEVATION)
        views[n] = vs
        _strip(vs, f"{OUT}/{n}_8views.png")
        print(f"  {n}: {len(vs)} views")

    pipe = Trellis2ImageTo3DPipeline.from_pretrained(MODEL); pipe.cuda()
    print("\n=== load FT into both stages ===")
    for key, ckpt in FT.items():
        m, u = pipe.models[key].load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=True), strict=False)
        print(f"  {key}: missing {len(m)} unexpected {len(u)}")
    pipe = enable_multi_image(pipe)

    print("\n=== FT generations (8-view) ===")
    for n in names:
        mesh = pipe.run_multi_image(views[n], seed=SEED, pipeline_type="512", mode="stochastic")[0]
        _export(mesh, f"{OUT}/glb/{n}.glb")
        print(f"  {n} -> glb/{n}.glb", flush=True)
    print(f"\nDONE -> {OUT}/glb")

if __name__ == "__main__":
    main()
