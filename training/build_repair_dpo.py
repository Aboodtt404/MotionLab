"""Repair-DPO pairs, verifier-labeled (ladder rung 1 — the repair loop rescued ONE brief ever).

For each failure state (a golden family instance perturbed by the mistake catalog, verified to
FAIL), sample K repair patches from the DEPLOYED adapter at temperature through the serving
grammar, then apply+solve+verify each sample. Preference pairs fall out of the verifier:
  chosen   = a sampled patch that flips the state to PASS (plus the known minimal-undo patch),
  rejected = a sampled patch that leaves it failing.
On-policy rejections (the model's OWN failure modes) + verified chosens — no teacher, no human.

Out: /workspace/.hf_home/cad_corpus/repair_dpo.jsonl   {system, prompt, chosen, rejected, meta}
Run: cad_pipeline/.venv/bin/python -m training.build_repair_dpo [n_states] [K]
Resume-safe: states are seeded by index; done indices tracked in a sidecar.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cad_pipeline.assembly import AsmPatch, apply_patch, repair_connectivity, solve_layout, verify_assembly  # noqa: E402
from cad_pipeline.asm_loop import _REPAIR_SYSTEM, _asm_feedback  # noqa: E402
from cad_pipeline.planner import _patch_schema  # noqa: E402
from training.build_asm_corpus import FAMILIES  # noqa: E402
from training.build_asm_pairs import _perturb  # noqa: E402

OUT = os.environ.get("DPO_OUT", "/workspace/.hf_home/cad_corpus/repair_dpo.jsonl")
SIDE = OUT + ".done.txt"
BASE = "http://localhost:8002/v1"
MODEL = os.environ.get("DPO_SAMPLER", "asm2")


def make_state(idx: int):
    """Deterministic failure state #idx: (user_prompt, solved_fail_state, undo_patch, category)."""
    rng = random.Random(20260715 + idx)
    fam = FAMILIES[idx % len(FAMILIES)]
    cat, _brief, asm = fam(rng)
    perturbed, undo = _perturb(json.loads(asm.model_dump_json()), rng)
    if perturbed is None:
        return None
    solved = repair_connectivity(solve_layout(perturbed.model_copy(deep=True)))
    rep = verify_assembly(solved)
    if rep["passed"]:
        return None
    feedback = _asm_feedback(rep)
    if not feedback.strip():
        return None
    fixed = repair_connectivity(solve_layout(apply_patch(solved, undo)))
    if not verify_assembly(fixed)["passed"]:
        return None                                   # undo must be a certified chosen
    user = (f"current assembly:\n{solved.model_dump_json()}\n\n"
            f"VERIFIER FAILURES (fix exactly these, minimally):\n{feedback}")
    return user, solved, undo, cat


def sample_patches(user: str, k: int) -> list[str]:
    body = json.dumps({
        "model": MODEL, "n": k, "temperature": 0.8, "top_p": 0.95, "max_tokens": 1400,
        "messages": [{"role": "system", "content": _REPAIR_SYSTEM}, {"role": "user", "content": user}],
        "chat_template_kwargs": {"enable_thinking": False},
        "extra_body": {"guided_json": _patch_schema()},
        "guided_json": _patch_schema(),
    }).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.load(r)
    return [c["message"]["content"] for c in out["choices"]]


def _verify_worker(state_json: str, patch_json: str, q):
    """Subprocess: apply+solve+verify one sampled patch (OCCT can hang — killable)."""
    try:
        from cad_pipeline.assembly import Assembly as A, AsmPatch as P, apply_patch as ap2, \
            repair_connectivity as rc, solve_layout as sl, verify_assembly as va
        st = A.model_validate_json(state_json)
        patch = P.model_validate_json(patch_json)
        fixed = rc(sl(ap2(st, patch)))
        q.put(bool(va(fixed)["passed"]))
    except Exception:  # noqa: BLE001
        q.put(False)


def verify_patch(state_json: str, patch_json: str, timeout=120) -> bool:
    q = mp.Queue()
    p = mp.Process(target=_verify_worker, args=(state_json, patch_json, q))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.kill(); p.join()
        return False
    return q.get() if not q.empty() else False


def main() -> int:
    n_states = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    done = set()
    if os.path.exists(SIDE):
        done = {int(x) for x in open(SIDE).read().split()}
    pairs_written = 0
    for idx in range(n_states):
        if idx in done:
            continue
        try:
            st = make_state(idx)
        except Exception:  # noqa: BLE001
            st = None
        if st is None:
            open(SIDE, "a").write(f"{idx}\n")
            continue
        user, solved, undo, cat = st
        state_json = solved.model_dump_json()
        try:
            raw = sample_patches(user, k)
        except Exception as e:  # noqa: BLE001
            print(f"[{idx}] sample error: {e}", flush=True)
            time.sleep(5)
            continue
        # verify the K samples in parallel subprocesses
        results: list[tuple[str, bool]] = []
        with ThreadPoolExecutor(max_workers=min(6, k)) as ex:
            futs = {ex.submit(verify_patch, state_json, r): r for r in raw}
            for f in futs:
                results.append((futs[f], f.result()))
        passing = [r for r, ok in results if ok]
        failing = [r for r, ok in results if not ok]
        undo_json = undo.model_dump_json(exclude_none=True)
        chosens = ([undo_json] + passing)[:2]                 # certified undo first, then on-policy wins
        n_state_pairs = 0
        with open(OUT, "a") as fh:
            for ci, ch in enumerate(chosens):
                for rj in failing[: (2 if ci == 0 else 1)]:   # cap pairs per state (≤3)
                    fh.write(json.dumps({
                        "system": _REPAIR_SYSTEM, "prompt": user,
                        "chosen": ch, "rejected": rj,
                        "meta": {"state": idx, "category": cat,
                                 "chosen_src": "undo" if ch == undo_json else "on-policy",
                                 "sampled_pass": len(passing), "sampled_fail": len(failing)},
                    }) + "\n")
                    n_state_pairs += 1
        pairs_written += n_state_pairs
        open(SIDE, "a").write(f"{idx}\n")
        print(f"[{idx}/{n_states}] {cat[:34]:34s} pass={len(passing)} fail={len(failing)} "
              f"+{n_state_pairs} pairs (total {pairs_written})", flush=True)
    print(f"DONE: {pairs_written} pairs → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
