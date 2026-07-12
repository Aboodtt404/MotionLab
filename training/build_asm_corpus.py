"""Assembly corpus: parametric GOLDEN-assembly families → verifier survival filter → NL brief →
target Assembly JSON. The assembly analog of build_newops_corpus (the playbook that fixed part-level).

The repair bank shows the model fails on RELATIONSHIPS (joint attachment 60×, interference 43×,
connectivity 41×, cutout 40×, pose sweep 33× across 20/20 failing episodes) — it never learned the
working mate/joint patterns the fixtures encode. Each family here emits the pattern the planner is
supposed to produce: components (parts + roles) + mates + joints, NO hand coordinates except where
the pattern itself is explicit (bearing seats, hinge hang). Gate: solve_layout → verify_assembly
must PASS. Target = the PRE-solve Assembly JSON (what the planner emits; the solver owns placement).

Run:  cad_pipeline/.venv/bin/python training/build_asm_corpus.py --per-family 60 \
          --out corpus_out/batch7_assemblies.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter

sys.path.insert(0, ".")

from cad_pipeline.assembly import (Assembly, Component, Joint, Mate, repair_connectivity,  # noqa: E402
                                   solve_layout, verify_assembly)
from cad_pipeline.spec import Spec  # noqa: E402


# ---------------------------------------------------------------- families (proven patterns, varied)
def fam_stool(rng) -> tuple:
    n = rng.choice([3, 4, 4, 5, 6])
    sd = round(rng.uniform(110, 170), 0); st = round(rng.uniform(12, 22), 0)
    lw = round(rng.uniform(12, 22), 0); lh = round(rng.uniform(80, 140), 0)
    splay = round(rng.uniform(0, 14), 0); r = round(sd * rng.uniform(0.32, 0.42), 0)
    seat = Component(name="seat", role="seat", part=Spec(
        object="seat", shape="cylinder", envelope={"diameter": sd, "height": st}))
    legs = [Component(name=f"leg{i}", role="leg", part=Spec(
        object="leg", shape="box", envelope={"length": lw, "width": lw, "height": lh})) for i in range(n)]
    asm = Assembly(object=f"{n}-leg stool", components=[seat, *legs], mates=[
        Mate(kind="radial", parts=[f"leg{i}" for i in range(n)], around="seat", count=n,
             radius=r, splay_deg=splay),
        Mate(kind="stack", a="seat", b="leg0", overlap=round(rng.uniform(2, 5), 0)),
    ], fuse=True)
    brief = (f"A {n}-legged stool, about {lh + st:.0f} mm tall: a round seat ⌀{sd:.0f}×{st:.0f} mm "
             f"resting on {n} legs ({lw:.0f}×{lw:.0f}×{lh:.0f} mm) arranged evenly around the seat "
             f"axis at radius {r:.0f} mm" + (f", splayed outward {splay:.0f}°." if splay else "."))
    return "stool (radial legs + stacked seat)", brief, asm


def fam_table_shelf(rng) -> tuple:
    kind = rng.choice(["table", "shelf"])
    if kind == "table":
        tl = round(rng.uniform(160, 260), 0); tw = round(rng.uniform(100, 180), 0); tt = round(rng.uniform(10, 18), 0)
        lw = round(rng.uniform(14, 24), 0); lh = round(rng.uniform(90, 150), 0)
        top = Component(name="top", role="top", part=Spec(
            object="table top", shape="box", envelope={"length": tl, "width": tw, "height": tt}))
        legs = [Component(name=f"leg{i}", role="leg", part=Spec(
            object="leg", shape="box", envelope={"length": lw, "width": lw, "height": lh})) for i in range(4)]
        asm = Assembly(object="four-leg table", components=[top, *legs], mates=[
            Mate(kind="corners", parts=[f"leg{i}" for i in range(4)], around="top",
                 dx=tl - lw - 10, dy=tw - lw - 10),
            Mate(kind="stack", a="top", b="leg0", overlap=3),
        ], fuse=True)
        brief = (f"A small four-leg table: a {tl:.0f}×{tw:.0f}×{tt:.0f} mm rectangular top on four "
                 f"{lw:.0f} mm square legs {lh:.0f} mm long, one at each corner, inset from the edges.")
        return "table (corner legs + stacked top)", brief, asm
    sl = round(rng.uniform(160, 240), 0); sw = round(rng.uniform(90, 150), 0); st = round(rng.uniform(8, 16), 0)
    bw = round(rng.uniform(40, 80), 0); bh = round(rng.uniform(40, 80), 0)
    shelf = Component(name="shelf", role="top", part=Spec(
        object="shelf", shape="box", envelope={"length": sl, "width": sw, "height": st}))
    bracket = Component(name="bracket", role="support", part=Spec(
        object="bracket", shape="box", envelope={"length": bw, "width": sw, "height": bh}))
    asm = Assembly(object="shelf on L-bracket", components=[bracket, shelf], mates=[
        Mate(kind="stack", a="shelf", b="bracket", overlap=3)], fuse=True)
    brief = (f"A wall shelf: a {sl:.0f}×{sw:.0f}×{st:.0f} mm board sitting on an "
             f"L-bracket {bw:.0f}×{sw:.0f}×{bh:.0f} mm, fused into one printable piece.")
    return "shelf on bracket (stack)", brief, asm


def fam_bolt_stack(rng) -> tuple:
    n = rng.choice([2, 2, 3])
    L = round(rng.uniform(32, 60), 0); t = round(rng.uniform(4, 8), 0)
    d = round(rng.uniform(5, 8.5), 1)
    plates = [Component(name=f"plate{i+1}", role="panel", part=Spec(
        object="plate", shape="box", envelope={"length": L, "width": L, "height": t},
        features=[{"type": "through_hole", "diameter": d}])) for i in range(n)]
    mates = [Mate(kind="stack", a=f"plate{i+1}", b=f"plate{i}", overlap=0.1) for i in range(1, n)]
    asm = Assembly(object=f"{n}-plate bolted stack", components=plates, mates=mates, fuse=True)
    brief = (f"A stack of {n} square plates ({L:.0f}×{L:.0f}×{t:.0f} mm each), face to face, every "
             f"plate drilled ⌀{d:g} mm through the center so a single bolt passes the whole stack.")
    return "bolted plate stack (coaxial holes)", brief, asm


def fam_shaft_bearings(rng) -> tuple:
    sd = rng.choice([6, 8, 10, 12]); sh = round(rng.uniform(50, 90), 0)
    bd = round(sd * rng.uniform(2.4, 3.0), 0); bt = round(rng.uniform(6, 9), 0)
    off = round(sh * rng.uniform(0.25, 0.35), 0)
    fit = round(sd + 0.05, 2)
    shaft = Component(name="shaft", role="body", part=Spec(
        object="shaft", shape="cylinder", envelope={"diameter": sd, "height": sh}))
    b1 = Component(name="bearing1", role="hub", at=(0.0, 0.0, off), part=Spec(
        object="bearing", shape="cylinder", envelope={"diameter": bd, "height": bt},
        features=[{"type": "through_hole", "diameter": fit}]))
    b2 = Component(name="bearing2", role="hub", at=(0.0, 0.0, -off), part=Spec(
        object="bearing", shape="cylinder", envelope={"diameter": bd, "height": bt},
        features=[{"type": "through_hole", "diameter": fit}]))
    asm = Assembly(object="shaft with two bearing seats", components=[shaft, b1, b2], fuse=False)
    brief = (f"A ⌀{sd} mm shaft {sh:.0f} mm long carrying two bearings (⌀{bd:.0f}×{bt:.0f} mm, "
             f"bore ⌀{fit:g} mm running fit) seated symmetrically {off:.0f} mm either side of "
             f"the shaft midpoint. Separate parts, not fused.")
    return "shaft + bearings (running fit)", brief, asm


def fam_hinge(rng) -> tuple:
    ph = round(rng.uniform(80, 130), 0); pw = round(rng.uniform(8, 14), 0)
    dl = round(rng.uniform(60, 100), 0); dh = round(ph * rng.uniform(0.8, 0.95), 0)
    dt = round(rng.uniform(4, 8), 0)
    hi = rng.choice([90, 110, 135, 180])
    post = Component(name="post", role="support", at=(0.0, 0.0, ph / 2), part=Spec(
        object="post", shape="box", envelope={"length": pw, "width": pw, "height": ph}))
    door = Component(name="door", role="panel", at=(pw / 2 + dl / 2 + 0.3, 0.0, ph / 2), part=Spec(
        object="door", shape="box", envelope={"length": dl, "width": dt, "height": dh}))
    asm = Assembly(object="hinged door", components=[post, door], fuse=True,
                   joints=[Joint(a="door", b="post", axis="z",
                                 at=(pw / 2 + 0.3, pw, ph / 2), limits=(0, hi))])
    brief = (f"A door on a hinge: a {pw:.0f} mm square post {ph:.0f} mm tall, with a "
             f"{dl:.0f}×{dt:.0f}×{dh:.0f} mm door hung on a vertical hinge along the post edge, "
             f"swinging 0–{hi}°. The door must clear the post through the whole swing.")
    return "hinged door (revolute)", brief, asm


def fam_enclosure_pcb(rng) -> tuple:
    el = round(rng.uniform(70, 120), 0); ew = round(rng.uniform(55, 95), 0); et = round(rng.uniform(3, 6), 0)
    sd = round(rng.uniform(5, 8), 0); sh = round(rng.uniform(4, 8), 0)
    px, py = round(el * 0.39, 0), round(ew * 0.36, 0)
    standoffs = [Component(name=f"so{i}", role="support", parent="enc", at=(x, y, et / 2), part=Spec(
        object="standoff", shape="cylinder", envelope={"diameter": sd, "height": sh}))
        for i, (x, y) in enumerate([(-px, -py), (px, -py), (-px, py), (px, py)])]
    asm = Assembly(object="pcb on standoffs", components=[
        Component(name="enc", role="base", at=(0.0, 0.0, et / 2), part=Spec(
            object="enclosure floor", shape="box", envelope={"length": el, "width": ew, "height": et})),
        *standoffs,
        Component(name="pcb", role="panel", part=Spec(
            object="pcb", shape="box", envelope={"length": round(el * 0.88, 0),
                                                 "width": round(ew * 0.85, 0), "height": 1.6})),
    ], mates=[Mate(kind="ground", a="enc"),
              Mate(kind="stack", a="pcb", b="so0", overlap=0.1, offset=(px, py))])
    brief = (f"An electronics base: a {el:.0f}×{ew:.0f}×{et:.0f} mm enclosure floor with four "
             f"⌀{sd:.0f}×{sh:.0f} mm standoffs fixed to it near the corners (children of the "
             f"enclosure frame), and a PCB resting on all four standoffs.")
    return "enclosure + parented standoffs + pcb", brief, asm


def fam_drone(rng) -> tuple:
    n = rng.choice([4, 4, 6])
    hd = round(rng.uniform(50, 80), 0); ht = round(rng.uniform(5, 9), 0)
    al = round(rng.uniform(60, 110), 0); aw = round(rng.uniform(10, 16), 0); at_ = round(rng.uniform(5, 8), 0)
    hub = Component(name="hub", role="hub", part=Spec(
        object="hub plate", shape="cylinder", envelope={"diameter": hd, "height": ht}))
    arms = [Component(name=f"arm{i}", role="arm", part=Spec(
        object="arm", shape="box", envelope={"length": al, "width": aw, "height": at_})) for i in range(n)]
    asm = Assembly(object=f"{n}-arm drone frame", components=[hub, *arms], mates=[
        Mate(kind="radial", parts=[f"arm{i}" for i in range(n)], around="hub", count=n,
             radius=round(hd / 2 + al / 2 - rng.uniform(6, 12), 0)),
    ], fuse=True)
    brief = (f"A {n}-arm drone frame: a round hub plate ⌀{hd:.0f}×{ht:.0f} mm with {n} rectangular "
             f"arms ({al:.0f}×{aw:.0f}×{at_:.0f} mm) radiating evenly from its rim, fused into one frame.")
    return "drone frame (radial arms)", brief, asm


def fam_cart(rng) -> tuple:
    # the car-campaign pattern (the car_corners fixture, parametrized): chassis grounded at ride
    # height + 4 AXLES welded into the chassis sides via `corners` + 4 sideways wheels whose inner
    # faces MEET the axle tips + one revolute per wheel with a DERIVED hinge point. All geometry
    # follows the fixture's arithmetic: dy_wheel = dy_axle + axle_len/2 + wheel_w/2.
    cl = round(rng.uniform(140, 260), 0); cw = round(rng.uniform(80, 130), 0); ct = round(rng.uniform(10, 18), 0)
    wd = round(rng.uniform(36, 60), 0); wt = round(rng.uniform(10, 18), 0)
    ad = round(rng.uniform(6, 10), 0); al = round(rng.uniform(18, 28), 0)   # axle ⌀ + length
    dxh = round(cl * rng.uniform(0.28, 0.36), 0)                            # half-wheelbase
    dy_axle = round(cw / 2 + al / 2, 1)     # axle inner face exactly at the chassis side (fixture arithmetic)
    dy_wheel = round(dy_axle + al / 2 + wt / 2, 1)                          # wheel inner face at the axle tip
    ride = round(wd / 2, 1)
    axles = ["front_left_axle", "front_right_axle", "rear_left_axle", "rear_right_axle"]
    wheels = ["front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel"]
    asm = Assembly(object="four-wheel cart", fuse=True, components=[
        # chassis FLOATS at ride height (grounding comes from the wheels touching the floor —
        # a `ground` mate here would drag it down and tear it off the ride-height axles)
        Component(name="chassis", role="body", at=(0.0, 0.0, ride + ct / 2), part=Spec(
            object="chassis", shape="box", envelope={"length": cl, "width": cw, "height": ct})),
        *[Component(name=a, role="support", part=Spec(
            object="axle", shape="cylinder", envelope={"diameter": ad, "height": al})) for a in axles],
        *[Component(name=w, role="other", part=Spec(
            object="wheel", shape="cylinder", envelope={"diameter": wd, "height": wt})) for w in wheels],
    ], mates=[
        Mate(kind="corners", parts=axles, around="chassis", dx=dxh, dy=dy_axle, axis="y", z=ride),
        Mate(kind="corners", parts=wheels, around="chassis", dx=dxh, dy=dy_wheel, axis="y"),
    ], joints=[Joint(a=w, b="chassis", axis="y", limits=(0, 360)) for w in wheels])
    brief = (f"A four-wheel cart: a {cl:.0f}×{cw:.0f}×{ct:.0f} mm chassis riding at wheel-center "
             f"height ({ride:g} mm), four ⌀{ad:.0f}×{al:.0f} mm stub axles welded into the chassis "
             f"sides at the corners (wheelbase {2 * dxh:.0f} mm), and four ⌀{wd:.0f}×{wt:.0f} mm "
             f"wheels seated on the axle tips, each spinning freely on its own revolute.")
    return "cart (axles + corner wheels + revolutes)", brief, asm


FAMILIES = [fam_stool, fam_table_shelf, fam_bolt_stack, fam_shaft_bearings,
            fam_hinge, fam_enclosure_pcb, fam_drone, fam_cart]


def _gate(asm: Assembly):
    """solve → (bounded repair for un-jointed) → verify; the report dict or None."""
    try:
        solved = solve_layout(asm.model_copy(deep=True))
        solved = repair_connectivity(solved)
        rep = verify_assembly(solved)
        return rep if rep["passed"] else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=60)
    ap.add_argument("--max-attempts", type=int, default=6)
    ap.add_argument("--out", default="corpus_out/batch7_assemblies.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    kept, rejects = [], []
    for fam in FAMILIES:
        got = attempts = 0
        seen = set()
        while got < a.per_family and attempts < a.per_family * a.max_attempts:
            attempts += 1
            category, brief, asm = fam(rng)
            sig = asm.model_dump_json()
            if sig in seen:
                continue
            seen.add(sig)
            rep = _gate(asm)
            if rep is None:
                rejects.append({"family": fam.__name__, "assembly": json.loads(sig)})
                continue
            kept.append({"category": category, "brief": brief,
                         "assembly": json.loads(asm.model_dump_json(exclude_none=True)),
                         "n_components": len(asm.components),
                         "has_joints": bool(asm.joints),
                         "report_categories": rep.get("failure_categories", [])})
            got += 1
        print(f"  {fam.__name__:22s} kept {got}/{attempts}", flush=True)

    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        for r in kept:
            f.write(json.dumps(r) + "\n")
    with open(a.out.replace(".jsonl", ".rejects.jsonl"), "w") as f:
        for r in rejects:
            f.write(json.dumps(r) + "\n")
    print(json.dumps({"out": a.out, "kept": len(kept), "rejected": len(rejects),
                      "jointed": sum(r["has_joints"] for r in kept),
                      "by_family": dict(Counter(r["category"] for r in kept))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
