"""Stratified eval — does off-the-shelf qwen3.6-27b realize the FULL vocabulary? (track-a-finetuning §5)

The golden/hard sets (eval_baseline.py) only exercise the original box/cylinder + holes/fillet/pocket
vocabulary. This harness adds the Tier 1–3 geometry (revolve, draft, counterbore/countersink, mirror,
shell, sweep, multi-profile loft, var_fillet, thread) and the hard OOD combinations, each tagged so we
report WHERE the model breaks, not just an aggregate:

  • by CAPABILITY (revolve / shell / sweep / …) — which new feature defeats it
  • by LEVEL (L1 single feature · L2 a couple · L3 many/combined) — the infer-vs-transcribe curve
  • by DISTRIBUTION (in = one capability in isolation · ood = novel multi-capability parts)

Primary metric = per-feature pass-rate (what the verifier optimizes; CD/IoU can't see it), plus
exec-validity and the failure-category profile. Every case is pre-flighted (built + verified by the
deterministic builder) so a failure is the MODEL's, not the verifier's. This localizes the residual
gap the §6 fine-tune must close.

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.eval_vocab [in|ood|all] [max_attempts]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import List

from ..loop import VLLMGenerator, run
from ..spec import Spec
from ..builder import build
from ..verifier import verify


@dataclass
class Case:
    spec: Spec
    cap: str            # capability under test (revolve / shell / sweep / composite / …)
    level: str          # L1 | L2 | L3
    dist: str           # in | ood


def C(spec, cap, level, dist):
    return Case(spec=spec, cap=cap, level=level, dist=dist)


# --------------------------------------------------------------------- IN-DISTRIBUTION (one capability)
# Each isolates a single new capability at L1–L2 — "can the model produce a correct <feature> at all?"
EVAL_IN: List[Case] = [
    C(Spec(object="a turned stepped hub spun on a lathe", shape="revolve",
           profile=[(0, 0), (20, 0), (20, 10), (12, 10), (12, 30), (0, 30)], tolerance=0.1), "revolve", "L2", "in"),
    C(Spec(object="a turned nozzle that tapers from a wide base to a narrow neck", shape="revolve",
           profile=[(0, 0), (20, 0), (20, 10), (8, 25), (8, 40), (0, 40)], tolerance=0.1), "revolve", "L2", "in"),
    C(Spec(object="a molded housing block with 5-degree draft on its side walls", shape="box",
           envelope={"length": 60, "width": 40, "height": 25}, features=[{"type": "draft", "angle": 5}], tolerance=0.1), "draft", "L1", "in"),
    C(Spec(object="a plate with a counterbored screw hole in the centre", shape="box",
           envelope={"length": 50, "width": 50, "height": 20},
           features=[{"type": "counterbore", "diameter": 6, "cbore_diameter": 12, "cbore_depth": 4, "at": [0, 0]}], tolerance=0.1), "counterbore", "L1", "in"),
    C(Spec(object="a plate with a countersunk (90 degree) flat-head screw hole", shape="box",
           envelope={"length": 50, "width": 50, "height": 20},
           features=[{"type": "countersink", "diameter": 6, "csk_diameter": 12, "csk_angle": 90, "at": [0, 0]}], tolerance=0.1), "countersink", "L1", "in"),
    C(Spec(object="a left/right symmetric bracket (mirror an off-centre hole)", shape="box",
           envelope={"length": 80, "width": 40, "height": 20},
           features=[{"type": "through_hole", "diameter": 8, "at": [25, 0]}, {"type": "mirror", "plane": "YZ"}], tolerance=0.1), "mirror", "L2", "in"),
    C(Spec(object="a thin-walled open enclosure, 3 mm walls, open at the top", shape="box",
           envelope={"length": 60, "width": 40, "height": 30}, features=[{"type": "shell", "thickness": 3, "open_face": "top"}], tolerance=0.1), "shell", "L1", "in"),
    C(Spec(object="an L-shaped round coolant pipe, 10 mm bore", shape="sweep", envelope={"diameter": 10},
           path=[(0, 0, 0), (60, 0, 0), (60, 0, 40)], tolerance=0.1), "sweep", "L2", "in"),
    C(Spec(object="a round-to-rectangular transition adapter", shape="loft",
           envelope={"length": 80, "width": 40, "height": 30, "diameter_top": 24}, tolerance=0.1), "loft", "L2", "in"),
    C(Spec(object="a block whose vertical edges blend from a 2 mm radius at the bottom to 10 mm at the top", shape="box",
           envelope={"length": 60, "width": 40, "height": 30},
           features=[{"type": "var_fillet", "r1": 2, "r2": 10, "edges": "all_vertical"}], tolerance=0.1), "var_fillet", "L2", "in"),
    C(Spec(object="a nut plate with an M12 tapped (internal threaded) hole", shape="box",
           envelope={"length": 40, "width": 40, "height": 12},
           features=[{"type": "thread", "diameter": 12, "pitch": 1.75, "kind": "internal", "at": [0, 0]}], tolerance=0.1), "thread", "L1", "in"),
    C(Spec(object="a panel with two square insets and a long groove (greeble detail)", shape="box",
           envelope={"length": 100, "width": 60, "height": 8},
           features=[{"type": "pocket", "length": 24, "width": 24, "depth": 2, "at": [-28, 0]},
                     {"type": "pocket", "length": 24, "width": 24, "depth": 2, "at": [28, 0]},
                     {"type": "pocket", "length": 80, "width": 3, "depth": 1.5, "at": [0, -22]}], tolerance=0.1), "panel", "L2", "in"),
]

# --------------------------------------------------------------------- OUT-OF-DISTRIBUTION (combinations)
# Novel multi-capability parts the goldens never show — the real test of whether the model can COMPOSE
# the vocabulary, where the synthetic→real gap bites (Zero-to-CAD 0.747→0.377).
EVAL_OOD: List[Case] = [
    C(Spec(object="a draughted enclosure: thin 2.5 mm walls, open top, 3-degree draft, four corner mounting holes", shape="box",
           envelope={"length": 90, "width": 70, "height": 35},
           features=[{"type": "draft", "angle": 3}, {"type": "shell", "thickness": 2.5, "open_face": "top"},
                     {"type": "through_hole", "diameter": 4, "at": [-38, -28]}, {"type": "through_hole", "diameter": 4, "at": [38, -28]},
                     {"type": "through_hole", "diameter": 4, "at": [-38, 28]}, {"type": "through_hole", "diameter": 4, "at": [38, 28]}], tolerance=0.1), "composite", "L3", "ood"),
    C(Spec(object="a turned pulley: a flanged hub with a central bore", shape="revolve",
           profile=[(0, 0), (30, 0), (30, 6), (10, 6), (10, 24), (30, 24), (30, 30), (0, 30)], tolerance=0.1), "revolve", "L3", "ood"),
    C(Spec(object="a faceplate with four countersunk corner holes and a central counterbored hole", shape="box",
           envelope={"length": 100, "width": 100, "height": 14},
           features=[{"type": "countersink", "diameter": 5, "csk_diameter": 10, "csk_angle": 90, "at": [-40, -40]},
                     {"type": "countersink", "diameter": 5, "csk_diameter": 10, "csk_angle": 90, "at": [40, -40]},
                     {"type": "countersink", "diameter": 5, "csk_diameter": 10, "csk_angle": 90, "at": [-40, 40]},
                     {"type": "countersink", "diameter": 5, "csk_diameter": 10, "csk_angle": 90, "at": [40, 40]},
                     {"type": "counterbore", "diameter": 8, "cbore_diameter": 16, "cbore_depth": 5, "at": [0, 0]}], tolerance=0.1), "composite", "L3", "ood"),
    C(Spec(object="a symmetric mounting bracket: mirror a plate that has an off-centre hole and a fillet", shape="box",
           envelope={"length": 100, "width": 50, "height": 10},
           features=[{"type": "fillet", "radius": 5, "edges": "all_vertical"},
                     {"type": "through_hole", "diameter": 8, "at": [30, 0]}, {"type": "mirror", "plane": "YZ"}], tolerance=0.1), "mirror", "L3", "ood"),
    C(Spec(object="a louvered vent panel: a plate milled with a row of 5 recessed slots", shape="box",
           envelope={"length": 80, "width": 50, "height": 6},
           features=[{"type": "pocket", "length": 8, "width": 30, "depth": 2, "at": [-24, 0]},
                     {"type": "pocket", "length": 8, "width": 30, "depth": 2, "at": [-12, 0]},
                     {"type": "pocket", "length": 8, "width": 30, "depth": 2, "at": [0, 0]},
                     {"type": "pocket", "length": 8, "width": 30, "depth": 2, "at": [12, 0]},
                     {"type": "pocket", "length": 8, "width": 30, "depth": 2, "at": [24, 0]}], tolerance=0.1), "panel", "L3", "ood"),
    C(Spec(object="a turned threaded boss: a stepped round post with an external M16 thread on the upper section", shape="revolve",
           profile=[(0, 0), (16, 0), (16, 10), (8, 10), (8, 40), (0, 40)],
           features=[{"type": "thread", "diameter": 16, "pitch": 2.0, "kind": "external"}], tolerance=0.1), "composite", "L3", "ood"),
    C(Spec(object="a chamfered terminal block, top rim chamfered, with three M6 tapped holes in a row", shape="box",
           envelope={"length": 90, "width": 40, "height": 20},
           features=[{"type": "chamfer", "distance": 3, "edges": "top"},
                     {"type": "thread", "diameter": 6, "pitch": 1.0, "kind": "internal", "at": [-25, 0]},
                     {"type": "thread", "diameter": 6, "pitch": 1.0, "kind": "internal", "at": [0, 0]},
                     {"type": "thread", "diameter": 6, "pitch": 1.0, "kind": "internal", "at": [25, 0]}], tolerance=0.1), "composite", "L3", "ood"),
    C(Spec(object="a tapered round-to-square duct with a mounting flange of four bolt holes at the square end", shape="loft",
           envelope={"length": 70, "width": 50, "height": 50, "diameter_top": 30}, tolerance=0.1), "loft", "L3", "ood"),
]

SETS = {"in": EVAL_IN, "ood": EVAL_OOD, "all": EVAL_IN + EVAL_OOD}


def preflight(cases: List[Case]) -> None:
    """Verifier-first guard — every case must build+verify under the deterministic builder, so a
    model failure is genuinely the model's (not a verifier gap on the new vocabulary)."""
    bad = []
    for c in cases:
        try:
            rep = verify(build(c.spec), c.spec)
            if not rep.passed:
                bad.append((c.spec.object, [r["name"] if isinstance(r, dict) else r.name for r in rep.rows if not (r["within_tol"] if isinstance(r, dict) else r.within_tol)]))
        except Exception as e:  # noqa: BLE001
            bad.append((c.spec.object, [f"EXC {type(e).__name__}: {e}"]))
    if bad:
        print("PRE-FLIGHT FAILED — the verifier can't cleanly check these (fix before judging the model):")
        for obj, rows in bad:
            print(f"  ✗ {obj}: {rows}")
        raise SystemExit(1)
    print(f"pre-flight ok: all {len(cases)} cases build + verify to spec\n")


def _rate(passed, total):
    return f"{passed}/{total} ({(100 * passed / total) if total else 0:.0f}%)"


def evaluate(cases: List[Case], max_attempts: int = 3, gen=None) -> dict:
    gen = gen if gen is not None else VLLMGenerator()
    rows = []
    feat_pass, feat_seen = Counter(), Counter()
    cat_profile = Counter()
    for i, c in enumerate(cases, 1):
        out = run(c.spec, gen, max_attempts=max_attempts)
        rep = out.get("best_report") or out.get("report")
        ever_valid = any(h["status"] == "ok" for h in out["history"])
        flag = "PASS" if out["passed"] else ("valid-but-wrong" if ever_valid else "never-valid")
        print(f"  [{i}/{len(cases)}] {c.cap:<11} {c.level} {c.dist:<3} → {flag}", flush=True)
        if rep:
            for r in rep["rows"]:
                feat_seen[r["name"]] += 1
                if r["within_tol"]:
                    feat_pass[r["name"]] += 1
                else:
                    cat_profile[r["category"]] += 1
        rows.append({"object": c.spec.object, "cap": c.cap, "level": c.level, "dist": c.dist,
                     "passed": out["passed"], "ever_valid": ever_valid,
                     "fails": [r["name"] for r in (rep["rows"] if rep else []) if not r["within_tol"]],
                     "trace": [f"{h['attempt']}:{h['status']}/{h['category']}" for h in out["history"]]})

    def strat(key):
        groups = {}
        for r in rows:
            g = groups.setdefault(r[key], {"pass": 0, "valid": 0, "n": 0})
            g["n"] += 1; g["pass"] += r["passed"]; g["valid"] += r["ever_valid"]
        return {k: {"pass_rate": _rate(v["pass"], v["n"]), "valid_rate": _rate(v["valid"], v["n"])}
                for k, v in sorted(groups.items())}

    n = len(cases)
    return {
        "n": n, "max_attempts": max_attempts,
        "pass_rate": _rate(sum(r["passed"] for r in rows), n),
        "ever_valid_rate": _rate(sum(r["ever_valid"] for r in rows), n),
        "by_capability": strat("cap"), "by_level": strat("level"), "by_distribution": strat("dist"),
        "feature_pass_rate": {k: f"{feat_pass[k]}/{feat_seen[k]}" for k in sorted(feat_seen)},
        "failure_category_profile": dict(cat_profile),
        "rows": rows,
    }


def main() -> int:
    args = sys.argv[1:]
    set_name = next((a for a in args if a in SETS), "all")
    max_attempts = next((int(a) for a in args if a.isdigit()), 3)
    cases = SETS[set_name]
    print(f"Vocab eval set='{set_name}' — {len(cases)} cases, max_attempts={max_attempts}, model=qwen3.6-27b (live)\n")
    preflight(cases)
    s = evaluate(cases, max_attempts)

    print("=" * 70)
    for r in s["rows"]:
        flag = "PASS" if r["passed"] else ("valid-but-wrong" if r["ever_valid"] else "never-valid")
        print(f"■ [{r['cap']:<11} {r['level']} {r['dist']:<3}] {flag:<15} {r['object'][:60]}")
        if r["fails"]:
            print(f"     unresolved: {', '.join(r['fails'][:6])}")
    print("=" * 70)
    print(f"OVERALL pass {s['pass_rate']}   ever-valid {s['ever_valid_rate']}")
    print(f"BY CAPABILITY  {json.dumps(s['by_capability'])}")
    print(f"BY LEVEL       {json.dumps(s['by_level'])}")
    print(f"BY DIST        {json.dumps(s['by_distribution'])}")
    print(f"FAILURE PROFILE {s['failure_category_profile']}")
    print("\nJSON:\n" + json.dumps(s, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
