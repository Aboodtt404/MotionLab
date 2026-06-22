# cad_pipeline — Track A (hard-surface text/image → parametric CAD)

The **verifier-first** spine for hard-surface assets: a spec is turned into CadQuery
code, executed in a sandbox, and checked by a **deterministic feature-level BRep
verifier** (the core IP — *resolve-twice* selector binding). Failures route a typed
4-class retry loop. Grounded in `docs/research/track-a-design.md` (§ cited per module).

## Data flow

```
            spec (typed contract)
                  │
   generator ─────┤  Golden | MockRetry | VLLM (live model)        loop.py / repair.py
   emits CadQuery │
                  ▼
   sandbox (subprocess, timeout, layered gates)                    executor.py / _exec_child.py
                  │  built solid
                  ▼
   DETERMINISTIC BRep verifier → structured Report                 verifier.py / selectors.py
   (envelope · hole ⌀+position · fillet r+binding · …)
                  │  pass? ──► done
                  ▼  fail → typed, NON-leaking feedback (§9)
   4-class retry  {exec-fix · dimensional · selector-binding · escalate}
   + error-driven retrieval on exec errors                         repair.py
```

## Module map (flat core — keep new core modules here)

| Module | Role | Doc |
|---|---|---|
| `spec.py` | Typed pydantic contract (envelope, features, selectors, tolerance) | §contract |
| `selectors.py` | Controlled selector grammar (orientation predicates, set-valued) — core IP | §3 |
| `builder.py` | Deterministic spec → CadQuery (`build`) + source emitter (`emit_code`) = golden reference | §7 |
| `verifier.py` | Deterministic feature-level BRep verifier → `Report` (resolve-twice) | §8 |
| `repair.py` | Error-driven retrieval: traceback → ground-truth CadQuery fix (motoko-repair pattern) | §9 |
| `executor.py` | Sandbox parent — spawns the child, parses its JSON report | §7 |
| `_exec_child.py` | Sandbox child — execs untrusted code, runs gates + verify, exports STEP/STL | §7 |
| `loop.py` | `run()` orchestration + `Generator`s (`Golden`, `MockRetry`, `VLLM`) | §5, §9 |

`tests/` holds the harnesses (not imported by the core):
| `tests/selftest.py` | GOLDEN (known-good must verify exact) + ADVERSARIAL (wrong solids must be caught) | §8 |
| `tests/eval_baseline.py` | Live-model baseline: pass-rate, per-feature, failure-category profile | §bake-off |

## Run (from repo root, with the venv)

```bash
cad_pipeline/.venv/bin/python -m cad_pipeline.tests.selftest        # golden + adversarial
cad_pipeline/.venv/bin/python -m cad_pipeline.tests.eval_baseline 3 # live baseline, 3 attempts
```

The live model (VLLMGenerator) expects vLLM on `http://localhost:8002/v1` serving
`qwen3.6-27b` (see `docs/research/HANDOFF.md` for the serve command).

## Conventions (keep organized from here on)

- **Core pipeline modules stay flat** at the package root; **harnesses/entry-points go in `tests/`**.
- Every module cites the `docs/research/track-a-design.md` section it implements; if reality
  forces a deviation, surface it and update the doc (standing rule).
- Public API is re-exported from `__init__.py` — import from `cad_pipeline`, not deep paths.
