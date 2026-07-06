"""Teacher-vs-baseline eval: frontier model (Anthropic) vs the local VLLMGenerator.

Runs every seed spec through the UNCHANGED loop.run() twice (baseline + teacher-with-tools,
plus an optional teacher-without-tools ablation), writes one JSONL line per spec, and prints
comparison statistics: first-attempt pass rate, overall pass rate (after retries),
selector-binding accuracy, average feature-level delta, and average tool calls per spec.

Specs are the same set eval_baseline.py uses (imported via its SETS map), so the two
harnesses are directly comparable.

Run (needs the vLLM server on :8002 for the baseline, and ANTHROPIC_API_KEY for the teacher):
    cad_pipeline/.venv/bin/python -m cad_pipeline.tests.eval_teacher hard 3
    cad_pipeline/.venv/bin/python -m cad_pipeline.tests.eval_teacher golden 3 --notools --model claude-sonnet-5
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from ..loop import VLLMGenerator, run
from ..teacher import TeacherGenerator
from .eval_baseline import SETS, preflight


# --------------------------------------------------------------------------- teacher wrapper
class TracingTeacher(TeacherGenerator):
    """TeacherGenerator that keeps EVERY attempt's trace across a full loop.run().

    TeacherGenerator.trace resets each generate() call, so after a multi-attempt run it holds
    only the last attempt. We accumulate per-attempt traces here (without touching the package)
    so tool-use / chain-of-thought is captured for the whole run and tool calls are counted honestly.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.run_traces: List[List[Dict[str, Any]]] = []

    def reset_run(self) -> None:
        self.run_traces = []

    def generate(self, spec: Any, feedback: str = "") -> str:
        code = super().generate(spec, feedback)
        # snapshot this attempt's trace (deep-enough copy — trace is plain JSON-able dicts)
        self.run_traces.append(json.loads(json.dumps(self.trace)))
        return code


# --------------------------------------------------------------------------- run extraction
def _report_of(out: dict) -> Optional[dict]:
    """The most-complete valid report from a loop.run() result (best over final)."""
    return out.get("best_report") or out.get("report")


def _summarize_run(out: dict) -> Dict[str, Any]:
    """Pull the comparable fields out of one loop.run() result dict."""
    rep = _report_of(out)
    history = out.get("history", [])
    return {
        "passed": bool(out.get("passed")),
        # loop.run returns `attempt` (the pass attempt) on success, `attempts` on escalate
        "first_attempt_pass": bool(out.get("passed")) and out.get("attempt") == 1,
        "final_status": history[-1]["status"] if history else "no-attempts",
        "report_passed": bool(rep["passed"]) if rep else False,
        "history": history,
        "feature_rows": rep["rows"] if rep else [],
    }


def _run_generator(spec: Any, generator: Any, max_attempts: int) -> Dict[str, Any]:
    """Drive loop.run() for one generator, tolerating a hard failure (server/API down)."""
    try:
        out = run(spec, generator, max_attempts=max_attempts)
        return _summarize_run(out)
    except Exception as exc:  # noqa: BLE001 — record, don't abort the whole sweep
        return {"passed": False, "first_attempt_pass": False, "final_status": "harness-error",
                "report_passed": False, "history": [], "feature_rows": [],
                "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- statistics
def _is_selector_row(r: Dict[str, Any]) -> bool:
    """Resolve-twice selector-binding rows: fillet/chamfer/var-fillet BINDING, hole/pocket
    POSITION, and the revolve axisymmetry/seam rows all carry category 'selector-binding'
    when they FAIL — but a PASSING binding row has category 'ok', so also match by name."""
    name = r.get("name", "")
    return r.get("category") == "selector-binding" or "binding" in name or "position" in name


def _agg_stats(rows_per_spec: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Selector-binding accuracy + average feature-level |delta| across all specs' rows."""
    sel_total = sel_ok = 0
    deltas: List[float] = []
    for rows in rows_per_spec:
        for r in rows:
            if _is_selector_row(r):
                sel_total += 1
                sel_ok += 1 if r.get("within_tol") else 0
            d = r.get("delta")
            if isinstance(d, (int, float)):
                deltas.append(abs(d))
    return {
        "selector_binding_accuracy": (round(sel_ok / sel_total, 3) if sel_total else None),
        "selector_binding_rows": f"{sel_ok}/{sel_total}",
        "avg_feature_delta": (round(sum(deltas) / len(deltas), 4) if deltas else None),
    }


def _tool_calls(run_traces: List[List[Dict[str, Any]]]) -> int:
    """Count tool_use blocks across every attempt of one spec's teacher run."""
    return sum(
        1
        for attempt in run_traces
        for turn in attempt
        for block in turn.get("content", [])
        if block.get("type") == "tool_use"
    )


def _summary_line(label: str, records: List[Dict[str, Any]], key: str) -> str:
    n = len(records)
    secs = [rec[key] for rec in records if key in rec]
    passed = sum(1 for s in secs if s["passed"])
    first = sum(1 for s in secs if s["first_attempt_pass"])
    stats = _agg_stats([s["feature_rows"] for s in secs])
    line = (f"  {label:<16} first-attempt {first}/{n} ({100*first/n:.0f}%) | "
            f"overall {passed}/{n} ({100*passed/n:.0f}%) | "
            f"selector-binding {stats['selector_binding_rows']} "
            f"({'n/a' if stats['selector_binding_accuracy'] is None else f'{100*stats['selector_binding_accuracy']:.0f}%'}) | "
            f"avg |Δ| {stats['avg_feature_delta']}")
    return line


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Compare the Anthropic teacher against the local baseline.")
    ap.add_argument("set", nargs="?", default="hard", choices=sorted(SETS), help="spec set (default: hard)")
    ap.add_argument("max_attempts", nargs="?", type=int, default=3, help="retries per spec (default: 3)")
    ap.add_argument("--model", default="claude-fable-5", help="teacher model id")
    ap.add_argument("--notools", action="store_true", help="also run a teacher WITHOUT tools (ablation)")
    ap.add_argument("--out", default="eval_teacher_results.jsonl", help="output JSONL path")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    specs = SETS[a.set]
    print(f"Eval set='{a.set}' — {len(specs)} specs, max_attempts={a.max_attempts}, teacher={a.model}\n")
    preflight(specs)  # offline: confirm the verifier cleanly checks every spec before judging models

    records: List[Dict[str, Any]] = []
    tool_calls_per_spec: List[int] = []

    with open(a.out, "w") as fh:
        for i, spec in enumerate(specs):
            spec_id = f"{i:02d}:{spec.object}"
            print(f"[{i+1}/{len(specs)}] {spec.object}")

            # --- baseline (local VLLMGenerator) ---
            baseline = _run_generator(spec, VLLMGenerator(), a.max_attempts)

            # --- teacher, tools enabled ---
            teacher = TracingTeacher(model=a.model, enable_tools=True, verbose=a.verbose)
            teacher.reset_run()
            teacher_tools = _run_generator(spec, teacher, a.max_attempts)
            teacher_tools_traces = teacher.run_traces
            tc = _tool_calls(teacher_tools_traces)
            tool_calls_per_spec.append(tc)

            rec: Dict[str, Any] = {
                "spec_id": spec_id,
                "spec_json": json.loads(spec.model_dump_json()),
                "baseline": baseline,
                "teacher_tools": {**teacher_tools, "trace": teacher_tools_traces, "tool_calls": tc},
            }

            # --- optional: teacher, tools disabled (ablation) ---
            if a.notools:
                teacher_nt = TracingTeacher(model=a.model, enable_tools=False, verbose=a.verbose)
                teacher_nt.reset_run()
                teacher_notools = _run_generator(spec, teacher_nt, a.max_attempts)
                rec["teacher_notools"] = {**teacher_notools, "trace": teacher_nt.run_traces}

            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            records.append(rec)

            def _mark(sec: Dict[str, Any]) -> str:
                if "error" in sec:
                    return "ERR(" + sec["error"][:40] + ")"
                return "PASS" if sec["passed"] else ("valid-but-wrong" if sec["report_passed"] is False and sec["feature_rows"] else "fail")
            extra = f" | teacher-notools {_mark(rec['teacher_notools'])}" if a.notools else ""
            print(f"    baseline {_mark(baseline)} | teacher(+tools, {tc} calls) {_mark(teacher_tools)}{extra}")

    # --------------------------------------------------------------------- summary
    n = len(records)
    print("\n" + "=" * 78)
    print(f"RESULTS  ({n} specs, set='{a.set}', max_attempts={a.max_attempts})")
    print("=" * 78)
    print(_summary_line("baseline", records, "baseline"))
    print(_summary_line("teacher (+tools)", records, "teacher_tools"))
    if a.notools:
        print(_summary_line("teacher (no tools)", records, "teacher_notools"))
    if tool_calls_per_spec:
        print(f"\n  teacher avg tool calls / spec: {sum(tool_calls_per_spec)/n:.2f} "
              f"(total {sum(tool_calls_per_spec)} across {n} specs)")
    print(f"\n  wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
