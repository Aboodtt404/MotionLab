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
import multiprocessing as mp
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")

from cad_pipeline.assembly import (Assembly, AsmPatch, apply_patch, repair_connectivity,  # noqa: E402
                                   solve_layout, verify_assembly)
from cad_pipeline.asm_loop import _REPAIR_SYSTEM, _asm_feedback, _route_for  # noqa: E402
from cad_pipeline.planner import (_OUTLINE_SCHEMA, _OUTLINE_SYSTEM, _SYSTEM,  # noqa: E402
                                  _asm_schema, _patch_schema, _patch_schema_scoped,
                                  dump_for_grammar)


def _plan_pairs(rec: dict, rng) -> list:
    """One golden → plan pairs across the CAPTION LADDER (l1 simple / l2 rough / l3 metric — the
    both-audiences requirement) + the template brief + the two-stage listing form. Ladder captions
    are generated from verified structure and per-level gated (l1 digit-free; l2/l3 numbers must
    map to structural quantities)."""
    from cad_pipeline.asm_captions import asm_describe, gate_caption
    brief, asm = rec["brief"], rec["assembly"]
    # decoder-producible target (pydantic defaults / key order / -0.0 all break xgrammar)
    target = dump_for_grammar(asm, _asm_schema())
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
            "code": dump_for_grammar({"parts": parts}, _OUTLINE_SCHEMA),
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
    if any(m.kind == "stack" and m.fraction is not None for m in asm.mates):
        moves.append("drop_fraction")          # rung-2 dialect lesson: mid shelf loses its height
    if any(m.kind == "corners" and m.dx for m in asm.mates):
        moves.append("corner_spread")          # the old table poison as a lesson: full-span dx/dy
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
    if move == "drop_fraction":
        # the mid-height shelf loses its fraction → solver stacks it ON TOP, colliding with the
        # real top shelf (unsanctioned interference / coincident duplicates). The minimal fix the
        # patch demonstrates = put the fraction back — the rung-2 dialect, in repair form.
        for m in asm.mates:
            if m.kind == "stack" and m.fraction is not None:
                m.fraction = None
                break
        return asm, AsmPatch(mates=original_mates)
    if move == "corner_spread":
        # corners dx/dy doubled to FULL spans (the exact poison the table family used to carry):
        # posts/legs/wheels land outside their reference → disconnected islands.
        for m in asm.mates:
            if m.kind == "corners" and m.dx:
                m.dx = round(m.dx * 2, 1)
                if m.dy:
                    m.dy = round(m.dy * 2, 1)
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
        # ROUTED format (FIX 4, 2026-07-25): the SERVED repair scopes both the system prompt and
        # the patch grammar to the worst failure class. Training the old flat format against a
        # routed server is a train/serve mismatch — so mirror asm_loop.VLLMAsmGenerator.repair
        # exactly, and SCOPE THE TARGET PATCH to the fields that route actually allows.
        route = _route_for(rep)
        feedback = _asm_feedback(rep, route["category"] if route else None)
        if not feedback.strip():
            return None
        system = _REPAIR_SYSTEM
        tgt = patch
        if route:
            system = (_REPAIR_SYSTEM + "\n\nTHIS PATCH IS ROUTED — one failure class only. "
                      + route["note"])
            keep = route["fields"]
            tgt = AsmPatch(upsert=patch.upsert if "upsert" in keep else [],
                           remove=patch.remove if "remove" in keep else [],
                           mates=patch.mates if "mates" in keep else None,
                           joints=patch.joints if "joints" in keep else None,
                           fillet_joints=patch.fillet_joints if "fillet_joints" in keep else None)
        # gate: the SCOPED patch — the only thing the routed grammar could emit — must itself fix it
        fixed = apply_patch(solved, tgt)
        fixed = repair_connectivity(solve_layout(fixed))
        if not verify_assembly(fixed)["passed"]:
            return None
    except Exception:  # noqa: BLE001
        return None
    user = (f"current assembly:\n{solved.model_dump_json()}\n\n"
            f"VERIFIER FAILURES (fix exactly these, minimally):\n{feedback}")
    # The served repair constrains generation with _patch_schema_scoped(route) — which REQUIRES
    # every in-route field present (null where inapplicable). exclude_none stripped exactly those,
    # so the old targets were unproducible. Conform to the same scoped schema the server compiles.
    pschema = (_patch_schema_scoped(route["fields"], route["must"], route.get("parts"))
               if route else _patch_schema())
    return {"system": system, "prompt": user,
            "code": dump_for_grammar(tgt, pschema),
            "source": "asm-repair", "category": rec["category"], "prompt_level": "repair",
            "route": route["category"] if route else "flat"}


def _repair_worker(rec_json: str, seed: int, q) -> None:
    """Subprocess: one perturb→double-gate attempt (OCCT can hang — killable, the fusion-sweep
    lesson: SIGALRM can't interrupt a C++ boolean)."""
    try:
        q.put(_repair_pair(json.loads(rec_json), random.Random(seed)))
    except Exception:  # noqa: BLE001
        q.put(None)


def _repair_pair_safe(rec: dict, seed: int, timeout: int = 240):
    q = mp.Queue()
    p = mp.Process(target=_repair_worker, args=(json.dumps(rec), seed, q))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.kill(); p.join()
        return None
    return q.get() if not q.empty() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="corpus_out/batch7_assemblies.jsonl")
    ap.add_argument("--fusion", default="/workspace/.hf_home/cad_corpus/fusion_joint_assemblies.jsonl",
                    help="fusion keeps (optional plan pairs; no briefs → skipped for SFT v1)")
    ap.add_argument("--repair-frac", type=float, default=0.15)
    ap.add_argument("--repair-count", type=int, default=0,
                    help="ABSOLUTE repair-pair target (overrides --repair-frac). The recipe's ~15%% "
                         "applies to the FINAL mixture — the old per-leg frac diluted to 3%% after "
                         "the fusion/leg3 merge. Size this against the planned mix.")
    ap.add_argument("--repair-rounds", type=int, default=6,
                    help="max perturb passes over the batch (different rng draws → different moves)")
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel repair-pair workers (each attempt is a killable subprocess)")
    ap.add_argument("--out", default="corpus_out/asm_pairs.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    recs = [json.loads(line) for line in open(a.batch)]
    pairs = []
    for r in recs:
        pairs.extend(_plan_pairs(r, rng))
        pairs.append(_outline_pair(r))

    # repair pairs: absolute target if given, else capped share of THIS file
    cap = a.repair_count or int(len(pairs) * a.repair_frac / (1 - a.repair_frac))
    repair, tried = [], 0
    seen: set = set()
    for rnd in range(a.repair_rounds):
        if len(repair) >= cap:
            break
        order = list(enumerate(recs))
        rng.shuffle(order)
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = [ex.submit(_repair_pair_safe, r, a.seed + 100_000 * rnd + i)
                    for i, r in order]
            for f in futs:
                tried += 1
                p = f.result()
                if not p or len(repair) >= cap:
                    continue
                key = hash((p["prompt"], p["code"]))
                if key in seen:
                    continue                    # same golden + same move can recur across rounds
                seen.add(key)
                repair.append(p)
        print(f"  repair round {rnd + 1}: {len(repair)}/{cap} kept ({tried} tried)", flush=True)
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
