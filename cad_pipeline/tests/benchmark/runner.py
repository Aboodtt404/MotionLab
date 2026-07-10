"""Benchmark runner. Two modes:

  • oracle preflight (default) — build our by-construction golden artifact for every runnable task and
    confirm it passes the deterministic verifier. This measures the ENGINE CEILING (what the pipeline
    can produce a valid artifact for) and validates that every encoded task is well-formed. Blocked
    tasks count as not-passed, so capability_score reflects true coverage of the 263-weight set.

  • model run (future, Phase 6) — swap the golden oracle for a generator + the repair loop, and record
    pass@1 vs pass@3 to measure a model's capability + repair skill.
"""
from __future__ import annotations

from .score import Scorecard, TaskResult
from .tasks import REGISTRY, Task


def _run_oracle(task: Task) -> TaskResult:
    if not task.runnable:
        return TaskResult(task_id=task.id, category=task.category, level=task.level,
                          runnable=False, blocked_on=task.blocked_on)
    try:
        rep = task.oracle()                     # golden build + verify
        passed = bool(rep.get("passed"))
        if passed and task.criteria is not None:
            passed = bool(task.criteria(rep))
        fcat = None
        if not passed:
            fc = rep.get("failure_categories") or []
            fcat = fc[0] if fc else "verify_fail"
    except Exception as e:                        # noqa: BLE001 — a golden that won't build is a red preflight
        passed, fcat = False, f"oracle_error:{type(e).__name__}"
    # golden path is deterministic → pass@1 == pass@3 (no model, no retry variance)
    return TaskResult(task_id=task.id, category=task.category, level=task.level,
                      passed_at1=passed, passed_at3=passed, attempts_used=1,
                      runnable=True, failure_category=fcat)


def oracle_scorecard() -> Scorecard:
    return Scorecard(results=[_run_oracle(t) for t in REGISTRY])


if __name__ == "__main__":
    card = oracle_scorecard()
    print(card.render())
    # red preflight = a mis-encoded runnable task (golden should ALWAYS pass); surface them
    reds = [r for r in card.results if r.runnable and not r.passed_at3]
    if reds:
        print("\n⚠ RUNNABLE TASKS THAT FAILED THE GOLDEN PREFLIGHT (encoding bugs):")
        for r in reds:
            print(f"   {r.task_id}: {r.failure_category}")
