"""batch7 golden assemblies → assembly-SFT pairs in the EXACT production formats (the DPO format
lesson: training must match the serving path byte-for-byte).

Three pair kinds (fable 03_training_recipe §3 + our failure data):
  • outline — Stage 1: _OUTLINE_SYSTEM + "object: <brief>" → {"parts":[{name,role,shape[,greeble]}]}
  • plan    — Stage 2: _SYSTEM + ("input: <brief>" one-shot AND the two-stage listing form)
              → the PRE-solve golden Assembly JSON (the solver owns placement).
  • repair  — §3c, the highest-value data (capped ~15%): PERTURB a golden with a mistakes-catalog
              failure (drop-mate → disconnected; weld-a-joint-pair → over-constrained; oversize a
              part → interference/attachment; shrink radial → clump), SOLVE it, run the REAL
              verifier, build the REAL _asm_feedback text, prompt = _REPAIR_SYSTEM's exact user
              format → target = the minimal AsmPatch that undoes the perturbation.
              Double gate: perturbed must FAIL verify; patch applied + re-solved must PASS.

Output records carry {"system", "prompt", "code"} — train_sft --mode instruct includes the system
message when present.

Run:  cad_pipeline/.venv/bin/python training/build_asm_pairs.py \
          --batch corpus_out/batch7_assemblies.jsonl --out corpus_out/asm_pairs.jsonl
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections import Counter

sys.path.insert(0, ".")

from cad_pipeline.assembly import (Assembly, AsmPatch, apply_patch, repair_connectivity,  # noqa: E402
                                   solve_layout, verify_assembly)
from cad_pipeline.asm_loop import _asm_feedback  # noqa: E402
from cad_pipeline.planner import _OUTLINE_SYSTEM, _SYSTEM  # noqa: E402
from cad_pipeline.asm_loop import _REPAIR_SYSTEM  # noqa: E402


def _plan_pairs(rec: dict, rng) -> list:
    """One golden → plan pairs across the CAPTION LADDER (l1 simple / l2 rough / l3 metric — the
    both-audiences requirement) + the template brief + the two-stage listing form. Ladder captions
    are generated from verified structure and per-level gated (l1 digit-free; l2/l3 numbers must
    map to structural quantities)."""
    from cad_pipeline.asm_captions import asm_describe, gate_caption
    brief, asm = rec["brief"], rec["assembly"]
    target = json.dumps(asm, separators=(",", ":"))
    asm_obj = Assembly(**asm)
    ladder = asm_describe(asm_obj, rng)
    out = []
    for lv, cap in [*ladder.items(), ("brief", brief)]:
        if lv != "brief" and not gate_caption(lv, cap, asm_obj):
            continue                                        # honesty gate — reject, never repair
        out.append({"system": _SYSTEM, "prompt": "input: " + cap, "code": target,
                    "source": "asm-plan", "category": rec["category"], "prompt_level": lv})
    listing = "; ".join(
        f"{c['name']} (role {c.get('role', 'other')}, {c['part'].get('shape', 'box')}"
        f"{', GREEBLED' if any(f.get('type') == 'greeble' for f in c['part'].get('features', [])) else ''})"
        for c in asm["components"])
    two_stage_user = (f"input: {brief}\nRealize THIS parts list as the assembly — one component per part with its "
                      f"role, dimensions, and the functional features it needs (GREEBLE the parts marked GREEBLED); "
                      f"connect every part with `mates` (radial/stack/ground/coaxial/flush/mirror), NOT coordinates:\n{listing}")
    out.append({"system": _SYSTEM, "prompt": two_stage_user, "code": target,
                "source": "asm-plan", "category": rec["category"], "prompt_level": "two_stage"})
    return out


def _outline_pair(rec: dict) -> dict:
    parts = []
    for c in rec["assembly"]["components"]:
        p = {"name": c["name"], "role": c.get("role", "other"), "shape": c["part"].get("shape", "box")}
        if any(f.get("type") == "greeble" for f in c["part"].get("features", [])):
            p["greeble"] = True
        parts.append(p)
    return {"system": _OUTLINE_SYSTEM, "prompt": "object: " + rec["brief"],
            "code": json.dumps({"parts": parts}, separators=(",", ":")),
            "source": "asm-outline", "category": rec["category"], "prompt_level": "outline"}


# ------------------------------------------------------------------ perturbations (catalog-driven)
def _perturb(asm_dict: dict, rng) -> tuple:
    """(perturbed Assembly, fixing AsmPatch) or (None, None) if this golden has no applicable move."""
    asm = Assembly(**copy.deepcopy(asm_dict))
    moves = []
    severable = [i for i, m in enumerate(asm.mates) if m.kind != "cutout"]
    if len(severable) >= 1 and len(asm.mates) >= 2:
        moves.append("drop_mate")
    if asm.joints:
        moves.append("weld_joint")
    non_base = [i for i, c in enumerate(asm.components)
                if c.role not in ("base",) and not c.parent]
    if non_base:
        moves.append("oversize")
    if any(m.kind == "radial" for m in asm.mates):
        moves.append("shrink_radial")
    if not moves:
        return None, None
    move = rng.choice(moves)
    original_mates = [m.model_copy(deep=True) for m in asm.mates]

    if move == "drop_mate":
        asm.mates.pop(rng.choice(severable))
        return asm, AsmPatch(mates=original_mates)
    if move == "weld_joint":
        j = rng.choice(asm.joints)
        from cad_pipeline.assembly import Mate
        asm.mates.append(Mate(kind="attach", a=j.a, b=j.b))
        return asm, AsmPatch(mates=original_mates)
    if move == "oversize":
        i = rng.choice(non_base)
        c = asm.components[i]
        original = Assembly(**copy.deepcopy(asm_dict)).components[i]
        for k in list(c.part.envelope.keys()):
            if k in ("diameter", "length", "width", "height"):
                c.part.envelope[k] = round(c.part.envelope[k] * 1.7, 1)
        return asm, AsmPatch(upsert=[original])
    if move == "shrink_radial":
        for m in asm.mates:
            if m.kind == "radial" and m.radius:
                m.radius = round(m.radius * 0.35, 1)
                break
        return asm, AsmPatch(mates=original_mates)
    return None, None


def _repair_pair(rec: dict, rng) -> dict | None:
    perturbed, patch = _perturb(rec["assembly"], rng)
    if perturbed is None:
        return None
    try:
        solved = repair_connectivity(solve_layout(perturbed.model_copy(deep=True)))
        rep = verify_assembly(solved)
        if rep["passed"]:
            return None                                     # perturbation didn't break it — not a lesson
        feedback = _asm_feedback(rep)
        if not feedback.strip():
            return None
        # gate: the fixing patch, applied + re-solved, must PASS
        fixed = apply_patch(solved, patch)
        fixed = repair_connectivity(solve_layout(fixed))
        if not verify_assembly(fixed)["passed"]:
            return None
    except Exception:  # noqa: BLE001
        return None
    user = (f"current assembly:\n{solved.model_dump_json()}\n\n"
            f"VERIFIER FAILURES (fix exactly these, minimally):\n{feedback}")
    return {"system": _REPAIR_SYSTEM, "prompt": user,
            "code": patch.model_dump_json(exclude_none=True),
            "source": "asm-repair", "category": rec["category"], "prompt_level": "repair"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="corpus_out/batch7_assemblies.jsonl")
    ap.add_argument("--fusion", default="/workspace/.hf_home/cad_corpus/fusion_joint_assemblies.jsonl",
                    help="fusion keeps (optional plan pairs; no briefs → skipped for SFT v1)")
    ap.add_argument("--repair-frac", type=float, default=0.15)
    ap.add_argument("--out", default="corpus_out/asm_pairs.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    recs = [json.loads(line) for line in open(a.batch)]
    pairs = []
    for r in recs:
        pairs.extend(_plan_pairs(r, rng))
        pairs.append(_outline_pair(r))

    # repair pairs: capped share of the final mixture
    cap = int(len(pairs) * a.repair_frac / (1 - a.repair_frac))
    repair, tried = [], 0
    order = recs[:]
    rng.shuffle(order)
    for r in order:
        if len(repair) >= cap:
            break
        tried += 1
        p = _repair_pair(r, rng)
        if p:
            repair.append(p)
    pairs.extend(repair)
    rng.shuffle(pairs)

    with open(a.out, "w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    print(json.dumps({"out": a.out, "total": len(pairs),
                      "by_kind": dict(Counter(p["prompt_level"] for p in pairs)),
                      "repair_kept": len(repair), "repair_tried": tried}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
