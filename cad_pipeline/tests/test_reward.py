"""GRPO reward harness tests — confirms the multiplicative exec-gate behaves (track-a-finetuning §3).

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.test_reward
"""
from __future__ import annotations

import sys

from ..builder import emit_code
from ..reward import compute_reward
from ..spec import Spec

SPEC = Spec(object="plate", shape="box", envelope={"length": 60, "width": 40, "height": 10},
            features=[{"type": "through_hole", "diameter": 8}], tolerance=0.1)


def fenced(code: str) -> str:
    return f"<think>brief reasoning</think>\n```python\n{code}\n```"


GOLDEN = emit_code(SPEC)
WRONG_DIM = "import cadquery as cq\nresult = cq.Workplane('XY').box(90.0, 40.0, 10.0).faces('>Z').workplane().hole(8.0)"
EXTRA = ("import cadquery as cq\nresult = (cq.Workplane('XY').box(60.0,40.0,10.0)"
         ".faces('>Z').workplane().hole(8.0)"
         ".faces('>Z').workplane().pushPoints([(20,0)]).hole(5.0))")
BROKEN = "import cadquery as cq\nresult = cq.Workplane('XY').nonsense_method()"

CASES = [
    # name, model_output, predicate(reward_dict)->bool, why
    ("golden + fmt",        fenced(GOLDEN), lambda r: r["reward"] > 0.9 and r["passed"],            "correct + formatted → ~1.0"),
    ("golden raw (no fmt)", GOLDEN,         lambda r: r["exec"] == 1.0 and r["fmt"] == 0.0 and r["reward"] > 0.85, "code salvaged, no fence → geo high, fmt 0"),
    ("broken exec",         fenced(BROKEN), lambda r: r["exec"] == 0.0 and r["reward"] <= 0.1,      "exec fail → geometric masked"),
    ("wrong dimension",     fenced(WRONG_DIM), lambda r: r["exec"] == 1.0 and r["feat"] < 1.0 and r["reward"] < 0.9, "valid solid, wrong size → feat<1"),
    ("extra feature",       fenced(EXTRA),  lambda r: r["topo"] < 1.0 or r["feat"] < 1.0,           "unexpected hole → penalty"),
    ("no code at all",      "I think it's a box.", lambda r: r["reward"] == 0.0,                    "no program, no fmt → 0"),
]


def main() -> int:
    ok = 0
    print(f"GRPO reward harness — {len(CASES)} cases\n" + "=" * 78)
    for name, out, pred, why in CASES:
        r = compute_reward(out, SPEC)
        passed = pred(r)
        ok += passed
        flag = "PASS" if passed else "FAIL"
        print(f"[{flag}] {name:<20} reward={r['reward']:<6} "
              f"exec={r['exec']} feat={r.get('feat')} topo={r.get('topo')} geo={r.get('geo')} fmt={r['fmt']}  ({why})")
    print("=" * 78)
    print(f"{ok}/{len(CASES)} passed")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
