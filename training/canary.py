"""Contamination canary — fable_run/out/03_training_recipe.md §5: "5 benchmark-lookalike tasks with
deliberately unusual dimensions kept secret from the team that builds the corpus; a sudden jump on
canaries without a matching jump on fresh tasks ⇒ leakage."

These specs mimic the benchmark's C/A categories but use DELIBERATELY non-round, off-catalog
dimensions that would never occur in the synthetic corpus (whose dims come from templates._r on
0.5-mm steps over realistic ranges) — so a trained model that scores high here has SEEN them
(leakage), because it cannot have learned these exact numbers by generalisation. Held out of ALL
training (their signatures are added to the holdout set); scored separately at every eval.
"""
from __future__ import annotations

from cad_pipeline.spec import Spec

# 5 benchmark-lookalikes, dims chosen to be un-guessable (prime-ish, sub-mm, never round)
CANARY = [
    # flange-like (cf. C05) — ⌀87.3×11.7, bore ⌀19.1, 7 holes on PCD 63.9
    Spec(object="canary flange", shape="cylinder", envelope={"diameter": 87.3, "height": 11.7},
         features=[{"type": "through_hole", "diameter": 19.1},
                   {"type": "hole_pattern", "pattern": "bolt_circle", "count": 7,
                    "pitch_diameter": 63.9, "diameter": 5.3}], tolerance=0.1),
    # filleted bracket (cf. C01) — 73.4×47.1×18.6, fillet r=3.7
    Spec(object="canary bracket", shape="box", envelope={"length": 73.4, "width": 47.1, "height": 18.6},
         features=[{"type": "fillet", "radius": 3.7, "edges": "all_vertical"}], tolerance=0.1),
    # counterbored plate (cf. C06) — 66.2×39.8×9.3, two ⌀4.7 / cbore ⌀8.9×4.1 at (±17.3, 0)
    Spec(object="canary counterbore plate", shape="box",
         envelope={"length": 66.2, "width": 39.8, "height": 9.3},
         features=[{"type": "counterbore", "diameter": 4.7, "cbore_diameter": 8.9, "cbore_depth": 4.1, "at": [-17.3, 0]},
                   {"type": "counterbore", "diameter": 4.7, "cbore_diameter": 8.9, "cbore_depth": 4.1, "at": [17.3, 0]}],
         tolerance=0.1),
    # stepped shaft (cf. C11) — ⌀21.3 / ⌀33.7 / ⌀21.3, unusual step heights
    Spec(object="canary stepped shaft", shape="revolve",
         profile=[(0, 0), (10.65, 0), (10.65, 13.4), (16.85, 13.4), (16.85, 31.9),
                  (10.65, 31.9), (10.65, 47.2), (0, 47.2)], tolerance=0.1),
    # offset-pocket plate (cf. C10) — pocket 37.3×22.9 depth 5.7 at (8.4, 3.6) in 93.1×57.6×11.4
    Spec(object="canary offset-pocket plate", shape="box",
         envelope={"length": 93.1, "width": 57.6, "height": 11.4},
         features=[{"type": "pocket", "length": 37.3, "width": 22.9, "depth": 5.7, "at": [8.4, 3.6]}], tolerance=0.1),
]


def canary_signatures() -> set:
    """Signatures to add to the training holdout so the canaries are never trained on."""
    import json
    from training.build_curriculum import _sig
    return {_sig(json.loads(s.model_dump_json())) for s in CANARY}


def selftest() -> int:
    """Every canary must build + verify (a valid held-out probe) — golden by construction."""
    from cad_pipeline.builder import build
    from cad_pipeline.verifier import verify
    bad = []
    for s in CANARY:
        rep = verify(build(s), s)
        print(f"  [{'ok ' if rep.passed else 'FAIL'}] {s.object}")
        if not rep.passed:
            bad.append(s.object)
    print(f"CANARY {len(CANARY) - len(bad)}/{len(CANARY)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
