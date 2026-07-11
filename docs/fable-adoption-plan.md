# Fable-5 Full Adoption Plan (Track A → the whole engine)

**Decision (2026-07-10):** "fully adopt everything from `fable_run/`" = **Option B** — Fable's §1.2
per-part representation decision table + the 8-category benchmark + the router IS the full-8-category
merge of Track A and Track B into one spec-first, verifier-looped engine. This document is the roadmap.

**Governing thesis (Fable manual §Summary):** *"nearly all quality in this domain comes from the
verifier loop, not the first draft."* Every phase below is gated by a verifier and a test — nothing is
"done" until it is measured green.

**Source of truth:** `fable_run/out/{00_manual,02_benchmark,03_training_recipe,04_schemas,05_mistakes}.md`.
Cross-reference every implementation against these; do not drift.

---

## Starting point (verified 2026-07-10)

Track A is ~90% aligned on the CAD/assembly spine. Already present: spec-first pipeline, part library
(partlib.py, 5 parts), capability_score machinery + CAD-20 bench slice, A6 fit row, repair-transcript
reject store, GLB gate, mate-graph solver, feature-program `Part` representation (green, **uncommitted**),
structural-richness arc (profile_extrude/loft/cutout/wheel). SFT done, GRPO built. Partial schema classes
in corpus.py. **DPO never run. Router does not exist. 80 of 100 bench tasks unencoded. Mesh/print/game
verifiers absent.**

---

## Phases (ordered by dependency; each ends committed + green)

### Phase 0 — Commit the green WIP  ✅ unblocks everything
Feature-program `Part` + mate-graph solver + structural-richness arc (~1560 lines, all tests green).
Loss risk. **Deliverable:** clean commit; `git status` clean on cad_pipeline.

### Phase 1 — The 5 schemas (04_schemas.md)  ← foundation, everything references it
Adopt the exact snake_case, `$id`-versioned, composable schemas as Pydantic models + JSON Schema export.
- `model_brief`: add `target_use`/`representation`/`units`/`up_axis`/`output_formats`/`budgets` — the
  fields that let ONE schema drive CAD **or** mesh **or** print (precondition for the router).
- `assembly_brief`: formalize `component_id`/`role`/`brief`($ref)/`count` + `fuse`/`clearance_mm`;
  our `Mate` vocabulary already matches exactly.
- `verifier_report`: conform Report/Row → exact shape; **`check_category` enum** (snake_case:
  `ok/dimensional/selector_binding/missing_feature/integrity/dfm/validity/structure/disconnected/component`)
  — rename our hyphenated `selector-binding`.
- `failure_report`: typed `status`/`category`/`error_signature`/`traceback_head`/`failed_rows`/`feedback`.
- `repair_transcript`: conform corpus.py's class to the exact shape.
- **Deliverable:** `cad_pipeline/schemas.py` (or extend corpus.py) with all 5 + a `test_schemas.py` that
  round-trips each example instance from 04_schemas.md and validates against the JSON Schema. Migrate
  verifier/corpus/asm_loop to emit conformant rows. All existing suites stay green.

### Phase 2 — The 100-task benchmark (02_benchmark.md)  ← makes the score real
Encode all 100 tasks as machine-checkable specs+assertions with the `[BREP]/[MESH]/[GLTF]/[BPY]/[RENDER]/
[WEB]/[CLR]/[UV]` toolkit. Order by what we can pass NOW:
1. **A01–A13** (assembly) + **D01–D08** (drone) — checkable with the verifier we already have. A01 = the
   stool we built. ~21 tasks, weight ~60/263. **First honest multi-category capability_score.**
2. **C01–C20** (have) + **P01–P10** (product) — mostly B-rep.
3. **M/B/W/G** (mesh/blender/web/game) — gated on Phase 3 verifiers + Phase 5 router.
- Harness: pass@1 + pass@3 (feedback loop), capability_score = 100·Σ(w·passed)/263, category sub-scores,
  bands (Weak…Expert), diagnostics (failure histogram, attempts-to-pass, pass@1↔pass@3 gap).
- Holdout discipline: the 100 tasks + near-dups (spec cosine ≥0.9 / AST match) excluded from training.
- **Deliverable:** `cad_pipeline/tests/benchmark/` with all 100 tasks + runner emitting the scorecard.

### Phase 3 — Complete the verifier suite (§3.4, §6, all 46 mistakes)
- CAD gaps: min-wall inward-raycast (10k samples), mass_props (volume×density), fastener_reach.
- **Anti-toy plausibility rows (§2.1)** — fillet hierarchy (3 radius classes), wall-thickness, visible
  fasteners, parting lines. (The "kid-drawing" ceiling lever.)
- **Mesh validation (§6.1)** — watertight/manifold/self-intersect/degenerate/winding/normals (trimesh+pymeshlab).
- **Print (§6.3)** — min wall, overhang, bridge, drain, slicer oracle (PrusaSlicer CLI).
- **Game (§6.4)** — tri budget, material slots, UV, LOD IoU, pivot, naming.
- **Web/GLB (§6.5)** — extend glb_gate to full gltf-validator + headless render smoke.
- Wire every one of the **46 mistakes (05)** as a detection row + typed repair feedback.
- **Deliverable:** one verifier per representation, same `verifier_report` envelope; mistake-catalog
  coverage test asserting each of the 46 has a live row.

### Phase 4 — Part library expansion (§2.4)
Grow partlib to Fable's minimum: fasteners (M2–M6 SHCS/CS/nut/washer + heat-set), bearings (623/685/608),
motors (2207/1404/NEMA17/N20), electronics (FC stacks/18650/USB-C/SMA), drivetrain (GT2, involute-gear
generator mod 0.5–2), hinges/pins. Each returns solid **+ named datums/joints**; instantiated by name in
assemblies (never remodeled). **Deliverable:** partlib families, each golden-by-construction (build→verify),
+ assembly instantiation-by-name path + tests.

### Phase 5 — Representation router (§1.2)  ← the Track A+B MERGE (Option B core)
Per-PART decision: dims/tolerances/fasteners→CadQuery-B-rep; organic/sculptural→TRELLIS; family/greebles/
terrain→Blender geometry-nodes/bpy; library-part→instantiate. Part-tree decomposition (§1.3) with the
stop-subdividing rule. Each rep has its own verifier (Phase 3); ONE repair loop, ONE corpus, ONE benchmark.
**TRELLIS becomes the "organic builder" behind the router, not a standalone flow.** Hybrid assembly = merge
B-rep + mesh + procedural at assembly time with unit/axis conversion (§1.4).
**Deliverable:** `router` that takes a `model_brief`/`assembly_brief`, dispatches per part, and returns a
verified hybrid asset; a drone (CAD frame + mesh canopy + procedural vents) end-to-end as the proof.

### Phase 6 — Training recipe (03_training_recipe.md)  SFT→DPO→GRPO
- **DPO stage** on the existing reject store (same-spec pass/fail pairs) — the "cheap middle step", data
  already exists.
- L0–L3 **4-level captions** (audit captions.py); diversity quotas per batch (≥40% multi-feature, ≤25%
  any single feature, reject >20% round-number dims, temp ladder 0.5→0.95 + dedup).
- Corpus rebuild through the conformant schema; provenance+license tags; benchmark holdout/dedup.
- Re-run the full training order; score at each stage boundary against Phase-2 benchmark; regression gates.
- **Deliverable:** DPO checkpoint + a capability_score delta table across SFT→DPO→GRPO.

### Phase 7 — Skill-file packaging (§7.1) + conventions/plausibility externalization
`skills/3d-modeling/`: SKILL.md, conventions.md (§1.4 verbatim), plausibility-rules.md (§2.1/§3.2),
lib/ (part library), verifiers/ (runnable, §6-report), templates/ (parse + repair prompts), examples/
(benchmark tasks with pass AND fail versions + repair diffs). **Deliverable:** the portable skill dir.

### Phase 8 — Tool stack hardening (§5) + build123d evaluation
Evaluate build123d vs CadQuery (Fable ranks build123d 1st; both OCCT). gltf-transform optimize, KTX2,
gltf-validator, PrusaSlicer oracle, puppeteer web smoke. **Deliverable:** decision memo on build123d +
the export/validate toolchain wired into the router.

---

## Sequencing & parallelism
- **Strict order:** 0 → 1 (foundation) → then 2 & 3 & 4 can proceed in parallel → 5 (needs 3+4) →
  6 (needs 1+2) → 7 & 8 (packaging/hardening, last).
- Commit at every phase boundary; keep every existing test green (regression gate).
- The capability_score against the Phase-2 benchmark is the single north-star metric; report it after
  each phase that could move it.

## Status log
- [x] Phase 0 — commit WIP  (97c903a; branch `fable-adoption`)
- [x] Phase 1 — 5 schemas  (`cad_pipeline/schemas.py` + `test_schemas.py` 36/36; corpus/asm_loop migrated to
      the conformant models via a `normalize_category` emit boundary; JSON-Schema export with versioned `$id`)
- [x] Phase 2 — 100-task benchmark  (`cad_pipeline/tests/benchmark/` — full 100-task registry conforming
      to 02_benchmark §Category distribution + difficulty spread, Σweight = 263; scorer with
      capability_score/category-floors/bands/diagnostics; oracle-preflight runner. **First honest
      multi-category ceiling: capability_score 22.05/263 — C 82.0, D 30.4, A 25.0, 24/100 runnable.**
      Remaining 76 tasks named-blocked on their pending Phase-3/4/5 verifier. `test_benchmark.py` 11/11.)
      TODO as verifiers land: encode P (mesh cavity/DFM), M/B/W/G, more A/D; add strict per-task Fable
      criteria to the runnable oracles; wire the model-generation pass@1/pass@3 mode (Phase 6).
- [~] Phase 3 — verifier suite (IN PROGRESS)
      - [x] 3a: mesh verifier §6.1 (`mesh_verify.py`) + min-wall raycast §2.3 — trimesh/rtree/scipy on
            OCCT-tessellated meshes; validated EXACT (2.499 for 2.5mm wall); `test_mesh_verify` 12/12.
            Wired M01/M02/M06/M07 → capability_score 22.05→24.33/263, M category live (16.2).
      - [x] 3b: anti-toy §2.1 / §3.4 plausibility (`plausibility.py`: mass_props, fillet hierarchy,
            min_wall — target-specific, off the hot path) + the 46-mistake catalog (`mistakes.py`,
            structured detection+repair+category). `test_plausibility` 16/16.
      - [x] 3c: print verifier §6.3 (`print_verify.py`: watertight, min_wall, overhang, bed-contact,
            build-volume + the prusa-slicer oracle — validated headless, 12m1s print time). Tooling
            installed full-fidelity: pymeshlab (self-intersection §6.1) + prusa-slicer 2.7.2 (apt).
            `test_print_verify` 9/9.
      - [x] 3d: web §6.5 + game §6.4 verifiers (`glb_verify.py`) — Khronos gltf-validator (node wrapper,
            local install), trimesh GLB introspection, Blender WORKBENCH headless render smoke (the
            §6.5 non-empty check; CYCLES lacks a denoiser on this build). `test_glb_verify` 9/9.
      - [~] 3e: wired M01/02/06/07 + W01/02 + G01 onto the new verifiers → **six categories live,
            capability_score 25.48/263** (C82 D30 A25 M16 W8 G3). STILL: P-category onto print/plausibility
            (per-task row selection), B-category (Blender bpy tasks), more M/W/G, strict per-task criteria.
- [x] Phase 4 — part library (`partlib_solids.py`: SHCS/hex-nut/washer/bearing(623-608)/dowel-pin +
      **involute gear** from the equation — root-disc+tooth-union for validity, FFT tooth count;
      golden by construction, ISO catalog dims + datums; `test_partlib` all green). Wired P05 spur gear
      → P category live, capability_score 25.48→26.62/263 (7 categories scoring). REMAINING: motors/
      electronics/GT2 (D-category depth) + assembly instantiate-by-name (lands with the Phase-5 router).
- [x] Phase 5 — representation router / Track A+B MERGE (COMPLETE)
      - [x] 5a: `engine/` package — router (§1.2 decision table), 4 builders (brep+library in-process,
            mesh→TRELLIS :8770 HTTP, procedural→Blender bpy — mesh/procedural degrade gracefully),
            build_part/build_asset orchestration, ModelBrief.to_spec adapter. Hybrid drone brief routes
            frame→brep, bearing→library, canopy→mesh. `engine/tests/test_engine` 18/18.
      - [x] 5b: hybrid ASSEMBLY merge (`engine/assemble.py` — common mm/Z-up frame, §1.4 unit/axis fit,
            mate-graph placement via a bbox proxy; test_assemble 9/9); repair loop (`engine/repair.py` —
            typed feedback from the 46-mistake catalog + deterministic A3 interference declump; test_repair
            6/6); Blender geometry-nodes generators (`engine/tools/bpy_generate.py` — staircase/array/
            window/scatter → B-category live, all 8 categories scoring, capability_score 28.90/263); router
            wired into the server (`/engine` endpoint → build_asset/repair_asset over a posted brief).
      **PHASE 5 COMPLETE — the Track A+B merge is live end-to-end (brief→router→per-rep build+verify→
      hybrid merge→repair→/engine).**
- [ ] Phase 6 — training SFT→DPO→GRPO
- [ ] Phase 7 — skill packaging
- [~] Phase 8 — build123d EVALUATED → stay on CadQuery (docs/build123d-evaluation.md; its OCP 7.9.3
      breaks cadquery 2.7 — same kernel, stylistic-only, negative cost/benefit). Remaining: §4 LOD/UV.
