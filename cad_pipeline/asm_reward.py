"""Shaped GRPO reward for the ASSEMBLY task — graded verifier signal, not a binary gate.

Why shaped (assembly-placement research 2026-07-21, arXiv:2606.31252 measured): GRPO with a
binary solver/verifier reward stalled — 68.3% of candidate groups had IDENTICAL rewards, so
there was no within-group variance to learn from. The learning signal IS the difference
between a 15/18 assembly with 3 islands and a 17/18 with one 200 mm³ overlap; a pass/fail
reward maps both (and garbage) to the same number.

    R = R_parse · (W_ROWS · rows_frac  +  W_CONN · 1/islands  +  W_INTF · interference_decay)

- R_parse ∈ {0,1} — completion must contain a pydantic-valid Assembly JSON. Malformed → 0
  (multiplicative mask, same as the part reward's exec gate).
- rows_frac — the verifier's within_tol fraction: the dense workhorse (connectivity, validity,
  grounding, statics, cutouts, kinematics all contribute distinct gradients).
- 1/islands — 1 connected solid → 1.0, 2 islands → 0.5, 3 → 0.33: the desk-failure axis.
- interference_decay = 1/(1 + log10(1 + worst_mm3)) — 0 mm³ → 1.0, 1 mm³ → 0.77, 1 cm³ → 0.25,
  a liter → 0.14: overlap severity becomes gradient instead of a cliff.
- A parsed-but-unbuildable assembly scores a small floor above zero: "valid JSON, dead geometry"
  must rank above "not even JSON" or the format lesson is lost.

Subprocess bridge (GRPO trainer runs in serve_venv, no cadquery):
    echo '{"output": "..."}' | cad_pipeline/.venv/bin/python -m cad_pipeline.asm_reward
Self-test:  cad_pipeline/.venv/bin/python -m cad_pipeline.asm_reward --selftest
"""
from __future__ import annotations

import json
import re
import sys

from .assembly import Assembly, repair_connectivity, solve_layout, verify_assembly

W_ROWS, W_CONN, W_INTF = 0.5, 0.25, 0.25
BUILD_FAIL_FLOOR = 0.05
# --- the GRPO-run-2 lesson (measured 2026-08-01): partial credit is NOT the gate ---------------
# Run 2 trained cleanly on the reward above and REGRESSED the eval 6/10 -> 3/10, with a brand-new
# dominant failure class: component-fix 0 -> 12 (parts whose own features don't materialise, e.g.
# "holes count measured 0 vs spec 4"). Cause: a part-level failure moved exactly ONE row of ~6-11
# (~8% of reward) while being FATAL to the real gate, so the policy drifted into the reward's
# blind spot while still scoring 0.5-0.76. Textbook Goodhart: it optimised the proxy, and the
# proxy said "more green rows" where the verifier says "ALL rows green".
# Two corrections, both aligning proxy with gate while KEEPING the dense shaping that fixed the
# original stall:
COMP_FAIL_MULT = 0.4   # any component failing its OWN verify costs 60% — not one row
PASS_BONUS = 0.5       # a FULL pass outranks every near-miss (cliff at the true gate)


def _extract_json(text: str) -> dict | None:
    """First balanced {...} block — completions may fence or preamble the JSON."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:  # noqa: BLE001
                        break
        start = text.find("{", start + 1)
    return None


def _interference_decay(worst_mm3: float) -> float:
    import math
    return 1.0 / (1.0 + math.log10(1.0 + max(0.0, worst_mm3)))


def score_assembly(asm: Assembly) -> dict:
    """Shaped score for an already-parsed Assembly. Never raises."""
    try:
        solved = repair_connectivity(solve_layout(asm))
        rep = verify_assembly(solved)
    except Exception as e:  # noqa: BLE001 — dead geometry is a data point, not a crash
        return {"reward": BUILD_FAIL_FLOOR, "rows_frac": 0.0, "islands": None,
                "worst_mm3": None, "error": f"build: {type(e).__name__}: {e}"[:120]}
    return score_report(rep)


def score_report(rep: dict) -> dict:
    """Verifier report -> shaped reward. Split out from score_assembly so the gates are
    unit-testable on synthetic reports (the builder clamps most bad geometry, so a
    locally-failing part is hard to construct but trivial to describe)."""
    rows = rep.get("rows", [])
    rows_frac = (sum(1 for r in rows if r.get("within_tol")) / len(rows)) if rows else 0.0

    islands = 1
    worst = 0.0
    for r in rows:
        name = str(r.get("name", ""))
        if "connectivity" in name or "part count" in name:
            try:
                measured, expected = float(r.get("measured", 1)), 1.0
                exp_raw = str(r.get("expected", "1"))
                expected = float(re.sub(r"[^\d.]", "", exp_raw) or 1)
                islands = max(1, int(round(measured - expected + 1)))
            except Exception:  # noqa: BLE001
                islands = 1 if r.get("within_tol") else 2
        if "interference" in name:
            try:
                worst = max(worst, float(r.get("measured", 0)))
            except Exception:  # noqa: BLE001
                worst = worst if r.get("within_tol") else max(worst, 1000.0)

    r_conn = 1.0 / islands
    r_intf = _interference_decay(worst)
    shaped = W_ROWS * rows_frac + W_CONN * r_conn + W_INTF * r_intf
    # component gate: the eval treats ANY locally-failing part as fatal, so the reward must too
    comps = rep.get("components", [])
    comp_ok = all(c.get("passed") for c in comps) if comps else True
    reward = shaped * (1.0 if comp_ok else COMP_FAIL_MULT)
    if rep.get("passed"):
        reward += PASS_BONUS
    return {"reward": round(reward, 4), "rows_frac": round(rows_frac, 4),
            "islands": islands, "worst_mm3": round(worst, 1),
            "r_conn": round(r_conn, 4), "r_intf": round(r_intf, 4),
            "comp_ok": comp_ok, "passed": bool(rep.get("passed"))}


def reward(output: str) -> dict:
    """Completion text → shaped reward. Any parse failure → 0.0 (masked)."""
    payload = _extract_json(output)
    if payload is None:
        return {"reward": 0.0, "error": "no JSON object in completion"}
    try:
        asm = Assembly.model_validate(payload)
    except Exception as e:  # noqa: BLE001
        return {"reward": 0.0, "error": f"schema: {type(e).__name__}"[:120]}
    return score_assembly(asm)


def _selftest() -> int:
    from .spec import Spec

    def box(name, l, w, h, at=(0, 0, 0), role="other"):
        from .assembly import Component
        return Component(name=name, role=role, at=at,
                         part=Spec(shape="box", envelope={"length": l, "width": w, "height": h}))

    from .assembly import Component, Mate  # noqa: F401
    legs = lambda: [box(f"leg{i+1}", 16, 16, 110, role="leg") for i in range(4)]  # noqa: E731
    good = Assembly(object="stool", components=[box("seat", 140, 140, 16, role="seat")] + legs(), mates=[
        Mate(kind="radial", parts=[f"leg{i+1}" for i in range(4)], around="seat", count=4, radius=52),
        Mate(kind="stack", a="seat", b="leg1", overlap=4)])
    islanded = Assembly(object="scatter", components=[
        box("a", 30, 30, 10, role="base"), box("b", 30, 30, 10, at=(300, 300, 0)),
        box("c", 30, 30, 10, at=(-300, -300, 0))], mates=[Mate(kind="ground", a="a")])
    overlapped = Assembly(object="clash", components=[
        box("a", 40, 40, 20, role="base"), box("b", 40, 40, 20, at=(5, 0, 5))],
        mates=[Mate(kind="ground", a="a")])

    s_good = score_assembly(good)
    # THE RUN-2 REGRESSION CASE (measured 2026-08-01): a near-perfect assembly whose ONE defect is
    # a locally-failing part ("holes count 0 vs spec 4"). Under the old reward this cost ~1 row of
    # 6 (~8%) and the policy drifted straight into it: component-fix 0 -> 12, eval 6/10 -> 3/10.
    # Stated as a synthetic REPORT because the builder clamps most bad geometry into validity.
    rep_partbad = {"passed": False,
                   "components": [{"name": "seat", "passed": False,
                                   "fails": ["holes · count (measured 0 vs spec 4)"]},
                                  {"name": "leg1", "passed": True, "fails": []}],
                   "rows": [{"name": "assembly · components", "within_tol": False, "category": "component"},
                            {"name": "assembly · connectivity (all parts attached)", "measured": 1,
                             "expected": 1, "within_tol": True, "category": "ok"},
                            {"name": "assembly · valid (watertight)", "within_tol": True, "category": "ok"},
                            {"name": "assembly · structurally supported", "within_tol": True, "category": "ok"},
                            {"name": "assembly · statics (CoM inside support polygon)", "within_tol": True,
                             "category": "ok"},
                            {"name": "assembly · interference (worst non-mated pair)", "measured": 0.0,
                             "within_tol": True, "category": "ok"}]}
    s_partbad = score_report(rep_partbad)
    s_isl = score_assembly(islanded)
    s_ovl = score_assembly(overlapped)
    s_junk = reward("the assembly is: not json at all")
    s_schema = reward('{"object": "x", "components": "wrong-type"}')

    rows = [("good stool", s_good), ("part broken", s_partbad), ("3 islands", s_isl),
            ("big overlap", s_ovl), ("junk text", s_junk), ("bad schema", s_schema)]
    for label, s in rows:
        print(f"  {label:12s} → {s.get('reward'):.4f}  {({k: v for k, v in s.items() if k != 'reward'})}")
    # the property the research demands: distinct severities → distinct rewards (variance!)
    vals = [s_good["reward"], s_isl["reward"], s_ovl["reward"], s_junk["reward"]]
    ok = (s_good["reward"] > 0.9 and s_good["reward"] > s_ovl["reward"] > s_junk["reward"]
          and s_good["reward"] > s_isl["reward"] > s_junk["reward"]
          and len({round(v, 3) for v in vals}) == len(vals)
          and s_junk["reward"] == 0.0 and s_schema["reward"] == 0.0)
    # run-2 corrections: a full pass must OUTRANK every near-miss, and a locally-broken part must
    # cost real reward (it was ~8% and produced the 6/10 -> 3/10 regression)
    gate_ok = (s_good.get("passed") and s_good["reward"] >= 1.0
               and not s_partbad.get("comp_ok")
               and s_partbad["reward"] < 0.5 * s_good["reward"])
    ok = ok and gate_ok
    print(f"SELFTEST {'PASS' if ok else 'FAIL'} — ordering good > flawed > junk, all distinct; "
          f"pass-cliff+component-gate {'ok' if gate_ok else 'FAILED'} "
          f"(good {s_good['reward']} vs part-broken {s_partbad['reward']})")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    payload = json.loads(sys.stdin.read())
    print(json.dumps(reward(payload.get("output", ""))))
