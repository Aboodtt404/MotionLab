# MotionLab Studio — frontend

React + TypeScript + Vite + three.js implementation of the **MotionLab Studio** design
(`docs/research/_design/.../MotionLab Studio.dc.html`), the asset-generation UI for the
sci-fi-film 3D pipeline.

```bash
npm install
npm run dev      # http://localhost:5174
npm run build    # typecheck + production build
```

## What it is
A faithful recreation of the design's three-pane studio — left rail, center 3D stage,
right settings/result panel — in the project's real stack (the design files are HTML/CSS
prototypes; this is the production-tech version). The generation + verification flow is
**mocked** (staged client-side simulation) since no backend exists yet — same as the
prototype.

## Layout
- `src/store.ts` — Zustand store: full studio state + the mocked generate/verify flow,
  plus the pure spec helpers (parse, build CadQuery, inspection, warnings) ported from the prototype.
- `src/viewport/scene.ts` — three.js scene (orbit, turntable, lighting moods, hard
  box/cylinder + organic blob, solid/wire/x-ray, heatmap).
- `src/components/` — Rail, Stage (+ overlays), Viewport, PromptDock, Library, RightPanel,
  ResultCard, Settings.

## Adaptations from our research (per "add/remove as research suggested")
The design was followed closely, with these changes driven by the Track A/B/C design docs:
- **Model lists → our actual picks.** Hard-surface: `Qwen3.6-27B · local · fine-tuned` /
  `Frontier · Opus 4.8` / `gpt-oss-120b · data engine`. Organic: `TRELLIS.2 · local` /
  `Hunyuan3D 2.1 · local · region-gated` / `Frontier · Opus 4.8 (judge)`.
- **Scale anchor (Track C).** Image mode shows a required real-dimension input — absolute
  scale can't be recovered from an image, so the user supplies one true dimension.
- **Organic result → bounded best-of-N + human sign-off (Track B).** The fidelity card shows
  "best of N · 9-view + normals" and an **Approve / Regenerate** gate — aesthetics have no
  objective fixpoint, so a human art-direction sign-off terminates the loop, not the VLM.
- **Hard result → "Selectors resolved" line (Track A).** Alongside watertight/manifold,
  reflecting the resolve-twice deterministic-verifier core IP.

## Not yet wired
No backend: generation is simulated, exports write placeholder files, and the viewport
shows procedural stand-in geometry. Hooking the real Track A/B/C pipelines behind the
`generate()` action + export buttons is the next step.
