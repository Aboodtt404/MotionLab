"""Full-100 model scorecard — the bridge eval_baseline flags it needs (its own note: "/263 full
benchmark + bands need all 100 tasks, 8 categories"). fable_run/out/02_benchmark.md §Scoring.

The 100 tasks split by who produces the artifact:
  • model-generatable (the LLM writes CadQuery code): the C/A/D/P spec-backed tasks — measured by the
    live generate→verify→retry loop (pass@1 / pass@N), i.e. eval_baseline's per-spec results;
  • engine-produced (mesh/procedural/web/game/library): the ENGINE builds these deterministically —
    there is no model code to grade, so they score by the golden oracle (oracle_scorecard).

`combined_scorecard` merges the two into ONE capability_score/263 with pass@1/pass@3 + bands, so the
number means what Fable intends the moment the model is served. Runs today with a mock so the harness
is verified without the GPU.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from .runner import oracle_scorecard
from .score import Scorecard, TaskResult
from .tasks import REGISTRY

# which categories the model actually GENERATES code for (vs the engine builds deterministically)
_MODEL_CATEGORIES = {"C", "A", "D", "P"}


def combined_scorecard(model_pass: Optional[Dict[str, tuple]] = None) -> Scorecard:
    """model_pass: {task_id: (passed@1: bool, passed@3: bool)} from the live loop (eval_baseline).
    For model categories, use those results; for engine categories, use the golden oracle ceiling."""
    model_pass = model_pass or {}
    oracle = {r.task_id: r for r in oracle_scorecard().results}
    results = []
    for t in REGISTRY:
        if t.category in _MODEL_CATEGORIES and t.id in model_pass:
            p1, p3 = model_pass[t.id]
            results.append(TaskResult(task_id=t.id, category=t.category, level=t.level,
                                      passed_at1=p1, passed_at3=p3, runnable=True))
        else:
            results.append(oracle.get(t.id, TaskResult(task_id=t.id, category=t.category,
                                                        level=t.level, runnable=False)))
    return Scorecard(results=results)


def run_with_model(generate_and_verify: Callable[[str], tuple]) -> Scorecard:
    """generate_and_verify(task_id) -> (passed@1, passed@3) for a model-category task, e.g. wrapping
    cad_pipeline.loop.run. Applied to every model-category task that carries a runnable oracle."""
    model_pass = {t.id: generate_and_verify(t.id) for t in REGISTRY
                  if t.category in _MODEL_CATEGORIES and t.runnable}
    return combined_scorecard(model_pass)
