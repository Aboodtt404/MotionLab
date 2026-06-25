"""Track A — generate → execute → verify → retry loop (track-a-design.md §9).

Verifier-guided. Failures are routed by the 4-class taxonomy
{exec-fix · dimensional-fix · selector-binding-fix · escalate}; the retry is fed
*failure deltas, not the answer key*; the loop stops on pass; and a kill criterion
flags >1% post-retry dimensional error as a harness/prompt/verifier bug (since
CadQuery is exact) rather than a tolerance to relax.

The generator is pluggable (Protocol). v0 ships a Golden and a Mock-retry generator
for a deterministic, offline demo; the real generator is the local fine-tuned model
(track-a §5) — VLLMGenerator wires the OpenAI-compatible endpoint with the CoT scaffold.
"""
from __future__ import annotations

from typing import Optional, Protocol

from .builder import emit_code
from .executor import run_code
from .repair import diagnose, error_signature, exception_head
from .spec import Spec


class Generator(Protocol):
    def generate(self, spec: Spec, feedback: Optional[str]) -> str: ...


class GoldenGenerator:
    """Deterministic golden reference — emits correct code, passes first attempt."""
    def generate(self, spec: Spec, feedback: Optional[str] = None) -> str:
        return emit_code(spec)


class MockRetryGenerator:
    """Demonstrates the verifier-guided retry: the first attempt drifts a hole
    out of tolerance; once it receives the verifier's diff, it corrects."""
    def generate(self, spec: Spec, feedback: Optional[str] = None) -> str:
        if feedback is None:
            s = spec.model_copy(deep=True)
            for f in s.features:
                if f.type == "through_hole":
                    f.diameter += spec.tolerance * 4  # push out of tolerance
                    break
            return emit_code(s)
        return emit_code(spec)  # corrected after feedback


def _category(res: dict) -> str:
    if res["status"] in ("error", "timeout"):
        return "exec-fix"
    if res["status"] == "gate_fail":
        return "validity"
    cats = res["report"]["failure_categories"]
    if "integrity" in cats or "selector-binding" in cats or "missing_feature" in cats:
        return "selector-binding-fix"
    if "dimensional" in cats:
        return "dimensional-fix"
    if "dfm" in cats:
        return "dfm-fix"          # manufacturability advisory (not a transcription error)
    return "ok"


def _feedback(res: dict, spec: Spec, repeated: bool = False, regressed: bool = False) -> str:
    """Typed, delta-only feedback — never the full golden spec (anti-leakage, §9).

    Exec errors get *error-driven retrieval* (repair.diagnose): the exception head plus
    the canonical CadQuery fix, not a raw stack trace — so the model can look up the truth
    instead of re-guessing. `repeated`/`regressed` add the motoko-repair discipline rules
    (stop re-guessing on a repeat; minimum-change after a regression)."""
    if res["status"] in ("error", "timeout"):
        tb = str(res.get("error", res["status"]))
        parts = ["exec error: " + (exception_head(tb) or res["status"])]
        hint = diagnose(tb)
        if hint:
            parts.append("FIX: " + hint)
        if repeated:
            parts.append("You hit this SAME error before — do NOT try a different rewrite. "
                         "Apply the FIX above and change ONLY the offending line.")
        return "\n".join(parts)
    if res["status"] == "gate_fail":
        return "invalid geometry: " + ", ".join(res.get("failed", [])) + (" " + res.get("error", "") if res.get("error") else "")
    fails = [r for r in res["report"]["rows"] if not r["within_tol"]]
    msg = "; ".join(_row_feedback(r, spec.tolerance) for r in fails)
    if regressed:
        msg = ("A PREVIOUS attempt built more of this part correctly — you rewrote it and broke "
               "working features. Make the MINIMUM change to fix only the issues below; keep "
               "everything that already passed.\n") + msg
    return msg


def _row_feedback(r: dict, tol: float) -> str:
    """One verifier row → a typed, quantified, NON-leaking hint (§9 anti-leakage).
    We surface the *kind* and *magnitude* of the miss — never the target value/coords —
    so selector-binding failures (the resolve-twice IP) get actionable guidance instead
    of a misleading "feature not found"."""
    name, cat, exp, meas = r["name"], r["category"], r["expected"], r["measured"]
    if cat == "missing_feature" or meas is None:
        return f"{name}: required feature not found in the geometry"
    if cat == "dimensional":
        return f"{name}: measured {meas} vs expected {exp} (Δ {r['delta']}, tol ±{tol})"
    # selector-binding family — the feature exists but landed on the wrong entity/place
    if "position" in name:
        return (f"{name}: feature is MISPLACED — {meas} mm from its intended location "
                f"(tol ±{tol}); re-check which edge/datum the offset is measured from")
    if "binding" in name:
        return (f"{name}: selector resolved to {meas} edges/faces but the feature must land on "
                f"exactly {exp} — wrong entity set, fix the selector not the dimension")
    if "unexpected" in name:
        return f"{name}: {meas} extra feature(s) present that the spec does not call for — remove them"
    return f"{name}: measured {meas} vs expected {exp}"


def run(spec: Spec, generator: Generator, max_attempts: int = 3, timeout: float = 60.0) -> dict:
    feedback: Optional[str] = None
    history: list[dict] = []
    seen_sigs: set[str] = set()   # exec-error signatures already encountered (repeat detection)
    best_pass = -1                # most verifier rows ever passed in one attempt (regression detection)
    best_report: Optional[dict] = None  # the most-complete valid report seen (for honest eval aggregation)
    res: dict = {}
    for attempt in range(1, max_attempts + 1):
        code = generator.generate(spec, feedback)
        res = run_code(code, spec, timeout=timeout)
        cat = _category(res)

        # motoko-repair rule 3: same error twice ⇒ the rewrite approach is wrong (stop re-guessing).
        repeated = False
        if res["status"] in ("error", "timeout"):
            sig = error_signature(str(res.get("error", "")))
            repeated = sig in seen_sigs
            seen_sigs.add(sig)

        # motoko-repair rule 2: minimum change ⇒ flag when a valid build loses ground vs the best so far.
        regressed = False
        if res["status"] == "ok":
            npass = sum(1 for r in res["report"]["rows"] if r["within_tol"])
            regressed = best_pass >= 0 and npass < best_pass
            if npass > best_pass:
                best_report = res["report"]   # keep the most-complete valid build, even if later attempts regress
            best_pass = max(best_pass, npass)

        history.append({"attempt": attempt, "status": res["status"], "category": cat,
                        "repeated_error": repeated, "regressed": regressed})
        if res["status"] == "ok" and res["report"]["passed"]:
            return {"passed": True, "attempt": attempt, "report": res["report"],
                    "best_report": res["report"], "history": history}
        feedback = _feedback(res, spec, repeated=repeated, regressed=regressed)

    # escalated: build the kill-criterion flag from the last report (§9)
    kill = False
    report = res["report"] if res["status"] == "ok" else None
    if report:
        for r in report["rows"]:
            if r["category"] == "dimensional" and r["expected"] and abs(r["delta"]) / r["expected"] > 0.01:
                kill = True
    return {
        "passed": False, "attempts": max_attempts, "category": "escalate",
        "report": report, "best_report": best_report, "history": history, "last_feedback": feedback,
        "kill_flag": kill,
        "kill_note": "post-retry dimensional error >1% — CadQuery is exact, so suspect a harness/prompt/verifier bug, not the tolerance" if kill else None,
    }


class VLLMGenerator:
    """Real generator slot — local model via the OpenAI-compatible endpoint
    (track-a §5: CoT 6-stage scaffold, geometric style, `result` contract).
    Not exercised in the offline demo; wire-and-run is the next step (the served
    model id must be confirmed — see [[local-llm-endpoints]] in memory)."""
    SYSTEM = (
        "You are a CAD engineer who writes CadQuery (Python). Think through the 6-stage method "
        "(decompose → workplane/frame → base profile → features → operation order → units) INSIDE a "
        "<think>...</think> block. After </think>, output ONLY the final program as a single ```python "
        "code block — NO prose, NO headings, NO explanation outside the block. The program must "
        "`import cadquery as cq` and assign the final solid to a variable named `result`. "
        "API: `.box(L,W,H)` is centered at the origin; Z-hole via "
        "`.faces('>Z').workplane().center(x,y).hole(d)` (workplane() takes a FLOAT offset, NOT a plane name); "
        "fillet/chamfer vertical edges via `.edges('|Z').fillet(r)` / `.chamfer(d)`; "
        "rectangular pocket via `.faces('>Z').workplane().rect(l,w).cutBlind(-depth)`. "
        "MULTIPLE holes: place them ALL AT ONCE with one "
        "`.faces('>Z').workplane().pushPoints([(x1,y1),(x2,y2),...]).hole(d)` (absolute, origin=part center) "
        "— do NOT chain `.center().hole()` per hole: `.center()` is RELATIVE and accumulates, drifting later holes. "
        "For advanced SHAPES (revolve / sweep / loft), molding (draft / shell), recessed or threaded holes "
        "(counterbore / countersink / thread), mirror symmetry, and variable-radius fillets, FOLLOW THE EXACT "
        "PATTERNS in the retrieved reference below — they encode the required conventions (axes, centering)."
    )

    def __init__(self, base_url: str = "http://localhost:8002/v1", model: str = "qwen3.6-27b",
                 rag: bool = True):
        # track-a §5: base Qwen3.6-27B (FP8) served via vLLM on :8002 — the fine-tune
        # *base*, run zero-shot here to bootstrap+exercise the loop (research predicts
        # off-the-shelf is weak at CAD, motivating the distillation program).
        # rag=True injects retrieved CadQuery docs (§5: TF-IDF/grep doc-lookup) — the
        # cheapest lever on the exec-fluency wall; toggle off to A/B its effect.
        self.base_url, self.model, self.rag = base_url, model, rag

    @staticmethod
    def _extract_code(txt: str) -> str:
        """Robustly pull the program out of a possibly-reasoning, possibly-truncated reply.
        A thinking model emits <think>…</think> (often only the CLOSING tag survives the
        chat template) then a fenced block; with a tight budget the closing fence can be
        cut off. Strategy: take everything after the last </think>, drop any remaining
        <think> span, take the LAST fenced block (closed or truncated-open), else salvage
        from `import cadquery`."""
        import re
        if "</think>" in txt:                       # real answer follows the (orphan) closing tag
            txt = txt.rsplit("</think>", 1)[1]
        txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
        closed = re.findall(r"```(?:python)?\s*(.*?)```", txt, re.S)
        if closed:
            return closed[-1].strip()
        open_fence = re.search(r"```(?:python)?\s*(.*)$", txt, re.S)  # unclosed (truncated) fence
        if open_fence:
            return open_fence.group(1).strip()
        idx = txt.find("import cadquery")  # no fence at all — salvage from the import
        return (txt[idx:] if idx != -1 else txt).strip()

    def generate(self, spec: Spec, feedback: Optional[str] = None) -> str:
        import json
        import urllib.request

        user = f"Build this part as CadQuery, assigning the solid to `result`:\n{spec.model_dump_json(indent=2)}"
        if feedback:
            user += f"\n\nThe previous attempt failed verification — fix ONLY these issues, keep the rest:\n{feedback}"
        if self.rag:
            from .rag import reference_block
            ref = reference_block(spec, feedback)
            if ref:
                user += f"\n\n{ref}"
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": self.SYSTEM}, {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": 8192,
            # no-think: this is a transcription task (spec→code), not a reasoning one. Thinking just
            # burns latency (free-form ramble at single-stream ~28 tok/s) and is how Phase-3 GRPO was
            # trained. vLLM honours chat_template_kwargs on the chat endpoint.
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode()
        req = urllib.request.Request(self.base_url + "/chat/completions", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            txt = json.loads(r.read())["choices"][0]["message"]["content"]
        return self._extract_code(txt)


def _print(label: str, out: dict) -> None:
    print(f"\n── {label} ──")
    def _mark(h):
        flags = ("↻repeat" if h.get("repeated_error") else "") + ("↓regress" if h.get("regressed") else "")
        return f"{h['attempt']}:{h['status']}/{h['category']}{(' ' + flags) if flags else ''}"
    print("  attempts:", " → ".join(_mark(h) for h in out["history"]))
    if out["passed"]:
        print(f"  PASSED on attempt {out['attempt']}")
    else:
        print(f"  FAILED (escalate){' · KILL: ' + out['kill_note'] if out.get('kill_flag') else ''}")
    if out.get("report"):
        for r in out["report"]["rows"]:
            mark = "✓" if r["within_tol"] else "✗"
            print(f"    {mark} {r['name']:<18} exp {r['expected']:<7} meas {r['measured']}  ({r['category']})")


if __name__ == "__main__":
    bracket = Spec(
        object="rectangular bracket", shape="box", envelope={"length": 80, "width": 50, "height": 30},
        features=[{"type": "fillet", "radius": 4}, {"type": "through_hole", "diameter": 12, "from_edge": 18}],
        tolerance=0.1,
    )
    _print("GoldenGenerator (expect: pass attempt 1)", run(bracket, GoldenGenerator()))
    _print("MockRetryGenerator (expect: fail→correct via verifier feedback)", run(bracket, MockRetryGenerator()))
