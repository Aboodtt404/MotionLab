"""Prompt-adherence VLM judge + the gated part-quality score (research Phase 3, MUSE-style).

The deterministic verifier owns GEOMETRY (dims, features, validity — the kernel is the authority and
the VLM is explicitly NOT asked to judge geometric correctness, where VLMs are weak). What the kernel
is blind to is INTENT: "does this look like what was asked for?" — the axis every 2026 text→CAD bench
(MUSE / Text2CAD-Bench / BenchCAD) scores with a rendered VLM rubric, and the one that correlates best
with human quality judgments. This module renders the solid (render.py) and asks the served
multimodal model (qwen3.6-27b on :8002, same machinery as critique.py) for a structured
intent rubric, then composes the defensible single number:

    Q = 1[valid solid] · 1[verifier gates pass] · intent ∈ [0, 1]

A part scores 0 unless the kernel gates pass; only then does the graded VLM intent score apply — so
the composite can never overstate quality past a hard-gate failure (the MUSE "failure cascade" rule).
"""
from __future__ import annotations

import base64
import json
import re
from typing import Optional

from .nl_spec import _chat
from .render import render_views

_RUBRIC = (
    "You are reviewing a 3D part that was generated from a text request. You see {n} rendered views "
    "of the SAME part. Judge ONLY whether the part matches the REQUEST below — its shape family, its "
    "stated features (holes, patterns, hollowing, bevels, panels…), and its rough proportions. Do NOT "
    "judge exact dimensions (a separate geometric checker owns measurements) and do NOT judge render "
    "quality/lighting.\n"
    "REQUEST: {prompt}\n"
    "Reply with ONLY a JSON object, no prose:\n"
    '{{"scores":{{"shape_match":0..1,"feature_match":0..1,"proportions":0..1}},'
    '"intent":0..1,"notes":"one short sentence"}}\n'
    "`intent` is your overall does-this-match-the-request score (not necessarily the mean)."
)


def judge_intent(prompt: str, solid, n_views: int = 3,
                 base_url: str = "http://localhost:8002/v1", model: str = "qwen3.6-27b",
                 timeout: int = 120) -> Optional[dict]:
    """Render → VLM rubric → {'intent': 0..1, 'scores': {...}, 'notes': str}, or None if the judge
    is unavailable/unparseable (callers treat None as 'no judgment', never as a failure)."""
    try:
        pngs = render_views(solid, n=n_views)
        images = [{"type": "image_url",
                   "image_url": {"url": "data:image/png;base64," + base64.b64encode(p).decode()}}
                  for p in pngs]
        rubric = _RUBRIC.format(n=len(pngs), prompt=prompt.strip()[:1200])
        messages = [{"role": "user", "content": [{"type": "text", "text": rubric}, *images]}]
        out = _chat(base_url, model, messages, timeout, think=False, max_tokens=400)
        m = re.search(r"\{.*\}", out, re.S)
        d = json.loads(m.group(0)) if m else None
        if not d or "intent" not in d:
            return None
        d["intent"] = max(0.0, min(1.0, float(d["intent"])))
        return d
    except Exception:  # noqa: BLE001 — judge down/unparseable ⇒ no judgment
        return None


def quality_score(prompt: str, solid, report: dict,
                  base_url: str = "http://localhost:8002/v1",
                  model: str = "qwen3.6-27b") -> dict:
    """The gated composite: Q = 1[valid] · 1[verifier passed] · VLM intent. `report` is the
    verifier Report.to_dict(). Returns the full evidence so the cascade stays visible."""
    gates = {"valid_solid": bool(report.get("valid")) and report.get("solids") == 1
             and (report.get("volume") or 0) > 0,
             "verifier_passed": bool(report.get("passed"))}
    if not all(gates.values()):
        return {"q": 0.0, "gates": gates, "intent": None,
                "notes": "hard gate failed — intent not scored (cascade rule)"}
    j = judge_intent(prompt, solid, base_url=base_url, model=model)
    if j is None:
        return {"q": None, "gates": gates, "intent": None,
                "notes": "gates passed; VLM judge unavailable"}
    return {"q": round(j["intent"], 3), "gates": gates,
            "intent": j["intent"], "scores": j.get("scores"), "notes": j.get("notes", "")}
