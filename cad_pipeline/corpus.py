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

Deviations from the 04_schemas draft (documented per its own append-only rule; this is our /1):
  • category strings keep the pipeline's live values (hyphenated: `selector-binding`,
    `exec-fix`, …) — the running verifier/loop are authoritative over the doc's snake_case.
  • row `category` is an open string, not a closed enum — the verifier grows categories
    (e.g. assembly's `blend`) and the corpus writer must not reject them.

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


# --------------------------------------------------------------------- verifier_report
class CheckRow(BaseModel):
    """One verifier measurement — exactly verifier.Row.to_dict()'s shape."""
    name: str
    expected: Any = None
    measured: Any = None
    delta: Optional[float] = None
    within_tol: bool
    category: str          # ok | dimensional | selector-binding | missing_feature | integrity |
    #                        dfm | validity | structure | disconnected | component | blend | ...


class VerifierReport(BaseModel):
    """The oracle's verdict — the ONLY authoritative pass signal in the pipeline."""
    report_id: str
    subject_ref: str                     # sample/brief id this report measures
    passed: bool
    valid: bool
    solids: int
    volume_mm3: Optional[float] = None
    rows: List[CheckRow]
    failure_categories: List[str] = Field(default_factory=list)
    toolchain: Dict[str, str] = Field(default_factory=lambda: dict(TOOLCHAIN))


def verifier_report_from(report: dict, subject_ref: str) -> VerifierReport:
    """Lift a pipeline report dict (verifier.Report.to_dict()) into the schema envelope."""
    return VerifierReport(
        report_id=_hid("vr", subject_ref, json.dumps(report, sort_keys=True, default=str)),
        subject_ref=subject_ref,
        passed=bool(report["passed"]),
        valid=bool(report.get("valid", False)),
        solids=int(report.get("solids", 0)),
        volume_mm3=report.get("volume"),
        rows=[CheckRow(**r) for r in report["rows"]],
        failure_categories=list(report.get("failure_categories", [])),
    )


# --------------------------------------------------------------------- failure_report
_STATUS_MAP = {"ok": "verify_fail", "gate_fail": "gate_fail", "error": "exec_error", "timeout": "timeout"}


class FailureReport(BaseModel):
    """One attempt's typed failure: routing category + the exact feedback the generator got."""
    failure_id: str
    subject_ref: str
    attempt: int
    status: Literal["exec_error", "timeout", "gate_fail", "verify_fail", "refused"]
    category: str                        # loop._category value: exec-fix | validity | ... | escalate
    error_signature: Optional[str] = None
    traceback_head: Optional[str] = None
    failed_rows: List[CheckRow] = Field(default_factory=list)
    feedback: str
    repeated_error: bool = False
    regressed: bool = False


# --------------------------------------------------------------------- repair_transcript
class Attempt(BaseModel):
    attempt: int
    code: str
    verifier_report: Optional[VerifierReport] = None   # None when execution produced no geometry
    failure_report: Optional[FailureReport] = None     # None iff this attempt passed
    feedback_to_next: Optional[str] = None
    edit_distance_lines: Optional[int] = None          # changed lines vs previous attempt


class Outcome(BaseModel):
    passed: bool
    attempts_used: int
    first_valid_attempt: Optional[int] = None
    final_category: Optional[str] = None


class RepairTranscript(BaseModel):
    """A complete generate→verify→retry episode for one spec — the unit of repair-training data."""
    transcript_id: str
    brief_ref: str
    generator: Dict[str, Any]            # {"model": ..., "config": {...}}
    spec: Dict[str, Any]                 # the Spec, verbatim (our model_brief)
    attempts: List[Attempt]
    outcome: Outcome
    created: str


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
                category=h.get("category", "escalate"),
                error_signature=error_signature(tb) or None if tb else None,
                traceback_head=exception_head(tb) or None if tb else None,
                failed_rows=[CheckRow(**r) for r in (res.get("report", {}) or {}).get("rows", [])
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
