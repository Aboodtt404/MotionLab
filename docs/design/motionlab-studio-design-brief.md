# MotionLab Studio — Full-App Design Brief (for Claude Design)

**Purpose.** Design, from scratch, the **entire MotionLab studio web app** — the current frontend will be
deleted and replaced by this design. This is the single source of truth. (Supersedes the earlier
`frontend-redesign-spec.md` and `assembler-design-brief.md`, which are folded in here.)

> **Design TO the architecture, not around it.** Every screen below maps to a real, working backend route.
> Where it says "the backend returns X" or "this takes ~N min/sec," that's a real contract — surface X
> **honestly**, design the **empty / loading / progress / error** states for that reality, and **do not invent**
> capabilities, fake metrics, or data the backend doesn't produce.

---

## 1. The product

MotionLab is a **self-hosted AI 3D studio** for an in-house team. One cohesive studio app, **three workspaces**
for **two kinds of users**:

| Workspace | Does | User |
|---|---|---|
| **Robotics** | text/image → **verified parametric CAD** → STEP/STL | engineers (precision, manufacturability) |
| **Create** | text/image → **generative 3D assets** (organic, PBR) → GLB/USDZ | film-makers / 3D artists |
| **Assemble** | **compose generated assets into a 3D scene** in-app, then render | film-makers / 3D artists |

**Create + Assemble share one Library** (generate assets in Create, drop them into Assemble). The studio has a
**top-level workspace switcher**. The same dark, cinematic visual system runs throughout, with a **per-workspace
accent** so each mode feels distinct.

**The strategic frame:** Create+Assemble is a **Meshy-style** flow (generate assets) **plus the in-app scene
assembler Meshy lacks** (Meshy makes you assemble in Blender/Unreal; we do it in the browser). That assembler
is the product's signature — give it the most design love.

## 2. Shared studio shell (applies to all workspaces)

- **Top bar:** brand (MotionLab); **workspace switch** (Robotics · Create · Assemble); shared **view/look-dev
  tools** for the 3D viewport (solid/wireframe/x-ray, turntable, lighting mood, frame, snapshot).
- **Three working zones** over a **full-bleed 3D viewport** (the viewport is the hero; chrome floats over it):
  - **Left:** contextual — Robotics: input mode + tools; Create: input mode + Library; Assemble: **Library ⇄
    Outliner**.
  - **Right:** **Inspector** — the contextual workspace (live editor / properties / results).
  - **Bottom:** **command bar** — the primary prompt/input + the workspace's main action button.
- **Everything generative is an async job** (see §6): non-blocking, **staged progress**, **cancellable**.
- Desktop-first; degrade gracefully on smaller screens.

## 3. Workspace A — Robotics (parametric, verified CAD)

**Flow:** describe a part (text) or upload an image (+ a real-world **scale anchor in mm**, since vision can't
recover absolute size) → the system interprets it into a **spec**, generates real CadQuery geometry, and
**verifies it against the spec** → export **STEP** (parametric BREP for CAD/CAM) or **STL** (mesh for printing).

- **Left:** input mode (Spec/Prompt · Image+scale), an **Assembly** toggle (multi-part), asset Library.
- **Right Inspector — the live spec editor** (this is rich; design it well):
  - Object name; **shape** (Box · Cylinder · Loft; Revolve/Sweep are prompt-defined, read-only here);
  - **Envelope** dimensions (box: L/W/H; cylinder: ⌀/H; loft: +tip W/H) — number inputs + sliders;
  - **Features** list, each editable: through-hole (⌀, position, axis), hole-pattern (bolt-circle/linear/grid,
    count, PCD…), counterbore, countersink, fillet (r), chamfer (d), pocket (L/W/D), shell (wall, open face);
    add-feature menu (incl. M3/M4/M6 quick holes);
  - **Tolerance** (± mm); **Fabrication** (Render vs Fabricate → reveals **min-wall** for DFM);
  - inline **warnings** (e.g. "hole ⌀12 exceeds the 10 mm face").
- **Right Inspector — the result = the VERIFICATION TABLE (the hero output).** A per-feature table:
  *Feature · Expected · Measured · ±tolerance gauge · pass/fail*, plus "watertight · manifold" and "selectors
  resolved N/N." This is what makes Robotics trustworthy — make it the centerpiece, not an afterthought. Show
  "N attempts" (the system auto-retries) and any auto-correction.
- **Assembly mode:** first prompt **plans** a multi-part object; subsequent prompts **edit** it ("make the legs
  20 mm longer"). Show the part is structurally supported.
- **Export:** STEP + STL (label what each is for). The 3D viewport shows the live spec preview, then the real
  generated mesh.
- **Backend reality (`/api/cad`, async):** `/generate {spec | prompt, fabrication, min_wall}` → `{passed,
  attempts, code (CadQuery), spec (interpreted), inspection[ {name, expected, measured, delta, within_tol} ],
  mesh_stl_b64, step_b64}`. `/plan {prompt}` + `/edit {assembly, instruction}` → assembly + same report.
  The interpreter is a **fine-tuned local LLM** (can take >a few s — design the wait). **Don't** invent
  fidelity scores or sliders the backend doesn't have; the verification table IS the proof.

## 4. Workspace B — Create (generative 3D assets)

**Flow:** text prompt or image → a textured 3D asset → refine (low-poly) → it lands in the **Library** for
Assemble. Plus ground/terrain tiles, a photoreal render, and a motion clip.

- **Input:** prompt OR image (drag-drop). Options: **Quality tier** with honest time hints — *Preview ~30s ·
  Standard ~1 min · High ~1.5 min · Max detail ~2–2.5 min*; **Multi-view** toggle ("front/side/back to lock
  geometry," +~30s).
- **Generating state:** real stages *queued → concept image (FLUX) → generating mesh*; **show the concept
  image** when it appears (real intermediate, click-to-zoom); **cancellable**; honest progress.
- **Result:** the textured 3D asset in the viewport + a report (face count, **PBR maps** present, watertight,
  time). Actions: **Low-Poly / game-ready** (a target-polycount slider, e.g. 1k–100k — turns a dense asset
  game-ready; design before/after), **add to Library / Assemble**, **export GLB / USDZ**.
- **Terrain/ground generator** (distinct, **heavier ~5–6 min** — design a patient, reassuring wait): pick a
  **biome** (plain, desert, forest, snowy mountain, arctic, mountain, coast, canyon, cliff, river) → a placeable
  ground tile.
- **Finish (per asset or scene):** **Photoreal render** (path-traced Cycles still + turntable, ~1–2 min) and
  **Motion clip** (render-to-real video from the turntable, ~40s, two variants). Design the output gallery
  (image, video player, downloads).
- **Library:** thumbnail grid of generated assets (name, type, poly/size, status), search/filter, quick
  actions (add-to-scene, Low-Poly, duplicate, delete, export); in-progress cards.
- **Backend reality (`/api/trackb`, async):** see §6 table.

## 5. Workspace C — Assemble (in-app scene assembly) — the signature screen

A real-time 3D canvas where the user composes a scene from Library assets. (No Meshy equivalent; borrow canvas
conventions from **Spline** / **three.js editor** / **Blender**.)

- **Left:** **Library** (assets to drop in, + "＋ Generate") ⇄ **Outliner** (placed objects: select/rename/
  hide/delete).
- **Canvas (center):** orbit/pan/zoom over a ground/terrain tile. **Add:** drag an asset in → drops on the
  ground at the cursor. **Select:** click object or outliner row (highlight). **Transform:** a **gizmo** with
  **Move / Rotate / Scale** modes (top-bar toggle + **W/E/R** shortcuts), drag axis/plane handles. **Duplicate**
  (Ctrl/Cmd+D), **Delete** (Del). **Ground-snap** so assets never float ("drop to ground"). Grid + soft shadow.
- **Right Inspector:** selected → numeric **transform** (pos/rot/scale + reset) + **Low-Poly / Duplicate /
  Delete / Export**; nothing selected → **scene settings** (ground/terrain tile, lighting mood, environment).
- **Bottom command bar:** inline "generate a new asset" + **Finish**: **Export GLB** (whole scene, instant,
  client-side) · **USDZ** · **Render** (photoreal Cycles of the composed scene) · **Animate** (LTX motion).
- **States to design:** empty canvas (invite drag/generate), object selected (gizmo + inspector), populated
  scene, mid-drag, generating-an-asset-without-leaving, terrain present vs absent.

## 6. Backend reality — the contracts to design to

**Async everywhere:** the client POSTs → gets a `job_id` → polls `GET /job/<id>` → `{status:
queued|running|done|error, stage, elapsed, …result}`. So **every generative action = a non-blocking, staged,
cancellable progress state**; the app stays usable while minutes-long jobs run.

| Action | Route | Returns | Time |
|---|---|---|---|
| **Robotics** part | `/api/cad/generate {spec\|prompt, fabrication, min_wall}` | verified mesh (STL+STEP) + **inspection table** + CadQuery code | secs–~min |
| Robotics assembly | `/api/cad/plan`, `/api/cad/edit` | multi-part assembly + report | ~min |
| Text → 3D asset | `/api/trackb/text2mesh {prompt, tier, multiview}` | GLB+PBR, **concept image**, face/vert/watertight report | 30s–2.5min |
| Image → 3D asset | `/api/trackb/image2mesh {image, tier, multiview}` | same | 30s–2.5min |
| Low-Poly | `/api/trackb/lowpoly {glb, target_faces}` | decimated GLB + report | ~8s |
| Terrain tile | `/api/trackb/terrain {biome, target_faces}` | vertex-colored GLB tile | **~5–6 min** |
| Photoreal render | `/api/trackb/render {glb, samples, res}` | beauty PNG + turntable MP4 | ~1–2min |
| Motion clip | `/api/trackb/animate {turntable, first_frame, variant}` | MP4 | ~40s |
| Cancel | `…/cancel/<id>` | — | instant |

Real facts to surface honestly: assets carry **PBR** (base color, metallic-roughness, normal); export = GLB /
USDZ (+ STEP/STL for Robotics); terrain tiles are **vertex-colored** (real-time) with full photoreal only in
the render. **No** fake fidelity scores / best-of-N / metrics the backend doesn't return.

## 7. Visual direction

- **Brand:** "MotionLab" — a precise, modern, **cinematic** tool. Confident, professional, not toy-like.
- **Mode:** **dark, professional** (the 3D viewport is the hero; chrome recedes). Floating glassy panels over a
  full-bleed canvas works well — but propose what's best.
- **Per-workspace accent** (distinct identity per mode): **Robotics** = cool indigo-violet (technical);
  **Create** = warm magenta-violet (cinematic); **Assemble** = a distinct third (suggestion: warm amber,
  workshop/build feel — propose).
- **Reference feel:** Meshy's clean task-oriented workspace + Spline's friendly editor + a cinematic edge.
- **Type today** (keep or improve): Space Grotesk (display) · Inter (UI) · JetBrains Mono (data/measurements).
- Clean line iconography; clear gizmo affordances in Assemble.

## 8. Constraints / do-not-invent
- Robotics: the **verification table** is the trust signal — don't bury it; don't fabricate metrics.
- Create/Assemble are **real-time in-browser** → assets must be **lightweight** (hence Low-Poly); photoreal is
  the **render** step, not live. No in-app sculpting/boolean/rigging UI (no backend).
- **No auto-"generate a whole scene"** button in Assemble — the user composes; the AI makes the parts.
- Respect **long waits** (terrain ~6 min, renders ~1–2 min) with calm, honest progress; keep jobs cancellable.

## 9. What we need from Claude Design
1. The **studio shell** (workspace switch, 3 zones, viewport, command bar) — desktop-first, responsive notes.
2. **Robotics** workspace: spec editor + the verification-table result + assembly mode + export.
3. **Create** workspace: generate flow + result/refine + terrain + render/motion gallery + Library.
4. **Assemble** workspace (the signature): canvas in all states (empty, selected+gizmo, populated, generating),
   Library/Outliner, Inspector, finish/export.
5. **Empty / loading / progress / error** states for every async action.
6. A coherent **visual system** (color, type, components, icons) with the three workspace accents.
