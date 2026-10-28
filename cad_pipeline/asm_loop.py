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
from .planner import (_ask_patch, _default_joint_blend, _patch_schema_scoped,
                      plan as _plan)

# ---------------------------------------------------------------------------- generator protocol
class AsmGenerator(Protocol):
    """Plans an assembly from a prompt, and repairs one from typed verifier feedback.
    `route` (optional) is the targeted-repair route dict from _route_for — a generator that
    honors it scopes the patch grammar to that failure class."""
    def plan(self, prompt: str) -> Assembly: ...
    def repair(self, asm: Assembly, feedback: str, route: Optional[dict] = None) -> AsmPatch: ...


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


# ------------------------------------------------------------------- targeted repair routes
# ArtiCAD routing (placement research §3, 3-0 verified): classify each verifier failure to a
# PATCH TYPE and scope the repair to it — rollback O(K^N) → O(N·K). Each route says which
# AsmPatch fields exist at all (enforced in the guided-json grammar, not just prose), whether
# the primary field must carry content, and whether upsert/remove are pinned BY NAME to the
# failing parts. Flat repair (full grammar) remains the fallback when a route makes no progress.
_ROUTES: dict[str, dict] = {
    "component": {"fields": {"upsert"}, "must": "upsert", "scope_names": True,
                  "note": "COMPONENT-GEOMETRY. Only `upsert` replacements for the named failing "
                          "parts are accepted — fix THEIR features/dims. Mates, joints and every "
                          "other part are locked."},
    "validity":  {"fields": {"upsert", "mates"}, "must": None, "scope_names": False,
                  "note": "GEOMETRY/WELD. Fix exactly-tangent faces via part dims (`upsert`) or "
                          "make mated parts overlap cleanly 1–4 mm (`mates` = FULL replacement "
                          "list). Removal and joints are locked."},
    "disconnected": {"fields": {"mates"}, "must": "mates", "scope_names": False,
                     "note": "MATE-ADD. Output ONLY a replacement `mates` list in which EVERY "
                             "component has a mate path to the main body (stack/flush/attach/"
                             "radial/port). Geometry edits are locked — connectivity is never "
                             "fixed by resizing parts or nudging coordinates."},
    "kinematic": {"fields": {"upsert", "remove", "mates", "joints"}, "must": None, "scope_names": False,
                  "note": "JOINT SUBSYSTEM. Whichever applies: remove the mate that welds the "
                          "moving side (`mates`), add bridging geometry — stub axle/pin/hub — "
                          "(`upsert`), reduce `limits` or fix sides (`joints`)."},
    "fit":       {"fields": {"upsert"}, "must": "upsert", "scope_names": True,
                  "note": "RUNNING FIT. Only the joint's pin/bore parts may change: size the pin "
                          "⌀ = bore ⌀ − 0.2 mm (running band 0.1–0.8 mm diametral); derive one "
                          "from the other, never set both independently."},
    "integrity": {"fields": {"upsert", "remove", "mates"}, "must": None, "scope_names": True,
                  "note": "MATE-PARAM. Prefer fixing the RELATIONSHIP that derives the colliding "
                          "pair's positions (`mates` = full list: bigger radial radius, proper "
                          "mate kind, real offset). Shrink one of the named parts (`upsert`) or "
                          "remove a redundant decorative one (`remove`) only when the mate is "
                          "already right. Other parts are locked."},
    "structure": {"fields": {"upsert", "mates"}, "must": None, "scope_names": False,
                  "note": "SUPPORT. Widen the footprint / reach the floor via mate params "
                          "(radius, z, fraction) and fix dangling mate references (every a/b/"
                          "around/parts entry must be an EXISTING component name). Raise a sunk "
                          "part via its mate, not raw coordinates."},
    "cutout":    {"fields": {"upsert", "mates"}, "must": None, "scope_names": True,
                  "note": "CARVE. The tool's placement mates and the cutout must AGREE: place "
                          "the tool overlapping/abutting the target, adjust clearance, or resize "
                          "tool/target (`upsert`) if the carve severed the target."},
    "blend":     {"fields": {"fillet_joints"}, "must": "fillet_joints", "scope_names": False,
                  "note": "BLEND-PARAM. Only `fillet_joints` may change — reduce it (0 disables "
                          "the seam blend)."},
}
# worst-first priority: local part validity → connectivity → kinematics → interference →
# support → cosmetics. Fixing upstream classes routinely clears downstream rows (support and
# statics are already gated on connectivity), so one class per attempt converges.
_ROUTE_ORDER = ("component", "validity", "disconnected", "kinematic", "fit",
                "integrity", "cutout", "structure", "blend")


def _failed_cats(rep: dict) -> set:
    cats = {r["category"] for r in rep.get("rows", []) if not r["within_tol"]}
    if any(not c["passed"] for c in rep.get("components", [])):
        cats.add("component")
    return cats


def _route_for(rep: dict) -> Optional[dict]:
    """Verifier report → the targeted route for its worst failure class (None ⇒ flat repair)."""
    cats = _failed_cats(rep)
    for cat in _ROUTE_ORDER:
        if cat not in cats:
            continue
        route = {"category": cat, **_ROUTES[cat]}
        if route.pop("scope_names"):
            names = {c["name"] for c in rep.get("components", []) if not c["passed"]}
            for r in rep.get("rows", []):
                if not r["within_tol"] and r["category"] == cat:
                    names |= set(r.get("parts", []))
            route["parts"] = sorted(names) or None
        else:
            route["parts"] = None
        return route
    return None


def _asm_feedback(rep: dict, focus: Optional[str] = None) -> str:
    """Verifier report → typed, delta-only feedback (kind + magnitude, never target values),
    each failure paired with its catalog repair prescription. With `focus` (a routed category),
    that class's rows lead and the rest are listed as LOCKED — one failure class per patch."""
    parts: list[str] = []
    deferred: list[str] = []
    for c in rep.get("components", []):
        if not c["passed"]:
            if focus in (None, "component"):
                parts.append(f"part '{c['name']}' FAILED locally: {', '.join(c['fails'])} — "
                             f"{_CATEGORY_FIX['component']}")
            else:
                deferred.append(f"part '{c['name']}' fails locally")
    for r in rep["rows"]:
        if r["within_tol"] or r["category"] == "component":
            continue
        line = f"{r['name']}: measured {r['measured']} vs expected {r['expected']}"
        if focus is not None and r["category"] != focus:
            deferred.append(line)
            continue
        fix = _CATEGORY_FIX.get(r["category"])
        if fix:
            line += f" — FIX: {fix}"
        parts.append(line)
    if deferred:
        parts.append("ALSO failing but LOCKED for this patch (fix the above first — these are "
                     "often downstream of it and get their own pass next):\n  " +
                     "\n  ".join(deferred))
    return "\n".join(parts)


def _category(rep: dict) -> str:
    """Route the attempt by its worst failure class (priority mirrors the part loop)."""
    cats = _failed_cats(rep)
    for c in _ROUTE_ORDER:
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

    def repair(self, asm: Assembly, feedback: str, route: Optional[dict] = None) -> AsmPatch:
        system, schema = _REPAIR_SYSTEM, None
        if route:
            # targeted repair: the grammar itself is scoped to the routed patch type — an
            # out-of-scope edit is unrepresentable, not merely discouraged
            system = (_REPAIR_SYSTEM + "\n\nTHIS PATCH IS ROUTED — one failure class only. "
                      + route["note"])
            schema = _patch_schema_scoped(route["fields"], route["must"], route.get("parts"))
        user = (f"current assembly:\n{asm.model_dump_json()}\n\n"
                f"VERIFIER FAILURES (fix exactly these, minimally):\n{feedback}")
        return _ask_patch(system, user, self.base_url, self.model, self.timeout, schema=schema)


def run_assembly(prompt: str, generator: AsmGenerator, max_attempts: int = 3) -> dict:
    """The retry loop. Returns the part-loop-shaped dict: passed/attempt(s)/report/best_report/
    history + attempt_log [{attempt, assembly, report}] for transcript building."""
    history: list[dict] = []
    attempt_log: list[dict] = []
    best_pass, best_report = -1, None
    asm: Optional[Assembly] = None
    rep: dict = {}
    feedback = ""
    route: Optional[dict] = None
    prev_route_cat: Optional[str] = None
    prev_cat_fails = -1
    from . import progress
    for attempt in range(1, max_attempts + 1):
        try:
            if asm is None:            # first attempt — or the previous plan() itself failed:
                progress.publish(stage=f"planning · attempt {attempt} — writing the assembly spec", attempt=attempt)
                asm = generator.plan(prompt)   # re-plan; there is nothing to patch yet
            else:
                scope = f" [{route['category']}]" if route else ""
                progress.publish(stage=f"repairing · attempt {attempt} — patching the failing checks{scope}", attempt=attempt)
                asm = _resolve(apply_patch(asm, generator.repair(asm, feedback, route)))
            progress.publish(assembly=json.loads(asm.model_dump_json()),
                             stage=f"verifying · attempt {attempt} — kinematics + interference")
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
        if rep.get("passed"):
            history.append({"attempt": attempt, "status": status, "category": cat, "regressed": regressed})
            attempt_log.append({"attempt": attempt,
                                "assembly": json.loads(asm.model_dump_json()) if asm else None,
                                "report": rep})
            return {"passed": True, "attempt": attempt, "report": rep, "best_report": rep,
                    "history": history, "attempt_log": attempt_log}
        # targeted route for the NEXT patch — with a no-progress fallback: if the last patch was
        # routed to this same class and its failing-row count didn't drop, the scoped grammar is
        # too tight for the real fix → escalate to the flat (full) patch grammar.
        route = _route_for(rep) if status == "ok" else None
        if route:
            cat_fails = sum(1 for r in rep.get("rows", [])
                            if not r["within_tol"] and r["category"] == route["category"])
            if route["category"] == "component":
                cat_fails += sum(1 for c in rep.get("components", []) if not c["passed"])
            if route["category"] == prev_route_cat and cat_fails >= prev_cat_fails >= 0:
                route = None
            else:
                prev_route_cat, prev_cat_fails = route["category"], cat_fails
        if route is None:
            prev_route_cat, prev_cat_fails = None, -1
        feedback = (_asm_feedback(rep, route["category"] if route else None)
                    if status == "ok" else rep.get("error", "planning failed"))
        if regressed:
            feedback = ("A PREVIOUS attempt passed more checks — your patch broke working parts. "
                        "Make the MINIMUM change that fixes only the rows below.\n") + feedback
        history.append({"attempt": attempt, "status": status, "category": cat, "regressed": regressed,
                        "route": route["category"] if route else "flat"})
        attempt_log.append({"attempt": attempt,
                            "assembly": json.loads(asm.model_dump_json()) if asm else None,
                            "report": rep, "feedback_next": feedback})
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
        # prefer the RECORDED feedback (routed/scoped as the model actually saw it); recompute
        # flat only for pre-routing logs that lack it
        fb = None if ok else (a.get("feedback_next")
                              or (_asm_feedback(rep) if rep.get("rows") else rep.get("error", "")))
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
