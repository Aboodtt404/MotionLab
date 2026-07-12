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

# Held-out GROWTH suite (batch6 capabilities): L3 combos, the cylinder bolt-circle (half-drill) fix,
# micro-bevel styling, greeble passes, and the HERO shapes. Odd parameters, in no training sample;
# both suites are also holdout-filtered from every curriculum (build_curriculum imports them).
EVAL_COMBOS = [
    ("cyl bolt-circle flange", Spec(object="bearing flange", shape="cylinder",
        envelope={"diameter": 73, "height": 13},
        features=[{"type": "through_hole", "diameter": 17},
                  {"type": "hole_pattern", "pattern": "bolt_circle", "count": 6, "pitch_diameter": 53, "diameter": 5.5}],
        tolerance=0.1)),
    ("shelled cup + base rim fillet", Spec(object="canister housing", shape="cylinder",
        envelope={"diameter": 51, "height": 37},
        features=[{"type": "fillet", "radius": 1.7, "edges": "bottom"},
                  {"type": "shell", "thickness": 2.3, "open_face": "top"}], tolerance=0.1)),
    ("prism L3 (chamfer+cbore)", Spec(object="hex mount boss", shape="prism", sides=6,
        envelope={"diameter": 33, "height": 17},
        features=[{"type": "chamfer", "distance": 1.1, "edges": "top"},
                  {"type": "counterbore", "diameter": 5.2, "cbore_diameter": 9.4, "cbore_depth": 2.6, "at": [0, 0]}],
        tolerance=0.1)),
    ("flared revolve + rim fillet", Spec(object="flared hub", shape="revolve",
        profile=[(0, 0), (17, 0), (17, 12), (9, 26), (0, 26)], profile_arcs=[0.0, 0.0, -2.3, 0.0],
        features=[{"type": "fillet", "radius": 1.4, "edges": "top"}], tolerance=0.1)),
    ("micro-beveled box", Spec(object="equipment housing", shape="box",
        envelope={"length": 74, "width": 47, "height": 21},
        features=[{"type": "fillet", "radius": 2.3, "edges": "all_vertical"},
                  {"type": "chamfer", "distance": 0.9, "edges": "top"},
                  {"type": "chamfer", "distance": 0.9, "edges": "bottom"}], tolerance=0.1)),
    ("double-chamfered cylinder", Spec(object="drum spacer", shape="cylinder",
        envelope={"diameter": 41, "height": 23},
        features=[{"type": "chamfer", "distance": 1.3, "edges": "top"},
                  {"type": "chamfer", "distance": 1.3, "edges": "bottom"}], tolerance=0.1)),
    ("greebled deck plate", Spec(object="deck plate", shape="box",
        envelope={"length": 93, "width": 61, "height": 9},
        features=[{"type": "greeble", "panel": 17, "depth": 1.7, "density": 0.55, "groove": 1.1,
                   "seed": 4242, "levels": 2, "subdiv": 0.3, "raised": 0.25, "raise_h": 1.3,
                   "focal": "center", "bevel": 0.5}], tolerance=0.1)),
    ("greebled engine drum", Spec(object="engine housing", shape="cylinder",
        envelope={"diameter": 57, "height": 63},
        features=[{"type": "greeble", "face": "side", "panel": 19, "depth": 1.9, "density": 0.5,
                   "groove": 1.0, "seed": 777, "levels": 2, "subdiv": 0.35, "raised": 0.3,
                   "raise_h": 1.4, "focal": "edges", "bevel": 0.0}], tolerance=0.1)),
    ("hero silhouette body", Spec(object="hull silhouette body", shape="profile_extrude",
        side_profile=[(0, 0), (187, 0), (187, 19), (139, 41), (53, 41), (0, 16)],
        side_arcs=[0.0, 0.0, 0.0, -3.1, 0.0, 0.0],
        plan_profile=[(0, -14), (53, -31), (139, -31), (187, -14), (187, 14), (139, 31), (53, 31), (0, 14)],
        tolerance=0.1)),
    ("hero lofted fuselage", Spec(object="fuselage body", shape="loft_sections",
        sections=[{"x": 0, "width": 21, "height": 17, "z_center": 21, "kind": "ellipse"},
                  {"x": 96, "width": 57, "height": 43, "z_center": 21, "kind": "ellipse"},
                  {"x": 191, "width": 24, "height": 18, "z_center": 21, "kind": "ellipse"}],
        tolerance=0.1)),
    ("mirrored bracket", Spec(object="symmetric bracket", shape="box",
        envelope={"length": 87, "width": 41, "height": 17},
        features=[{"type": "through_hole", "diameter": 7.3, "at": [29, 0]},
                  {"type": "mirror", "plane": "YZ"}], tolerance=0.1)),
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
    ap.add_argument("--suite", choices=["newops", "combos", "all"], default="newops")
    a = ap.parse_args()
    suite = {"newops": EVAL_NEWOPS, "combos": EVAL_COMBOS, "all": EVAL_NEWOPS + EVAL_COMBOS}[a.suite]
    # sanity: every eval spec must itself build+verify (else the golden is wrong, not the model)
    from cad_pipeline.builder import build
    for name, s in suite:
        assert verify(build(s), s).passed, f"BAD GOLDEN: {name}"
    print(f"{a.suite} eval — {len(suite)} held-out specs, pass@1(t0.2) + pass@3(any of 3 @t0.7)\n")
    for model in a.models:
        p1 = pk = 0
        rows = []
        for name, spec in suite:
            a1 = _pass(model, spec, 0.2)
            anyk = a1 or any(_pass(model, spec, 0.7) for _ in range(2))
            p1 += int(a1); pk += int(anyk)
            rows.append(f"  [{'P' if a1 else '.'}{'k' if anyk and not a1 else ' '}] {name}")
        n = len(suite)
        print(f"===== {model.upper()} =====")
        print("\n".join(rows))
        print(f"  >>> pass@1 {p1}/{n} = {p1/n:.0%}   pass@3 {pk}/{n} = {pk/n:.0%}\n", flush=True)
    print("NEWOPS_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
