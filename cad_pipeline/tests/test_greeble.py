"""Greeble feature test — the procedural hard-surface detail pass (greeble-detail-research.md).

Covers BOX top-face (Stage A/B) and CYLINDER side-face (Stage C) greebling. Each case asserts:
  • build → verify PASSES, the solid is VALID and a SINGLE solid,
  • detail was actually cut (the `greeble · detail` row is green),
  • DETERMINISM — same seed ⇒ identical volume across two builds,
  • EMIT-ROUNDTRIP — emit_code() exec'd reproduces the same volume (build == emit).
Plus a ROBUSTNESS STRESS (the Stage-C risk): dense radial cuts on a curved face — near-tangent
booleans — must stay a single valid solid (proves the fuzzy-tol + deferred-clean path holds).

Run:  python -m cad_pipeline.tests.test_greeble
"""
from __future__ import annotations

import sys

import cadquery as cq
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from ..builder import build, emit_code
from ..spec import Spec
from ..verifier import verify


def _vol(solid) -> float:
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid.val().wrapped, g)
    return g.Mass()


def _greeble(shape: str, env: dict, **gp) -> Spec:
    face = "side" if shape == "cylinder" else "top"
    return Spec(object="greeble case", shape=shape, envelope=env,
                features=[{"type": "greeble", "face": face, **gp}])


# (label, shape, envelope, greeble params)
CASES = [
    ("box panel",        "box",      {"length": 200, "width": 120, "height": 15}, dict(panel=32, depth=2, density=0.5)),
    ("box plating",      "box",      {"length": 250, "width": 100, "height": 18}, dict(panel=18, depth=3, density=0.8)),
    ("cyl fuel tank",    "cylinder", {"diameter": 120, "height": 200},            dict(panel=40, depth=3, density=0.6)),
    ("cyl pod (edges)",  "cylinder", {"diameter": 80,  "height": 120},            dict(panel=30, density=0.5, focal="edges")),
    ("cyl hull tube",    "cylinder", {"diameter": 150, "height": 250},            dict(panel=18, depth=3, density=0.8)),
    ("box beveled",      "box",      {"length": 200, "width": 120, "height": 15}, dict(panel=40, depth=3, density=0.6, bevel=1.0)),
    ("cyl beveled",      "cylinder", {"diameter": 120, "height": 200},            dict(panel=40, depth=3, density=0.6, bevel=1.0)),
]

# dense / extreme geometry — the near-tangent-boolean robustness probe (Stage C).
STRESS = [
    ("cyl dense+raised", "cylinder", {"diameter": 120, "height": 200}, dict(panel=8,  density=0.9, depth=3, raised=0.4)),
    ("cyl thin tall",    "cylinder", {"diameter": 40,  "height": 300}, dict(panel=10, density=0.85)),
    ("cyl wide short",   "cylinder", {"diameter": 300, "height": 60},  dict(panel=12, density=0.8, focal="center")),
]

# revolve (turned bodies) + loft (tapered bar) — Stage C curved/tilted faces. Built as explicit Specs
# (they need a profile / top dims). (label, spec).
CURVED = [
    ("rev nozzle", Spec(object="nozzle", shape="revolve", envelope={"angle": 360.0},
                        profile=[[40, 0], [40, 40], [25, 90], [25, 120]],
                        features=[{"type": "greeble", "face": "side", "panel": 30, "depth": 3, "density": 0.6}])),
    ("rev tank+dome", Spec(object="tank", shape="revolve", envelope={"angle": 360.0},
                          profile=[[0, 0], [50, 0], [50, 120], [35, 160], [0, 175]],
                          features=[{"type": "greeble", "face": "side", "panel": 35, "depth": 4, "density": 0.7, "focal": "center"}])),
    ("rev stepped+bevel", Spec(object="stepped", shape="revolve", envelope={"angle": 360.0},
                              profile=[[30, 0], [30, 50], [45, 50], [45, 100]],
                              features=[{"type": "greeble", "panel": 25, "density": 0.8, "bevel": 1.0}])),
    ("loft bar", Spec(object="arm", shape="loft",
                      envelope={"length": 160, "width": 60, "height": 40, "width_top": 30, "height_top": 20},
                      features=[{"type": "greeble", "panel": 28, "depth": 3, "density": 0.7}])),
]


def _check(label: str, spec: Spec) -> bool:
    s = build(spec)
    rep = verify(s, spec)
    d = rep.to_dict()
    passed = d["passed"]
    single = rep.solids == 1 and rep.valid
    detail = any(r["name"] == "greeble · detail" and r["within_tol"] for r in d["rows"])
    det = abs(_vol(s) - _vol(build(spec))) < 1e-6                      # determinism
    ns = {"cq": cq}; exec(emit_code(spec), ns)                        # noqa: S102 — golden roundtrip
    emit = abs(_vol(s) - _vol(ns["result"])) < 1e-3
    ok = passed and single and detail and det and emit
    flag = "ok " if ok else "FAIL"
    print(f"  [{flag}] {label:18s} passed={passed} solid={single} detail={detail} det={det} emit={emit}")
    return ok


def _sweep_noop() -> bool:
    """greeble on a SWEEP is a documented no-op (deferred) — it must still BUILD a valid solid, not crash."""
    spec = Spec(object="tube", shape="sweep", envelope={"diameter": 16},
                path=[[0, 0, 0], [0, 0, 60], [40, 0, 90]],
                features=[{"type": "greeble", "panel": 20, "density": 0.6}])
    try:
        rep = verify(build(spec), spec)
        ok = rep.valid and rep.solids == 1
    except Exception as e:  # noqa: BLE001
        ok = False; print(f"    sweep+greeble raised {type(e).__name__}: {e}")
    print(f"  [{'ok ' if ok else 'FAIL'}] sweep+greeble no-op builds a valid solid")
    return ok


def _greebled_assembly() -> bool:
    """Greebled parts must survive placement + fuse + seam-blend as ONE valid solid (planner can now put
    greeble on assembly parts) — non-gated (no model)."""
    from ..assembly import Assembly, Component, verify_assembly
    hull = Spec(object="hull", shape="box", envelope={"length": 100, "width": 60, "height": 24},
                features=[{"type": "greeble", "panel": 28, "density": 0.6, "bevel": 0.8}])
    pod = Spec(object="pod", shape="box", envelope={"length": 60, "width": 40, "height": 20},
               features=[{"type": "greeble", "panel": 20, "density": 0.7}])
    asm = Assembly(object="ship", fuse=True, fillet_joints=2.0,
                   components=[Component(name="hull", part=hull),
                               Component(name="pod", part=pod, at=(75, 0, 0))])   # 10mm overlap
    rep = verify_assembly(asm)
    ok = rep["passed"] and rep["solids"] == 1
    print(f"  [{'ok ' if ok else 'FAIL'}] greebled parts fuse to one valid solid (solids={rep['solids']})")
    return ok


def main() -> int:
    print("GREEBLE — golden (box + cylinder):")
    g_ok = sum(_check(lbl, _greeble(sh, env, **gp)) for lbl, sh, env, gp in CASES)
    print("GREEBLE — curved/tilted bodies (revolve + loft):")
    c_ok = sum(_check(lbl, spec) for lbl, spec in CURVED)
    print("GREEBLE — robustness stress (dense curved-face booleans):")
    s_ok = sum(_check(lbl, _greeble(sh, env, **gp)) for lbl, sh, env, gp in STRESS)
    print("GREEBLE — sweep no-op (deferred shape):")
    n_ok = int(_sweep_noop())
    print("GREEBLE — in an assembly (planner can greeble hero parts):")
    a_ok = int(_greebled_assembly())
    total = len(CASES) + len(CURVED) + len(STRESS) + 2; ok = g_ok + c_ok + s_ok + n_ok + a_ok
    print(f"\nGREEBLE {ok}/{total}  (golden {g_ok}/{len(CASES)} · curved {c_ok}/{len(CURVED)} · "
          f"stress {s_ok}/{len(STRESS)} · sweep-noop {n_ok}/1 · assembly {a_ok}/1)")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
