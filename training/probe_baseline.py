"""Baseline probe: where does the LOCAL model start on text→feature-program-CadQuery, scored by
our reward harness? Establishes (a) the cold-start baseline, (b) whether few-shot alone gets partway,
(c) end-to-end validation of the model→code→reward loop (the RL lever). Minimal, honest, ~5 cases.

Run:  cad_pipeline/.venv/bin/python -m training.probe_baseline
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

import cadquery as cq

from cad_pipeline.builder import build_part
from cad_pipeline.spec import Part, SketchExtrude, SketchLoop, Spec, Step
from training.reward import reward

ENDPOINT = "http://localhost:8002/v1/chat/completions"
MODEL = "qwen3.6-27b"

SYSTEM = """You write CadQuery (Python) that builds a single CAD part and assigns it to `result`.
Model the part as a sequence of sketch→extrude→boolean steps (a feature program):
- start with the base body, then `.union(...)` to add material, `.cut(...)` to remove (holes/slots),
  `.intersect(...)` to trim.
- Use millimetres. Center parts sensibly. Emit ONLY a python code block, assigning `result`.

Example — "a 60x40x10 mm plate with a 12 mm hole through the centre":
```python
import cadquery as cq
plate = cq.Workplane("XY").box(60, 40, 10)
hole = cq.Workplane("XY").circle(6).extrude(20, both=True)
result = plate.cut(hole)
```"""


def _gt(*steps) -> cq.Shape:
    return build_part(Part(steps=list(steps))).val()


def _box(l, w, h):
    return Spec(object="b", shape="box", envelope={"length": l, "width": w, "height": h})


def _cyl(d, h):
    return Spec(object="c", shape="cylinder", envelope={"diameter": d, "height": h})


CASES = [
    ("A rectangular plate 40 x 30 x 10 mm.",
     _gt(Step(op="new_body", operand=_box(40, 30, 10)))),
    ("A cylinder 20 mm in diameter and 25 mm tall.",
     _gt(Step(op="new_body", operand=_cyl(20, 25)))),
    ("A 40 x 40 x 15 mm plate with a 10 mm diameter hole through its centre.",
     _gt(Step(op="new_body", operand=_box(40, 40, 15)),
         Step(op="cut", operand=_cyl(10, 40), at=(0, 0, -20)))),
    ("A 50 x 50 x 8 mm base plate with a 20 mm diameter, 12 mm tall cylindrical boss centred on top.",
     _gt(Step(op="new_body", operand=_box(50, 50, 8)),
         Step(op="join", operand=_cyl(20, 12), at=(0, 0, 4)))),
    ("An L-shaped bracket: a 60 x 20 x 8 mm base with a 20 x 8 x 40 mm wall rising from one end.",
     _gt(Step(op="new_body", operand=_box(60, 20, 8)),
         Step(op="join", operand=_box(20, 8, 40), at=(-20, 0, 24)))),
]


def _call(prompt: str) -> str:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": 0.2, "max_tokens": 2000,
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _extract(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def main() -> int:
    rewards = []
    for prompt, gt in CASES:
        try:
            code = _extract(_call(prompt))
            r = reward(code, gt)
        except Exception as e:  # noqa: BLE001
            r = {"reward": 0.0, "error": f"{type(e).__name__}: {e}"[:80]}
        rewards.append(r["reward"])
        print(f"\n■ {prompt}")
        print(f"  reward={r['reward']}  {({k: v for k, v in r.items() if k != 'reward'})}")
    n = len(rewards)
    print(f"\nBASELINE (local {MODEL}, few-shot, n={n}): "
          f"mean reward {sum(rewards)/n:.3f}, passing(≥0.9) {sum(x>=0.9 for x in rewards)}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
