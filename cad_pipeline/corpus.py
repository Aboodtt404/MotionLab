"""Corpus contracts — schema-stable training data (fable_run 04_schemas, adapted v1).

Implements the pipeline's data contracts as pydantic models so every corpus line is
VALIDATED AT WRITE TIME:

  • CheckRow / VerifierReport   — the oracle's structured verdict (verifier.Report.to_dict()
                                  lifted into a stable, id-carrying envelope)
  • FailureReport               — one attempt's typed failure + the exact feedback issued
  • RepairTranscript            — a full generate→verify→retry episode (the unit of
                                  repair-training data), built from loop.run() output
  • TrainingSample              — the spec-first 6-tuple synth.py emits, with the full
                                  verifier report embedded (not just row names)

The five schema models themselves now live in `schemas.py` (the canonical, conformant contract);
this module imports them and adds the corpus-construction helpers (report lift, transcript builder,
training-sample assembler). Live verifier/loop category strings are normalised onto Fable's exact
snake_case enums at the emit boundary (`schemas.normalize_category` / `normalize_failure_category`),
so every corpus line is fully conformant while the running pipeline keeps its internal values.

IDs are deterministic (content-hash prefixes), so identical inputs dedupe naturally and
re-runs are reproducible.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .schemas import (Attempt, CheckRow, FailureReport, Outcome, RepairTranscript,
                      VerifierReport, normalize_failure_category)
from .spec import Spec

# Oracle versions stamped into every report — reproducibility (schema `toolchain`).
try:
    import cadquery as _cq
    _CQ_VERSION = getattr(_cq, "__version__", "unknown")
except Exception:  # noqa: BLE001 — corpus models must import even without OCP present
    _CQ_VERSION = "unavailable"
TOOLCHAIN: Dict[str, str] = {"cadquery": _CQ_VERSION, "verifier": "cad_pipeline/1"}


def _hid(prefix: str, *parts: Any) -> str:
    """Deterministic short id: content-hash of the parts (stable across re-runs, dedupes)."""
    h = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:12]
    return f"{prefix}-{h}"


# --------------------------------------------------------------------- verifier_report lift
def verifier_report_from(report: dict, subject_ref: str) -> VerifierReport:
    """Lift a pipeline report dict (verifier.Report.to_dict()) into the conformant schema envelope,
    normalising every row category onto the snake_case check_category vocabulary."""
    return VerifierReport(
        report_id=_hid("vr", subject_ref, json.dumps(report, sort_keys=True, default=str)),
        subject_ref=subject_ref,
        passed=bool(report["passed"]),
        valid=bool(report.get("valid", False)),
        solids=int(report.get("solids", 0)),
        volume_mm3=report.get("volume"),
        rows=[CheckRow.from_live(r) for r in report["rows"]],
        failure_categories=list(report.get("failure_categories", [])),
        toolchain=dict(TOOLCHAIN),
    )


# failure_report status lift (live loop status → schema failure_status)
_STATUS_MAP = {"ok": "verify_fail", "gate_fail": "gate_fail", "error": "exec_error", "timeout": "timeout"}


def _edit_lines(prev: Optional[str], cur: str) -> Optional[int]:
    if prev is None:
        return None
    return sum(1 for d in difflib.unified_diff(prev.splitlines(), cur.splitlines(), lineterm="")
               if (d.startswith("+") or d.startswith("-")) and not d.startswith(("+++", "---")))


def transcript_from_run(spec: Spec, run_out: dict, generator: Dict[str, Any]) -> RepairTranscript:
    """Build a schema-valid RepairTranscript from loop.run(..) output.

    Requires the run's per-attempt capture (run_out["attempt_log"]: [{attempt, code, res}]) —
    present since loop.run started recording attempts. Feedback strings are reconstructed
    exactly as issued (loop._feedback with the recorded repeat/regress flags), so the
    transcript's feedback fields are byte-identical to what the generator saw.
    """
    from .loop import _feedback  # local import to avoid a cycle at module load

    brief_ref = _hid("mb", spec.model_dump_json())
    history = {h["attempt"]: h for h in run_out.get("history", [])}
    attempts: List[Attempt] = []
    prev_code: Optional[str] = None
    first_valid: Optional[int] = None

    raw = run_out.get("attempt_log", [])
    if not raw:
        raise ValueError("run_out has no attempt_log — was loop.run() called with attempt capture?")
    for i, a in enumerate(raw):
        n, code, res = a["attempt"], a["code"], a["res"]
        h = history.get(n, {})
        vr = verifier_report_from(res["report"], brief_ref) if res.get("report") else None
        if res.get("status") == "ok" and first_valid is None:
            first_valid = n
        attempt_passed = bool(res.get("status") == "ok" and res["report"]["passed"])
        fb = None if attempt_passed else _feedback(
            res, spec, repeated=h.get("repeated_error", False), regressed=h.get("regressed", False))
        failure = None
        if not attempt_passed:
            from .repair import error_signature, exception_head
            tb = str(res.get("error", "")) if res.get("status") in ("error", "timeout") else ""
            failure = FailureReport(
                failure_id=_hid("fl", brief_ref, n, fb or ""),
                subject_ref=brief_ref, attempt=n,
                status=_STATUS_MAP.get(res.get("status", "error"), "exec_error"),
                category=normalize_failure_category(h.get("category", "escalate")),
                error_signature=error_signature(tb) or None if tb else None,
                traceback_head=exception_head(tb) or None if tb else None,
                failed_rows=[CheckRow.from_live(r) for r in (res.get("report", {}) or {}).get("rows", [])
                             if not r["within_tol"]],
                feedback=fb or "",
                repeated_error=h.get("repeated_error", False),
                regressed=h.get("regressed", False),
            )
        attempts.append(Attempt(
            attempt=n, code=code, verifier_report=vr, failure_report=failure,
            feedback_to_next=fb if i < len(raw) - 1 else None,
            edit_distance_lines=_edit_lines(prev_code, code),
        ))
        prev_code = code

    out = Outcome(
        passed=bool(run_out.get("passed")),
        attempts_used=raw[-1]["attempt"],
        first_valid_attempt=first_valid,
        final_category=None if run_out.get("passed") else run_out.get("category"),
    )
    return RepairTranscript(
        transcript_id=_hid("rt", brief_ref, generator.get("model", "?"), len(raw)),
        brief_ref=brief_ref, generator=generator,
        spec=json.loads(spec.model_dump_json()),
        attempts=attempts, outcome=out,
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# --------------------------------------------------------------------- training_sample
class TrainingSample(BaseModel):
    """The spec-first, verifier-gated sample synth.py emits (track-a-corpus-scope 6-tuple),
    with the FULL verifier report embedded so labels carry their evidence."""
    sample_id: str
    category: str
    tags: Dict[str, Any]                 # {"capabilities": [...], "level": "L1|L2|L3"}
    prompts: Dict[str, str]              # L0–L3 captions
    code: str                            # golden target (builder source)
    spec: Dict[str, Any]
    verifier_report: VerifierReport
    toolchain: Dict[str, str] = Field(default_factory=lambda: dict(TOOLCHAIN))


def training_sample(category: str, tags: dict, prompts: dict, code: str,
                    spec: Spec, report: dict) -> TrainingSample:
    """Assemble + VALIDATE one corpus line. Raises pydantic.ValidationError on any shape drift."""
    sid = _hid("ts", spec.model_dump_json(), code)
    return TrainingSample(
        sample_id=sid, category=category, tags=tags, prompts=prompts, code=code,
        spec=json.loads(spec.model_dump_json()),
        verifier_report=verifier_report_from(report, sid),
    )
