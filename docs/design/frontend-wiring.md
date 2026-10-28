# MotionLab Studio — Frontend Wiring Plan (2026-07-13)

The frontend was rebuilt from the Claude-Design handoff bundle (`Motionlab studio design brief-handoff.zip`
→ prototype in `Main Section.dc.html`). This doc maps **every control to its backend wire** and states
plainly what is live, what is local-only, and what is planned. The serving stack is unchanged:
Caddy `:8088` → static `frontend/dist` + `/api/cad/*` → `:8765` (Track A) + `/api/trackb/*` → `:8770`
(Track B) + `/presets/*` static, fronted by the Cloudflare quick-tunnel.

Verified E2E on 2026-07-13 through `:8088` (the exact submit→poll path the app uses):
- `text2mesh` 512: job `073433f55cae` → 998k-face GLB in 66 s, **real gate rows** (M1–M10) rendered
  in the verification card.
- `generate` with vLLM down → typed `URLError … Connection refused` rendered in the error card
  (failures are first-class, per the brief).

## Source layout

| file | role |
|---|---|
| `src/theme.css` | design system: CSS vars, keyframes, the data-attribute hover system (verbatim from the prototype helmet) |
| `src/sx.ts` | style-string → React style parser (prototype styles copied verbatim → no pixel drift) |
| `src/icons.tsx` | the full SVG symbol set from the prototype `<defs>` |
| `src/api.ts` | Track A + Track B async-job clients (`submit → {job_id} → poll`), `/edit`, `health()` |
| `src/gltf.ts` | GLB parse/export/thumbnail + **binary/ASCII STL parser** (CAD `mesh_stl_b64`) |
| `src/persist.ts` | IndexedDB library persistence (GLB blobs deduped) |
| `src/viewport.ts` | the persistent WebGL viewport (orbit/pan/zoom/pick, gizmo cube, explode entrance, joints, extents, wire/xray, warm light, thumbnails) |
| `src/store.tsx` | the Studio contract: routing, auth, tasks, library, health |
| `src/App.tsx` | task engine: submit → poll → verification card → library |
| `src/screens/*` | Login, Shell (sidebar/header), Dashboard, Projects, ProjectDetail, Settings, Editor, Result, GenerateModal |

## Wiring map

### LIVE (real backend)
| control | wire |
|---|---|
| Dashboard GENERATE / START TO GENERATE / header GENERATE — CAD·PART | `POST /api/cad/generate {prompt}` → poll `GET /api/cad/job/<id>` |
| — CAD·ASSEMBLY | `POST /api/cad/plan {prompt}` (server runs the plan→verify→repair loop, best attempt ships) |
| — MESH (tier FAST/QUALITY/HERO) | `POST /api/trackb/text2mesh {prompt, pipeline_type: 512/1024_cascade/1536_cascade}` |
| Generate-modal GENERATE (image drop) | `POST /api/trackb/image2mesh {image_b64, pipeline_type}`; **Multi-view (Beta) toggle → the real `multiview` flag** (the vehicle side-profile rule) |
| Editor EDIT (assembly loaded) | `POST /api/cad/edit {assembly, instruction}` — the real parametric-edit lane |
| Editor EDIT (part/mesh loaded) | re-runs `/generate` with the instruction appended to the original prompt (no part-edit route server-side yet — see Planned) |
| RE-GENERATE / RETRY | re-submits the last run (same track/kind/tier/prompt/image) |
| Verification card rows | CAD: `inspection[]` verbatim (name/expected/measured/delta/within_tol/category). Mesh: `report.gate.rows` (M1–M10 + W*) + faces/PBR/size summary rows |
| Attempt timeline chips | CAD `history[]` (fails per verify round) + `attempts`; mesh = single attempt from gate |
| VERIFIED / N FAILED seal | CAD `passed`; mesh `report.gate.passed` (profile-gated; warn rows still shown ✕) |
| Joint panel (assemblies) | joint count from `assembly.joints`, sweep verdict from the kinematic `inspection` rows; slider articulates demo joints only — real articulation needs per-part meshes (Planned) |
| Exports STL / STEP / CODE / GLB | client-side downloads of `mesh_stl_b64` / `step_b64` / `code` / `glb_b64` |
| Editor FILE | loads a local `.glb`/`.stl` into the viewport (client-side parse) |
| Engine pills (header) | `GET /api/cad/health` + `GET /api/trackb/health`, 20 s poll. Assembly pill = the CAD process. NOTE: Track B `/health` says "reachable", not "warm" — weights may still be streaming |
| Generation Tasks panel | real task list; stage + elapsed from the poll loop; % = elapsed/estimate (the backends don't emit fractional progress) |
| Recent Models / Projects / Project detail / gallery | the persisted library (IndexedDB): every finished job with artifacts, thumbnail (offscreen render), checks count, engine tag, verified/failed seal |

## Generation theater (added 2026-07-13, second pass)

The running phase is no longer a spinner — both tracks show the pipeline's REAL intermediate
artifacts as they happen:

**Mesh (Track B — no backend change needed):**
- The FLUX concept image slides in the moment the backend publishes `concept_png_b64`
  (deliver-once semantics on the server; the client latches it).
- With Multi-view on, the MV-Adapter views fly in from the four screen corners as
  `mv_views_b64[]` arrives (256px thumbnails).
- On completion the GLB loads behind an animated clipping plane and un-clips bottom→top —
  the mesh "reconstructs" in the viewport (`viewport.revealGlb`).

**CAD (Track A — new progress channel):**
- `cad_pipeline/progress.py` — a contextvar sink installed per job THREAD by `server._run_job`;
  `publish(**fields)` from anywhere inside the job lands in the job record. No sink ⇒ no-op:
  evals/training byte-identical (regression: test_assembly 5/5 + test_kinematic 31/31).
- `planner._chat` streams the vLLM tokens (SSE) when a sink is active and publishes the growing
  assembly JSON as `spec_stream` → the user watches the spec being written in real time.
  (Non-streaming original request when inactive.)
- `asm_loop.run_assembly` publishes attempt stages + the locked `assembly` JSON per attempt;
  `server` publishes parse/build/verify/export stages; `/generate` publishes the parsed `spec`.
- `assembly.build_assembly` publishes each placed part as `{name, role, stl_b64}` (≈30 KB each)
  the moment it's built — parts changed by the cut phase (wheel arches) re-publish with
  `revised: true`.
- `GET /job/<id>?parts_after=N` returns `{stage, attempt, spec, spec_stream, assembly,
  parts_total, parts[N:]}` while running — the client accumulates, so parts transfer once.
- Frontend: each arriving part DROPS into the viewport (ease-out fall + fade, smooth camera
  re-fit) — the assembly constructs in front of the user. The staged per-part meshes are KEPT as
  the final model (real per-part visibility in the editor's Component Parts panel) and are
  PERSISTED on the library item (`Model.parts`), so re-opening a saved assembly replays the
  construction. The live-spec panel shows the streaming JSON + a construction checklist.

Verified: golden `/generate` streamed `stage` + `spec` mid-run over HTTP; `build_assembly`
published 5/5 stool parts with sink and zero events without; sink append + `parts_after` slicing
unit-tested; real text2mesh 512 delivered `concept_png_b64` mid-run through the tunnel path.
NOT yet run live: the `/plan` token-streaming + parts stream E2E (needs the Track A vLLM serve,
currently stopped) — first rover-style /plan after relaunch will exercise it.

## Users, auth & per-user data (added 2026-07-13, third pass — REAL now)

`studio_api/server.py` (stdlib + SQLite) on `:8092`, proxied at **`/api/studio/*`**:
- **Auth**: email+password signup/login → PBKDF2-HMAC-SHA256 (240k iters, per-user salt), opaque
  bearer tokens in a sessions table (revocable; 45-day sliding TTL). Login failures are
  constant-shape (no email-exists leak). `POST /signup|/login|/logout`, `GET/PATCH /me`.
- **Per-user data**: every row scoped by `user_id`. `GET/POST /projects`,
  `GET /models` (light metadata + thumb + inspection — no meshes),
  `GET /models/<id>` (full artifacts), `POST /models`, `DELETE /models/<id>`.
- **Storage**: `studio_data/studio.db` (WAL) + one JSON artifact file per model under
  `studio_data/artifacts/` (STL/STEP/GLB/code/spec/assembly/per-part meshes) — list endpoints stay
  light; the frontend hydrates artifacts on first open of a model.
- **Frontend**: token in localStorage; boot validates `GET /me` (401 → clean login screen);
  `finishModel` POSTs the model (with thumb) to the account; projects/settings wired to the API.
  One-time migration: on first sign-in with an empty server library, the pre-auth IndexedDB
  library uploads into the account.
- Verified E2E through Caddy: signup → save-with-artifacts → light list → hydrate → project
  counts → cross-user isolation (list + direct id) → bad-token 401. 13/13 direct API checks.
- Run: `python3 -m studio_api.server 8092` (stdlib only; log `/workspace/.hf_home/studio_api.log`).

## Quick-win pack (2026-07-13, fourth pass)

- **Real joint articulation**: the result-screen slider now rotates the ACTUAL jointed parts —
  on first drag, `viewport.configureJoints` wraps each joint's part mesh in a pivot group at the
  joint's axis point (`Joint.at`, bbox-center fallback) and rotates about the real axis within
  the real limits. Works on any saved assembly (per-part meshes + joints persist).
- **Display flyout** (editor rail): solid/wire/x-ray mode, EXPLODE slider (parts move outward
  from the assembly centroid), SECTION slider (clip plane slices from the top — shell interiors).
- **Prompt dice 🎲** (dashboard): `POST /api/cad/suggest {track}` → one playful buildable brief
  (themed, casual/metric mixed, ~1-2s via the serve; graceful toast when the engine is down).
- **First-login seeds**: `studio_data/seeds/` (built by `training/build_seed_models.py` —
  deterministic golden families + terrain preset; full artifacts incl. per-part meshes, verified
  rows, rendered thumbs). `_seed_models` inserts them into an "Examples" project on signup
  (per-user artifact copies; existing account backfilled).
- LLM naming (`/name`) + project picker (gen-panel destination + result-card move via
  `PATCH /models/<id>`) landed earlier the same day.

### LOCAL-ONLY (by design)
share links (client-generated string) · suggestions panel toggles · parameters sliders (first
slider scales the viewport model; true parametric regen is Planned) · language/theme pickers ·
password reset (admin-assisted — no email infra on the box).

### PLANNED (backend work, in priority order)
1. **Per-part meshes for assemblies** — `/plan` returns one fused STL; return `parts: [{name, stl_b64, at, rotate}]`
   so the joint slider articulates the *real* geometry and the parts panel eye-toggles work per part.
   (Server change in `cad_pipeline/server.py:_assembly_job` — build each component solid separately.)
2. **Part-level `/edit`** — accept `{spec, instruction}` and reuse the verifier loop, replacing the
   prompt-append workaround.
3. **Mid-job progress for CAD** — `/job/<id>` only returns `{status, elapsed}` while running; emit
   `stage` + `attempt` so the running card can show the live attempt timeline (it currently fills in
   at completion).
4. **`/lowpoly`, `/repair`, `/terrain` lanes** — clients exist in `api.ts` (kept from the old app);
   surface as post-processing actions on mesh results (the modal's "Low Poly"/"Remesh" buttons toast
   for now).
5. **Concept-image → CAD** (editor IMAGE button) and **retexture/refine** modal tabs — blocked on the
   image→CAD lift + Paint 2.1 adoptions from the research audit.
6. Quality score (0–1 gates × judge) chip on library cards — `judge.py` exists server-side.

## Ops notes
- Rebuild after src changes: `cd frontend && npx tsc --noEmit && npm run build` (Caddy serves `dist/` statically — no restart needed).
- Old frontend preserved at `frontend-backup-20260713/` (src only, gitignored).
- CAD API `:8765` was relaunched 2026-07-13 (`setsid nohup cad_pipeline/.venv/bin/python -m cad_pipeline.server 8765 > /workspace/.hf_home/cad_server.log`) — the HTTP server holds **no GPU**; model calls fail typed until the vLLM serve (`serve_qwen_fp8_lora.sh`) is back.
