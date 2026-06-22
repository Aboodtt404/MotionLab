# MotionLab — Architecture

AI 3D asset generation for film (sci-fi production). Two inputs, two generation
branches, two output targets, one shared verify-and-export spine.

## Objective
Generate film assets — both **hard-surface** (props, panels, ships, weapons) and
**organic** (creatures, environments) — from either a **text + metrics** spec or a
**concept image**, producing geometry that is both **render-ready** and, for a
subset, **fabrication-ready** (3D-printed / CNC'd practical props).

## Pipeline
```
INPUT  (text + metrics | concept image)
   -> [router: classify asset_class]
        |
   HARD-SURFACE branch                 ORGANIC branch
   spec -> LLM emits CadQuery          spec/image -> generative mesh
   -> sandboxed exec -> exact BRep        (Hunyuan3D / TRELLIS) -> raw mesh
        |                                   |
   -> VERIFY (bifurcated) -> retry (max 3) on failure
        |
   -> EXPORT: render (glTF / USD)  +  fabricate (STEP hard-surface / STL both)
   -> R3F viewer
```

## Shared structured spec
Both branches target one typed spec carrying `asset_class`
(`hard_surface` | `organic`) and `fabrication` (`render` | `fabricate`), which
route the generator and select the verifier. Image input fills the same spec
(image -> generative mesh directly, or image -> estimated metrics -> CadQuery).

## Verifier (bifurcated)
- **Hard-surface:** exact dimensional + feature checks via OCP/BRep introspection
  (enumerate faces, classify cylinders/planes/fillets, measure radius/axis/extent
  against the spec). RANSAC/mesh fitting is *not* used here — the BRep is exact.
- **Organic:** printability (manifold, watertight, min wall thickness,
  self-intersections) via trimesh, plus a visual-fidelity score (VLM/CLIP vs
  prompt). Fabricated organic meshes pass through a print-prep stage (repair,
  hollow, wall-thickness) reusing Blender `bpy`.

## Build order
1. Hard-surface text -> CadQuery spine (deterministic verifier, infra ready).
2. Organic text -> mesh branch (serve a generative-mesh model; printability verifier).
3. Image input for both branches.
4. Shared export + R3F viewer.

## Infra notes
- Local code model: vLLM Qwen3-Coder-30B (OpenAI-compatible, `localhost:8000/v1`).
  A frontier API model is the accuracy ceiling for hard-surface generation.
- CadQuery/OCP runs on CPU. The organic branch needs a generative-mesh model
  served on the GPU — VRAM is currently saturated and must be freed first.
- Executor baseline for the hard-surface branch: CadQuery 2.4 / Python 3.10
  (matches the Text2CAD-Bench setup, arXiv 2605.18430).
