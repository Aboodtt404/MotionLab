"""Track B text→image front-end — FLUX.1-dev concept art that feeds the TRELLIS.2 backbone.

This is what makes the organic branch description/chat-driven: a prompt → a clean PHOTOREAL concept
image → `backbone.generate()` → a GLB. The image is an INTERMEDIATE optimised as a TRELLIS input
(single centred subject, plain background, full object visible) but rendered PHOTOREALISTICALLY —
TRELLIS reconstructs what it sees, so a photoreal/cinematic concept is what yields a non-game-y asset.

Model: black-forest-labs/FLUX.1-dev — the full (non-distilled) FLUX. Far higher fidelity than schnell;
needs CFG guidance (~3.5) and ~28 steps (schnell was guidance-free/4-step). NON-COMMERCIAL license —
fine here (in-house tool, not a commercial product). Runs in `trellis_venv` (torch 2.11/cu128) alongside
TRELLIS; `enable_model_cpu_offload()` keeps only the active module on the GPU (peak ~4 GB) so it co-hosts
with vLLM + TRELLIS. ~28-step dev generation is ~30-60 s offloaded (slower than schnell — the quality cost).

  from track_b.t2i import text_to_image
  img = text_to_image("a weathered alien deep-sea anglerfish, bioluminescent lure")  # -> PIL.Image
"""
from __future__ import annotations

import os

os.environ.setdefault("HF_HOME", "/workspace/.hf_home")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
if "HF_TOKEN" not in os.environ:                            # FLUX.1-schnell is gated; HF_HOME hides ~/.cache token
    _tok = os.path.expanduser("~/.cache/huggingface/token")
    if os.path.exists(_tok):
        os.environ["HF_TOKEN"] = open(_tok).read().strip()

MODEL = os.environ.get("T2I_MODEL", "black-forest-labs/FLUX.1-dev")

# Steer FLUX toward a clean TRELLIS input regardless of how terse the user's prompt is. TRELLIS reconstructs
# what it can SEE, so the whole subject must be visible, centred, unoccluded, on a plain background, lit flatly
# enough that albedo isn't lost to shadow. Kept generic so it doesn't fight the user's content words.
_TRELLIS_SUFFIX = (
    ", single centered subject, full object in frame, plain neutral studio background, "
    "photorealistic, cinematic lighting, hyper-detailed, intricate surface detail, "
    "sharp focus, high dynamic range, shot on film"
)

_pipe = None


def _pipeline():
    """Load FLUX.1-dev once, kept resident with SEQUENTIAL CPU-offload. dev's transformer is ~24 GB, and
    co-hosting with vLLM (~63 GB) + resident TRELLIS (~22 GB) leaves only ~10 GB — model-level offload
    (whole 24 GB transformer on GPU) OOMs. Sequential offload streams submodules (~4–6 GB peak) so it
    fits; the cost is slower generation, which is the right trade for the higher-fidelity concept."""
    global _pipe
    if _pipe is None:
        import torch
        from diffusers import FluxPipeline
        _pipe = FluxPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16)
        _pipe.enable_sequential_cpu_offload()   # submodule-granular → low VRAM peak, co-fits with TRELLIS+vLLM
        _pipe.set_progress_bar_config(disable=True)
    return _pipe


def text_to_image(prompt: str, *, seed: int = 42, steps: int = 28, guidance: float = 3.5,
                  width: int = 1024, height: int = 1024, raw: bool = False):
    """prompt → a PIL.Image tuned as a photoreal TRELLIS input. FLUX.1-dev defaults: ~28 steps +
    guidance ~3.5 (the full model needs CFG, unlike schnell). `raw=True` skips the prompt steering."""
    import torch
    full = prompt if raw else (prompt.rstrip(" .,") + _TRELLIS_SUFFIX)
    gen = torch.Generator("cpu").manual_seed(int(seed))
    out = _pipeline()(
        full, num_inference_steps=int(steps), guidance_scale=float(guidance),
        width=int(width), height=int(height), generator=gen,
    )
    return out.images[0]


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m track_b.t2i \"<prompt>\" [out.png] [seed] [steps]"); return 2
    prompt = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "concept.png"
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    steps = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    import time
    t = time.time()
    img = text_to_image(prompt, seed=seed, steps=steps)
    img.save(out)
    print(f"[{time.time()-t:.0f}s] {out}  ({img.width}x{img.height})  <- {prompt!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
