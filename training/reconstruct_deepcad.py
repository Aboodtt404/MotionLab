"""Translate DeepCAD construction sequences (215k ABC-derived sketch+extrude programs, MIT license)
into our feature-program `Part`. Fix 4 (the real-complex-data lever): DeepCAD is ~25× the Fusion
reconstruction set, so even at a similar simple-skew its ABSOLUTE complex-part count is far larger.

DeepCAD's JSON schema is the SAME Onshape-API family as Fusion reconstruction, so this reuses the
Fusion translator's machinery (`_part_from` etc.) with two differences:
  - coords are NORMALIZED (~[-0.2,0.2]) not cm → scale uniformly (CM=100 → a mm-ish range), no ×10;
  - NO ground-truth STEP ships → gate on valid-single-solid + bbox-match to the JSON's recorded
    `properties.bounding_box`. This is a TRANSLATION-fidelity gate (we're translating a known-good
    program, not reverse-engineering), honestly weaker than Fusion's full voxel-IoU gate.

Run:  cad_pipeline/.venv/bin/python -m training.reconstruct_deepcad [n]
"""
from __future__ import annotations

import glob
import json
import sys

import cadquery as cq

import training.reconstruct_fusion as R
from cad_pipeline.builder import build_part

R.CM = 100.0                                    # DeepCAD normalized units → mm-ish; shared funcs use R.CM
DC_ROOT = "/workspace/.hf_home/datasets/deepcad/data/cad_json"
CM = R.CM


def reconstruct_dc(path: str, want_part: bool = False) -> dict:
    d = json.load(open(path))
    stem = path.rsplit("/", 1)[-1][:-5]
    part, skipped, ops = R._part_from(d)
    n_ex = len(ops)
    g = None
    if part.steps:
        try:
            g = build_part(part).val()
        except Exception:  # noqa: BLE001
            g = None
    res = {"id": stem, "extrudes": n_ex, "ops": ops, "skipped": skipped, "kept": False}
    if want_part:
        res["part"] = part.model_dump()
    if g is None or not g.Solids():
        return res
    valid = g.isValid() and len(g.Solids()) == 1 and g.Volume() > 1e-9
    bb = d["properties"]["bounding_box"]
    exp = sorted(abs(bb["max_point"][a] - bb["min_point"][a]) * CM for a in ("x", "y", "z"))
    gb = g.BoundingBox()
    got = sorted((gb.xlen, gb.ylen, gb.zlen))    # sorted extents → shape-match regardless of axis labels
    bbox_ok = all(abs(gg - ee) <= max(0.02 * ee, 0.05) for gg, ee in zip(got, exp))
    res["kept"] = bool(valid and bbox_ok and skipped == 0)
    res["bbox_ok"] = bool(bbox_ok)
    res["valid"] = bool(valid)
    return res


def main() -> int:
    files = sorted(glob.glob(f"{DC_ROOT}/**/*.json", recursive=True))
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 30
    files = files[:: max(1, len(files) // n)][:n]           # spread across the dataset
    import collections
    kept = 0
    byc = collections.Counter()
    keptc = collections.Counter()
    for p in files:
        try:
            r = reconstruct_dc(p)
        except Exception as e:  # noqa: BLE001
            print(f"{p.rsplit('/',1)[-1][:-5]}: ERR {type(e).__name__}: {str(e)[:40]}", flush=True)
            continue
        byc[min(r["extrudes"], 7)] += 1
        if r["kept"]:
            kept += 1; keptc[min(r["extrudes"], 7)] += 1
        print(f"{r['id']}: ex={r['extrudes']} skipped={r['skipped']} valid={r.get('valid')} "
              f"bbox_ok={r.get('bbox_ok')} kept={r['kept']}", flush=True)
    m = len([1 for _ in files])
    print(f"\nDEEPCAD n={m}: kept {kept}/{m} ({100*kept/m:.0f}%)")
    print("attempted by n_extrudes:", dict(sorted(byc.items())))
    print("kept by n_extrudes:", dict(sorted(keptc.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
