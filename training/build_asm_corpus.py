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
import math
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
        # corners dx/dy are HALF-spacings (the cart's dxh convention): legs must land INSET inside
        # the top's footprint. The old full-span values (tl-lw-10) solved the legs ~2× outside the
        # top and only gated via repair_connectivity drag — training data poison (wrong dialect).
        asm = Assembly(object="four-leg table", components=[top, *legs], mates=[
            Mate(kind="corners", parts=[f"leg{i}" for i in range(4)], around="top",
                 dx=(tl - lw) / 2 - 5, dy=(tw - lw) / 2 - 5),
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


def _rotor_noun(rng, n: int) -> str:
    """Vocabulary variety — the OOD cliff was partly LEXICAL: the corpus only ever said 'drone
    frame', so 'quadcopter' (a dashboard suggested prompt!) fell off-distribution. Rotate the
    object noun through the words users actually type."""
    if n == 4:
        return rng.choice(["drone frame", "quadcopter frame", "quad frame",
                           "4-rotor multirotor frame", "UAV frame"])
    if n == 6:
        return rng.choice(["drone frame", "hexacopter frame", "6-rotor multirotor frame"])
    return "drone frame"


def fam_drone(rng) -> tuple:
    n = rng.choice([4, 4, 6])
    noun = _rotor_noun(rng, n)
    hd = round(rng.uniform(50, 80), 0); ht = round(rng.uniform(5, 9), 0)
    al = round(rng.uniform(60, 110), 0); aw = round(rng.uniform(10, 16), 0); at_ = round(rng.uniform(5, 8), 0)
    hub = Component(name="hub", role="hub", part=Spec(
        object="hub plate", shape="cylinder", envelope={"diameter": hd, "height": ht}))
    arms = [Component(name=f"arm{i}", role="arm", part=Spec(
        object="arm", shape="box", envelope={"length": al, "width": aw, "height": at_})) for i in range(n)]
    asm = Assembly(object=f"{n}-arm {noun}", components=[hub, *arms], mates=[
        Mate(kind="radial", parts=[f"arm{i}" for i in range(n)], around="hub", count=n,
             radius=round(hd / 2 + al / 2 - rng.uniform(6, 12), 0)),
    ], fuse=True)
    brief = (f"A {n}-arm {noun}: a round hub plate ⌀{hd:.0f}×{ht:.0f} mm with {n} rectangular "
             f"arms ({al:.0f}×{aw:.0f}×{at_:.0f} mm) radiating evenly from its rim, fused into one frame.")
    return "drone frame (radial arms)", brief, asm


def fam_quadcopter(rng) -> tuple:
    # HERO family (rung 3): the quad-test OOD cliff, answered with the shapes the representation
    # already supports but no family ever composed — a SHAPED profile_extrude center plate, tapered
    # loft arms, bolt-circle motor pads PARENTED at the arm tips (frame hierarchy), a standoff ring,
    # and a top plate stacked on the standoff group. Optionally a battery box flush underneath.
    n = rng.choice([4, 4, 4, 6])
    noun = _rotor_noun(rng, n)
    hub_r = round(rng.uniform(38, 60), 0); pt_ = round(rng.uniform(3.5, 6), 1)
    al = round(rng.uniform(70, 130), 0); aw = round(rng.uniform(12, 18), 0); ah = round(rng.uniform(6, 10), 0)
    awt = round(aw * rng.uniform(0.5, 0.7), 0); aht = round(ah * rng.uniform(0.6, 0.85), 0)
    pd = round(rng.uniform(22, 30), 0); pth = round(rng.uniform(3, 5), 1)     # motor pad ⌀ / thickness
    bc = round(pd * rng.uniform(0.55, 0.7), 0)                                # bolt-circle PCD
    hd_ = rng.choice([2.5, 3.0]); shaft = round(rng.uniform(5, 8), 0)         # bolt + shaft holes
    sod = round(rng.uniform(5, 8), 0); soh = round(rng.uniform(22, 40), 0)    # standoffs ⌀×h
    sink = round(rng.uniform(8, 14), 0)                                       # arm root buried in the plate rim
    # standoff ring must stay radially CLEAR of the arm roots (arms start at hub_r − sink; both
    # radial rings share phase 0, so a too-wide ring parks standoff k ON arm k — measured 45 mm³)
    sor = round(min(0.48 * hub_r, hub_r - sink - sod / 2 - 3), 0)
    tp_r = round(hub_r * rng.uniform(0.85, 1.0), 0); tpt = round(rng.uniform(3, 5), 1)

    if rng.random() < 0.7:      # shaped plate: a 2n-gon PHASE-ALIGNED to the arms, so every arm
        #                         meets a full-radius vertex dead-on (an 8-gon under 6 arms left
        #                         4 arms hanging where the outline dips — 5 islands, measured)
        pts = []
        for k in range(2 * n):
            r = hub_r if k % 2 == 0 else round(hub_r * 0.82, 1)
            a = math.pi * k / n
            pts.append([round(r * math.cos(a), 1), round(r * math.sin(a), 1)])
        plate_spec = Spec(object="center plate", shape="profile_extrude",
                          side_profile=[[-hub_r, 0], [hub_r, 0], [hub_r, pt_], [-hub_r, pt_]],
                          plan_profile=pts)
        plate_txt = (f"a shaped {'octagonal' if n == 4 else 'twelve-sided'} center plate "
                     f"({2 * hub_r:.0f} mm across, {pt_:g} mm thick)")
        plate_top = pt_ / 2          # profile_extrude solids are CENTERED on the origin
    else:
        plate_spec = Spec(object="center plate", shape="cylinder",
                          envelope={"diameter": 2 * hub_r, "height": pt_})
        plate_txt = f"a round center plate ⌀{2 * hub_r:.0f}×{pt_:g} mm"
        plate_top = pt_              # cylinders are BASE-origin — top face at full thickness

    arms = [Component(name=f"arm{i}", role="arm", part=Spec(
        object="arm", shape="loft", envelope={"length": al, "width": aw, "height": ah,
                                              "width_top": awt, "height_top": aht})) for i in range(n)]
    # motor pads ride the arm tips in the ARM's local frame (tip at +length/2; sections centered
    # in YZ): the pattern rotation carries each pad to its arm's angle — frame hierarchy, no
    # world coordinates. CYLINDERS ARE BASE-ORIGIN (the pcb-standoff convention): the local z is
    # the pad's UNDERSIDE — put it 1 mm below the tip half-height, which the ruled taper only
    # grows inboard, so the pad is sunk (welded) at any x along the tip.
    pads = [Component(name=f"motor_pad{i}", role="hub", parent=f"arm{i}",
                      at=(al / 2 - pd / 2, 0.0, aht / 2 - 1.0), part=Spec(
        object="motor pad", shape="cylinder", envelope={"diameter": pd, "height": pth},
        features=[{"type": "through_hole", "diameter": shaft},
                  {"type": "hole_pattern", "pattern": "bolt_circle", "count": 4,
                   "diameter": hd_, "pitch_diameter": bc}])) for i in range(n)]
    standoffs = [Component(name=f"standoff{i}", role="support", part=Spec(
        object="standoff", shape="cylinder", envelope={"diameter": sod, "height": soh}))
        for i in range(4)]
    top = Component(name="top_plate", role="top", part=Spec(
        object="top plate", shape="cylinder", envelope={"diameter": 2 * tp_r, "height": tpt}))

    # role 'hub', NOT 'base': a multirotor frame is a FREE frame (the drone-family precedent) —
    # 'base'/'leg' roles make the support row demand floor contact it shouldn't have.
    comps = [Component(name="bottom_plate", role="hub", part=plate_spec), *arms, *pads, *standoffs, top]
    mates = [
        Mate(kind="radial", parts=[f"arm{i}" for i in range(n)], around="bottom_plate", count=n,
             radius=round(hub_r + al / 2 - sink, 0)),
        # radial z sets the component `at` = a cylinder's BASE: 1 mm below the plate's top face
        # (plate_top is variant-aware — the two plate shapes have different z origins)
        Mate(kind="radial", parts=[f"standoff{i}" for i in range(4)], around="bottom_plate",
             count=4, radius=sor, z=round(plate_top - 1.0, 1)),
        Mate(kind="stack", a="top_plate", b="standoff0", overlap=1),
    ]
    bat_txt = ""
    if rng.random() < 0.35:
        bl = round(hub_r * 1.2, 0); bw = round(hub_r * 0.7, 0); bh = round(rng.uniform(12, 20), 0)
        comps.append(Component(name="battery_box", role="body", part=Spec(
            object="battery box", shape="box", envelope={"length": bl, "width": bw, "height": bh})))
        mates.append(Mate(kind="flush", a="battery_box", b="bottom_plate", side="-z", overlap=1))
        bat_txt = f", and a {bl:.0f}×{bw:.0f}×{bh:.0f} mm battery box slung flush under the plate"
    asm = Assembly(object=f"{n}-arm {noun}", components=comps, mates=mates, fuse=True)
    brief = (f"A {n}-arm {noun}: {plate_txt} with {n} tapered arms "
             f"({al:.0f} mm long, {aw:.0f}×{ah:.0f} mm at the root narrowing to {awt:.0f}×{aht:.0f} mm) "
             f"radiating from its rim, each tip carrying a ⌀{pd:.0f}×{pth:g} mm motor pad drilled "
             f"⌀{shaft:.0f} mm for the shaft with 4×⌀{hd_:g} mm on a {bc:.0f} mm bolt circle; four "
             f"⌀{sod:.0f}×{soh:.0f} mm standoffs on a {sor:.0f} mm ring carry a ⌀{2 * tp_r:.0f}×{tpt:g} mm "
             f"top plate{bat_txt}. One fused frame.")
    return "quadcopter (hero: shaped plate + pads + standoffs)", brief, asm


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


def fam_rack(rng) -> tuple:
    # the MID-HEIGHT dialect family (rung 2): shelves fixed PARTWAY UP corner posts via
    # stack+fraction — the z the eval said was inexpressible (a rack's middle shelf sits between
    # the group ends, not on top). Posts are role 'leg' (grounded, spread, statics-checked);
    # every shelf spans the post rectangle so it welds through all four posts (sanctioned).
    tiers = rng.choice([2, 2, 2, 3])
    sl = round(rng.uniform(150, 240), 0); sw = round(rng.uniform(90, 160), 0); st = round(rng.uniform(8, 14), 0)
    pw = round(rng.uniform(12, 20), 0); ph = round(rng.uniform(130, 230), 0)
    dx = round((sl - pw) / 2 - rng.uniform(4, 10), 1)      # posts INSET inside the shelf footprint
    dy = round((sw - pw) / 2 - rng.uniform(4, 10), 1)      # (corners dx/dy are HALF-spacings)
    fr_mid = round(rng.uniform(0.38, 0.62), 2)

    def shelf(nm):
        return Component(name=nm, role="top", part=Spec(
            object="shelf", shape="box", envelope={"length": sl, "width": sw, "height": st}))

    posts = [Component(name=f"post{i}", role="leg", part=Spec(
        object="post", shape="box", envelope={"length": pw, "width": pw, "height": ph})) for i in range(4)]
    comps = [*posts, shelf("top_shelf"), shelf("mid_shelf")]
    mates = [
        Mate(kind="corners", parts=[f"post{i}" for i in range(4)], around="top_shelf", dx=dx, dy=dy),
        Mate(kind="stack", a="top_shelf", b="post0", overlap=3),
        Mate(kind="stack", a="mid_shelf", b="post0", fraction=fr_mid),
    ]
    mid_txt = ("about halfway up the posts" if 0.45 <= fr_mid <= 0.55
               else f"{round(fr_mid * 100):g}% of the way up the posts")
    low_txt = ""
    if tiers == 3:
        fr_low = round(rng.uniform(0.10, 0.24), 2)
        comps.append(shelf("low_shelf"))
        mates.append(Mate(kind="stack", a="low_shelf", b="post0", fraction=fr_low))
        low_txt = f", plus a low shelf at {round(fr_low * 100):g}% of the post height"
    asm = Assembly(object=f"{'three' if tiers == 3 else 'two'}-tier rack",
                   components=comps, mates=mates, fuse=True)
    brief = (f"A {'three' if tiers == 3 else 'two'}-tier storage rack: four {pw:.0f} mm square posts "
             f"{ph:.0f} mm tall at the corners of a {sl:.0f}×{sw:.0f} mm footprint, a "
             f"{sl:.0f}×{sw:.0f}×{st:.0f} mm top shelf resting on the post tops, and a middle shelf "
             f"fixed {mid_txt}{low_txt}, all fused into one frame.")
    return "rack (posts + mid-height shelves)", brief, asm


FAMILIES = [fam_stool, fam_table_shelf, fam_bolt_stack, fam_shaft_bearings,
            fam_hinge, fam_enclosure_pcb, fam_drone, fam_cart, fam_rack, fam_quadcopter]


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
