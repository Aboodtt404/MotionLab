"""Stage A NL exposure — synthesize NL→greeble-spec pairs so the parser learns the greeble feature.
Correct-by-construction: build the (box + greeble) spec, back-translate to NL that names the detail look
and (sometimes) the density/panel size. Maps density words → values. Run:
  cad_pipeline/.venv/bin/python training/build_greeble_corpus.py
Out: /workspace/.hf_home/cad_corpus/greeble.jsonl  ({prompt, code, shape, level})
"""
import json, random, sys
sys.path.insert(0, "/home/abdelrahman/MotionLab")
from cad_pipeline.nl_spec import PARSER_HINT

random.seed(11)
OUT = "/workspace/.hf_home/cad_corpus/greeble.jsonl"
OBJS = ["hull panel", "bulkhead panel", "armor panel", "access panel", "reactor casing", "ship plating",
        "greeble panel", "hull plate", "control panel", "engine casing", "detailed plate", "tech panel",
        "spacecraft panel", "machinery cover", "side panel", "fuselage panel"]
# density words → density value
DENS = {"lightly": 0.3, "sparsely": 0.25, "": 0.5, "moderately": 0.5, "medium": 0.5,
        "heavily": 0.8, "densely": 0.85, "richly": 0.8, "intricately": 0.85}
PANELWORD = {"fine": 12, "small": 14, "": 22, "large": 32, "big": 34, "chunky": 36}

def row(prompt, spec):
    return {"prompt": PARSER_HINT + prompt, "code": json.dumps(spec, separators=(",", ":")),
            "shape": "box", "level": "greeble"}

def main():
    rows = []
    for _ in range(1500):
        L = random.choice(range(80, 301, 10)); W = random.choice(range(60, min(L, 221), 10)); H = random.choice([8, 10, 12, 15, 20, 25])
        dw = random.choice(list(DENS)); pw = random.choice(list(PANELWORD))
        density = DENS[dw]; panel = PANELWORD[pw]; depth = random.choice([2, 2, 3, 3, 4]); seed = random.randint(0, 9999)
        obj = random.choice(OBJS)
        g = {"type": "greeble", "panel": panel, "depth": depth, "density": density, "seed": seed}
        spec = {"object": obj, "shape": "box", "envelope": {"length": L, "width": W, "height": H},
                "features": [g], "tolerance": 0.1}
        dpart = (dw + " ") if dw else ""
        ppart = (f"{pw} panels, " if pw else "")
        verb = random.choice(["greebled", "detailed", "panelled", "industrial-detailed", "covered in greeble",
                              "with sci-fi surface detail", "with hard-surface paneling"])
        p = random.choice([
            f"a {dpart}{verb} {obj} {L}x{W}x{H}mm",
            f"a {L}x{W}x{H}mm {obj}, {dpart}{verb}",
            f"a {obj} {L} x {W} x {H}, {ppart}{dpart}{verb}",
            f"a {L}x{W}x{H} {obj} with {dpart}greeble detail",
        ]).replace("  ", " ").strip()
        rows.append(row(p, spec))
    random.shuffle(rows)
    open(OUT, "w").write("\n".join(json.dumps(r) for r in rows))
    print(f"wrote {len(rows)} NL→greeble pairs -> {OUT}")
    print("sample:", rows[0]["prompt"].split("Description: ")[1], "->", rows[0]["code"][:120])

if __name__ == "__main__":
    main()
