"""Build DPO preference pairs — fable_run/out/03_training_recipe.md §4 (the cheap middle step:
"chosen = 3a code, rejected = 3b code for the SAME spec; preference = verifier pass > fail, no reward
model") + §7.3 ("perturb params outside valid ranges to manufacture LABELED failures — run verifiers
to label them"). CPU-only, deterministic, no LLM:

  1. sample a golden spec (templates.py) → build + verify → must PASS. chosen = emit_code(spec).
  2. perturb ONE param to inject a catalog mistake (mistakes.py) → build + verify against the ORIGINAL
     spec → must FAIL. rejected = emit_code(perturbed).
  3. prompt = a deterministic L2/L3 caption of the golden spec (captions.describe).
  4. keep the pair only if chosen passed AND rejected failed (a real, verifier-labeled contrast).

Output: JSONL {prompt, chosen, rejected, mistake, level, reject_categories} ready for TRL DPOTrainer.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
from typing import List, Optional, Tuple

from cad_pipeline import templates
from cad_pipeline.builder import build, emit_code
from cad_pipeline.captions import describe
from cad_pipeline.spec import Spec
from cad_pipeline.verifier import verify

# the template spec samplers (CPU, no LLM) — the golden-spec source
SAMPLERS = [templates.mounting_bracket, templates.motor_mount, templates.bolt_circle_flange,
            templates.turned_shaft_or_hub, templates.electronics_enclosure, templates.standoff_or_spacer,
            templates.threaded_boss_or_plate, templates.adapter_or_duct, templates.coolant_line]


# ── perturbations: spec → (perturbed spec, mistake_id). Each targets a catalog failure mode. ──
def _first_hole(feats):
    for i, f in enumerate(feats):
        if getattr(f, "type", None) in ("through_hole", "counterbore", "countersink"):
            return i
    return None


def p_unit(spec: Spec) -> Optional[Tuple[Spec, str]]:      # C7: unit mixup — a dimension ×10
    s = spec.model_copy(deep=True)
    if not s.envelope:
        return None
    k = next(iter(s.envelope))
    s.envelope[k] = s.envelope[k] * 10.0
    return s, "C7"


def p_dia(spec: Spec) -> Optional[Tuple[Spec, str]]:       # C8: radius/diameter confusion — hole ⌀×2
    s = spec.model_copy(deep=True)
    i = _first_hole(s.features)
    if i is None:
        return None
    s.features[i].diameter = s.features[i].diameter * 2.0
    return s, "C8"


def p_datum(spec: Spec) -> Optional[Tuple[Spec, str]]:     # C6: hole measured from the wrong datum
    s = spec.model_copy(deep=True)
    i = _first_hole(s.features)
    if i is None or s.shape != "box":
        return None
    off = s.envelope.get("length", 40) / 2.0
    at = getattr(s.features[i], "at", None) or [0.0, 0.0]
    s.features[i].at = [at[0] + off, at[1]]
    return s, "C6"


def p_drop(spec: Spec) -> Optional[Tuple[Spec, str]]:      # missing_feature: drop a declared feature
    if not spec.features:
        return None
    s = spec.model_copy(deep=True)
    s.features = s.features[1:]
    return s, "C4"


def p_envelope(spec: Spec) -> Optional[Tuple[Spec, str]]:  # C14/dimensional: wrong overall size (×1.4)
    s = spec.model_copy(deep=True)
    if not s.envelope:
        return None
    k = next(iter(s.envelope))
    s.envelope[k] = round(s.envelope[k] * 1.4, 2)
    return s, "C14"


PERTURBATIONS = [p_dia, p_datum, p_drop, p_unit, p_envelope]


def _passes(spec: Spec) -> bool:
    try:
        return verify(build(spec), spec).passed
    except Exception:  # noqa: BLE001
        return False


def _fails_against(pert: Spec, target: Spec) -> Tuple[bool, List[str]]:
    """Build the perturbed spec and verify it against the ORIGINAL target — a real reject fails."""
    try:
        rep = verify(build(pert), target)
        return (not rep.passed), rep.failure_categories()
    except Exception:  # noqa: BLE001 — a perturbation that won't even build is also a valid negative
        return True, ["validity"]


def make_pair(spec: Spec, rng: random.Random) -> Optional[dict]:
    if not _passes(spec):
        return None
    caps = describe(spec, rng)
    prompt = rng.choice([caps["l2"], caps["l3"]])
    for pert in rng.sample(PERTURBATIONS, len(PERTURBATIONS)):
        res = pert(spec)
        if res is None:
            continue
        pert_spec, mid = res
        bad, cats = _fails_against(pert_spec, spec)
        if bad:
            return {"prompt": prompt, "chosen": emit_code(spec), "rejected": emit_code(pert_spec),
                    "mistake": mid, "level": _level(spec), "reject_categories": cats}
    return None


def _level(spec: Spec) -> str:
    nf = len(spec.features)
    return "L1" if nf <= 1 else ("L2" if nf <= 2 else "L3")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400, help="target pairs")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="/workspace/.hf_home/cad_corpus/dpo_pairs.jsonl")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    pairs: List[dict] = []
    tries = 0
    while len(pairs) < a.n and tries < a.n * 6:
        tries += 1
        spec = SAMPLERS[tries % len(SAMPLERS)](rng)
        pr = make_pair(spec, rng)
        if pr:
            pairs.append(pr)
    with open(a.out, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    from collections import Counter
    print(f"DPO pairs written: {len(pairs)}/{a.n} (tries {tries}) → {a.out}")
    print("by mistake:", dict(Counter(p["mistake"] for p in pairs)))
    print("by level:  ", dict(Counter(p["level"] for p in pairs)))
    return 0 if pairs else 1


if __name__ == "__main__":
    raise SystemExit(main())
