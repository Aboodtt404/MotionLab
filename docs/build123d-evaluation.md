# build123d Evaluation (Phase 8) — Decision: stay on CadQuery

Fable (`fable_run/out/00_manual.md §5`) ranks **build123d** as the first-choice parametric-CAD tool,
CadQuery second. Our entire pipeline is CadQuery 2.7. This memo records an actual, hands-on evaluation.

## What was tested (2026-07-11)
Installed `build123d 0.11.1` into the cad_pipeline venv and built the same part (80×50×30 bracket,
4× ⌀5.5 corner holes, r4 vertical fillet) in both libraries.

- **build123d builds correctly** — valid solid, right bbox/volume; the builder-context + algebraic API
  is genuinely nicer for some ops (named `Axis`/`Plane` selectors, `filter_by`, location contexts).
- **Both sit on the same OCCT kernel** → identical geometry class. build123d is an *ergonomic* choice,
  not a capability gain.

## The blocker (decisive)
Installing build123d **broke CadQuery**: it pulls `cadquery-ocp-novtk` / `cadquery-ocp-proxy` **7.9.3**,
which conflicts with CadQuery 2.7's `cadquery-ocp` **7.8.1** — the `-novtk` build omits `IVtkOCC`, which
CadQuery 2.7 imports at module load, so `import cadquery` fails. The two cannot share one venv without
matching their OCP versions. Recovering required force-reinstalling `cadquery-ocp==7.8.1.1.post1`.

## Decision: **stay on CadQuery 2.7**
- The gain is **stylistic, not functional** (same kernel, same STEP output).
- Adopting build123d would require (a) resolving the OCP version conflict (a separate venv, or upgrading
  CadQuery to a version whose OCP matches build123d's) **and** (b) rewriting `builder.py` / `emit_code` /
  the whole synthetic corpus, which is keyed to CadQuery idioms. The cost dwarfs the benefit.
- **Cost/benefit is clearly negative right now.** Revisit only if a concrete CadQuery limitation bites
  that build123d demonstrably fixes.

## If we ever migrate
Do it in an **isolated venv** (never alongside CadQuery), port `emit_code` to build123d's algebraic API
first (it's the corpus target), and A/B the two emitters on the 100-task benchmark before committing.
Both target STEP, so interop at the assembly/export boundary is clean.

**Status: Phase 8 (build123d) — evaluated, decided (stay on CadQuery). build123d uninstalled; venv restored + regression green.**
