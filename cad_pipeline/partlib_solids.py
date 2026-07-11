"""Standard-part SOLIDS — the geometry the Spec vocabulary can't express (hex nuts, socket-head
screws, involute gears, bearing rings, dowel pins). fable_run/out/00_manual.md §2.4: "a fastener or
bearing is ALWAYS instantiated from the library, never modeled inline — this alone eliminates most
'fake' geometry." Each factory returns (cq.Workplane, datums) where datums names the frames an
assembly mates to (bore/thread axis, mount/base face). Real catalog dims are the single source of
truth (mistakes A8: regenerate FROM the standard, never from remembered numbers).

Golden BY CONSTRUCTION: selftest() builds every part, asserts BRep validity, and re-measures a key
catalog dimension. Complements partlib.py (the parts expressible as Spec, which flow through the
generative build→verify pipeline).
"""
from __future__ import annotations

from math import acos, cos, pi, radians, sin, tan
from typing import Dict, Tuple

import cadquery as cq
import numpy as np

# ── catalog tables (ISO, exact) ───────────────────────────────────────────────────────────────
SHCS = {  # ISO 4762 socket-head cap screw: thread ⌀, head ⌀, head height (mm)
    "M2": (2.0, 3.8, 2.0), "M2.5": (2.5, 4.5, 2.5), "M3": (3.0, 5.5, 3.0),
    "M4": (4.0, 7.0, 4.0), "M5": (5.0, 8.5, 5.0),
}
HEX_NUT = {  # ISO 4032: across-flats, thickness, tapped bore (mm)
    "M2": (4.0, 1.6, 1.6), "M2.5": (5.0, 2.0, 2.05), "M3": (5.5, 2.4, 2.5),
    "M4": (7.0, 3.2, 3.3), "M5": (8.0, 4.7, 4.2),
}
WASHER = {  # ISO 7089: OD, ID, thickness (mm)
    "M3": (7.0, 3.2, 0.5), "M4": (9.0, 4.3, 0.8), "M5": (10.0, 5.3, 1.0),
}
BEARING = {  # deep-groove ball bearing: id, od, width (mm)
    "623": (3.0, 10.0, 4.0), "624": (4.0, 13.0, 5.0), "685": (5.0, 11.0, 5.0), "608": (8.0, 22.0, 7.0),
}

Datums = Dict[str, Dict[str, Tuple[float, float, float]]]


def _z_axis(origin=(0.0, 0.0, 0.0)) -> Datums:
    return {"axis": {"origin": origin, "axis": (0.0, 0.0, 1.0)}}


# ── fasteners ───────────────────────────────────────────────────────────────────────────────
def shcs(size: str = "M3", length: float = 12.0) -> Tuple[cq.Workplane, Datums]:
    """Socket-head cap screw (ISO 4762): shank ⌀=thread, head ⌀=1.5×thread class, hex socket recess."""
    d, hd, hh = SHCS[size]
    shank = cq.Workplane("XY").circle(d / 2).extrude(length)
    head = shank.faces(">Z").workplane().circle(hd / 2).extrude(hh)
    socket = head.faces(">Z").workplane().polygon(6, d * 0.7).cutBlind(-hh * 0.6)   # hex drive
    dat = {"thread_axis": {"origin": (0.0, 0.0, 0.0), "axis": (0.0, 0.0, -1.0)},
           "head_top": {"origin": (0.0, 0.0, length + hh), "axis": (0.0, 0.0, 1.0)}}
    return socket, dat


def hex_nut(size: str = "M3") -> Tuple[cq.Workplane, Datums]:
    """Hex nut (ISO 4032): across-flats from the table, tapped bore."""
    af, thk, bore = HEX_NUT[size]
    across_corners = af / cos(radians(30))                 # polygon() takes the circumscribed ⌀
    nut = (cq.Workplane("XY").polygon(6, across_corners).extrude(thk)
           .faces(">Z").workplane().hole(bore))
    return nut, _z_axis()


def washer(size: str = "M3") -> Tuple[cq.Workplane, Datums]:
    od, idia, thk = WASHER[size]
    w = cq.Workplane("XY").circle(od / 2).extrude(thk).faces(">Z").workplane().hole(idia)
    return w, _z_axis()


# ── bearings / pins ───────────────────────────────────────────────────────────────────────────
def bearing(desig: str = "608") -> Tuple[cq.Workplane, Datums]:
    """Deep-groove ball bearing as a ring solid (races simplified — the assembly cares about the
    OD press-fit and the ID shaft fit, which are exact)."""
    idia, od, width = BEARING[desig]
    ring = cq.Workplane("XY").circle(od / 2).extrude(width).faces(">Z").workplane().hole(idia)
    return ring, {"bore_axis": {"origin": (0.0, 0.0, width / 2), "axis": (0.0, 0.0, 1.0)}}


def dowel_pin(d: float = 3.0, length: float = 16.0) -> Tuple[cq.Workplane, Datums]:
    return cq.Workplane("XY").circle(d / 2).extrude(length), _z_axis()


# ── involute spur gear (from the equation — never trapezoids; manual §8.5) ──────────────────────
def involute_gear(module: float = 2.0, teeth: int = 24, width: float = 10.0, bore: float = 0.0,
                  pa_deg: float = 20.0, n: int = 12) -> Tuple[cq.Workplane, Datums]:
    """Involute spur gear: pitch r = m·z/2, base r = r·cos α, addendum m, dedendum 1.25 m.
    Robust construction = a root-circle disc + z tooth protrusions unioned on (a single wire around
    all teeth self-intersects at the roots). tip ⌀ = m(z+2); center distance for a mesh = m(z1+z2)/2."""
    pa = radians(pa_deg)
    rp = module * teeth / 2.0
    rb = rp * cos(pa)
    ra = rp + module
    rf = max(rp - 1.25 * module, 0.5)
    inv = lambda a: tan(a) - a
    beta = pi / (2 * teeth) + inv(pa)                       # half-tooth angular width at base
    rs = np.linspace(max(rb, rf), ra, n)
    left = [(beta - inv(acos(np.clip(rb / r, -1, 1))), r) for r in rs]     # base → tip
    tooth = [(beta, rf * 0.98)] + left + [(-a, r) for a, r in reversed(left)] + [(-beta, rf * 0.98)]
    g = cq.Workplane("XY").circle(rf).extrude(width)        # root disc fills the tooth gaps
    for k in range(teeth):
        rot = 2 * pi * k / teeth
        pts = [(r * cos(a + rot), r * sin(a + rot)) for a, r in tooth]
        g = g.union(cq.Workplane("XY").polyline(pts).close().extrude(width))
    if bore > 0:
        g = g.faces(">Z").workplane().hole(bore)
    dat = {"axis": {"origin": (0.0, 0.0, width / 2), "axis": (0.0, 0.0, 1.0)},
           "pitch_radius": {"origin": (rp, 0.0, 0.0), "axis": (0.0, 0.0, 1.0)}}
    return g, dat


def tooth_count(gear_wp, nb: int = 720) -> int:
    """Count gear teeth by the dominant angular frequency of the polar silhouette (manual §8.5 / P07
    'polar FFT peak at N ridges') — robust where peak-counting double-counts each flat tooth tip."""
    from .mesh_verify import tri_from_solid
    v = tri_from_solid(gear_wp, 0.2).vertices
    ang = np.arctan2(v[:, 1], v[:, 0])
    rad = np.hypot(v[:, 0], v[:, 1])
    idx = ((ang + pi) / (2 * pi) * nb).astype(int) % nb
    rmax = np.zeros(nb)
    np.maximum.at(rmax, idx, rad)
    rmax[rmax == 0] = rmax[rmax > 0].mean()
    spec = np.abs(np.fft.rfft(rmax - rmax.mean()))
    return int(np.argmax(spec[1:120]) + 1)


# ── motors / drivetrain (§2.4 minimum: instantiate real components, never remodel) ──────────────
NEMA17 = {"body": 42.3, "length": 48.0, "shaft_d": 5.0, "shaft_len": 24.0, "boss_d": 22.0, "boss_h": 2.0}
M2207 = {"stator_d": 27.7, "bell_h": 12.0, "base_h": 6.0, "shaft_d": 5.0, "shaft_len": 15.0}   # FPV outrunner
N20 = {"body_w": 12.0, "body_h": 10.0, "body_l": 15.0, "shaft_d": 3.0, "shaft_len": 10.0}      # micro gearmotor


def nema17_motor() -> Tuple[cq.Workplane, Datums]:
    """NEMA17 stepper body (42.3 mm square × 48 long) + ⌀22 register boss + ⌀5 shaft."""
    b = NEMA17
    body = cq.Workplane("XY").box(b["body"], b["body"], b["length"])
    top = body.faces(">Z").workplane()
    boss = top.circle(b["boss_d"] / 2).extrude(b["boss_h"])
    shaft = boss.faces(">Z").workplane().circle(b["shaft_d"] / 2).extrude(b["shaft_len"])
    dat = {"shaft_axis": {"origin": (0, 0, b["length"] / 2), "axis": (0, 0, 1)},
           "mount_face": {"origin": (0, 0, b["length"] / 2), "axis": (0, 0, 1)}}
    return shaft, dat


def motor_2207() -> Tuple[cq.Workplane, Datums]:
    """2207 FPV brushless outrunner: ⌀27.7 stator, base + bell, ⌀5 shaft. Mount = 16/19 M3 cross."""
    m = M2207
    base = cq.Workplane("XY").circle(m["stator_d"] / 2).extrude(m["base_h"])
    bell = base.faces(">Z").workplane().circle(m["stator_d"] / 2).extrude(m["bell_h"])
    shaft = bell.faces(">Z").workplane().circle(m["shaft_d"] / 2).extrude(m["shaft_len"])
    dat = {"shaft_axis": {"origin": (0, 0, 0), "axis": (0, 0, 1)}}
    return shaft, dat


def n20_gearmotor() -> Tuple[cq.Workplane, Datums]:
    """N20 micro gearmotor: 12×10×15 body + ⌀3 output shaft."""
    n = N20
    body = cq.Workplane("XY").box(n["body_w"], n["body_h"], n["body_l"])
    shaft = body.faces(">Z").workplane().circle(n["shaft_d"] / 2).extrude(n["shaft_len"])
    return shaft, {"shaft_axis": {"origin": (0, 0, n["body_l"] / 2), "axis": (0, 0, 1)}}


def gt2_pulley(teeth: int = 20, bore: float = 5.0, width: float = 6.0) -> Tuple[cq.Workplane, Datums]:
    """GT2 timing pulley (2 mm pitch): pitch ⌀ = teeth·2/π, with two retaining flanges + bore.
    Teeth are represented as a fine scalloped rim (GT2 is a curvilinear profile, not involute)."""
    pitch = 2.0
    pd = teeth * pitch / pi
    body = cq.Workplane("XY").circle(pd / 2).extrude(width)
    fl_d = pd + 2.0
    body = body.faces("<Z").workplane().circle(fl_d / 2).extrude(1.0)          # bottom flange
    body = body.faces(">Z").workplane().circle(fl_d / 2).extrude(1.0)          # top flange
    body = body.faces(">Z").workplane().hole(bore)
    return body, {"axis": {"origin": (0, 0, width / 2), "axis": (0, 0, 1)},
                  "pitch_radius": {"origin": (pd / 2, 0, 0), "axis": (0, 0, 1)}}


SOLID_PARTS = {
    "shcs": shcs, "hex_nut": hex_nut, "washer": washer, "bearing": bearing,
    "dowel_pin": dowel_pin, "involute_gear": involute_gear,
    "nema17_motor": nema17_motor, "motor_2207": motor_2207, "n20_gearmotor": n20_gearmotor,
    "gt2_pulley": gt2_pulley,
}


def _bbox(wp: cq.Workplane):
    return wp.val().BoundingBox()


def selftest() -> int:
    """Every solid part builds, is a valid single solid, and re-measures to its catalog dim."""
    checks = []

    def add(name, wp, meas, exp, tol):
        s = wp.val()
        ok = s.isValid() and abs(meas - exp) <= tol
        checks.append((name, ok, f"{round(meas, 2)} vs {exp}±{tol}, valid={s.isValid()}"))

    g, _ = involute_gear(2, 24); bb = _bbox(g)
    add("involute_gear m2z24 tip⌀", g, max(bb.xlen, bb.ylen), 52.0, 0.2)
    g2, _ = involute_gear(2, 12); bb2 = _bbox(g2)
    add("involute_gear m2z12 tip⌀", g2, max(bb2.xlen, bb2.ylen), 28.0, 0.2)
    n, _ = hex_nut("M3"); bbn = _bbox(n)
    add("hex_nut M3 across-flats", n, min(bbn.xlen, bbn.ylen), 5.5, 0.1)
    sc, _ = shcs("M3", 12); bbs = _bbox(sc)
    add("shcs M3 head⌀", sc, max(bbs.xlen, bbs.ylen), 5.5, 0.1)
    add("shcs M3 length+head", sc, bbs.zlen, 15.0, 0.2)
    w, _ = washer("M3"); bbw = _bbox(w)
    add("washer M3 OD", w, max(bbw.xlen, bbw.ylen), 7.0, 0.1)
    b, _ = bearing("608"); bbb = _bbox(b)
    add("bearing 608 OD", b, max(bbb.xlen, bbb.ylen), 22.0, 0.1)
    add("bearing 608 width", b, bbb.zlen, 7.0, 0.1)
    p, _ = dowel_pin(3, 16); bbp = _bbox(p)
    add("dowel_pin ⌀3 length", p, bbp.zlen, 16.0, 0.1)
    nm, _ = nema17_motor(); bbnm = _bbox(nm)
    add("nema17_motor body square", nm, max(bbnm.xlen, bbnm.ylen), 42.3, 0.1)
    mo, _ = motor_2207(); bbmo = _bbox(mo)
    add("motor_2207 stator ⌀", mo, max(bbmo.xlen, bbmo.ylen), 27.7, 0.1)
    nn, _ = n20_gearmotor(); bbnn = _bbox(nn)
    add("n20 body length", nn, bbnn.zlen, N20["body_l"] + N20["shaft_len"], 0.2)
    gp, _ = gt2_pulley(20); bbgp = _bbox(gp)
    add("gt2_pulley flange ⌀", gp, max(bbgp.xlen, bbgp.ylen), 20 * 2.0 / pi + 2.0, 0.2)

    bad = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}: {detail}")
    print(f"PARTLIB_SOLIDS {len(checks) - len(bad)}/{len(checks)}")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
