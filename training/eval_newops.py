"""New-operator eval: did the SFT actually LEARN the Phase-1 operators (rim fillet/chamfer on
cylinder/revolve, shell on cylinder, prism base, rect sweep)? Held-out specs with parameters that
appear in NO training sample (fresh dims), scored in the adapters' training format (NL caption →
code, thinking OFF, no RAG) — exactly eval_dpo_confirm's TrainFmtGen. Compares base vs sft vs phase22.

Run (after relaunching the :8002 serve with the phase22 LoRA module):
  cad_pipeline/.venv/bin/python -m training.eval_newops --models base sft phase22
"""
import argparse
import json
import random
import re
import sys
import urllib.request

sys.path.insert(0, "/home/abdelrahman/MotionLab")

from cad_pipeline.captions import describe   # noqa: E402
from cad_pipeline.spec import Spec           # noqa: E402
from cad_pipeline.verifier import verify     # noqa: E402

URL = "http://localhost:8002/v1/chat/completions"

# Held-out new-operator specs — fresh parameters (NOT in the corpus's sampled ranges/values), one per
# capability the Phase-1 guard-lifts unlocked. Each must build+verify (checked below before eval).
EVAL_NEWOPS = [
    ("cyl top-rim fillet", Spec(object="spacer", shape="cylinder", envelope={"diameter": 37, "height": 23},
        features=[{"type": "fillet", "radius": 2.7, "edges": "top"}], tolerance=0.1)),
    ("cyl bottom-rim chamfer", Spec(object="collar", shape="cylinder", envelope={"diameter": 44, "height": 19},
        features=[{"type": "chamfer", "distance": 1.8, "edges": "bottom"}], tolerance=0.1)),
    ("revolve rim fillet", Spec(object="turned hub", shape="revolve",
        profile=[(0, 0), (18, 0), (18, 13), (11, 13), (11, 27), (0, 27)],
        features=[{"type": "fillet", "radius": 1.6, "edges": "top"}], tolerance=0.1)),
    ("cyl shell open-top", Spec(object="cup", shape="cylinder", envelope={"diameter": 47, "height": 33},
        features=[{"type": "shell", "thickness": 2.4, "open_face": "top"}], tolerance=0.1)),
    ("cyl shell sealed", Spec(object="canister", shape="cylinder", envelope={"diameter": 39, "height": 51},
        features=[{"type": "shell", "thickness": 1.9, "open_face": "none"}], tolerance=0.1)),
    ("hex standoff + hole", Spec(object="standoff", shape="prism", sides=6, envelope={"diameter": 17, "height": 22},
        features=[{"type": "through_hole", "diameter": 4.5}], tolerance=0.1)),
    ("hex boss corner fillet", Spec(object="hex boss", shape="prism", sides=6, envelope={"diameter": 26, "height": 13},
        features=[{"type": "fillet", "radius": 1.3, "edges": "all_vertical"}], tolerance=0.1)),
    ("octagon shelled housing", Spec(object="octagon housing", shape="prism", sides=8, envelope={"diameter": 46, "height": 28},
        features=[{"type": "shell", "thickness": 2.2, "open_face": "top"}], tolerance=0.1)),
    ("square post + top chamfer", Spec(object="square post", shape="prism", sides=4, envelope={"diameter": 31, "height": 27},
        features=[{"type": "chamfer", "distance": 1.4, "edges": "top"}], tolerance=0.1)),
    ("box-section beam", Spec(object="beam", shape="sweep", envelope={"width": 22, "height": 14},
        path=[(0, 0, 0), (110, 0, 0)], tolerance=0.1)),
    ("rect channel L-path", Spec(object="channel", shape="sweep", envelope={"width": 18, "height": 11},
        path=[(0, 0, 0), (65, 0, 0), (65, 0, 44)], tolerance=0.1)),
    ("square rail 3D path", Spec(object="rail", shape="sweep", envelope={"width": 9, "height": 9},
        path=[(0, 0, 0), (44, 0, 0), (44, 33, 0), (44, 33, 27)], tolerance=0.1)),
]


def _extract(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    code = m.group(1) if m else text
    return code if "import cadquery" in code else ("import cadquery as cq\n" + code)


def _gen(model: str, prompt: str, temp: float) -> str:
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": temp, "top_p": 0.9, "max_tokens": 2048,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return _extract(json.loads(r.read())["choices"][0]["message"]["content"])


def _pass(model: str, spec, temp: float) -> bool:
    import cadquery as cq
    try:
        prompt = describe(spec, random.Random(0))["l3"]
        ns = {"cq": cq}
        exec(_gen(model, prompt, temp), ns)   # noqa: S102
        res = ns.get("result")
        wp = res if isinstance(res, cq.Workplane) else cq.Workplane(obj=res)
        return verify(wp, spec).passed
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["base", "sft", "phase22"])
    a = ap.parse_args()
    # sanity: every eval spec must itself build+verify (else the golden is wrong, not the model)
    from cad_pipeline.builder import build
    for name, s in EVAL_NEWOPS:
        assert verify(build(s), s).passed, f"BAD GOLDEN: {name}"
    print(f"New-operator eval — {len(EVAL_NEWOPS)} held-out specs, pass@1(t0.2) + pass@3(any of 3 @t0.7)\n")
    for model in a.models:
        p1 = pk = 0
        rows = []
        for name, spec in EVAL_NEWOPS:
            a1 = _pass(model, spec, 0.2)
            anyk = a1 or any(_pass(model, spec, 0.7) for _ in range(2))
            p1 += int(a1); pk += int(anyk)
            rows.append(f"  [{'P' if a1 else '.'}{'k' if anyk and not a1 else ' '}] {name}")
        n = len(EVAL_NEWOPS)
        print(f"===== {model.upper()} =====")
        print("\n".join(rows))
        print(f"  >>> pass@1 {p1}/{n} = {p1/n:.0%}   pass@3 {pk}/{n} = {pk/n:.0%}\n", flush=True)
    print("NEWOPS_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
