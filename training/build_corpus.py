"""Build the part-level SFT/RL corpus from the reconstruction dataset (docs/research/
track-a-feature-program-representation.md §5, §9-step5). Each record = one REAL part translated to
our feature-program `Part`, STRICTLY gated (skipped==0 AND voxel-IoU≥0.95 — corpus-gate-on-artifact),
with links to its thumbnail (.png) and ground-truth solid (.step) so the corpus serves image→program
or text→program, code or JSON targets, decided downstream.

Record: {stem, iou, n_extrudes, thumbnail, step, part}  (part = Part.model_dump()).
Parallel over CPU workers (spawn context — OCCT/cadquery global state isn't fork-safe). The
face-count guard + deterministic voxel IoU (see reconstruct_fusion) make each task hang-free.

Run:  cad_pipeline/.venv/bin/python -m training.build_corpus [n] [--workers W] [--out PATH]
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import multiprocessing as mp
import sys

from training.reconstruct_fusion import ROOT

OUT = "/workspace/.hf_home/cad_corpus/partlevel_recon.jsonl"


def _process(path: str):
    """Worker: translate one part → a gated corpus record, or None. Imports live inside the worker
    so the spawn context sets up OCCT fresh per process."""
    from training.reconstruct_fusion import reconstruct
    stem = path.rsplit("/", 1)[-1][:-5]
    try:
        r = reconstruct(path, want_part=True)
    except Exception:  # noqa: BLE001
        return None
    if r["skipped"] == 0 and r["iou"] >= 0.95:
        return {"stem": stem, "iou": r["iou"], "n_extrudes": r["extrudes"],
                "thumbnail": f"{ROOT}/{stem}.png", "step": f"{ROOT}/{stem}.step", "part": r["part"]}
    return None


def main() -> int:
    args = sys.argv[1:]
    files = sorted(glob.glob(f"{ROOT}/*.json"))
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 10
    out_path = args[args.index("--out") + 1] if "--out" in args else OUT
    # the positional count is a bare digit NOT consumed by a flag (--workers/--out take the next arg)
    consumed = set()
    for flag in ("--workers", "--out"):
        if flag in args:
            i = args.index(flag)
            consumed.add(i); consumed.add(i + 1)
    nargs = [a for k, a in enumerate(args) if a.isdigit() and k not in consumed]
    n = int(nargs[0]) if nargs else len(files)
    files = files[:n]

    kept = done = 0
    ctx = mp.get_context("spawn")
    with open(out_path, "w") as f, \
            cf.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        futs = {ex.submit(_process, p): p for p in files}
        for fut in cf.as_completed(futs):
            done += 1
            try:
                rec = fut.result(timeout=120)   # a task that runs away past 2min is abandoned
            except Exception:  # noqa: BLE001 (incl. TimeoutError — a stuck worker)
                rec = None
            if rec is not None:
                f.write(json.dumps(rec) + "\n"); f.flush(); kept += 1
            if done % 200 == 0:
                print(f"  ...{done}/{len(files)} kept={kept}", flush=True)
    print(f"\nCORPUS: {kept}/{len(files)} kept ({100*kept/len(files):.1f}%) → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
