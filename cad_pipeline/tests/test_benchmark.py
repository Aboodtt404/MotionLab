"""Phase-2: the 100-task benchmark registry + scorer conform to fable_run/out/02_benchmark.md,
and every RUNNABLE task passes the golden oracle preflight (encodings are well-formed).
"""
from __future__ import annotations

import sys

from cad_pipeline.tests.benchmark.runner import oracle_scorecard
from cad_pipeline.tests.benchmark.score import TOTAL_WEIGHT, WEIGHT
from cad_pipeline.tests.benchmark.tasks import REGISTRY

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    PASS, FAIL = (PASS + 1, FAIL) if cond else (PASS, FAIL + 1)
    print(f"  [{'ok ' if cond else 'FAIL'}] {msg}")


def test_registry_shape():
    print("\n■ registry conforms to 02_benchmark §Category distribution + difficulty spread")
    check(len(REGISTRY) == 100, f"100 tasks registered (got {len(REGISTRY)})")
    counts = {c: sum(1 for t in REGISTRY if t.category == c) for c in "CMBWGPDA"}
    check(counts == {"C": 20, "M": 15, "B": 12, "W": 10, "G": 12, "P": 10, "D": 8, "A": 13},
          f"category counts match Fable (got {counts})")
    spread = {lvl: sum(1 for t in REGISTRY if t.level == lvl) for lvl in (1, 2, 3, 4)}
    check(spread == {1: 13, 2: 32, 3: 34, 4: 21}, f"difficulty spread L1×13/L2×32/L3×34/L4×21 (got {spread})")
    total = sum(WEIGHT[t.level] for t in REGISTRY)
    check(total == TOTAL_WEIGHT == 263, f"total weight = 263 (got {total})")
    ids = [t.id for t in REGISTRY]
    check(len(set(ids)) == 100, "all task ids unique")


def test_oracle_preflight():
    print("\n■ golden oracle preflight — every runnable task builds + verifies")
    card = oracle_scorecard()
    runnable = [r for r in card.results if r.runnable]
    reds = [r for r in runnable if not r.passed_at3]
    check(len(runnable) >= 20, f"≥20 tasks runnable now (got {len(runnable)})")
    check(not reds, "0 runnable tasks fail the golden preflight"
          + ("" if not reds else f" — RED: {[(r.task_id, r.failure_category) for r in reds]}"))
    # category coverage: C, A, D have runnable tasks (the first honest multi-category score)
    runnable_cats = {r.category for r in runnable}
    check({"C", "A", "D"} <= runnable_cats, f"C+A+D categories are live (got {sorted(runnable_cats)})")


def test_scorecard_math():
    print("\n■ scorecard math (capability_score / bands / diagnostics)")
    card = oracle_scorecard()
    s1, s3 = card.capability_score(False), card.capability_score(True)
    check(0 <= s1 <= 100 and 0 <= s3 <= 100, f"capability_score in range (pass@1={s1}, pass@3={s3})")
    d = card.diagnostics()
    check(d["encoded_runnable"] + d["blocked"] == 100, "runnable + blocked = 100")
    check(card.band() in ("Weak", "Basic", "Competent", "Strong", "Expert"), f"band = {card.band()}")
    print("\n" + card.render())


def main() -> int:
    print("=" * 64)
    print("BENCHMARK — 100 tasks (02_benchmark.md) registry + oracle preflight")
    print("=" * 64)
    for fn in (test_registry_shape, test_oracle_preflight, test_scorecard_math):
        fn()
    print("\n" + "=" * 64)
    print(f"BENCHMARK {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
