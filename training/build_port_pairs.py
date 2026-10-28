"""PORT exemplars from REAL Fusion mechanisms — the corpus FIX 2 has been missing.

The gap this closes (measured, 2026-07-25 live desk): the planner emits port mates zero-shot but
gets ~2/3 of them semantically right, because it has never seen a worked example. Meanwhile the
AutoMate filter (filter_fusion_joints.py) left 9,380 engineer-authored attachments already
classified into the port vocabulary — real mechanisms, not synthetic caricatures.

What this does: every RIGID Fusion keep whose bodies our primitive fitter reproduced carries a
generic `attach` mate ("snap to the nearest face" — vague by construction). This rewrites that
into the PRECISE typed `port` mate that reproduces the SAME geometry, then proves it:

    solve_layout(rewritten) must land the moving body within REPRO_TOL of where the real
    assembled mechanism had it — otherwise the port vocabulary cannot express that attachment
    and the set is dropped, honestly, rather than taught as an approximation.

Only RIGID sets qualify: solve_layout deliberately DROPS mates between a joint's two sides (the
welded-hinge guard), so a port mate on a revolute pair would silently vanish. That split is the
right pedagogy anyway — ports are structural attachment, joints are kinematics.

Out: /workspace/.hf_home/cad_corpus/port_pairs.jsonl  (+ .sets.json for the eval-split holdout)
Run: cad_pipeline/.venv/bin/python -m training.build_port_pairs [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cad_pipeline.asm_captions import asm_describe, gate_caption  # noqa: E402
from cad_pipeline.assembly import (Assembly, Mate, _bare_solid, _place_world,  # noqa: E402
                                   solve_layout, verify_assembly)
from cad_pipeline.planner import (_OUTLINE_SCHEMA, _OUTLINE_SYSTEM, _SYSTEM,  # noqa: E402
                                  _asm_schema, dump_for_grammar)

CAPTIONED = "/workspace/.hf_home/cad_corpus/fusion_joint_assemblies.captioned.jsonl"
FILTERED = "/workspace/.hf_home/cad_corpus/fusion_joints_filtered.jsonl"
OUT = "/workspace/.hf_home/cad_corpus/port_pairs.jsonl"

REPRO_TOL = 1.5        # mm — the rewritten port mate must reproduce the real placement this well
_FACE_OPP = {"top": "bottom", "bottom": "top", "front": "back",
             "back": "front", "left": "right", "right": "left"}
# axis -> (low-face, high-face) in the solver's bbox frame (_PORTS in assembly.py)
_AXIS_FACES = {"x": ("back", "front"), "y": ("right", "left"), "z": ("bottom", "top")}
_NORMALS = {"top": (0, 0, 1), "bottom": (0, 0, -1), "front": (1, 0, 0),
            "back": (-1, 0, 0), "left": (0, 1, 0), "right": (0, -1, 0)}


def _world_bb(asm: Assembly, name: str):
    comps = {c.name: c for c in asm.components}
    c = comps[name]
    return _place_world(_bare_solid(c.part), c, comps).BoundingBox()


def _port_pt(bb, port: str, fraction=None, offset=(0.0, 0.0)):
    """Mirror of assembly._port_point — kept local so a solver change can't silently skew the
    inverse derivation without the reproduction gate catching it."""
    pick = {"top": (bb.center.x, bb.center.y, bb.zmax), "bottom": (bb.center.x, bb.center.y, bb.zmin),
            "front": (bb.xmax, bb.center.y, bb.center.z), "back": (bb.xmin, bb.center.y, bb.center.z),
            "left": (bb.center.x, bb.ymax, bb.center.z), "right": (bb.center.x, bb.ymin, bb.center.z)}
    x, y, z = pick[port]
    if fraction is not None and port not in ("top", "bottom"):
        z = bb.zmin + fraction * (bb.zmax - bb.zmin)
    if port in ("top", "bottom"):
        x, y = x + offset[0], y + offset[1]
    return (x, y, z)


def derive_port(bb_a, bb_b) -> dict:
    """INVERSE of the solver's port branch: the (a_port, b_port, overlap, fraction|offset) that
    reproduce a's measured pose relative to b. Axis choice mirrors filter_fusion_joints._mine_port
    (dominant centre separation normalised by b's span)."""
    d = (bb_a.center.x - bb_b.center.x, bb_a.center.y - bb_b.center.y, bb_a.center.z - bb_b.center.z)
    spans = {"x": max(bb_b.xlen, 1e-6), "y": max(bb_b.ylen, 1e-6), "z": max(bb_b.zlen, 1e-6)}
    ax = max(spans, key=lambda k: abs(d["xyz".index(k)]) / spans[k])
    lo, hi = _AXIS_FACES[ax]
    b_port = hi if d["xyz".index(ax)] >= 0 else lo
    a_port = _FACE_OPP[b_port]
    m = {"a_port": a_port, "b_port": b_port}
    if b_port in ("top", "bottom"):
        m["offset"] = (round(bb_a.center.x - bb_b.center.x, 3), round(bb_a.center.y - bb_b.center.y, 3))
        fraction = None
    else:
        # side port: `fraction` is the only handle on z, so it must carry a's centre height
        fraction = (bb_a.center.z - bb_b.zmin) / max(bb_b.zlen, 1e-6)
        m["fraction"] = round(fraction, 4)
    pb = _port_pt(bb_b, b_port, fraction, m.get("offset", (0.0, 0.0)))
    pa = _port_pt(bb_a, a_port)
    nb = _NORMALS[b_port]
    # solver sets pa_final = pb - nb*overlap; we want pa_final == pa (a stays where it really is)
    m["overlap"] = round(sum((pb[i] - pa[i]) * nb[i] for i in range(3)), 3)
    return m


def rewrite(rec: dict) -> dict | None:
    """attach -> port, PROVEN by re-solving. None when the vocabulary can't express it."""
    asm = Assembly(**rec["assembly"])
    att = [m for m in asm.mates if m.kind == "attach" and m.a and m.b]
    if len(att) != 1 or len(asm.components) != 2 or asm.joints:
        return None
    a_name, b_name = att[0].a, att[0].b
    try:
        bb_a, bb_b = _world_bb(asm, a_name), _world_bb(asm, b_name)
    except Exception:  # noqa: BLE001 — an unbuildable fit is already out of scope
        return None
    p = derive_port(bb_a, bb_b)
    if not (0.0 <= p.get("fraction", 0.5) <= 1.0):
        return None                       # a sits off the end of b's span — not a face attachment
    if p["overlap"] < -0.5 or p["overlap"] > 0.5 * max(bb_a.xlen, bb_a.ylen, bb_a.zlen) + 5:
        return None                       # gap, or an insertion deeper than the part is thick

    out = asm.model_copy(deep=True)
    out.mates = [Mate(kind="port", a=a_name, b=b_name, **p)]
    for c in out.components:              # the port mate must do ALL the placing of `a`
        if c.name == a_name:
            c.at = (0.0, 0.0, 0.0)
    try:
        solved = solve_layout(out.model_copy(deep=True))
        got = _world_bb(solved, a_name)
    except Exception:  # noqa: BLE001
        return None
    err = max(abs(got.center.x - bb_a.center.x), abs(got.center.y - bb_a.center.y),
              abs(got.center.z - bb_a.center.z))
    if err > REPRO_TOL:
        return None                       # the port mate does NOT reproduce the real mechanism
    try:
        rep = verify_assembly(solved)
    except Exception:  # noqa: BLE001
        return None
    # 2-part FRAGMENTS never promised to stand on the floor (translator's own waiver)
    if [r for r in rep["rows"] if not r["within_tol"] and "statics" not in r["name"]]:
        return None
    return {"assembly": json.loads(out.model_dump_json(exclude_none=True)), "repro_err": round(err, 3),
            "port": p, "solved_rows": len(rep["rows"])}


def pairs_for(rec: dict, rw: dict, rng: random.Random) -> list:
    asm_json = rw["assembly"]
    caps = asm_describe(Assembly(**asm_json), rng)      # RE-captioned: carries the port phrase
    # GATE ON THE SHIPPED ARTIFACT: the target must be a string the guided decoder can
    # actually emit — pydantic defaults, key order and -0.0 all make it unproducible.
    target = dump_for_grammar(asm_json, _asm_schema())
    name = rec.get("name", "assembly").lower()
    out = []
    for lv in ("l1", "l2", "l3"):
        cap = caps.get(lv)
        if not cap or not gate_caption(lv, cap, Assembly(**asm_json)):
            continue
        out.append({"system": _SYSTEM, "prompt": "input: " + cap, "code": target,
                    "source": "asm-plan-port", "category": "fusion-port", "prompt_level": lv})
    listing = "; ".join(f"{c['name']} (role {c.get('role', 'other')}, {c['part'].get('shape', 'box')})"
                        for c in asm_json["components"])
    out.append({"system": _SYSTEM, "prompt": f"input: {name}\nparts: {listing}", "code": target,
                "source": "asm-plan-port", "category": "fusion-port", "prompt_level": "two-stage"})
    out.append({"system": _OUTLINE_SYSTEM, "prompt": "object: " + name,
                "code": dump_for_grammar({"parts": [{"name": c["name"], "role": c.get("role", "other"),
                                                    "shape": c["part"].get("shape", "box")}
                                                   for c in asm_json["components"]]}, _OUTLINE_SCHEMA),
                "source": "asm-outline-port", "category": "fusion-port", "prompt_level": "outline"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    ports = {}
    for line in open(FILTERED):
        r = json.loads(line)
        if r.get("keep") and r.get("port", {}).get("class") == "port":
            ports[r["set"]] = r
    caps = [json.loads(line) for line in open(CAPTIONED)]
    cands = [r for r in caps if r["set"] in ports and r["joint"] == "RigidJointType"]
    if a.limit:
        cands = cands[:a.limit]
    print(f"[port-pairs] candidates: {len(cands)} rigid ∩ clean-port ∩ shape-fitted", flush=True)

    rng = random.Random(11)
    rows, kept_sets, errs, drops = [], {"train": [], "eval": []}, [], 0
    for i, rec in enumerate(cands):
        rw = rewrite(rec)
        if rw is None:
            drops += 1
            continue
        errs.append(rw["repro_err"])
        split = ports[rec["set"]].get("split", "train")
        kept_sets[split].append(rec["set"])
        if split == "eval":
            continue                       # HOLD OUT: real-mechanism OOD probe, never trained on
        rows += pairs_for(rec, rw, rng)
        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(cands)}] kept={len(errs)} pairs={len(rows)}", flush=True)

    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(OUT.replace(".jsonl", ".sets.json"), "w") as f:
        json.dump(kept_sets, f, indent=1)
    n_keep = len(errs)
    print(f"\n[port-pairs] rewrote {n_keep}/{len(cands)} ({100*n_keep/max(len(cands),1):.0f}%) — "
          f"dropped {drops} the port vocabulary can't express")
    if errs:
        errs.sort()
        print(f"  reproduction error mm: median {errs[len(errs)//2]:.3f}  max {errs[-1]:.3f} "
              f"(tol {REPRO_TOL})")
    print(f"  train sets {len(kept_sets['train'])} -> {len(rows)} pairs | "
          f"eval sets {len(kept_sets['eval'])} HELD OUT -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
