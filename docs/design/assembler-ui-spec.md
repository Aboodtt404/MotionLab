# MotionLab Assembler — UI/UX spec (Meshy-grounded, 2026-06-29)

**Goal:** an in-app, Meshy-style **assemble** workspace where film-makers compose a scene from generated
assets (the differentiator — Meshy generates + manages assets but has **no in-app scene assembler**; assembly
happens in Blender/Unreal). So we mirror **Meshy's look + workflow** for generation/library, and borrow the
**scene-assembly canvas** conventions from in-browser 3D editors (Spline, three.js editor).

## What we're mirroring
- **Meshy Workspace 3.0** ([UI overview](https://help.meshy.ai/en/articles/12618267-workspace-ui-overview-and-how-to-use-and-navigate-it), [blog](https://www.meshy.ai/blog/workspace3)): **3-panel** layout — Left nav sidebar (modes: Assets/Agent/Image/Model/Print/Animate), Center 3D viewport + a **post-gen toolbar** (Retexture / Remesh / Unwrap UV / Edit Texture), Right asset/history panel (search, upload, generation results w/ variations). Dark, professional.
- **Spline** ([UI doc](https://docs.spline.design/basics/understanding-splines-ui)): **Top toolbar** (object add `+`, Transform tool = move/scale/rotate, zoom, export), **Left sidebar** Outliner ⇄ Assets, **Right sidebar** Property/Inspector, center Viewport. Womp = "Figma for 3D, drag-and-drop everything."
- **three.js `TransformControls`**: Move/Rotate/Scale **gizmos** (Blender-like W/E/R), click-drag axes; select object, not camera.

## The Assembler layout — Command Deck shell + the above conventions
Keeps our dark glass + accent identity (already matches Meshy's dark-professional feel); adds the editor panels.

```
┌───────────────────────────────────────────────────────────────────────┐
│ TopBar:  [Robotics][Film][Assemble]   | Move·Rotate·Scale | Snap | view  │
├──────────────┬───────────────────────────────────────────┬─────────────┤
│ LEFT PANEL    │            VIEWPORT (canvas)              │  INSPECTOR   │
│ ┌Assets┐Outln │   orbit/pan/zoom · ground terrain tile    │ (right glass)│
│ │ asset │ tree│   selected asset → transform GIZMO        │ selected:    │
│ │ grid  │ list│   click-select · drag gizmo · drop-to-grnd│  pos/rot/scl │
│ │ +Gen  │     │                                           │  Low-Poly    │
│ └───────┘     │                                           │  Duplicate   │
│              │                                            │  Delete      │
│              │                                            │ (none: scene │
│              │                                            │  ground+light)│
├──────────────┴───────────────────────────────────────────┴─────────────┤
│ CommandBar:  describe a new asset… [Generate]   | Export GLB · Render · Animate │
└───────────────────────────────────────────────────────────────────────┘
```

- **Left — Library/Outliner** (Meshy left + Spline left): tabbed **Assets** (thumbnail grid of generated
  objects/creatures/trees/terrain + `＋ Generate`; click/drag → add to scene) ⇄ **Outliner** (placed objects:
  select, rename, hide, delete).
- **Center — Viewport canvas**: our `StudioScene` (orbit/pan/zoom) + **`TransformControls` gizmo** on the
  selected asset (mode from the TopBar Move/Rotate/Scale toggle, W/E/R shortcuts); click-to-select (raycast),
  **drop-to-ground** (raycast onto the terrain tile), the terrain tile as the base ground.
- **Right — Inspector**: selected asset → **numeric transform** (pos/rot/scale) + actions (**Low-Poly**,
  **Duplicate**, **Delete**, Retexture later); nothing selected → **scene settings** (ground/terrain tile,
  light mood).
- **Bottom — CommandBar**: inline **generate a new asset** (prompt → Track B) + finish actions: **Export GLB**
  (three `GLTFExporter`), **Render** (photoreal Cycles of the assembled scene), **Animate** (LTX).

## Interactions (Spline / Blender conventions)
select (click / outliner) · W/E/R move/rotate/scale via gizmo · Ctrl/Cmd+D duplicate · Del delete ·
drag-from-library to add · drop-to-ground · orbit-drag / pan-shift-drag / wheel-zoom (existing controls).

## Visual style
Keep the **Command Deck** dark blue-black + glass panels + per-workspace accent (matches Meshy's dark
professional look). New **"Assemble"** workspace accent (proposed: warm amber — workshop/build feel; or reuse).
Mirror Meshy's *layout + interaction model + clean task-oriented feel*, not its exact proprietary assets.

## Build order
P1: Assemble tab + viewport gizmos (TransformControls) + scene-graph store (assets+transforms) + library
(session assets) + add/select/move/rotate/scale/duplicate/delete/drop-to-ground + GLB export.
P2: photoreal Cycles render + LTX motion of the assembled scene. P3: persisted library, Low-Poly/Retexture
buttons in the inspector, save/load scenes.
