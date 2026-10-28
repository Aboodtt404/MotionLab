"""FIX 5 — AutoMate-style quality filter over the 38,312 Fusion 360 j1.0.0 joint sets.

The placement research (docs/research/assembly-placement-research.md §5, AutoMate arXiv:2208.01779,
3-0 verified) measured that mined mate data is extremely noisy — AutoMate kept ~6% after heuristic
filtering — and that real mate axes come almost entirely from a small DISCRETE set of
geometry-derived candidates (cylinder axes, face-center normals; 96.3% axis-location accuracy by
candidate selection). This filter applies both lessons to our mined sets BEFORE the expensive
primitive-fit translation (translate_fusion_joints.py — that gate is about our Spec vocabulary
approximating the parts; THIS gate is about whether the joint itself is physically credible):

  CHECK 1 — CONTACT: the two bodies in their assembled pose actually meet (gap ≤ 2 mm; running
            clearance 0.1–0.8 mm sits inside). A joint between parts 60 mm apart is an
            authoring artifact, not supervision.
  CHECK 2 — DISCRETE AXIS (revolute/cylindrical only): the declared joint axis coincides with a
            geometry-derived candidate on EITHER body (cylindrical/conical face axes + circular
            edge axes): parallel within 1° and axis-line distance ≤ 1 mm.

Survivors also get a mined PORT-PAIR label (which bbox face of the moving body meets which face
of the base + overlap/fraction/offset) — real-mechanism supervision in exactly the port mate
vocabulary the planner emits (FIX 2), and the honest OOD eval split (hash-stable 10%).

Run:   cad_pipeline/.venv/bin/python -m training.filter_fusion_joints [n_sets|all]
Stats: cad_pipeline/.venv/bin/python -m training.filter_fusion_joints --stats
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import sys

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder

from cad_pipeline.assembly import _bb_overlap, _solid_gap
from training.translate_fusion_joints import CM, ROOT, _apply_pose

OUT = "/workspace/.hf_home/cad_corpus/fusion_joints_filtered.jsonl"

CONTACT_TOL = 2.0     # mm — running fits (0.1–0.8) and weld contact both pass; authoring gaps fail
AXIS_ANG_TOL = math.radians(1.0)
AXIS_DIST_TOL = 1.0   # mm — the declared axis must LIE ON a geometry-derived candidate line

REPRESENTABLE = ("RevoluteJointType", "CylindricalJointType", "RigidJointType")


# --------------------------------------------------------------------------- axis candidates
def _axis_candidates(solid: cq.Solid) -> list:
    """Geometry-derived axis candidates (point, unit direction) — the AutoMate discrete set:
    cylindrical + conical face axes, and circular edge axes (a drilled hole's rim is a circle
    even when its wall face got split or turned into a cone by a chamfer)."""
    cands: list = []
    for f in solid.Faces():
        try:
            ad = BRepAdaptor_Surface(f.wrapped)
            t = ad.GetType()
            if t == GeomAbs_Cylinder:
                ax = ad.Cylinder().Axis()
            elif t == GeomAbs_Cone:
                ax = ad.Cone().Axis()
            else:
                continue
            p, d = ax.Location(), ax.Direction()
            cands.append(((p.X(), p.Y(), p.Z()), (d.X(), d.Y(), d.Z())))
        except Exception:  # noqa: BLE001 — a degenerate face contributes no candidate
            continue
    for e in solid.Edges():
        try:
            ad = BRepAdaptor_Curve(e.wrapped)
            if ad.GetType() != GeomAbs_Circle:
                continue
            circ = ad.Circle()
            p, d = circ.Location(), circ.Axis().Direction()
            cands.append(((p.X(), p.Y(), p.Z()), (d.X(), d.Y(), d.Z())))
        except Exception:  # noqa: BLE001
            continue
    return cands


def _axis_match(origin, direction, cands) -> dict:
    """Best candidate for the declared joint axis: parallel within AXIS_ANG_TOL and the joint
    origin within AXIS_DIST_TOL of the candidate LINE (point-to-line, both lines parallel)."""
    best = {"matched": False, "angle_deg": None, "dist_mm": None}
    dj = cq.Vector(*direction).normalized()
    oj = cq.Vector(*origin)
    for (cp, cd) in cands:
        dc = cq.Vector(*cd).normalized()
        cosang = abs(dj.dot(dc))
        ang = math.acos(min(1.0, cosang))
        if ang > AXIS_ANG_TOL:
            continue
        w = oj - cq.Vector(*cp)
        dist = (w - dc.multiply(w.dot(dc))).Length
        if best["dist_mm"] is None or dist < best["dist_mm"]:
            best = {"matched": dist <= AXIS_DIST_TOL, "angle_deg": round(math.degrees(ang), 3),
                    "dist_mm": round(dist, 3)}
            if best["matched"] and dist < 0.05:
                break
    return best


# --------------------------------------------------------------------------- port mining
_FACES = {"x": ("left", "right"), "y": ("front", "back"), "z": ("bottom", "top")}


def _mine_port(bb_move, bb_base) -> dict:
    """Assembled pose → the FIX-2 port vocabulary: dominant center-to-center axis picks the face
    pair (moving part's near face onto the base's facing face), plus overlap depth along that
    axis, side-height fraction, and top/bottom XY offset — real-mechanism port supervision."""
    d = (bb_move.center.x - bb_base.center.x, bb_move.center.y - bb_base.center.y,
         bb_move.center.z - bb_base.center.z)
    spans = {"x": max(bb_base.xlen, 1e-6), "y": max(bb_base.ylen, 1e-6), "z": max(bb_base.zlen, 1e-6)}
    rel = {a: abs(d[i]) / spans[a] for i, a in enumerate("xyz")}
    ax = max(rel, key=rel.get)
    i = "xyz".index(ax)
    lo_face, hi_face = _FACES[ax]
    if d[i] >= 0:      # moving part sits on the base's HIGH side of this axis
        b_port, a_port = hi_face, lo_face
        overlap = (bb_base.xmax, bb_base.ymax, bb_base.zmax)[i] - (bb_move.xmin, bb_move.ymin, bb_move.zmin)[i]
    else:
        b_port, a_port = lo_face, hi_face
        overlap = (bb_move.xmax, bb_move.ymax, bb_move.zmax)[i] - (bb_base.xmin, bb_base.ymin, bb_base.zmin)[i]
    port = {"a_port": a_port, "b_port": b_port, "overlap_mm": round(overlap, 2)}
    if ax in ("x", "y") and bb_base.zlen > 1e-6:
        port["fraction"] = round((bb_move.center.z - bb_base.zmin) / bb_base.zlen, 3)
    if ax == "z":
        port["offset"] = [round(bb_move.center.x - bb_base.center.x, 2),
                          round(bb_move.center.y - bb_base.center.y, 2)]
    # classify against the FIX-2 port grammar so downstream exemplar builders never train the
    # port mate on geometry it can't express (measured in the smoke: fraction −2.7, overlap 80 mm):
    #   port   — shallow face weld, fraction inside [0,1]: a clean port-mate exemplar
    #   insert — deep engagement along the axis (shaft-in-housing): coaxial supervision, not port
    #   oov    — the moving part sits outside the base's span (fraction out of range)
    move_span = max((bb_move.xlen, bb_move.ylen, bb_move.zlen)["xyz".index(ax)], 1e-6)
    frac = port.get("fraction")
    if frac is not None and not (-0.05 <= frac <= 1.05):
        port["class"] = "oov"
    elif overlap > 8.0 and overlap / move_span > 0.3:
        port["class"] = "insert"
    else:
        port["class"] = "port"
        if frac is not None:
            port["fraction"] = min(1.0, max(0.0, frac))
    return port


# --------------------------------------------------------------------------- per-set filter
def filter_set(path: str) -> dict:
    d = json.load(open(path))
    b1, b2 = d["body_one"], d["body_two"]
    j = d["joints"][0]
    jm = j["joint_motion"]
    jtype = jm.get("joint_type", "RigidJointType")
    out = {"set": path.split("/")[-1], "bodies": [b1, b2], "joint": jtype,
           "representable": jtype in REPRESENTABLE}
    s1 = _apply_pose(cq.importers.importStep(f"{ROOT}/{b1}.step").val(),
                     j["geometry_or_origin_one"].get("transform"))
    s2 = _apply_pose(cq.importers.importStep(f"{ROOT}/{b2}.step").val(),
                     j["geometry_or_origin_two"].get("transform"))
    bb1, bb2 = s1.BoundingBox(), s2.BoundingBox()
    # CHECK 1 — contact (bbox broad-phase spares the exact BRepExtrema on obvious misses)
    if _bb_overlap(bb1, bb2, pad=CONTACT_TOL):
        gap, _dir = _solid_gap(s1, s2)
    else:
        gap = 1e9   # bboxes don't even come within tolerance
    out["contact_gap_mm"] = round(gap, 3) if gap < 1e9 else None
    contact_ok = gap <= CONTACT_TOL
    out["contact_ok"] = contact_ok
    # CHECK 2 — discrete axis (only meaningful for axis-bearing joints)
    axis_ok = True
    if jtype in ("RevoluteJointType", "CylindricalJointType"):
        g = j["geometry_or_origin_one"]
        av = g.get("primary_axis_vector", {})
        o = g.get("origin", {})
        origin = (o.get("x", 0) * CM, o.get("y", 0) * CM, o.get("z", 0) * CM)
        direction = (av.get("x", 0), av.get("y", 0), av.get("z", 1))
        m = _axis_match(origin, direction, _axis_candidates(s1) + _axis_candidates(s2))
        out["axis"] = m
        axis_ok = m["matched"]
    out["keep"] = out["representable"] and contact_ok and axis_ok
    if out["keep"]:
        out["port"] = _mine_port(bb2, bb1)   # body_two = moving part, body_one = base (translator's roles)
        out["split"] = "eval" if int(hashlib.md5(out["set"].encode()).hexdigest(), 16) % 10 == 0 else "train"
    return out


def _iso_worker(path: str, q) -> None:
    try:
        q.put(filter_set(path))
    except Exception as e:  # noqa: BLE001
        q.put({"set": path.split("/")[-1], "skip": f"worker {type(e).__name__}: {str(e)[:120]}"})


def _stats() -> int:
    rows = [json.loads(ln) for ln in open(OUT)]
    kept = [r for r in rows if r.get("keep")]
    n = len(rows)
    print(f"processed {n} sets → keep {len(kept)} ({100 * len(kept) / max(n, 1):.1f}%)")
    skips = sum(1 for r in rows if "skip" in r)
    print(f"  worker skips/errors: {skips}")
    rep = sum(1 for r in rows if r.get("representable"))
    print(f"  representable joint types: {rep} ({100 * rep / max(n, 1):.1f}%)")
    cok = sum(1 for r in rows if r.get("contact_ok"))
    print(f"  contact ≤ {CONTACT_TOL} mm: {cok} ({100 * cok / max(n, 1):.1f}%)")
    ax = [r for r in rows if "axis" in r]
    axok = sum(1 for r in ax if r["axis"]["matched"])
    print(f"  axis on discrete candidate (of {len(ax)} axis-bearing): {axok} "
          f"({100 * axok / max(len(ax), 1):.1f}%)")
    for t in sorted({r.get("joint") for r in kept if r.get("joint")}):
        print(f"  keep · {t}: {sum(1 for r in kept if r['joint'] == t)}")
    ev = sum(1 for r in kept if r.get("split") == "eval")
    print(f"  splits: train {len(kept) - ev} / eval {ev}")
    ports = [r["port"]["b_port"] for r in kept if "port" in r]
    from collections import Counter
    print(f"  mined b_port histogram: {dict(Counter(ports).most_common())}")
    return 0


def main() -> int:
    if "--stats" in sys.argv:
        return _stats()
    arg = sys.argv[1] if len(sys.argv) > 1 else "200"
    n = 10 ** 9 if arg == "all" else int(arg)
    seen_path = OUT.replace(".jsonl", ".processed.txt")
    try:
        seen = set(open(seen_path).read().split())
    except FileNotFoundError:
        seen = set()
    sets = [p for p in sorted(glob.glob(f"{ROOT}/joint_set_*.json"))
            if p.split("/")[-1] not in seen][:n]
    done = kept = 0
    import multiprocessing as mp
    import time as _time
    K = max(1, int(os.environ.get("SWEEP_WORKERS", "12")))
    TIMEOUT = 120.0   # no booleans here (extrema + face census only) — hangs should be rare
    pending = list(sets)
    active: list = []

    def _handle(r: dict) -> None:
        nonlocal done, kept
        done += 1
        with open(OUT, "a") as f:
            f.write(json.dumps(r) + "\n")
        if "skip" in r:
            print(f"{r['set']}: SKIP {r['skip']}", flush=True)
            return
        kept += bool(r["keep"])
        if done % 100 == 0:
            print(f"[{done}/{len(sets)}] keep-rate {100 * kept / max(done, 1):.1f}%", flush=True)

    while pending or active:
        while pending and len(active) < K:
            p = pending.pop(0)
            with open(seen_path, "a") as sf:
                sf.write(p.split("/")[-1] + "\n")
            q = mp.Queue()
            proc = mp.Process(target=_iso_worker, args=(p, q), daemon=True)
            proc.start()
            active.append((proc, q, p, _time.monotonic()))
        still: list = []
        for proc, q, p, t0 in active:
            if not proc.is_alive():
                try:
                    _handle(q.get_nowait())
                except Exception:  # noqa: BLE001
                    done += 1
                    print(f"{p.split('/')[-1]}: SKIP worker died (no result)", flush=True)
                proc.join()
            elif _time.monotonic() - t0 > TIMEOUT:
                proc.kill(); proc.join()
                done += 1
                with open(OUT, "a") as f:
                    f.write(json.dumps({"set": p.split("/")[-1], "skip": "TIMEOUT"}) + "\n")
                print(f"{p.split('/')[-1]}: SKIP TIMEOUT >{int(TIMEOUT)}s", flush=True)
            else:
                still.append((proc, q, p, t0))
        active = still
        _time.sleep(0.1)
    print(f"\nFILTER keep-rate: {kept}/{done} ({100 * kept / max(done, 1):.1f}%) — "
          f"contact ≤ {CONTACT_TOL} mm + declared axis on a discrete geometry candidate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
