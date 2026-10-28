"""Build the COMPLEX part of the corpus from DeepCAD (Fix 4). Targets the 36K parts at 3+ extrudes
(the complex tail Fusion lacks; simple parts we already have), translates each to our feature-program,
gates on valid-single-solid + bbox-match to the JSON's recorded bounding_box (DeepCAD ships no STEP →
translation-fidelity gate, weaker than Fusion's voxel-IoU). Parallel, spawn workers.

Record: {stem, source:"deepcad", iou:null, n_extrudes, part}. (No thumbnail/step — DeepCAD ships
neither; input-side conditioning (render/caption) is generated downstream.)

Run:  cad_pipeline/.venv/bin/python -m training.build_corpus_deepcad [--min-ex E] [--workers W] [--out P]
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import multiprocessing as mp
import sys

DC_ROOT = "/workspace/.hf_home/datasets/deepcad/data/cad_json"
OUT = "/workspace/.hf_home/cad_corpus/partlevel_deepcad_complex.jsonl"


def _count_ex(path: str) -> int:
    try:
        d = json.load(open(path))
        return sum(1 for s in d["sequence"] if s["type"] == "ExtrudeFeature")
    except Exception:  # noqa: BLE001
        return -1


def _process(path: str):
    """Worker: translate one DeepCAD part → gated corpus record or None (imports inside for spawn)."""
    from training.reconstruct_deepcad import reconstruct_dc
    stem = path.rsplit("/", 1)[-1][:-5]
    try:
        r = reconstruct_dc(path, want_part=True)
    except Exception:  # noqa: BLE001
        return None
    if r.get("kept"):
        return {"stem": stem, "source": "deepcad", "iou": None,
                "n_extrudes": r["extrudes"], "part": r["part"]}   # reconstruct_dc key is "extrudes"
    return None


def main() -> int:
    args = sys.argv[1:]
    min_ex = int(args[args.index("--min-ex") + 1]) if "--min-ex" in args else 3
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 10
    out_path = args[args.index("--out") + 1] if "--out" in args else OUT

    print("scanning for complex (>= %d extrude) parts..." % min_ex, flush=True)
    allf = sorted(glob.glob(f"{DC_ROOT}/**/*.json", recursive=True))
    ctx = mp.get_context("spawn")
    # cheap parallel pre-filter by extrude count
    with cf.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        counts = list(ex.map(_count_ex, allf, chunksize=200))
    complex_files = [p for p, c in zip(allf, counts) if c >= min_ex]
    print(f"complex files (>= {min_ex} extrude): {len(complex_files)} of {len(allf)}", flush=True)

    kept = done = 0
    with open(out_path, "w") as f, \
            cf.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
        futs = {ex.submit(_process, p): p for p in complex_files}
        for fut in cf.as_completed(futs):
            done += 1
            try:
                rec = fut.result(timeout=120)
            except Exception:  # noqa: BLE001
                rec = None
            if rec is not None:
                f.write(json.dumps(rec) + "\n"); f.flush(); kept += 1
            if done % 500 == 0:
                print(f"  ...{done}/{len(complex_files)} kept={kept}", flush=True)
    print(f"\nDEEPCAD COMPLEX CORPUS: {kept}/{len(complex_files)} kept "
          f"({100*kept/max(len(complex_files),1):.1f}%) → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
