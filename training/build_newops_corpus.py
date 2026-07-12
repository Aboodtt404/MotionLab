"""Phase-2 corpus batch for the PHASE-1 operators (the CADEvolve seed→sample→verifier-filter loop,
CPU-only — no LLM engine, so it runs while Track B owns the GPU).

The bench A/B found the fine-tune starves exactly the non-box convention families; Phase 1 then LIFTED
the box-only guards, so the model can now be TAUGHT operators it was previously forbidden to emit:
  • rim fillet / chamfer on a cylinder or revolve (edges='top'|'bottom')
  • shell on a cylinder (open cup / sealed hollow)
  • the regular N-gon PRISM base (hex/square/octagon standoff, boss, housing) + its box-style finishing
  • the non-circular (rectangular) SWEEP section (channel / box-section beam / rail)

Each family is a PARAMETRIC seed generator; we sample it, then the verifier is the survival filter:
a candidate is kept only if it BUILDS+verifies AND its emitted idiomatic artifact exec+verifies
(the corpus-gate-on-artifact discipline — gate the SHIPPED code, not the internal builder). Captions
come from the deterministic rule-based describe() (l0–l3), code from emit_idiomatic (the fine-tune
target), records via corpus.training_sample (schema-validated). Output plugs straight into
build_curriculum.py --corpus.

Run:
  cad_pipeline/.venv/bin/python training/build_newops_corpus.py \
      --per-family 120 --out corpus_out/batch5_newops.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter

sys.path.insert(0, ".")

import cadquery as cq  # noqa: E402

from cad_pipeline.builder import build, emit_code  # noqa: E402
from cad_pipeline.captions import describe  # noqa: E402
from cad_pipeline.emit_idiomatic import emit_idiomatic  # noqa: E402
from cad_pipeline.corpus import training_sample  # noqa: E402
from cad_pipeline.spec import Spec, feature_shape_conflicts  # noqa: E402
from cad_pipeline.verifier import verify  # noqa: E402


def _level(spec: Spec) -> str:
    n = len(spec.features)
    return "L1" if n <= 1 else ("L2" if n <= 3 else "L3")


def _hole(rng, dmax):
    return {"type": "through_hole", "diameter": round(rng.uniform(3, max(3.1, dmax)), 1)}


# ---------------------------------------------------------------- parametric seed families
def cyl_rim_fillet(rng) -> tuple:
    D = round(rng.uniform(16, 80), 1); H = round(rng.uniform(12, 60), 1)
    r = round(rng.uniform(1.0, min(4.0, D / 6, H / 3)), 1)
    edge = rng.choice(["top", "bottom"])
    feats = [{"type": "fillet", "radius": r, "edges": edge}]
    if rng.random() < 0.5:
        feats.append(_hole(rng, D * 0.3))
    return "rim-filleted cylindrical spacer/boss", Spec(
        object=rng.choice(["spacer", "boss", "roller", "hub cap", "bushing"]),
        shape="cylinder", envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def cyl_rim_chamfer(rng) -> tuple:
    D = round(rng.uniform(18, 80), 1); H = round(rng.uniform(12, 60), 1)
    c = round(rng.uniform(1.0, min(3.5, D / 8, H / 4)), 1)
    feats = [{"type": "chamfer", "distance": c, "edges": rng.choice(["top", "bottom"])}]
    if rng.random() < 0.5:
        feats.append(_hole(rng, D * 0.3))
    return "chamfered cylindrical boss/collar", Spec(
        object=rng.choice(["collar", "boss", "lead-in bush", "nozzle ferrule"]),
        shape="cylinder", envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def revolve_rim(rng) -> tuple:
    # a stepped/tapered hub, then break the top rim (fillet or chamfer)
    R0 = round(rng.uniform(10, 26), 1); R1 = round(rng.uniform(6, R0 - 2), 1)
    h0 = round(rng.uniform(8, 20), 1); h1 = round(rng.uniform(10, 24), 1)
    profile = [(0, 0), (R0, 0), (R0, h0), (R1, h0), (R1, h0 + h1), (0, h0 + h1)]
    if rng.random() < 0.5:
        f = {"type": "fillet", "radius": round(rng.uniform(1.0, min(3.0, R1 / 2)), 1), "edges": "top"}
    else:
        f = {"type": "chamfer", "distance": round(rng.uniform(1.0, min(2.5, R1 / 2)), 1), "edges": "top"}
    return "stepped turned hub with a broken rim", Spec(
        object=rng.choice(["stepped hub", "turned pulley", "shaft collar", "spindle boss"]),
        shape="revolve", profile=profile, features=[f], tolerance=0.1)


def cyl_shell(rng) -> tuple:
    D = round(rng.uniform(30, 90), 1); H = round(rng.uniform(20, 70), 1)
    t = round(rng.uniform(1.5, min(4.0, D / 8)), 1)
    face = rng.choice(["top", "none"])
    feats = [{"type": "shell", "thickness": t, "open_face": face}]
    if face == "top" and rng.random() < 0.4:
        feats.append(_hole(rng, D * 0.25))
    return "hollow cylindrical cup/canister/housing", Spec(
        object=rng.choice(["cup", "canister", "cylindrical housing", "cap", "sleeve"]),
        shape="cylinder", envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def prism_standoff(rng) -> tuple:
    sides = rng.choice([4, 6, 6, 8])   # hex is the common one
    D = round(rng.uniform(10, 40), 1); H = round(rng.uniform(8, 45), 1)
    feats = [_hole(rng, D * 0.4)] if rng.random() < 0.8 else []
    return "hex/square/octagon standoff or nut stock", Spec(
        object=rng.choice(["standoff", "hex nut blank", "spacer post", "pillar"]),
        shape="prism", sides=sides, envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def prism_boss_fillet(rng) -> tuple:
    sides = rng.choice([4, 6, 8]); D = round(rng.uniform(16, 44), 1); H = round(rng.uniform(8, 30), 1)
    r = round(rng.uniform(0.8, min(2.5, D / 10)), 1)
    kind = rng.choice(["fillet", "chamfer"])
    f = ({"type": "fillet", "radius": r, "edges": "all_vertical"} if kind == "fillet"
         else {"type": "chamfer", "distance": r, "edges": "top"})
    feats = [f]
    if rng.random() < 0.5:
        feats.append(_hole(rng, D * 0.35))
    return "polygon boss with softened corners/rim", Spec(
        object=rng.choice(["hex boss", "octagon cap", "square post", "knob blank"]),
        shape="prism", sides=sides, envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def prism_shell(rng) -> tuple:
    sides = rng.choice([6, 8]); D = round(rng.uniform(30, 60), 1); H = round(rng.uniform(18, 45), 1)
    t = round(rng.uniform(1.5, min(3.0, D / 12)), 1)
    return "hollow polygonal housing", Spec(
        object=rng.choice(["hex housing", "octagon enclosure", "polygonal cup"]),
        shape="prism", sides=sides, envelope={"diameter": D, "height": H},
        features=[{"type": "shell", "thickness": t, "open_face": "top"}], tolerance=0.1)


def rect_sweep(rng) -> tuple:
    w = round(rng.uniform(8, 30), 1); h = round(rng.uniform(6, 24), 1)
    # a straight beam, an L-channel, or a 3D-bent rail
    kind = rng.choice(["straight", "L", "3d"])
    if kind == "straight":
        path = [[0, 0, 0], [round(rng.uniform(60, 160), 1), 0, 0]]
    elif kind == "L":
        a = round(rng.uniform(40, 90), 1); b = round(rng.uniform(30, 70), 1)
        path = [[0, 0, 0], [a, 0, 0], [a, 0, b]]
    else:
        a = round(rng.uniform(30, 70), 1); b = round(rng.uniform(25, 55), 1); c = round(rng.uniform(20, 45), 1)
        path = [[0, 0, 0], [a, 0, 0], [a, b, 0], [a, b, c]]
    return "box-section beam / channel / rail", Spec(
        object=rng.choice(["box beam", "channel", "extruded rail", "guide bar"]),
        shape="sweep", envelope={"width": w, "height": h}, path=path, tolerance=0.1)


FAMILIES = [cyl_rim_fillet, cyl_rim_chamfer, revolve_rim, cyl_shell,
            prism_standoff, prism_boss_fillet, prism_shell, rect_sweep]


# ---------------------------------------------------------------- batch6: part-level GROWTH families
# L3 multi-feature combos on the lifted vocabulary, the cylinder-bolt-circle (half-drill) fix,
# micro-bevel styling (film-hardware research: break every rim), greeble detail passes (feature-pure —
# the greeble verifier short-circuits per-feature inventory, so greebled samples carry no other
# features to keep captions honest), and the HERO shapes (profile_extrude / loft_sections — the
# structural-richness arc's film bodies, absent from every earlier batch).

def flange_cyl_boltcircle(rng) -> tuple:
    # THE half-drill fix: bolt circles on a z∈[0,H] cylinder (the model assumed box-centered z)
    D = round(rng.uniform(50, 110), 1); H = round(rng.uniform(8, 22), 1)
    n = rng.choice([4, 6, 8]); pcd = round(D * rng.uniform(0.6, 0.8), 1)
    d = round(rng.uniform(4, 8), 1)
    feats = [{"type": "through_hole", "diameter": round(rng.uniform(10, D * 0.3), 1)},
             {"type": "hole_pattern", "pattern": "bolt_circle", "count": n, "pitch_diameter": pcd, "diameter": d}]
    if rng.random() < 0.4:
        feats.append({"type": "chamfer", "distance": round(rng.uniform(0.8, 2.0), 1), "edges": "top"})
    return "bolt-circle flange (cylinder)", Spec(
        object=rng.choice(["bolt-circle flange", "bearing flange", "pipe flange", "motor flange"]),
        shape="cylinder", envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def combo_shelled_rim_cyl(rng) -> tuple:
    # hollow cup with a broken rim — shell(top) removes the top rim, so break the BOTTOM
    D = round(rng.uniform(34, 80), 1); H = round(rng.uniform(24, 60), 1)
    t = round(rng.uniform(1.8, min(4.0, D / 9)), 1)
    kind = rng.choice(["fillet", "chamfer"])
    rim = ({"type": "fillet", "radius": round(rng.uniform(1.0, 2.5), 1), "edges": "bottom"} if kind == "fillet"
           else {"type": "chamfer", "distance": round(rng.uniform(0.8, 2.0), 1), "edges": "bottom"})
    return "hollow housing with a finished base rim", Spec(
        object=rng.choice(["canister housing", "sensor pod shell", "cup housing", "battery sleeve"]),
        shape="cylinder", envelope={"diameter": D, "height": H},
        features=[rim, {"type": "shell", "thickness": t, "open_face": "top"}], tolerance=0.1)


def combo_prism_l3(rng) -> tuple:
    sides = rng.choice([4, 6, 8]); D = round(rng.uniform(26, 52), 1); H = round(rng.uniform(14, 34), 1)
    feats = []
    if rng.random() < 0.5:
        feats.append({"type": "fillet", "radius": round(rng.uniform(0.8, min(2.0, D / 14)), 1), "edges": "all_vertical"})
    else:
        feats.append({"type": "chamfer", "distance": round(rng.uniform(0.8, 1.8), 1), "edges": "top"})
    if rng.random() < 0.5:
        feats.append({"type": "counterbore", "diameter": round(rng.uniform(4, 6), 1),
                      "cbore_diameter": round(rng.uniform(8, 12), 1), "cbore_depth": round(rng.uniform(2, 4), 1),
                      "at": [0, 0]})
    else:
        pw = round(D * rng.uniform(0.25, 0.4), 1)
        feats.append({"type": "pocket", "length": pw, "width": pw, "depth": round(rng.uniform(1.5, H * 0.25), 1)})
        feats.append({"type": "through_hole", "diameter": round(rng.uniform(3.5, 6), 1)})
    return "multi-feature polygonal mount", Spec(
        object=rng.choice(["hex mount boss", "octagon fitting", "square coupler block"]),
        shape="prism", sides=sides, envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def combo_revolve_arcs_rim(rng) -> tuple:
    # turned body with a CURVED meridian (arc flank — barrel/flare) + a broken top rim
    R0 = round(rng.uniform(12, 26), 1); R1 = round(rng.uniform(7, R0 - 3), 1)
    h0 = round(rng.uniform(10, 22), 1); h1 = round(rng.uniform(10, 20), 1)
    profile = [(0, 0), (R0, 0), (R0, h0), (R1, h0 + h1), (0, h0 + h1)]
    sag = round(-rng.uniform(1.0, 3.0), 1)          # outward bulge on the taper run
    arcs = [0.0, 0.0, sag, 0.0]
    kind = rng.choice(["fillet", "chamfer"])
    rim = ({"type": "fillet", "radius": round(rng.uniform(1.0, min(2.5, R1 / 3)), 1), "edges": "top"} if kind == "fillet"
           else {"type": "chamfer", "distance": round(rng.uniform(0.8, min(2.0, R1 / 3)), 1), "edges": "top"})
    return "flared turned body with a finished rim", Spec(
        object=rng.choice(["flared hub", "barrel spindle", "curved nozzle body", "vase-turned boss"]),
        shape="revolve", profile=profile, profile_arcs=arcs, features=[rim], tolerance=0.1)


def micro_bevel_box(rng) -> tuple:
    # film-hardware rule: break EVERY edge — verticals filleted, both rims chamfered
    L = round(rng.uniform(40, 110), 1); W = round(rng.uniform(30, 80), 1); H = round(rng.uniform(12, 40), 1)
    feats = [{"type": "fillet", "radius": round(rng.uniform(1.5, 4.0), 1), "edges": "all_vertical"},
             {"type": "chamfer", "distance": round(rng.uniform(0.6, 1.2), 1), "edges": "top"},
             {"type": "chamfer", "distance": round(rng.uniform(0.6, 1.2), 1), "edges": "bottom"}]
    if rng.random() < 0.5:
        feats.append({"type": "through_hole", "diameter": round(rng.uniform(5, 12), 1)})
    return "micro-beveled housing block (every edge broken)", Spec(
        object=rng.choice(["equipment housing", "console block", "junction body", "chassis block"]),
        shape="box", envelope={"length": L, "width": W, "height": H}, features=feats, tolerance=0.1)


def micro_bevel_cyl(rng) -> tuple:
    D = round(rng.uniform(24, 70), 1); H = round(rng.uniform(14, 50), 1)
    feats = [{"type": "chamfer", "distance": round(rng.uniform(0.7, 1.6), 1), "edges": "top"},
             {"type": "chamfer", "distance": round(rng.uniform(0.7, 1.6), 1), "edges": "bottom"}]
    if rng.random() < 0.5:
        feats.append({"type": "through_hole", "diameter": round(rng.uniform(5, D * 0.3), 1)})
    return "double-chamfered cylindrical body", Spec(
        object=rng.choice(["spacer bushing", "drum body", "piston blank", "roller sleeve"]),
        shape="cylinder", envelope={"diameter": D, "height": H}, features=feats, tolerance=0.1)


def _greeble_feat(rng, face="top") -> dict:
    return {"type": "greeble", "face": face,
            "panel": round(rng.uniform(12, 26), 1), "depth": round(rng.uniform(1.2, 3.0), 1),
            "density": round(rng.uniform(0.35, 0.7), 2), "groove": round(rng.uniform(0.8, 1.4), 1),
            "seed": rng.randint(0, 9999), "levels": rng.choice([1, 2, 2]),
            "subdiv": round(rng.uniform(0.25, 0.45), 2), "raised": round(rng.uniform(0.15, 0.4), 2),
            "raise_h": round(rng.uniform(1.0, 2.0), 1), "focal": rng.choice(["center", "edges", "none"]),
            "bevel": rng.choice([0.0, 0.5, 0.8])}


def greeble_box(rng) -> tuple:
    L = round(rng.uniform(70, 160), 1); W = round(rng.uniform(50, 110), 1); H = round(rng.uniform(6, 16), 1)
    return "greebled hull/deck panel", Spec(
        object=rng.choice(["hull panel", "deck plate", "bulkhead panel", "sci-fi wall tile"]),
        shape="box", envelope={"length": L, "width": W, "height": H},
        features=[_greeble_feat(rng)], tolerance=0.1)


def greeble_cyl(rng) -> tuple:
    D = round(rng.uniform(45, 100), 1); H = round(rng.uniform(40, 100), 1)
    return "greebled cylindrical housing (lateral panels)", Spec(
        object=rng.choice(["engine housing", "thruster drum", "reactor casing", "silo body"]),
        shape="cylinder", envelope={"diameter": D, "height": H},
        features=[_greeble_feat(rng, face="side")], tolerance=0.1)


def greeble_revolve(rng) -> tuple:
    R0 = round(rng.uniform(22, 40), 1); R1 = round(rng.uniform(14, R0 - 4), 1)
    h0 = round(rng.uniform(20, 40), 1); h1 = round(rng.uniform(16, 30), 1)
    profile = [(0, 0), (R0, 0), (R0, h0), (R1, h0), (R1, h0 + h1), (0, h0 + h1)]
    return "greebled stepped drum (turned)", Spec(
        object=rng.choice(["stepped engine drum", "turbine casing", "turret base"]),
        shape="revolve", profile=profile, features=[_greeble_feat(rng, face="side")], tolerance=0.1)


def hero_profile_extrude(rng) -> tuple:
    """Silhouette bodies: a stepped/chamfered side outline (X–Z), optionally trimmed by a hexagonal-ish
    plan; arcs on one run for a curved deck. Parametric + always simple/closed by construction."""
    L = round(rng.uniform(120, 240), 1)
    h_nose = round(rng.uniform(10, 22), 1); h_mid = round(rng.uniform(28, 52), 1)
    x_rise = round(L * rng.uniform(0.2, 0.35), 1); x_fall = round(L * rng.uniform(0.65, 0.8), 1)
    h_tail = round(rng.uniform(12, 26), 1)
    side = [(0, 0), (L, 0), (L, h_tail), (x_fall, h_mid), (x_rise, h_mid), (0, h_nose)]
    side_arcs = [0.0] * 6
    if rng.random() < 0.5:                       # curved canopy run between the two mid stations
        side_arcs[3] = round(-rng.uniform(2, 6), 1)
    W = round(rng.uniform(40, 90), 1)
    if rng.random() < 0.5:                       # plan taper: hexagonal plan narrows nose + tail
        wn = round(W * rng.uniform(0.35, 0.6), 1)
        plan = [(0, -wn / 2), (x_rise, -W / 2), (x_fall, -W / 2), (L, -wn / 2),
                (L, wn / 2), (x_fall, W / 2), (x_rise, W / 2), (0, wn / 2)]
        spec = Spec(object=rng.choice(["hull silhouette body", "vehicle body blank", "fuselage slab"]),
                    shape="profile_extrude", side_profile=side, side_arcs=side_arcs,
                    plan_profile=plan, tolerance=0.1)
    else:
        spec = Spec(object=rng.choice(["profiled chassis slab", "silhouette bracket blank", "deck profile body"]),
                    shape="profile_extrude", side_profile=side, side_arcs=side_arcs,
                    envelope={"width": W}, tolerance=0.1)
    return "hero silhouette body (side ∩ plan)", spec


def hero_loft_sections(rng) -> tuple:
    """Fuselage: 3–5 stations along X, small nose → full mid → tapered tail, mixed rect/ellipse."""
    n = rng.choice([3, 4, 5])
    L = round(rng.uniform(140, 260), 1)
    wmax = round(rng.uniform(40, 80), 1); hmax = round(rng.uniform(30, 60), 1)
    xs = sorted(round(L * k / (n - 1), 1) for k in range(n))
    # bell-shaped size profile: ends small, middle full
    def _sz(i):
        t = abs((i / (n - 1)) - 0.5) * 2          # 0 at mid → 1 at ends
        s = 1.0 - t * rng.uniform(0.5, 0.7)
        return s
    sections = []
    kind = rng.choice(["ellipse", "rect", "mix"])
    for i, x in enumerate(xs):
        s = _sz(i)
        k = ("ellipse" if kind == "ellipse" else "rect" if kind == "rect"
             else rng.choice(["ellipse", "rect"]))
        sections.append({"x": x, "width": round(max(10.0, wmax * s), 1),
                         "height": round(max(8.0, hmax * s), 1),
                         "z_center": round(hmax / 2, 1), "kind": k})
    return "hero lofted fuselage (multi-station)", Spec(
        object=rng.choice(["fuselage body", "lofted hull", "pod body", "nacelle body"]),
        shape="loft_sections", sections=sections, tolerance=0.1)


def mirror_combo_box(rng) -> tuple:
    L = round(rng.uniform(60, 110), 1); W = round(rng.uniform(30, 60), 1); H = round(rng.uniform(12, 28), 1)
    hx = round(L * rng.uniform(0.25, 0.4), 1)
    return "mirror-symmetric bracket", Spec(
        object=rng.choice(["symmetric bracket", "twin-boss plate", "mirrored link plate"]),
        shape="box", envelope={"length": L, "width": W, "height": H},
        features=[{"type": "through_hole", "diameter": round(rng.uniform(5, 10), 1), "at": [hx, 0]},
                  {"type": "mirror", "plane": "YZ"}], tolerance=0.1)


GROWTH_FAMILIES = [flange_cyl_boltcircle, combo_shelled_rim_cyl, combo_prism_l3, combo_revolve_arcs_rim,
                   micro_bevel_box, micro_bevel_cyl, greeble_box, greeble_cyl, greeble_revolve,
                   hero_profile_extrude, hero_loft_sections, mirror_combo_box]

# hero shapes + greeble aren't in emit_idiomatic's vocabulary (greeble is a precomputed layout dump
# shared verbatim by build/emit/verifier — emit_code IS its canonical form) — their training target is
# the golden emit_code trace (same double-gate discipline: the SHIPPED string must exec+verify).
_EMIT_CODE_FAMILIES = {"hero_profile_extrude", "hero_loft_sections",
                       "greeble_box", "greeble_cyl", "greeble_revolve"}


def _gate(spec: Spec, emitter) -> tuple:
    """Survival filter: no shape conflict, builds+verifies, AND the emitted artifact exec+verifies
    (gate the SHIPPED code). Returns (verifier report, code) or (None, None)."""
    if feature_shape_conflicts(spec):
        return None, None
    try:
        rep = verify(build(spec), spec)
        if not rep.passed:
            return None, None
        code = emitter(spec)
        ns = {"cq": cq}
        exec(code, ns)  # noqa: S102 — our own emitter
        res = ns.get("result")
        wp = res if isinstance(res, cq.Workplane) else cq.Workplane(obj=res)
        if not verify(wp, spec).passed:
            return None, None
        return rep, code
    except Exception:  # noqa: BLE001
        return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=120, help="keep target per family")
    ap.add_argument("--max-attempts", type=int, default=8, help="param resamples per keep before giving up")
    ap.add_argument("--set", choices=["newops", "growth", "all"], default="newops",
                    help="newops = the Phase-1 operator batch; growth = batch6 combos/heroes/greeble")
    ap.add_argument("--out", default="corpus_out/batch5_newops.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    fams = {"newops": FAMILIES, "growth": GROWTH_FAMILIES, "all": FAMILIES + GROWTH_FAMILIES}[a.set]

    kept, rejects = [], []
    for fam in fams:
        emitter = emit_code if fam.__name__ in _EMIT_CODE_FAMILIES else emit_idiomatic
        got = 0
        attempts = 0
        seen_sigs = set()
        while got < a.per_family and attempts < a.per_family * a.max_attempts:
            attempts += 1
            category, spec = fam(rng)
            sig = spec.model_dump_json()
            if sig in seen_sigs:
                continue
            seen_sigs.add(sig)
            rep, code = _gate(spec, emitter)
            if rep is None:
                rejects.append({"family": fam.__name__, "spec": json.loads(spec.model_dump_json())})
                continue
            prompts = describe(spec, random.Random(a.seed ^ hash(sig) & 0xFFFF))
            sample = training_sample(
                category=category,
                tags={"capabilities": sorted({spec.shape, *[f.type for f in spec.features]}),
                      "level": _level(spec)},
                prompts=prompts,
                code=code,
                spec=spec,
                report=rep.to_dict(),
            )
            kept.append(json.loads(sample.model_dump_json()))
            got += 1
        print(f"  {fam.__name__:24s} kept {got}/{attempts} attempts", flush=True)

    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        for r in kept:
            f.write(json.dumps(r) + "\n")
    with open(a.out.replace(".jsonl", ".rejects.jsonl"), "w") as f:
        for r in rejects:
            f.write(json.dumps(r) + "\n")

    caps = Counter(c for r in kept for c in r["tags"]["capabilities"])
    shapes = Counter(r["spec"]["shape"] for r in kept)
    levels = Counter(r["tags"]["level"] for r in kept)
    print(json.dumps({"out": a.out, "kept": len(kept), "rejected": len(rejects),
                      "by_shape": dict(shapes), "by_level": dict(levels),
                      "capability_coverage": dict(caps.most_common())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
