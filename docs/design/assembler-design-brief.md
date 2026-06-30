# MotionLab — Asset Generation + Scene Assembly Studio — Design Brief (for Claude Design)

**Purpose.** A complete, architecture-grounded brief to design (from scratch) the UI/UX of MotionLab's
**asset-generation + scene-assembly** web app — a Meshy-style 3D generator fused with the **in-app scene
assembler Meshy lacks**. This is the source of truth.

> **Design TO the architecture, not around it.** Every feature below maps to a real, working backend route.
> Where it says "the backend returns X" or "this takes ~N min/sec," that is a real contract — surface X
> honestly, design the **waiting / empty / error** states for that reality, and **do not invent** capabilities,
> fake metrics, or data the backend doesn't produce.

---

## 1. The product & the user

MotionLab is a self-hosted AI 3D studio for an in-house **film-making team**. This app is its creative side:
**generate individual 3D assets from text or images, then manually assemble them into a scene — all in the
browser.** Meshy (our reference) is best-in-class at generating + managing assets but makes you assemble the
scene in Blender/Unreal; **our differentiator is the in-app assembly canvas.**

- **Primary user:** a film-maker / 3D artist, beginner-to-intermediate. Comfortable with a Figma-like tool,
  not necessarily Blender. Wants: idea → a composed, exportable 3D scene without leaving the app.
- **The job:** populate a scene — generate a hero (sword, creature), props (barrel, crate), nature (trees,
  rocks), and a ground/terrain, then arrange them into a shot.
- **Out of scope for this brief (mention only as a sibling workspace):** a separate **Robotics** track that
  turns text into verified parametric CAD with STEP/STL export — different users, different flow.

## 2. The core loop (design the whole journey)

```
GENERATE an asset ──► it lands in the LIBRARY ──► drag onto the ASSEMBLY CANVAS ──► place / move / rotate /
   (text or image)        (thumbnails, status)        scale / duplicate / ground-snap ──► repeat to build the
                                                       scene ──► FINISH: export GLB · photoreal render · motion clip
```
Plus a per-asset **REFINE** sub-loop: **Low-Poly / game-ready** (decimate to a polycount), and (future)
Retexture / re-pose.

## 3. Information architecture

A single studio with a **workspace switcher** (top): **Create** (generate assets) and **Assemble** (compose
the scene) — they share one **Library**. (A third **Robotics** workspace exists as a sibling; style it as a
peer but don't design its internals here.)

Three working zones (the assembler is the hero screen):
- **Left** — **Library ⇄ Outliner** (tabbed). Library = generated assets as a thumbnail grid + a "＋ Generate"
  entry; Outliner = the objects currently placed in the scene (tree list).
- **Center** — the **3D viewport / canvas** (full-bleed hero).
- **Right** — **Inspector** (contextual: selected-asset properties, or scene settings).
- **Bottom** — a **command bar** (generate a new asset inline) + the **finish actions**.
- **Top** — brand, workspace switch, and the canvas **transform-mode** controls.

## 4. Screens & states (design each state explicitly)

### 4.1 Generate (an asset)
Inputs: a **text prompt** OR an **uploaded image** (drag-drop). Options to expose:
- **Quality tier** (real backend tiers → honest time hints): *Preview ~30s · Standard ~1 min · High ~1.5 min ·
  Max detail ~2–2.5 min.*
- **Multi-view** toggle ("feed front/side/back to lock geometry," +~30s) — for image mode especially.
- **Asset type** affordance: *object/creature/prop* (text→3D), *tree/rock/foliage* (same), *ground/terrain*
  (a distinct generator — see 4.5). Number-of-variations is a nice-to-have.
States: **idle/empty** (invite a prompt, show example prompts), **generating** (a real staged progress —
stages are *queued → concept image (FLUX) → generating mesh*; show the **concept image** when it appears, it's
a real intermediate; **cancellable**; ~30s–2.5min), **done** (the textured 3D result + report: face count,
PBR maps present, watertight, generation time), **error** (clear message; offer retry).

### 4.2 Library
A grid of the user's generated assets (this session at minimum): **thumbnail** (auto-rendered), name, type
badge, poly/size, and quick actions (add-to-scene, Low-Poly, duplicate, delete, export). Search/filter. An
"in-progress" card for assets still generating. This is the bridge between Create and Assemble.

### 4.3 Assembly canvas — THE HERO SCREEN (see §5 for full detail)
The 3D scene the user composes. Empty state: an inviting ground plane + "drag an asset in, or generate one."

### 4.4 Inspector (right)
- **Asset selected:** numeric **transform** (position / rotation / scale, with reset), and asset **actions**:
  **Low-Poly** (slider for target face budget, e.g. 1k–100k — real `/lowpoly` route), **Duplicate**, **Delete**,
  **Export this asset** (GLB/USDZ). (Future: Retexture.)
- **Nothing selected:** **scene settings** — the **ground/terrain tile** (pick/generate a biome), **lighting
  mood** (Studio / Dramatic / Soft / Rim), environment.

### 4.5 Terrain / ground generator
A distinct generator (it's heavier): pick a **biome** (plain, desert, forest, snowy mountain, arctic, mountain,
coast, canyon, cliff, river) → generate a **ground tile** (~5–6 min — design a patient, reassuring waiting
state; it is **slower than object gen**, set that expectation). Result = a placeable, real-time ground in the
scene.

### 4.6 Finish (export / render / motion)
On the assembled scene:
- **Export GLB** (the whole composed scene — instant, client-side) + **USDZ**.
- **Photoreal render** — send the scene for a path-traced Cycles still (+ a turntable). ~1–2 min, async.
- **Motion clip** — render-to-real video from the turntable (~40s, async). Two variants (faithful / aggressive).
Design the gallery for these outputs (still image, video player, downloads).

## 5. The assembly canvas — interaction detail (the heart)

Mirror conventions from **Spline** and the **three.js editor / Blender** (Meshy has no canvas to copy):
- **Add:** drag an asset from the Library into the viewport, or click "add to scene." It drops onto the
  ground at the cursor.
- **Select:** click an object in the viewport, or a row in the **Outliner**. Show a selection highlight.
- **Transform:** a **gizmo** on the selected object with three modes — **Move / Rotate / Scale** — switchable
  from the top toolbar and via **W / E / R** shortcuts (Blender/Spline convention). Drag an axis/plane handle.
- **Numeric transform** mirrors in the Inspector (two-way).
- **Duplicate** (Ctrl/Cmd+D or button), **Delete** (Del), **rename** (in outliner).
- **Ground-snap:** objects rest on the terrain surface (raycast); a "drop to ground" action re-seats a
  floating object. This matters — assets should never float.
- **Navigate:** orbit (drag), pan (shift-drag / middle-drag), zoom (wheel). A "frame all / frame selection"
  control. Optional grid + ground shadow.
- **Outliner:** list of placed objects with select / hide / rename / delete; reflects + drives selection.
Design all of: empty canvas, object selected (gizmo + inspector), multi-object scene, mid-drag, and the
ground/terrain present vs. absent.

## 6. Backend reality — the contracts to design to

**Everything is an async job:** the client POSTs and gets a `job_id`, then polls `GET /job/<id>` →
`{status: queued|running|done|error, stage, elapsed, ...result}`. So **every generative action needs a
non-blocking, cancellable, staged progress state** (the app stays usable; jobs can run minutes).

| Action | Route | Returns | Time |
|---|---|---|---|
| Text → 3D asset | `/text2mesh {prompt, tier, multiview}` | GLB + PBR, **concept image** (FLUX), face/vert/watertight report | ~30s–2.5min by tier |
| Image → 3D asset | `/image2mesh {image, tier, multiview}` | same | ~30s–2.5min |
| Low-Poly / game-ready | `/lowpoly {glb, target_faces}` | decimated GLB + report | ~8s |
| Ground/terrain tile | `/terrain {biome, target_faces}` | vertex-colored GLB tile | **~5–6 min** |
| Photoreal render (scene/asset) | `/render {glb, samples, res}` | beauty PNG + turntable MP4 | ~1–2min |
| Motion clip | `/animate {turntable, first_frame, variant}` | MP4 | ~40s |
| Cancel | `/cancel/<id>` | — | instant |

Other real facts to surface honestly: assets carry **PBR materials** (base color, metallic-roughness, normal);
**export formats** are GLB / USDZ (web/AR) and the scene exports as one GLB. Terrain tiles are **vertex-colored**
(real-time) — full photoreal only appears in the Cycles render. **Don't** show fake "fidelity scores,"
best-of-N, or metrics the backend doesn't return.

## 7. Visual direction

- **Brand:** "MotionLab" — a precise, modern, **cinematic** tool for film-makers. Confident, not toy-like.
- **Mode:** **dark, professional** (matches Meshy + every pro 3D tool; the viewport is the hero so chrome
  recedes). Floating, glassy panels over a full-bleed 3D canvas reads well — but you have latitude to propose.
- **Reference feel:** Meshy's clean task-oriented workspace + Spline's friendly editor + a cinematic edge.
- **Existing identity (evolve or replace, your call):** near-black blue canvas (`#07080D`), glass panels,
  per-workspace accent (Robotics = indigo-violet, Film = magenta-violet); we want a **distinct accent for the
  Assemble workspace** (suggestion: a warm amber "workshop" tone — propose what's best). Type today is Space
  Grotesk (display) / Inter (UI) / JetBrains Mono (data) — keep or improve.
- **Iconography:** clean line icons; clear Move/Rotate/Scale gizmo affordances.

## 8. Constraints / do-not-invent
- The assembler is **real-time in-browser** → assets must be **lightweight** (hence Low-Poly). Don't imply
  photoreal real-time editing — photoreal is the **render** step.
- Don't invent features without a backend: no in-app sculpting/boolean modeling, no auto-scene "generate a
  whole scene" button (the user assembles), no rigging UI yet.
- Respect the **long waits** (terrain ~6 min, renders ~1–2 min) with honest, calm progress — don't fake speed.
- Keep generation **cancellable** and the app usable while jobs run.

## 9. What we need from Claude Design
1. The full **studio layout** (workspace switch, the 3 zones, command bar) — desktop-first.
2. The **assembly canvas** screen in all key states (empty, selected+gizmo, populated, generating-an-asset).
3. The **Generate** flow + **Library** + **Inspector** (asset + scene) + **Terrain** generator + **Finish/export** gallery.
4. Empty / loading / progress / error states for every async action.
5. A coherent **visual system** (color, type, components, icons) and the **Assemble** accent.
6. Responsive behavior notes (degrade gracefully on smaller screens).
