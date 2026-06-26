"""Stage 2.1 SEMANTIC eval — does the parser's spec MATCH the prompt's intent (shape + hole
positions), not merely build? This is the check eval_parser.py lacked (it only tested buildability,
which masked holes-at-center and cube->cylinder).

Held-out set = correct-by-construction positioned-hole cases (seed disjoint from training) + a few
canonical shape cases with known ground truth. For each model adapter we score:
  shape_ok       — spec.shape == expected
  holes_ok       — the set of through-hole (x,y) positions matches expected within 2mm (count + place)
  semantic_ok    — shape_ok AND holes_ok
plus latency. Run AFTER the retrained adapter is served.

Run:  cad_pipeline/.venv/bin/python training/eval_parser_semantic.py [adapter_name ...]
"""
import sys, json, time, random, urllib.request
sys.path.insert(0, "/home/abdelrahman/MotionLab")
from cad_pipeline.spec import Spec
from cad_pipeline.nl_spec import _extract_json, _SYSTEM, PARSER_HINT

random.seed(7)  # disjoint from training seed (42)

def thru_positions(spec: Spec):
    """Set of (x,y) for explicit-at through-holes; from_edge -> (-L/2+N, 0); rounded to 0.5."""
    out = []
    L = spec.envelope.get("length", 0.0)
    for f in spec.features:
        if f.type == "through_hole":
            if f.at is not None:
                out.append((round(f.at[0], 1), round(f.at[1], 1)))
            elif f.from_edge is not None:
                out.append((round(-L/2 + f.from_edge, 1), 0.0))
    return sorted(out)

# ---- held-out cases: (NL, expected_shape, expected_positions or None) ----
CASES = []
# positioned-hole cases, correct-by-construction (unseen seed)
for _ in range(24):
    L = random.choice(range(60, 161, 5)); W = random.choice(range(30, min(L, 110), 5)); H = random.choice([8, 10, 12, 16])
    d = random.choice([5, 6, 8]); kind = random.choice(["corner", "ends", "fromedge"])
    if kind == "corner":
        I = random.choice([10, 12, 15]); x, y = round(L/2-I, 1), round(W/2-I, 1)
        if min(L/2-I, W/2-I) < d/2+2: continue
        CASES.append((f"a {L}x{W}x{H}mm mounting plate, {d}mm holes {I}mm in from each corner",
                      "box", sorted([(sx, sy) for sx in (-x, x) for sy in (-y, y)])))
    elif kind == "ends":
        E = random.choice([10, 12, 15, 20]); x = round(L/2-E, 1)
        if L/2-E < d/2+2: continue
        CASES.append((f"a {L}mm long bar, {W}x{H}mm, with a {d}mm hole {E}mm from each end",
                      "box", sorted([(-x, 0.0), (x, 0.0)])))
    else:
        N = random.choice([12, 18, 25]);
        if N > L-d: continue
        CASES.append((f"a {L}x{W}x{H}mm plate with a {d}mm hole {N}mm from the left edge",
                      "box", sorted([(round(-L/2+N, 1), 0.0)])))
# canonical shape cases (positions known or n/a)
CASES += [
    ("a tapered motor-mount arm, 70mm long, 30x20mm at the hub down to 16x16mm at the tip, with an 8mm hole at each end", "loft", "ends70"),
    ("a turned nozzle that tapers from a 30mm base to a 12mm neck over 40mm tall", "revolve", None),
    ("an 8mm coolant line routed 60mm along X then 40mm up Z", "sweep", None),
    ("a 50mm cube with a 20mm hole through the center", "box", [(0.0, 0.0)]),
    ("a 90mm flange, 12mm bore, six 6mm bolts on a 70mm circle", "cylinder", None),  # bore at center; pattern separate
]

def call(model, messages, think):
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 2048}
    if not think: body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request("http://localhost:8002/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=200).read())["choices"][0]["message"]["content"]

def positions_match(got, exp, tol=2.0):
    if exp is None: return True            # n/a (shape-only case)
    if exp == "ends70": exp = None         # accept any 2 symmetric end holes; checked specially below
    if exp is None: return None
    if len(got) != len(exp): return False
    return all(any(abs(g[0]-e[0]) <= tol and abs(g[1]-e[1]) <= tol for g in got) for e in exp)

def run(label, model, think, system, fmt):
    shape_ok = pos_ok = sem_ok = n_pos = 0; tot = 0.0; fails = []
    for nl, exp_shape, exp_pos in CASES:
        t = time.time()
        try:
            txt = call(model, [{"role": "system", "content": system}, {"role": "user", "content": fmt(nl)}], think)
            spec = Spec(**json.loads(_extract_json(txt)))
            dt = time.time()-t; tot += dt
            sh = spec.shape == exp_shape
            got = thru_positions(spec)
            if exp_pos == "ends70":  # two symmetric holes inset from ±35
                pm = (len(got) == 2 and abs(got[0][0]+got[1][0]) <= 2 and all(abs(p[1]) <= 2 for p in got)
                      and all(10 <= abs(p[0]) <= 33 for p in got))
            else:
                pm = positions_match(got, exp_pos)
            if exp_pos is not None and exp_pos != "ends70" or exp_pos == "ends70":
                n_pos += 1; pos_ok += 1 if pm else 0
            shape_ok += 1 if sh else 0
            ok = sh and (pm is not False)
            sem_ok += 1 if ok else 0
            if not ok: fails.append(f"{exp_shape}: got shape={spec.shape} pos={got} (want {exp_pos})")
        except Exception as e:
            tot += time.time()-t; fails.append(f"PARSE-FAIL {type(e).__name__}: {nl[:40]}")
    n = len(CASES)
    print(f"\n== {label} ==  shape {shape_ok}/{n}  holes {pos_ok}/{n_pos}  SEMANTIC {sem_ok}/{n}  avg {tot/n:.1f}s")
    for f in fails: print("   x", f[:100])

CONFIGS = {
    "base": ("base+fewshot", "qwen3.6-27b", True, _SYSTEM, lambda nl: "input: "+nl),
    "parser": ("parser-finetuned", "parser3", False, "", lambda nl: PARSER_HINT+nl),
}
which = sys.argv[1:] or ["base", "parser"]
for k in which:
    label, model, think, system, fmt = CONFIGS[k]
    run(label, model, think, system, fmt)
