"""Render→VLM greeble-critique smoke test (Stage C). GATED on the vLLM server at :8002 (skips if down,
like eval_baseline) — the VLM verdict is non-deterministic, so we assert STRUCTURE + BOUNDEDNESS +
VALIDITY, not an exact judgement:
  • render_views produces non-empty PNGs,
  • critique() returns a known verdict + a suggest dict whose values are in range,
  • refine() on a deliberately-uniform greeble applies only in-range changes and keeps the solid valid.

Run:  python -m cad_pipeline.tests.test_critique
"""
from __future__ import annotations

import sys
import urllib.request

from ..builder import build
from ..spec import Spec
from ..verifier import verify

_VERDICTS = {"good", "too_uniform", "too_sparse", "too_busy", "noisy", "error"}
_FOCAL = {"none", "center", "edges"}


def _up(url: str = "http://localhost:8002/v1/models") -> bool:
    try:
        urllib.request.urlopen(url, timeout=3); return True
    except Exception:  # noqa: BLE001
        return False


def _uniform_spec() -> Spec:
    # the BAD case: a flat uniform blanket (no focal, no hierarchy, no raises) — should read as too_uniform
    return Spec(object="hull panel", shape="box", envelope={"length": 220, "width": 140, "height": 18},
                features=[{"type": "greeble", "panel": 28, "depth": 2, "density": 1.0,
                           "focal": "none", "levels": 1, "raised": 0.0}])


def _in_range(g, s: dict) -> bool:
    dim = min(g_env["length"], g_env["width"])  # noqa: F821 — set below
    ok = True
    if "density" in s: ok &= 0.05 <= s["density"] <= 1.0
    if "focal" in s: ok &= s["focal"] in _FOCAL
    if "depth" in s: ok &= 0.5 <= s["depth"] <= 0.4 * dim + 1e-6
    if "panel" in s: ok &= 6.0 <= s["panel"] <= dim + 1e-6
    if "bevel" in s: ok &= 0.0 <= s["bevel"] <= 0.3 * g.depth + 0.6
    return ok


def main() -> int:
    from ..render import render_views
    if not _up():
        print("SKIP test_critique — vLLM :8002 is down (gated, like eval_baseline)"); return 0
    from ..critique import critique, refine
    global g_env
    spec = _uniform_spec(); g_env = spec.envelope
    solid = build(spec)

    pngs = render_views(solid, n=2)
    r_ok = len(pngs) == 2 and all(len(p) > 1000 for p in pngs)
    print(f"  [{'ok ' if r_ok else 'FAIL'}] render_views → {len(pngs)} PNGs {[len(p) for p in pngs]}")

    c = critique(spec, solid)
    g = next(f for f in spec.features if f.type == "greeble")
    c_ok = c["verdict"] in _VERDICTS and isinstance(c.get("suggest"), dict) and _in_range(g, c["suggest"])
    print(f"  [{'ok ' if c_ok else 'FAIL'}] critique verdict={c['verdict']} suggest={c.get('suggest')} :: {c.get('notes','')[:60]}")

    rspec, hist = refine(spec, rounds=2)
    rg = next(f for f in rspec.features if f.type == "greeble")
    rep = verify(build(rspec), rspec)
    bounded = (0.05 <= rg.density <= 1.0 and rg.focal in _FOCAL and 0.5 <= rg.depth <= 0.4 * min(g_env["length"], g_env["width"]) + 1e-6)
    f_ok = len(hist) >= 1 and rep.valid and rep.solids == 1 and bounded
    print(f"  [{'ok ' if f_ok else 'FAIL'}] refine {len(hist)} rounds → density={rg.density} focal={rg.focal} depth={rg.depth} valid={rep.valid} solids={rep.solids}")

    ok = sum((r_ok, c_ok, f_ok))
    print(f"\nCRITIQUE {ok}/3")
    return 0 if ok == 3 else 1


if __name__ == "__main__":
    sys.exit(main())
