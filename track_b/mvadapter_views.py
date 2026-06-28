"""MV-Adapter (i2mv SDXL) — one reference image → N consistent orbit views, the front half of the
multi-view pipeline (see docs/research/multiview-conditioning-research.md).

Runs in trellis_venv (pure-diffusers — no custom CUDA, just works on sm_120). The SDXL pipeline + BiRefNet
are loaded once and kept resident. Views feed TRELLIS.2's run_multi_image (track_b/trellis_multiview.py).

  from .mvadapter_views import multiview
  views = multiview(hero_image, text="a detailed sci-fi bust", num_views=6)   # list[PIL.Image]
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional

os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
MV_REPO = os.environ.get("MVADAPTER_REPO", "/workspace/.hf_home/MV-Adapter")
if MV_REPO not in sys.path:
    sys.path.insert(0, MV_REPO)

# default 6-view orbit (matches MV-Adapter's training layout); 0=front … 180=back
DEFAULT_AZIMUTH = [0, 45, 90, 180, 270, 315]
_pipe = None
_birefnet = None
_tf = None


def _load():
    """Load the MV-Adapter SDXL pipeline + BiRefNet bg-remover once; keep resident."""
    global _pipe, _birefnet, _tf
    if _pipe is None:
        import torch
        from scripts.inference_i2mv_sdxl import prepare_pipeline
        _pipe = prepare_pipeline(
            base_model="stabilityai/stable-diffusion-xl-base-1.0",
            vae_model="madebyollin/sdxl-vae-fp16-fix",
            unet_model=None, lora_model=None,
            adapter_path="huanngzh/mv-adapter", scheduler=None,
            num_views=6, device="cuda", dtype=torch.float16,
        )
    if _birefnet is None:
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
        _birefnet = AutoModelForImageSegmentation.from_pretrained(
            "ZhengPeng7/BiRefNet", trust_remote_code=True).to("cuda")
        _birefnet.eval()
        _tf = transforms.Compose([
            transforms.Resize((1024, 1024)), transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
    return _pipe, _birefnet, _tf


def multiview(ref_image, text: str = "high quality, detailed", num_views: int = 6, seed: int = 42,
              azimuth_deg: Optional[List[int]] = None, guidance_scale: float = 3.0,
              num_inference_steps: int = 50) -> List["object"]:
    """Reference image (path or PIL.Image) → list of `num_views` consistent views (PIL.Images).

    The reference is background-removed (BiRefNet) and centered; views are generated at `azimuth_deg`
    (default the canonical 6-view orbit). `text` lightly guides appearance/quality."""
    import torch  # noqa: F401  (ensures CUDA context inside the gpu lock)
    from PIL import Image
    from scripts.inference_i2mv_sdxl import remove_bg, run_pipeline

    pipe, birefnet, tf = _load()
    img = (Image.open(ref_image) if isinstance(ref_image, str) else ref_image).convert("RGB")  # RGB for BiRefNet
    rmbg = lambda x: remove_bg(x, birefnet, tf, "cuda")  # noqa: E731
    images, _ref = run_pipeline(
        pipe, num_views=num_views, text=text, image=img, height=768, width=768,
        num_inference_steps=num_inference_steps, guidance_scale=guidance_scale, seed=seed,
        remove_bg_fn=rmbg, azimuth_deg=azimuth_deg or DEFAULT_AZIMUTH[:num_views],
    )
    return images
