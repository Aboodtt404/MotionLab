"""Leg-3: LLM-synth brief diversity → REAL planner → verifier keep-loop → SFT pairs.

1. Brief taxonomy: one guided LLM call expands seed categories into diverse briefs (film props,
   mechanisms, furniture, robotics, gantries…), deduped, saved for reproducibility.
2. Each brief runs the REAL serving path (asm_loop.run_assembly, PLAN_MODEL adapter, 2 attempts).
   ONLY verifier-passing assemblies are kept — the model teaches itself from its own successes,
   the verifier decides what counts (CADEvolve pattern; keeps bank forever).
3. Kept assemblies → pairs in the exact leg-1 serving formats via build_asm_pairs helpers
   (gated caption ladder + brief + two-stage + outline).

PARALLEL: K worker processes each drive a full plan loop; the vLLM serve batches their calls
(aggregate throughput scales; per-plan latency stays ~constant). Wall-clock budget capped.

Out: /workspace/.hf_home/cad_corpus/leg3_briefs.json         (the taxonomy)
     /workspace/.hf_home/cad_corpus/leg3_keeps.jsonl         (verified assemblies, resume-safe)
     /workspace/.hf_home/cad_corpus/leg3_pairs.jsonl         (training pairs)
Run: cad_pipeline/.venv/bin/python -m training.build_leg3_synth [budget_minutes]
     (SWEEP_WORKERS=6, PLAN_MODEL honored by the planner itself)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://localhost:8002/v1"
BRIEFS_OUT = "/workspace/.hf_home/cad_corpus/leg3_briefs.json"
KEEPS_OUT = "/workspace/.hf_home/cad_corpus/leg3_keeps.jsonl"
PAIRS_OUT = "/workspace/.hf_home/cad_corpus/leg3_pairs.jsonl"

_SEEDS = [
    "workshop / lab equipment (vises, jigs, stands, holders)",
    "film-set sci-fi props with moving parts (hatches, turrets, antenna mounts)",
    "furniture (tables, benches, shelving, stools with variety)",
    "robotics fixtures (gimbals, pan-tilt heads, grippers, sensor masts)",
    "carts, trolleys, dollies and wheeled rigs",
    "doors, lids, hatches and hinged covers on frames",
    "gantries, cranes and pivoting booms",
    "brackets, mounts and clamps holding a second part",
]

_BRIEF_SCHEMA = {"type": "object", "properties": {"briefs": {
    "type": "array", "minItems": 10, "maxItems": 20,
    "items": {"type": "string", "maxLength": 220}}}, "required": ["briefs"]}


def make_briefs(per_seed: int = 14) -> list:
    if os.path.exists(BRIEFS_OUT):
        return json.load(open(BRIEFS_OUT))
    briefs: list = []
    for seed in _SEEDS:
        body = {"model": "qwen3.6-27b",
                "messages": [
                    {"role": "system", "content":
                     "Write generation briefs for a parametric CAD assembly engine (3-8 rigid parts, "
                     "mates, optional revolute joints). Mix TWO styles ~evenly: casual one-liners "
                     "('a rolling tool cart with a push handle') and metric-precise engineering asks "
                     "('300x200x12 mm base plate, two 40 mm pillars 180 mm apart, pivoting arm on a "
                     "revolute'). Every brief must be a BUILDABLE rigid assembly — no fabric, no "
                     "electronics-internals, no humans. Output JSON {\"briefs\": [...]}."},
                    {"role": "user", "content": f"{per_seed} varied briefs for: {seed}"},
                ],
                "temperature": 0.9, "max_tokens": 1600,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {"name": "b", "schema": _BRIEF_SCHEMA}}}
        req = urllib.request.Request(BASE_URL + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                got = json.loads(json.loads(r.read())["choices"][0]["message"]["content"])["briefs"]
            briefs += [b.strip() for b in got if len(b.strip()) > 12]
            print(f"taxonomy: +{len(got)}  ({seed.split('(')[0].strip()})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"taxonomy seed failed: {e}", flush=True)
    briefs = sorted(set(briefs))
    json.dump(briefs, open(BRIEFS_OUT, "w"), indent=1)
    return briefs


def _iso_worker(brief: str, q) -> None:
    """One brief through the REAL plan loop; queue a keep or a skip."""
    try:
        from cad_pipeline.asm_loop import VLLMAsmGenerator, run_assembly
        out = run_assembly(brief, VLLMAsmGenerator(), max_attempts=3)
        if not out.get("passed"):
            q.put({"brief": brief, "skip": f"not passed ({out.get('category')})"})
            return
        best = out["attempt_log"][-1]
        asm = best["assembly"]
        # HOLLOW-PASS gate: a 1-2 part plan for a 3-8 part brief passes the geometric verifier
        # trivially and would TEACH under-decomposition. Keep only real decompositions.
        if len(asm.get("components", [])) < 3 or len(asm.get("mates", [])) < 2:
            q.put({"brief": brief, "skip": f"hollow pass ({len(asm.get('components', []))} parts)"})
            return
        q.put({"brief": brief, "assembly": asm, "category": "leg3-synth"})
    except Exception as e:  # noqa: BLE001
        q.put({"brief": brief, "skip": f"{type(e).__name__}: {str(e)[:110]}"})


def main() -> int:
    import multiprocessing as mp
    import random
    import time

    budget_min = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    briefs = make_briefs()
    seen = set()
    try:
        seen = {json.loads(l)["brief"] for l in open(KEEPS_OUT)}
    except FileNotFoundError:
        pass
    todo = [b for b in briefs if b not in seen]
    random.Random(11).shuffle(todo)
    print(f"leg3: {len(todo)} briefs to try ({len(seen)} kept already), budget {budget_min:.0f} min", flush=True)

    K = max(1, int(os.environ.get("SWEEP_WORKERS", "6")))
    TIMEOUT = 15 * 60.0
    deadline = time.monotonic() + budget_min * 60
    pending = list(todo)
    active: list = []
    kept = tried = 0
    while (pending or active) and not (time.monotonic() > deadline and not active):
        while pending and len(active) < K and time.monotonic() < deadline:
            b = pending.pop(0)
            q = mp.Queue()
            proc = mp.Process(target=_iso_worker, args=(b, q), daemon=True)
            proc.start()
            active.append((proc, q, b, time.monotonic()))
        still: list = []
        for proc, q, b, t0 in active:
            if not proc.is_alive():
                tried += 1
                try:
                    r = q.get_nowait()
                except Exception:  # noqa: BLE001
                    r = {"brief": b, "skip": "worker died"}
                if "skip" in r:
                    print(f"MISS ({tried}) {b[:64]!r}: {r['skip'][:60]}", flush=True)
                else:
                    kept += 1
                    with open(KEEPS_OUT, "a") as f:
                        f.write(json.dumps(r) + "\n")
                    print(f"KEEP ({kept}) {b[:64]!r} — {len(r['assembly']['components'])} parts", flush=True)
                proc.join()
            elif time.monotonic() - t0 > TIMEOUT:
                proc.kill(); proc.join(); tried += 1
                print(f"MISS (timeout) {b[:60]!r}", flush=True)
            else:
                still.append((proc, q, b, t0))
        active = still
        time.sleep(0.3)

    # keeps → pairs in the leg-1 serving formats
    from training.build_asm_pairs import _outline_pair, _plan_pairs
    rng = random.Random(23)
    n = 0
    if not os.path.exists(KEEPS_OUT):
        print("\nleg3 done: zero keeps banked — nothing to pair", flush=True)
        return 0
    with open(PAIRS_OUT, "w") as f:
        for line in open(KEEPS_OUT):
            rec = json.loads(line)
            try:
                for p in _plan_pairs(rec, rng) + [_outline_pair(rec)]:
                    f.write(json.dumps(p) + "\n"); n += 1
            except Exception as e:  # noqa: BLE001
                print(f"pair DROP {rec['brief'][:50]!r}: {type(e).__name__}", flush=True)
    print(f"\nleg3 done: {kept} keeps this run / {tried} tried → {n} total pairs → {PAIRS_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
