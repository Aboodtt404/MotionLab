"""Multi-view conditioning for TRELLIS.2 — reference-cycling (the only method that works on the
single-image-trained 4B checkpoint). See docs/research/multiview-conditioning-research.md.

The released TRELLIS.2 pipeline is single-image only. This module *binds* two extra methods onto a live
pipeline instance — `inject_sampler_multi_image` (a context manager that round-robins one view per denoise
step) and `run_multi_image` (orchestrates it across all three sampler stages) — WITHOUT editing the shared
cloned trellis2 repo. Logic is ported near-verbatim from the community reference
(HF Space `opsiclear-admin/Trellis.2.multiview`), which itself ports TRELLIS-1.0's `inject_sampler_multi_image`.

Two modes:
  - 'stochastic'   (DEFAULT, recommended): each step conditions on ONE view (round-robin). Every forward pass
                   stays in the single-image training distribution; views are fused temporally across steps.
  - 'multidiffusion' (NOT recommended): averages per-view predictions each step — re-implements CFG and
                   mishandles the guidance mixins; documented to produce WORSE/incorrect geometry. Kept for parity.

Usage:
    from .trellis_multiview import enable_multi_image
    enable_multi_image(pipe)
    meshes = pipe.run_multi_image([v0, v1, v2, v3], pipeline_type="1024_cascade", mode="stochastic")
"""
from __future__ import annotations

import types
from contextlib import contextmanager
from typing import List, Literal, Optional

import numpy as np
import torch
from PIL import Image


@contextmanager
def inject_sampler_multi_image(self, sampler_name: str, num_images: int, num_steps: int,
                               mode: Literal['stochastic', 'multidiffusion'] = 'stochastic'):
    """Temporarily patch a sampler's `_inference_model` to condition on multiple views.

    stochastic: round-robin — step t uses view (t % N). Each forward pass is a normal single-image
    conditioning call (in-distribution). This is the mode that works."""
    sampler = getattr(self, sampler_name)
    setattr(sampler, '_old_inference_model', sampler._inference_model)

    if mode == 'stochastic':
        if num_images > num_steps:
            print(f"\033[93mWarning: more conditioning views ({num_images}) than steps ({num_steps}) "
                  f"for {sampler_name}; some views won't be seen.\033[0m")
        cond_indices = (np.arange(num_steps) % num_images).tolist()

        def _new_inference_model(self, model, x_t, t, cond, **kwargs):
            nonlocal cond_indices
            if not cond_indices:
                cond_indices = (np.arange(num_steps) % num_images).tolist()
            cond_idx = cond_indices.pop(0)
            cond_i = cond[cond_idx:cond_idx + 1]               # one view's DINO tokens → in-distribution
            return self._old_inference_model(model, x_t, t, cond=cond_i, **kwargs)

    elif mode == 'multidiffusion':
        from trellis2.pipelines.samplers import FlowEulerSampler

        def _new_inference_model(self, model, x_t, t, cond, neg_cond=None, guidance_strength=1,
                                 guidance_interval=(0, 1), guidance_rescale=0.0, **kwargs):
            preds = [FlowEulerSampler._inference_model(self, model, x_t, t, cond[i:i + 1], **kwargs)
                     for i in range(len(cond))]
            avg_pred = sum(preds) / len(preds)
            if not (guidance_interval[0] <= t <= guidance_interval[1]):
                guidance_strength = 1
            if guidance_strength == 1 or neg_cond is None:
                return avg_pred
            neg_pred = FlowEulerSampler._inference_model(self, model, x_t, t, neg_cond, **kwargs)
            pred = guidance_strength * avg_pred + (1 - guidance_strength) * neg_pred
            if guidance_rescale > 0:
                x_0_pos = self._pred_to_xstart(x_t, t, avg_pred)
                x_0_cfg = self._pred_to_xstart(x_t, t, pred)
                std_pos = x_0_pos.std(dim=list(range(1, x_0_pos.ndim)), keepdim=True)
                std_cfg = x_0_cfg.std(dim=list(range(1, x_0_cfg.ndim)), keepdim=True)
                x_0 = guidance_rescale * (x_0_cfg * (std_pos / std_cfg)) + (1 - guidance_rescale) * x_0_cfg
                pred = self._xstart_to_pred(x_t, t, x_0)
            return pred
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    sampler._inference_model = _new_inference_model.__get__(sampler, type(sampler))
    try:
        yield
    finally:
        sampler._inference_model = sampler._old_inference_model
        delattr(sampler, '_old_inference_model')


@torch.no_grad()
def run_multi_image(self, images: List[Image.Image], num_samples: int = 1, seed: int = 42,
                    sparse_structure_sampler_params: dict = {}, shape_slat_sampler_params: dict = {},
                    tex_slat_sampler_params: dict = {}, preprocess_image: bool = True,
                    return_latent: bool = False, pipeline_type: Optional[str] = None,
                    max_num_tokens: int = 49152,
                    mode: Literal['stochastic', 'multidiffusion'] = 'stochastic',
                    tex_mode: Optional[Literal['stochastic', 'multidiffusion']] = None):
    """Reconstruct one mesh conditioned on multiple consistent views of the same object."""
    tex_mode = tex_mode or mode
    pipeline_type = pipeline_type or self.default_pipeline_type
    if pipeline_type not in ('512', '1024', '1024_cascade', '1536_cascade'):
        raise ValueError(f"Invalid pipeline type: {pipeline_type}")

    if preprocess_image:
        images = [self.preprocess_image(image) for image in images]
    torch.manual_seed(seed)
    cond_512 = self.get_cond(images, 512)
    cond_512['neg_cond'] = cond_512['neg_cond'][:1]            # one shared negative, not one per view
    if pipeline_type != '512':
        cond_1024 = self.get_cond(images, 1024)
        cond_1024['neg_cond'] = cond_1024['neg_cond'][:1]
    else:
        cond_1024 = None

    ss_res = {'512': 32, '1024': 64, '1024_cascade': 32, '1536_cascade': 32}[pipeline_type]
    ss_steps = {**self.sparse_structure_sampler_params, **sparse_structure_sampler_params}.get('steps')
    with self.inject_sampler_multi_image('sparse_structure_sampler', len(images), ss_steps, mode=mode):
        coords = self.sample_sparse_structure(cond_512, ss_res, num_samples, sparse_structure_sampler_params)

    shape_steps = {**self.shape_slat_sampler_params, **shape_slat_sampler_params}.get('steps')
    tex_steps = {**self.tex_slat_sampler_params, **tex_slat_sampler_params}.get('steps')
    with self.inject_sampler_multi_image('shape_slat_sampler', len(images), shape_steps, mode=mode), \
         self.inject_sampler_multi_image('tex_slat_sampler', len(images), tex_steps, mode=tex_mode):
        if pipeline_type == '512':
            shape_slat = self.sample_shape_slat(cond_512, self.models['shape_slat_flow_model_512'],
                                                coords, shape_slat_sampler_params)
            tex_slat = self.sample_tex_slat(cond_512, self.models['tex_slat_flow_model_512'],
                                            shape_slat, tex_slat_sampler_params)
            res = 512
        elif pipeline_type == '1024':
            shape_slat = self.sample_shape_slat(cond_1024, self.models['shape_slat_flow_model_1024'],
                                                coords, shape_slat_sampler_params)
            tex_slat = self.sample_tex_slat(cond_1024, self.models['tex_slat_flow_model_1024'],
                                            shape_slat, tex_slat_sampler_params)
            res = 1024
        elif pipeline_type == '1024_cascade':
            shape_slat, res = self.sample_shape_slat_cascade(
                cond_512, cond_1024, self.models['shape_slat_flow_model_512'],
                self.models['shape_slat_flow_model_1024'], 512, 1024, coords,
                shape_slat_sampler_params, max_num_tokens)
            tex_slat = self.sample_tex_slat(cond_1024, self.models['tex_slat_flow_model_1024'],
                                            shape_slat, tex_slat_sampler_params)
        else:  # 1536_cascade
            shape_slat, res = self.sample_shape_slat_cascade(
                cond_512, cond_1024, self.models['shape_slat_flow_model_512'],
                self.models['shape_slat_flow_model_1024'], 512, 1536, coords,
                shape_slat_sampler_params, max_num_tokens)
            tex_slat = self.sample_tex_slat(cond_1024, self.models['tex_slat_flow_model_1024'],
                                            shape_slat, tex_slat_sampler_params)
    torch.cuda.empty_cache()
    out_mesh = self.decode_latent(shape_slat, tex_slat, res)
    return (out_mesh, (shape_slat, tex_slat, res)) if return_latent else out_mesh


def enable_multi_image(pipe):
    """Bind run_multi_image + inject_sampler_multi_image onto a live pipeline instance (idempotent)."""
    if not hasattr(pipe, "run_multi_image"):
        pipe.inject_sampler_multi_image = types.MethodType(inject_sampler_multi_image, pipe)
        pipe.run_multi_image = types.MethodType(run_multi_image, pipe)
    return pipe
