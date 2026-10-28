"""Geometric reward for RL (GRPO) on the feature-program task — the high-leverage lever
(docs/research/track-a-feature-program-representation.md §8b: RL-with-a-geometric-reward >> SFT
corpus). Execution-gated, like CAD-Coder's CD reward, but IoU-based and validity-aware.

The model emits a CadQuery code STRING (assigning `result`). We execute it, take the solid, and
score it against a ground-truth solid: exec-fail / empty / non-solid → 0; otherwise IoU vs target,
penalized if the topology is invalid or multi-body. This is also the offline EVAL harness (feed
known-good vs wrong code) and the reconstruction-environment reward (target = the dataset's STEP).

SECURITY: `exec` of model output is unsafe in the open; acceptable for controlled in-house RL over
our own model (standard in the CAD-RL literature). Sandbox before any untrusted use.

Run (self-test):  cad_pipeline/.venv/bin/python -m training.reward
"""
from __future__ import annotations

import sys

import cadquery as cq

from cad_pipeline.verifier import _iou, measure


def score_solid(solid: cq.Shape, target: cq.Shape) -> dict:
    """Score a built solid against a target: IoU (geometric fidelity) gated by validity. A valid
    single watertight solid gets full IoU credit; an invalid/multi-body result is halved (it may
    render/measure but isn't a clean part). reward ∈ [0, 1]."""
    m = measure(solid)
    valid_single = m.valid and m.solids == 1 and m.volume > 0
    iou = _iou(solid, target)
    reward = iou if valid_single else 0.5 * iou
    return {"reward": round(reward, 4), "iou": round(iou, 4),
            "valid": m.valid, "solids": m.solids, "volume": round(m.volume, 2)}


def _extract_solid(result) -> cq.Shape | None:
    """Pull a solid out of whatever the code assigned to `result` (Workplane | Shape | Compound)."""
    if result is None:
        return None
    s = result.val() if isinstance(result, cq.Workplane) else result
    try:
        return s if s.Solids() else None
    except Exception:  # noqa: BLE001
        return None


def reward(code: str, target: cq.Shape) -> dict:
    """Execute a model-emitted CadQuery `code` string (must assign `result`) and score vs `target`.
    Any exec failure / missing / empty `result` → reward 0.0 (execution-gated)."""
    ns: dict = {"cq": cq, "__name__": "__reward_sandbox__"}
    try:
        exec(code, ns)  # noqa: S102 — controlled in-house RL; sandbox before untrusted use
    except Exception as e:  # noqa: BLE001
        return {"reward": 0.0, "iou": 0.0, "error": f"exec: {type(e).__name__}: {e}"[:100]}
    solid = _extract_solid(ns.get("result"))
    if solid is None:
        return {"reward": 0.0, "iou": 0.0, "error": "no valid `result` solid"}
    try:
        return score_solid(solid, target)
    except Exception as e:  # noqa: BLE001
        return {"reward": 0.0, "iou": 0.0, "error": f"score: {type(e).__name__}: {e}"[:100]}


def reward_for_step(code: str, step_path: str) -> dict:
    """Reward against a ground-truth STEP file (the reconstruction RL environment)."""
    return reward(code, cq.importers.importStep(step_path).val())


# --------------------------------------------------------------------------------- self-test
def _selftest() -> int:
    target = cq.Workplane("XY").box(40, 30, 20).val()
    passed = failed = 0

    def check(label, ok, detail=""):
        nonlocal passed, failed
        passed, failed = passed + ok, failed + (not ok)
        print(f"  [{'ok ' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")

    exact = reward('import cadquery as cq\nresult = cq.Workplane("XY").box(40, 30, 20)', target)
    check("exact match → reward≈1", exact["reward"] >= 0.99, str(exact))

    wrong = reward('import cadquery as cq\nresult = cq.Workplane("XY").box(40, 30, 12)', target)
    check("wrong size → reward well below 1", wrong["reward"] < 0.8, str(wrong))

    shifted = reward('import cadquery as cq\nresult = cq.Workplane("XY").box(40, 30, 20).translate((10,0,0))', target)
    check("shifted → reward < 1 (position matters)", shifted["reward"] < 0.95, str(shifted))

    broken = reward('import cadquery as cq\nresult = cq.Workplane("XY").box(oops)', target)
    check("broken code → reward 0 (exec-gated)", broken["reward"] == 0.0, str(broken))

    noresult = reward('import cadquery as cq\nx = cq.Workplane("XY").box(1,1,1)', target)
    check("no `result` → reward 0", noresult["reward"] == 0.0, str(noresult))

    multi = reward('import cadquery as cq\nresult = cq.Workplane("XY").pushPoints([(-30,0),(30,0)]).box(10,10,10)', target)
    check("multi-body invalid → penalized (reward < iou-if-valid)", multi["reward"] <= 0.5, str(multi))

    print(f"\nREWARD SELF-TEST {passed}/{passed + failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_selftest())
