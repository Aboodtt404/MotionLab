"""Assembly retry loop — plan → verify → typed feedback → PATCH → re-verify (the assembly
analog of loop.py's part loop; the math text's step 5: "iterate on failure").

The feedback discipline follows the free-variables lesson (ARCH_R = TIRE_R + 0.040): every
hint tells the model to fix the RELATIONSHIP that derives a position — a mate, a joint, a
radius, a shared parameter — never to nudge raw coordinates, because independent coordinates
are where collisions live. Repairs are MINIMAL AsmPatch deltas (upsert/remove/mates/joints),
not whole-assembly regeneration, so working parts stay untouched (the motoko-repair rule).

Per-category repair prescriptions come from the mistakes catalog (fable_run 05_mistakes A1–A8):
disconnected → add the missing mate; interference → clearance via the mate/radius, shrink the
part not the spec; kinematic sweep → gap(θ) > 0 must hold over the WHOLE range; statics → widen
the support polygon. Anti-leakage as always: kind + magnitude of each miss, never target values.

Episodes emit the 04_schemas repair_transcript (corpus.RepairTranscript) so assembly repairs
are training data in the same format as part repairs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional, Protocol

from .assembly import (Assembly, AsmPatch, apply_patch, repair_connectivity,
                       solve_layout, verify_assembly)
from .corpus import (Attempt, CheckRow, FailureReport, Outcome, RepairTranscript,
                     VerifierReport, _hid)
from .schemas import normalize_failure_category
from .planner import _ask_patch, _default_joint_blend, plan as _plan

# ---------------------------------------------------------------------------- generator protocol
class AsmGenerator(Protocol):
    """Plans an assembly from a prompt, and repairs one from typed verifier feedback."""
    def plan(self, prompt: str) -> Assembly: ...
    def repair(self, asm: Assembly, feedback: str) -> AsmPatch: ...


_REPAIR_SYSTEM = (
    "You REPAIR a parametric CAD assembly that FAILED verification. You get the current assembly "
    "JSON and the verifier's failure rows; output the MINIMAL patch that fixes ONLY those failures: "
    "`upsert` = full replacements for the components you change (exact same name), `remove` = names "
    "to delete, `mates`/`joints` = the FULL updated list ONLY when connections must change. "
    "Do not touch anything that passed.\n"
    "Reason through the chain for each failing part: (1) FRAME — whose frame places it, is it the "
    "right parent/reference? (2) MATE — which relationship should derive its position, and does it "
    "leave the right degrees of freedom? (3) CLEARANCE — which inequality must hold (gap > 0), and "
    "is the opening DERIVED from its neighbour or guessed? (4) PROOF — will the fix pass the exact "
    "check that failed?\n"
    "Fix RELATIONSHIPS, never raw coordinates: interpenetrating parts need a changed mate/radius/"
    "size (derive one position from the other — shared parameters, fewer free variables), not a "
    "nudged `at`. A hinge that can't move means a mate WELDED the moving side — remove that mate, "
    "keep the joint. A swing collision means the moving part's swept volume needs clearance over "
    "its WHOLE range — enlarge the opening, move the obstacle, or reduce `limits`. A part that "
    "won't build has infeasible feature dims — shrink the feature, not the part."
)

# per-category repair prescriptions (mistakes-catalog A1–A8 REPAIR column, condensed)
_CATEGORY_FIX = {
    "component": "the named part fails on its own — fix ITS features/dims (see its failing rows); do not move other parts",
    "validity": "the fused result is not a valid solid — avoid exactly-tangent faces; overlapping mates should overlap 1–4 mm, cleanly",
    "disconnected": "some parts are not welded to the main body — every component needs a mate path (stack/flush/attach/radial); do NOT fix this by moving coordinates",
    "integrity": "non-mated parts occupy the same space — derive their positions from ONE shared parameter (bigger radial radius, proper mate, smaller part); never nudge `at`. If the collider is a redundant decorative shell (an 'arch'/'fender' part over a wheel that already has a cutout), REMOVE that part — the cutout IS the arch",
    "structure": "the assembly tips or floats — widen the support footprint (bigger radial radius, legs that reach z=0) or move mass over the support polygon. A part whose min-z is BELOW 0 is sunk into the floor: raise its `at` z (a suspended chassis sits at z = wheel radius, never 0)",
    "kinematic": "a joint is welded shut (remove the mate between its two sides), redundant, floating (add a joint/mate path), physically unattached (its two sides don't touch — add bridging geometry: a stub axle/pin/hub reaching from the fixed side to the moving part), or its motion collides — clearance must hold over the WHOLE limits range",
    "fit": "the joint's pin/bore clearance is not a running fit — a pin the same ⌀ as its bore is SEIZED; size the pin ⌀ = bore ⌀ − 0.2 mm (running band 0.1–0.8 mm diametral): derive one from the other, never set both independently",
    "blend": "the joint blend corrupted the solid — reduce fillet_joints (or set 0)",
    "cutout": "a cutout (carve) failed — if it removed nothing, the tool's grown volume misses the "
              "target (place the tool so it overlaps/abuts the target, or raise clearance); if the "
              "target split into pieces, the carve went too deep (reduce clearance or shrink the "
              "tool); if the clearance gap is short, another mate moved the tool after the carve "
              "(the tool's placement mates and the cutout must agree)",
}


def _asm_feedback(rep: dict) -> str:
    """Verifier report → typed, delta-only feedback (kind + magnitude, never target values),
    each failure paired with its catalog repair prescription."""
    parts: list[str] = []
    for c in rep.get("components", []):
        if not c["passed"]:
            parts.append(f"part '{c['name']}' FAILED locally: {', '.join(c['fails'])} — "
                         f"{_CATEGORY_FIX['component']}")
    for r in rep["rows"]:
        if r["within_tol"] or r["category"] == "component":
            continue
        line = f"{r['name']}: measured {r['measured']} vs expected {r['expected']}"
        fix = _CATEGORY_FIX.get(r["category"])
        if fix:
            line += f" — FIX: {fix}"
        parts.append(line)
    return "\n".join(parts)


def _category(rep: dict) -> str:
    """Route the attempt by its worst failure class (priority mirrors the part loop)."""
    cats = {r["category"] for r in rep["rows"] if not r["within_tol"]}
    if any(not c["passed"] for c in rep.get("components", [])):
        cats.add("component")
    for c in ("component", "validity", "disconnected", "kinematic", "fit", "integrity", "structure", "blend"):
        if c in cats:
            return c + "-fix"
    return "ok"


def _resolve(asm: Assembly) -> Assembly:
    """Re-run the deterministic layout pipeline after a patch (same as plan()/edit())."""
    asm = solve_layout(asm)
    asm = repair_connectivity(asm)          # no-ops for jointed assemblies
    _default_joint_blend(asm)
    return asm


# ---------------------------------------------------------------------------- generators
class VLLMAsmGenerator:
    """The live generator: planner.plan() for attempt 1, repair patches thereafter."""
    def __init__(self, base_url: str = "http://localhost:8002/v1",
                 model: str = os.environ.get("PLAN_MODEL", "qwen3.6-27b"), timeout: float = 300.0):
        self.base_url, self.model, self.timeout = base_url, model, timeout

    def plan(self, prompt: str) -> Assembly:
        return _plan(prompt, base_url=self.base_url, model=self.model, timeout=self.timeout)

    def repair(self, asm: Assembly, feedback: str) -> AsmPatch:
        user = (f"current assembly:\n{asm.model_dump_json()}\n\n"
                f"VERIFIER FAILURES (fix exactly these, minimally):\n{feedback}")
        return _ask_patch(_REPAIR_SYSTEM, user, self.base_url, self.model, self.timeout)


def run_assembly(prompt: str, generator: AsmGenerator, max_attempts: int = 3) -> dict:
    """The retry loop. Returns the part-loop-shaped dict: passed/attempt(s)/report/best_report/
    history + attempt_log [{attempt, assembly, report}] for transcript building."""
    history: list[dict] = []
    attempt_log: list[dict] = []
    best_pass, best_report = -1, None
    asm: Optional[Assembly] = None
    rep: dict = {}
    feedback = ""
    for attempt in range(1, max_attempts + 1):
        try:
            if asm is None:            # first attempt — or the previous plan() itself failed:
                asm = generator.plan(prompt)   # re-plan; there is nothing to patch yet
            else:
                asm = _resolve(apply_patch(asm, generator.repair(asm, feedback)))
            rep = verify_assembly(asm)
            status = "ok"
        except Exception as e:  # noqa: BLE001 — a plan/patch that won't produce an assembly
            rep = {"passed": False, "rows": [], "components": [], "solids": 0,
                   "envelope": {}, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            status = "error"
        cat = _category(rep) if status == "ok" else "escalate"
        npass = sum(1 for r in rep.get("rows", []) if r["within_tol"])
        regressed = best_pass >= 0 and npass < best_pass
        if npass > best_pass:
            best_pass, best_report = npass, rep
        history.append({"attempt": attempt, "status": status, "category": cat, "regressed": regressed})
        attempt_log.append({"attempt": attempt,
                            "assembly": json.loads(asm.model_dump_json()) if asm else None,
                            "report": rep})
        if rep.get("passed"):
            return {"passed": True, "attempt": attempt, "report": rep, "best_report": rep,
                    "history": history, "attempt_log": attempt_log}
        feedback = _asm_feedback(rep) if status == "ok" else rep.get("error", "planning failed")
        if regressed:
            feedback = ("A PREVIOUS attempt passed more checks — your patch broke working parts. "
                        "Make the MINIMUM change that fixes only the rows below.\n") + feedback
    return {"passed": False, "attempts": max_attempts, "category": "escalate", "report": rep,
            "best_report": best_report, "history": history, "attempt_log": attempt_log,
            "last_feedback": feedback}


# ---------------------------------------------------------------------------- transcript (04_schemas)
def _asm_verifier_report(rep: dict, subject_ref: str) -> VerifierReport:
    """Adapter: verify_assembly's dict → the schema VerifierReport. `valid` lives in a row
    (watertight) rather than top-level; volume rides in envelope."""
    valid_row = next((r for r in rep.get("rows", []) if "watertight" in r["name"]), None)
    return VerifierReport(
        report_id=_hid("vr", subject_ref, json.dumps(rep, sort_keys=True, default=str)),
        subject_ref=subject_ref,
        passed=bool(rep.get("passed")),
        valid=bool(valid_row["measured"]) if valid_row else False,
        solids=int(rep.get("solids", 0)),
        volume_mm3=(rep.get("envelope") or {}).get("volume"),
        rows=[CheckRow.from_live(r) for r in rep.get("rows", [])],
        failure_categories=sorted({r["category"] for r in rep.get("rows", []) if not r["within_tol"]}),
    )


def asm_transcript(prompt: str, run_out: dict, generator: dict) -> RepairTranscript:
    """One assembly episode → a schema-valid RepairTranscript (the 04_schemas unit of
    repair-training data). The `code` artifact of each attempt is the assembly JSON —
    assemblies ARE the program on this path."""
    brief_ref = _hid("ab", prompt)
    history = {h["attempt"]: h for h in run_out.get("history", [])}
    attempts: list[Attempt] = []
    first_valid = None
    raw = run_out.get("attempt_log", [])
    for i, a in enumerate(raw):
        rep = a["report"]
        ok = bool(rep.get("passed"))
        vr = _asm_verifier_report(rep, brief_ref) if rep.get("rows") is not None else None
        if first_valid is None and rep.get("solids", 0) > 0:
            first_valid = a["attempt"]
        fb = None if ok else _asm_feedback(rep) if rep.get("rows") else rep.get("error", "")
        failure = None
        if not ok:
            failure = FailureReport(
                failure_id=_hid("fl", brief_ref, a["attempt"], fb or ""),
                subject_ref=brief_ref, attempt=a["attempt"],
                status="verify_fail" if rep.get("rows") else "exec_error",
                category=normalize_failure_category(history.get(a["attempt"], {}).get("category", "escalate")),
                failed_rows=[CheckRow.from_live(r) for r in rep.get("rows", []) if not r["within_tol"]],
                feedback=fb or "",
                regressed=history.get(a["attempt"], {}).get("regressed", False),
            )
        attempts.append(Attempt(
            attempt=a["attempt"],
            code=json.dumps(a["assembly"]) if a["assembly"] else "",
            verifier_report=vr, failure_report=failure,
            feedback_to_next=fb if i < len(raw) - 1 else None,
        ))
    return RepairTranscript(
        transcript_id=_hid("rt", brief_ref, generator.get("model", "?"), len(raw)),
        brief_ref=brief_ref, generator=generator,
        spec={"prompt": prompt, "kind": "assembly_brief"},
        attempts=attempts,
        outcome=Outcome(passed=bool(run_out.get("passed")),
                        attempts_used=raw[-1]["attempt"] if raw else 0,
                        first_valid_attempt=first_valid,
                        final_category=None if run_out.get("passed") else run_out.get("category")),
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
