# MotionLab — Frontend Redesign Spec (for Claude Design)

**Purpose.** A complete, architecture-grounded brief to redesign the MotionLab studio UI/UX from scratch around its two real users — a **Robotics** team and a **Film-making** team — while staying faithful to what the backend actually does. Every requirement below traces to a real capability or constraint of the system. Design *to the architecture*, not around it.

> Read this as the source of truth for the redesign. Where it says "the backend returns X," that is a real contract — surface X, don't invent metrics. Where it says "this takes ~2 min," design the waiting state for that reality.

---

## 1. What MotionLab is

A **self-hosted** AI 3D-asset generator for film + engineering, running on a single multi-GPU box (vast.ai). Two independent generation tracks, one shared 3D viewport, one app. Users describe an object in **text** or upload a **reference image**; the system produces a real, downloadable 3D asset.

- **Track A → the Robotics workspace** — hard-surface *parametric CAD*. Text/spec → typed Spec → CadQuery → a verified BREP solid. Output: **STEP + STL**. Deterministic, dimension-accurate, **verified against the spec**. Fast (seconds).
- **Track B → the Film workspace** — *organic generative mesh*. Text → concept image (FLUX) → 3D mesh (TRELLIS.2) with PBR. Or image → mesh directly. Output: **GLB (+PBR), USD**. Slow (minutes), asynchronous, art-directed.

The redesign keeps **one app with a top-level Robotics ⇄ Film switch**. The 3D viewport, asset library, and shell are shared; everything else (inputs, settings, results, exports, terminology) is per-workspace.

---

## 2. Architecture constraints that *drive* the UX

These are non-negotiable realities the design must accommodate.

| Constraint | Source | UX consequence |
|---|---|---|
| **Track A is fast + synchronous** (~1–10 s) | CadQuery build + verify in-process | Robotics generation can feel near-instant; a light staged progress is fine. |
| **Track B is slow + asynchronous** (~30 s at `512`, **~2–2.5 min at `1536_cascade`**) | TRELLIS.2 diffusion + CPU mesh extraction | Film needs a **first-class long-running job UX**: live stage + elapsed, cancel, and the ability to leave/return. |
| **Cloudflare tunnel cuts any single request at ~100 s** | quick-tunnel limit | Track B uses a **submit→poll** job model (`POST → {job_id}`, then `GET /job/{id}`). The UI must reflect job *status/stage*, never a single hanging spinner. |
| **One GPU, jobs serialized** | single device, resident models | At most one heavy job runs at a time. Design for a **queue/"busy" state** if a second request arrives. |
| **The verifier is the core IP** (resolve-twice selector binding, feature-level dimensional check) | Track A `verifier.py` | The **verification report is the hero** of the Robotics result — not a footnote. |
| **Aesthetics have no objective fixpoint** | Track B | Film ends in a **human art-direction sign-off** (Approve), not a pass/fail score. Never fake a "fidelity score." |
| **Backend can be offline** → deterministic mock fallback | dev resilience | Every result surface needs an **offline/degraded** state (clearly labeled "preview, not a real result"; exports disabled). |
| **Self-hosted, no external wallets/services** | infra | No third-party login/upsell UI. It's an internal tool for two teams. |

**Honesty principle (hard rule):** only display values the backend actually returns. The previous UI faked a "Visual fidelity · VLM judge / Best of N" card and placeholder export files — both were removed. Do not reintroduce invented metrics, fake progress percentages decoupled from real stages, or export buttons that don't emit the real asset.

---

## 3. Real data contracts (design to these fields)

### Track A — `cad_pipeline` (proxied at `/api/cad`)
- `POST /generate {prompt | spec, use_model?, max_attempts?}` →
  `{ passed: bool, attempts: int, history[], code: string|null (CadQuery), spec, inspection: Row[], mesh_stl_b64, step_b64 }`
- `POST /plan {prompt}` and `POST /edit {assembly, instruction}` → multi-part **assembly**:
  `{ passed, assembly, components: int, object, inspection: Row[] (incl. per-component "part · NAME" rows), mesh_stl_b64, step_b64 }`
- **Inspection Row** = `{ name, expected, measured, within_tol: bool, category, delta }` → the dimensional table.
- **Spec features** available (expose progressively): positioned `through_hole` (at[x,y]/axis), `hole_pattern` (bolt_circle/linear/grid), `counterbore`, `countersink`, `fillet`, `chamfer`, `pocket`, `shell` (hollow + open_face), `draft`, `thread`, `mirror`, `greeble` (sci-fi detail), and shapes `box | cylinder | loft | revolve | sweep`. `tolerance` (± mm), DFM gates (`fabrication`, `min_wall`).

### Track B — `track_b` (proxied at `/api/trackb`)
- `POST /text2mesh {prompt, pipeline_type, seed}` and `POST /image2mesh {image_b64, pipeline_type, seed}` → `{ job_id }` (returns instantly).
- `GET /job/{id}` → `{ status: queued|running|done|error, stage: concept|generating, elapsed: sec, ...when done: glb_b64, report, seconds, pipeline_type, concept_png_b64 }`.
- **report** = `{ faces, verts, watertight: bool, pbr: string[] (e.g. baseColorTexture, metallicRoughnessTexture), size_mb }`.
- **Quality tiers** (`pipeline_type`): `512` (fast, ~30 s) · `1024` · `1024_cascade` · `1536_cascade` (max detail, ~2–2.5 min). Higher = more geometry + sharper texture + longer.
- **Stages**: `concept` = FLUX is painting the concept image; `generating` = TRELLIS is lifting it to 3D + extracting the mesh.

### Shared viewport (Three.js, already real)
Solid / wireframe / x-ray view modes · turntable play-pause · lighting moods (studio / dramatic / soft / rim) · **snapshot → PNG** · frame/recenter · scale-figure reference (1.7 m human) · wall-thickness heatmap. Renders real **STL** (Track A) and **GLB w/ PBR** (Track B).

---

## 4. The two users (personas + jobs-to-be-done)

### 4a. Robotics engineer — "I need a correct, fabricable part."
- **Mindset:** precision, trust, repeatability. Millimeters and tolerances matter. Wants proof the geometry matches intent before sending to a printer or CAM.
- **Inputs:** a spec (dimensions + features) typed in a structured editor, OR a natural-language description ("80×50×30 bracket, 4 mm fillet, ⌀12 hole, ±0.1"), OR a reference image **+ an explicit real-world scale** (vision can't recover absolute size).
- **Core loop:** edit spec → generate (seconds) → **read the verification report** → adjust → export **STEP** (CAD/CAM) or **STL** (print).
- **Power features:** multi-part **assemblies** (plan a stool/bracket-stack, then edit it conversationally), fabrication mode with **min-wall DFM** checks, hole patterns, counterbores.
- **Emotional need:** *confidence.* The UI must make "this is verified, watertight, selectors resolved N/N, within ±tol" unmissable.

### 4b. Film artist / art director — "I need a great-looking asset, fast to iterate."
- **Mindset:** visual exploration, speed of iteration, art direction. Exact dimensions don't matter; the *look* does.
- **Inputs:** a text prompt ("a battle-worn recon drone…") or a concept/reference image. A **look/style** selector.
- **Core loop:** prompt → **review the FLUX concept image** → (reseed if not feeling it) → wait for the 3D lift → **look-dev** (lighting, turntable) → **approve** → export **GLB/USD** for Blender/Houdini/Unreal.
- **Power features:** quality-tier selector (fast preview ↔ hero render), concept-image reseed, look-dev presets, art-direction sign-off.
- **Emotional need:** *flow.* Long waits must feel productive (show the concept image immediately, let them keep working), and iteration must be one click.

---

## 5. Information architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  RAIL (left)        STAGE (center, shared)            PANEL (right)  │
│  ───────────        ──────────────────────            ───────────── │
│  ◆ Logo             3D viewport (STL or GLB+PBR)       RESULT card   │
│  ┌─────────┐        · view modes / turntable /          (per-team)  │
│  │ROBOTICS │ ←      ·  lighting / snapshot / frame      ───────────  │
│  │  FILM   │  team  · concept-image inset (film)        SETTINGS     │
│  └─────────┘ switch · generating overlay (stage+timer)    (per-team) │
│  · input mode       PROMPT DOCK (bottom, per-team)                  │
│  · asset library    · examples · image upload · Generate            │
└────────────────────────────────────────────────────────────────────┘
```

- **Team switch** (Robotics ⇄ Film) is the **primary axis**, top of the rail. Switching reconfigures inputs, settings, result card, exports, terminology, and defaults. It's the single most important control — make it unmistakable and stateful (the whole app should *feel* different per team without becoming a different app).
- **Shared:** stage/viewport + all view tools, asset library, prompt-dock chassis.
- **Per-team:** settings body, result card, export set, prompt placeholder/examples, accent metadata.

---

## 6. Screen / component spec

### 6.1 Shared — Stage & viewport
- Large 3D canvas, dark studio gradient, ground plane + soft shadow. Orbit (drag), zoom (scroll).
- **Top-left:** asset name + workspace badge (ROBOTICS / FILM) + an envelope/size readout (Robotics: `80 × 50 × 30 mm`; Film: `120 mm tall` target).
- **Top-right view toolbar:** Solid / Wireframe / X-ray · (Robotics: Dimensions toggle) / (Film: wall-thickness heatmap) · Frame · Snapshot.
- **Stage pill:** turntable play/pause · lighting mood picker (studio/dramatic/soft/rim) · (Film: scale-figure toggle).
- **Generating overlay** (center): see §7.
- **Concept-image inset** (Film only): when a text→mesh job is running/done, show the FLUX concept thumbnail top-left ("concept · FLUX") so the artist sees *what's being built* during the long lift.

### 6.2 Robotics workspace
**Settings panel (the parametric editor):**
- Object name; **shape** toggle: Box · Cylinder · Loft (revolve/sweep are prompt-defined → show an inline note, not broken fields).
- **Envelope** fields per shape (Box: L/W/H; Cylinder: ⌀/H; Loft: length + base W/H + tip W/H) — number + slider, live.
- **Features list** — each feature is a card with its params. Param types: **number** (diameter, depth…) and **enum dropdown** (axis x/y/z, pattern bolt_circle/linear/grid, open_face top/bottom/none). "Add feature" menu grouped: Holes (through-hole, pattern, counterbore, countersink) · Edges (fillet, chamfer) · Recesses (pocket) · Body (shell). Quick-add chips for standard metric holes (M3/M4/M6).
- **Tolerance** (± mm). **Fabrication** section: Render ⇄ Fabricate; Fabricate reveals **min-wall** (DFM). Live **warnings** (hole won't fit, shell leaves no cavity, etc.).
- **Assembly mode:** a toggle that turns the prompt into a *planner* — first prompt plans a multi-part design, subsequent prompts *edit* it. When an assembly exists, show a **component list** with per-component pass/fail.
- **Model toggle (real):** golden deterministic builder ⇄ fine-tuned Qwen3.6-27B.

**Result card (verification is the hero):**
- Big status: **Verified** (green) / fails (red) / **Offline preview** (amber, when mock fallback ran).
- **Dimensional inspection table** — per feature: name · expected · measured · pass dot · a **tolerance gauge** (a track with a ±band and a marker showing where the measured value lands). This is the signature element — make it precise and legible (monospace numbers).
- "Watertight · manifold" + "**Selectors resolved · N/N**" (resolve-twice IP) lines. A "corrected · …" line when the generate→verify→retry loop fixed something.
- For assemblies: per-component pass/fail rolled into one "Assembly verified" header.
- **Export:** STEP (parametric, CAD/CAM) + STL (mesh, printing). Disabled with a reason tooltip when the payload is absent. Caption: "STEP = parametric BREP · STL = mesh."

### 6.3 Film workspace
**Settings panel:**
- **Look** selector (style swatches; in future steers the FLUX concept).
- **Quality tier** selector: 512 (fast preview) · 1024 · 1024_cascade · 1536_cascade (max) — **with honest time hints** ("~30 s" … "~2–2.5 min"). This is the speed/quality dial; make the trade-off obvious.
- Organic params: detail, symmetry, target height (mm).
- **Concept review:** the FLUX concept image with a **Reseed / Regenerate concept** affordance (new seed) before committing to the long 3D lift. (A true "approve concept then lift" gate is a future backend split — design the affordance now.)

**Result card (no fake scores):**
- Status: **Generated**.
- Real mesh report: faces · PBR maps present · watertight · time @ tier.
- **Art-direction sign-off:** Approve ⇄ Regenerate (regenerate re-runs the real pipeline). Approval is a human decision, shown as "Approved by art direction."
- **Export:** GLB (PBR, immediate) + USD/USDZ (for DCC). Caption: "GLB with PBR maps — import into Blender / Houdini / Unreal."

### 6.4 Shared — Prompt dock (bottom)
- Multiline prompt; per-team placeholder + example chips (Robotics: "80×50×30 bracket, ⌀12 hole, ±0.1"; Film: "a weathered gargoyle bust").
- Image-upload affordance (both teams support image input; Robotics image mode also shows a **scale anchor** mm field).
- Primary action button: **Generate** (Robotics) / **Generate** (Film) / **Plan** or **Edit** (Robotics assembly mode).

### 6.5 Shared — Asset library
- Grid of generated assets with **real rendered thumbnails** (use the viewport `snapshot()` at generation time — today they're placeholder icons; the redesign should capture a real thumbnail). Each card: name · class badge (robotics/film) · pass dot · version. Click to reload into the stage.

---

## 7. The waiting / job experience (most important new UX)

Track B jobs run **minutes**. This must feel intentional, not broken.

- **Generating overlay** shows the **real stage**, not a fake %:
  - Robotics: "Generating CadQuery → Executing → Verifying" (fast, fine as staged).
  - Film: "Painting concept (FLUX)" → "Lifting to 3D (TRELLIS)" with a **live elapsed timer** and the concept thumbnail appearing as soon as it's ready.
- **Cancel** affordance on long Film jobs (stops polling; note copy: the server job may continue).
- **Busy/queue state** if a second generation is requested while one runs (single GPU).
- **Leave-and-return:** because it's a polled job, the design should allow the user to keep adjusting settings / browsing the library while a job runs, and surface a small persistent "job running" indicator.
- **Error state:** real backend error message, with a retry. **Offline state:** clearly labeled mock preview, exports disabled.

---

## 8. State matrix (every result/stage surface must handle)

| State | Robotics | Film |
|---|---|---|
| Idle / editing | live spec editor + procedural preview in viewport | prompt + look + tier; empty stage |
| Submitting | (n/a, sync) | "queued" instant |
| Running | staged: CadQuery→Exec→Verify | `concept` → `generating` + elapsed + concept thumb |
| Done | verification table + STEP/STL | mesh report + Approve/Regenerate + GLB/USD |
| Failed verification | red rows, which dim is out of tol | (n/a — film has no pass/fail) |
| Backend error | error banner + retry | error banner + retry |
| Offline mock | amber "preview", exports disabled | (text path requires backend; show clear unavailable) |
| Cancelled | — | back to idle |

---

## 9. Design system (keep & evolve)

The current dark "studio" identity works for both a precision tool and a creative tool — **keep the spirit, tighten the execution.**

- **Palette:** near-black studio background (`#08080C`–`#1C1B26` radial), panels `~#14141B`, borders low-contrast. **Accent:** violet (`#7C5CF2` → `#A78BFA`). Status: green `#34D399` (verified), red `#F87171` (fail), amber (offline/warn).
- **Consider a subtle per-team accent shift** so the workspace is instantly recognizable (e.g. Robotics leans cooler/technical, Film leans warmer/cinematic) — without breaking the shared identity.
- **Type:** clean sans for UI; **monospace for all numbers/dimensions/measurements** (precision signal). Robotics leans on mono heavily; Film leans on the imagery.
- **Shape:** rounded 9–16 px, glass-blur floating overlays over the viewport, soft large shadows.
- **Motion:** restrained. Real progress only. A confident "verified" reveal for Robotics; a smooth concept→mesh transition for Film.
- **Iconography:** single-stroke line icons (existing set). Add clear team glyphs (wrench/robotics, clapperboard/film).
- **Density:** Robotics panel is information-dense (a CAD tool); Film panel is sparse and image-forward.

---

## 10. Explicit requirements checklist (for the design deliverable)

Produce screens/states for:

1. **Shell + team switch** — Robotics and Film variants, switch interaction.
2. **Robotics:** spec editor (all feature cards incl. enum dropdowns, shape toggle, fabrication/min-wall, warnings); verification result card with the **tolerance-gauge table**; assembly mode (component list + edit loop); STEP/STL export; offline-preview state.
3. **Film:** prompt dock; **quality-tier selector with time costs**; concept-image review + reseed; long-running **job overlay** (concept→generating, elapsed, cancel); mesh report + **art-direction Approve/Regenerate**; GLB/USD export.
4. **Shared viewport** look-dev toolbar (view modes, lighting moods, turntable, snapshot, scale figure, heatmap) — designed once, themed per team.
5. **Asset library** with real thumbnails + versioning.
6. **Global states:** queued/busy (single GPU), backend error, offline mock, empty/first-run.
7. **Responsive behavior** for a ~1280–1920 px studio window (this is a desktop tool; mobile not required).

**Anti-requirements (do not design):** fake quality/fidelity scores, placeholder exports, marketing/upsell, external wallets/auth, anything the backend can't actually produce.

---

## 11. North star

> A robotics engineer should *trust* the part before they ever open it in CAD.
> A film artist should *enjoy* the wait and *love* the result before they ever open Blender.
> Same engine, same viewport — two crafts, two feelings.
