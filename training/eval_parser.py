"""A/B the fine-tuned NL→spec parser vs the few-shot base parser, over the vLLM server (HTTP).
Held-out prompts (frontend-style). For each: generate a spec, check it parses (pydantic) + builds
(executor), and time it. The fine-tuned parser uses the short HINT + no-think (the latency win); the
base uses the full few-shot _SYSTEM + reason-first (the current prompt_to_spec).

Run AFTER the restore launch is up:  cad_pipeline/.venv/bin/python training/eval_parser.py
"""
import sys, json, time, urllib.request
sys.path.insert(0, "/home/abdelrahman/MotionLab")
from cad_pipeline.spec import Spec
from cad_pipeline.executor import run_code
from cad_pipeline.nl_spec import _SYSTEM, _extract_json
from training.build_nl_spec import HINT  # the short schema hint the parser was trained with

# held-out NL prompts (fresh phrasings, not verbatim training rows)
PROMPTS = [
    "a tapered motor-mount arm, 70mm long, 30x20mm at the hub down to 16x16mm at the tip, with an 8mm hole at each end",
    "a turned nozzle that tapers from a 30mm base to a 12mm neck over 40mm tall",
    "an 8mm coolant line routed 60mm along X then 40mm up Z",
    "a 90mm flange, 12mm bore, six 6mm bolts on a 70mm circle",
    "an L-bracket 80x60x40mm, 5mm wall, two 8mm mounting holes",
    "a 50mm cube with a 20mm hole through the center",
    "a shafted hub: 60mm long round body, 24mm shaft tapering to a 40mm flange, 10mm bore",
    "a vented enclosure 100x70x40mm, 3mm walls, open top, four 5mm corner holes inset 10mm",
]

def call(model, messages, think):
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 2048}
    if not think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request("http://localhost:8002/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=200).read())["choices"][0]["message"]["content"]

def run(label, model, nl, think, system, user_fmt):
    t = time.time()
    try:
        txt = call(model, [{"role": "system", "content": system}, {"role": "user", "content": user_fmt(nl)}], think)
        spec = Spec(**json.loads(_extract_json(txt)))
        dt = time.time() - t
        res = run_code_safe(spec)
        return {"ok_parse": True, "shape": spec.shape, "builds": res, "secs": round(dt, 1)}
    except Exception as e:
        return {"ok_parse": False, "err": f"{type(e).__name__}: {str(e)[:80]}", "secs": round(time.time() - t, 1)}

def run_code_safe(spec):
    try:
        return run_code(spec_to_code_via_self(spec), spec, timeout=40).get("status") == "ok"
    except Exception:
        return None

def spec_to_code_via_self(spec):
    # build the gold code deterministically to test the SPEC is buildable (isolates parser from codegen)
    from cad_pipeline.builder import emit_code
    return emit_code(spec)

CONFIGS = [
    ("base+fewshot(think)", "qwen3.6-27b", True, _SYSTEM, lambda nl: "input: " + nl),
    ("parser-final(nothink)", "parser", False, "", lambda nl: HINT + nl),
    ("parser-800(nothink)", "parser800", False, "", lambda nl: HINT + nl),
]
for label, model, think, system, fmt in CONFIGS:
    print(f"\n================ {label} ================")
    parse_ok = build_ok = 0; tot_s = 0.0
    for nl in PROMPTS:
        r = run(label, model, nl, think, system, fmt)
        tot_s += r["secs"]
        if r.get("ok_parse"):
            parse_ok += 1; build_ok += 1 if r.get("builds") else 0
            print(f"  [{r['secs']:5.1f}s] shape={r['shape']:8} builds={r['builds']}  | {nl[:50]}")
        else:
            print(f"  [{r['secs']:5.1f}s] PARSE-FAIL {r['err']}  | {nl[:50]}")
    n = len(PROMPTS)
    print(f"  >> parse {parse_ok}/{n}  build {build_ok}/{n}  avg {tot_s/n:.1f}s/prompt")
