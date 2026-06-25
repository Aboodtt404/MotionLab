"""Stage 2.1 — synthesize POSITIONED-hole NL→spec pairs (the gap that broke the Stage-2 parser).

targeted_pilot has 0/1059 off-center `at` holes, so the fine-tune never learned to place a hole anywhere
but (0,0). We fix that with correct-BY-CONSTRUCTION data: build the spec first (exact, known positions),
then back-translate to NL that states those positions explicitly. Covers corner / each-end / explicit-xy
/ from-edge / spaced-pair placements on box (and loft for end-holes), with varied dims + phrasings.

Run:  cad_pipeline/.venv/bin/python training/build_positioned_holes.py
Out:  /workspace/.hf_home/cad_corpus/positioned_holes.jsonl  ({prompt, code, shape, level})
"""
import json, random
import sys
sys.path.insert(0, "/home/abdelrahman/MotionLab")
from cad_pipeline.nl_spec import PARSER_HINT

random.seed(42)
OUT = "/workspace/.hf_home/cad_corpus/positioned_holes.jsonl"

OBJS_BOX = ["mounting plate", "base plate", "bracket", "panel", "mounting bracket", "cover plate",
            "adapter plate", "spacer plate", "gusset", "flat bar"]
OBJS_ARM = ["arm", "link", "strut", "tie bar", "motor-mount arm", "connecting bar"]
DIAS = [4, 5, 6, 8, 10, 12]

def spec_json(d):
    return json.dumps(d, separators=(",", ":"))

def row(prompt, spec, shape):
    return {"prompt": PARSER_HINT + prompt, "code": spec_json(spec), "shape": shape, "level": "pos"}

def box(L, W, H):
    return {"object": "part", "shape": "box", "envelope": {"length": L, "width": W, "height": H},
            "features": [], "tolerance": 0.1}

def thru(x, y, d):
    return {"type": "through_hole", "diameter": d, "at": [round(x, 1), round(y, 1)]}

def emit(rows):
    out = []
    # --- A) four corner holes, inset I ---
    for _ in range(700):
        L = random.choice(range(40, 161, 5)); W = random.choice(range(30, min(L, 121), 5)); H = random.choice([6, 8, 10, 12, 15, 20])
        d = random.choice(DIAS); I = random.choice([8, 10, 12, 15, 18, 20])
        if L/2 - I < d/2 + 2 or W/2 - I < d/2 + 2:   # keep holes inside
            continue
        x, y = round(L/2 - I, 1), round(W/2 - I, 1)
        s = box(L, W, H); obj = random.choice(OBJS_BOX); s["object"] = obj
        s["features"] = [thru(sx, sy, d) for sx in (-x, x) for sy in (-y, y)]
        p = random.choice([
            f"a {L}x{W}x{H}mm {obj} with a {d}mm hole {I}mm in from each corner",
            f"{obj}, {L} x {W} x {H}, four {d}mm mounting holes inset {I}mm from the corners",
            f"a {obj} {L}mm by {W}mm by {H}mm thick, {d}mm holes {I}mm from each corner",
        ])
        rows.append(row(p, s, "box"))
    # --- B) a hole near each END (along length), inset E — box AND loft ---
    for _ in range(600):
        L = random.choice(range(50, 181, 5)); W = random.choice(range(16, 60, 4)); H = random.choice([10, 12, 16, 20, 25])
        d = random.choice(DIAS); E = random.choice([8, 10, 12, 15, 20, 25])
        if L/2 - E < d/2 + 2:
            continue
        x = round(L/2 - E, 1)
        as_loft = random.random() < 0.4
        if as_loft:
            wt, ht = random.choice([(W//2, H), (W, H//2), (max(8, W-8), max(8, H-6))])
            s = {"object": random.choice(OBJS_ARM), "shape": "loft",
                 "envelope": {"length": L, "width": W, "height": H, "width_top": wt, "height_top": ht},
                 "features": [thru(-x, 0, d), thru(x, 0, d)], "tolerance": 0.1}
            obj = s["object"]
            p = random.choice([
                f"a tapered {obj} {L}mm long, {W}x{H}mm tapering to {wt}x{ht}mm, with a {d}mm hole {E}mm from each end",
                f"{obj}: {L}mm long loft from {W}x{H} to {wt}x{ht}, {d}mm holes set {E}mm in from both ends",
            ])
            rows.append(row(p, s, "loft"))
        else:
            s = box(L, W, H); obj = random.choice(OBJS_ARM); s["object"] = obj
            s["features"] = [thru(-x, 0, d), thru(x, 0, d)]
            p = random.choice([
                f"a {L}mm long {obj}, {W}x{H}mm section, with a {d}mm hole {E}mm from each end",
                f"{obj} {L} x {W} x {H}, two {d}mm holes, one {E}mm in from each end",
                f"a {W}x{H}mm bar {L}mm long with {d}mm holes {E}mm from both ends",
            ])
            rows.append(row(p, s, "box"))
    # --- C) explicit single/again offset hole ---
    for _ in range(350):
        L = random.choice(range(50, 161, 5)); W = random.choice(range(40, 121, 5)); H = random.choice([8, 10, 12, 16, 20])
        d = random.choice(DIAS); off = random.choice(range(10, int(L/2 - d/2 - 2), 5) or [10])
        s = box(L, W, H); obj = random.choice(OBJS_BOX); s["object"] = obj
        s["features"] = [thru(off, 0, d)]
        p = random.choice([
            f"a {L}x{W}x{H}mm {obj} with a single {d}mm hole {off}mm from center along its length",
            f"{obj} {L} x {W} x {H}, one {d}mm hole offset {off}mm from the middle",
        ])
        rows.append(row(p, s, "box"))
    # --- D) from_edge (box-only convention) ---
    for _ in range(350):
        L = random.choice(range(40, 141, 5)); W = random.choice(range(30, 101, 5)); H = random.choice([8, 10, 12, 16])
        d = random.choice(DIAS); N = random.choice(range(8, int(L - d), 4) or [8])
        s = box(L, W, H); obj = random.choice(OBJS_BOX); s["object"] = obj
        s["features"] = [{"type": "through_hole", "diameter": d, "from_edge": N}]
        p = random.choice([
            f"a {L}x{W}x{H}mm {obj} with a {d}mm hole {N}mm in from the left edge",
            f"{obj} {L} x {W} x {H}, a {d}mm hole {N}mm from one end face",
        ])
        rows.append(row(p, s, "box"))
    # --- E) a spaced pair, S apart, centered ---
    for _ in range(300):
        L = random.choice(range(60, 181, 5)); W = random.choice(range(30, 90, 5)); H = random.choice([8, 10, 12, 16])
        d = random.choice(DIAS); S = random.choice(range(20, int(L - d - 8), 10) or [20])
        x = round(S/2, 1)
        s = box(L, W, H); obj = random.choice(OBJS_BOX); s["object"] = obj
        s["features"] = [thru(-x, 0, d), thru(x, 0, d)]
        p = random.choice([
            f"a {L}x{W}x{H}mm {obj} with two {d}mm holes {S}mm apart, centered",
            f"{obj} {L} x {W} x {H}, a pair of {d}mm holes spaced {S}mm on center",
        ])
        rows.append(row(p, s, "box"))
    return rows

rows = emit([])
random.shuffle(rows)
with open(OUT, "w") as w:
    for r in rows:
        w.write(json.dumps(r) + "\n")
from collections import Counter
print(f"wrote {len(rows)} positioned-hole pairs -> {OUT}")
print("shapes:", dict(Counter(r["shape"] for r in rows)))
print("sample:", rows[0]["prompt"].split("Description: ")[1][:80], "->", rows[0]["code"][:140])
