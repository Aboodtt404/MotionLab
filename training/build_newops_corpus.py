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

from cad_pipeline.builder import build  # noqa: E402
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


def _gate(spec: Spec):
    """Survival filter: no shape conflict, builds+verifies, AND the emitted idiomatic artifact
    exec+verifies (gate the SHIPPED code). Returns the verifier report dict or None."""
    if feature_shape_conflicts(spec):
        return None
    try:
        rep = verify(build(spec), spec)
        if not rep.passed:
            return None
        ns = {"cq": cq}
        exec(emit_idiomatic(spec), ns)  # noqa: S102 — our own emitter
        res = ns.get("result")
        wp = res if isinstance(res, cq.Workplane) else cq.Workplane(obj=res)
        if not verify(wp, spec).passed:
            return None
        return rep
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=120, help="keep target per family")
    ap.add_argument("--max-attempts", type=int, default=8, help="param resamples per keep before giving up")
    ap.add_argument("--out", default="corpus_out/batch5_newops.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    kept, rejects = [], []
    for fam in FAMILIES:
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
            rep = _gate(spec)
            if rep is None:
                rejects.append({"family": fam.__name__, "spec": json.loads(spec.model_dump_json())})
                continue
            prompts = describe(spec, random.Random(a.seed ^ hash(sig) & 0xFFFF))
            sample = training_sample(
                category=category,
                tags={"capabilities": sorted({spec.shape, *[f.type for f in spec.features]}),
                      "level": _level(spec)},
                prompts=prompts,
                code=emit_idiomatic(spec),
                spec=spec,
                report=rep.to_dict(),
            )
            kept.append(json.loads(sample.model_dump_json()))
            got += 1
        print(f"  {fam.__name__:20s} kept {got}/{attempts} attempts", flush=True)

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
