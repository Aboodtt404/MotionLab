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
]

# dense / extreme geometry — the near-tangent-boolean robustness probe (Stage C).
STRESS = [
    ("cyl dense+raised", "cylinder", {"diameter": 120, "height": 200}, dict(panel=8,  density=0.9, depth=3, raised=0.4)),
    ("cyl thin tall",    "cylinder", {"diameter": 40,  "height": 300}, dict(panel=10, density=0.85)),
    ("cyl wide short",   "cylinder", {"diameter": 300, "height": 60},  dict(panel=12, density=0.8, focal="center")),
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


def main() -> int:
    print("GREEBLE — golden (box + cylinder):")
    g_ok = sum(_check(lbl, _greeble(sh, env, **gp)) for lbl, sh, env, gp in CASES)
    print("GREEBLE — robustness stress (dense curved-face booleans):")
    s_ok = sum(_check(lbl, _greeble(sh, env, **gp)) for lbl, sh, env, gp in STRESS)
    total = len(CASES) + len(STRESS); ok = g_ok + s_ok
    print(f"\nGREEBLE {ok}/{total}  (golden {g_ok}/{len(CASES)} · stress {s_ok}/{len(STRESS)})")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
