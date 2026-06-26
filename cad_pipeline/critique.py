"""Render→VLM critique + refine loop for the greeble detail pass (Seek-CAD, arXiv 2505.17702).

Greeble has no ground-truth dimensions — the deterministic verifier can only confirm "detail was cut
and the solid is valid", never "it looks filmic". So the quality signal comes from LOOKING: render the
greebled solid (render.py) and ask the served VLM (qwen3.6-27b on :8002 — it takes images) to judge it
against the research's filmic rules (greeble-detail-research.md: strategic NON-uniform distribution,
focal points vs rest areas, recess/negative-space hierarchy — "detail everywhere = no detail"). The
critique returns concrete greeble-param suggestions; `refine` applies them, rebuilds, and re-critiques
in a bounded loop. Greeble is builder-routed, so each round is fast geometry + one VLM call.
"""
from __future__ import annotations

import base64
import json
import re

from .builder import build
from .nl_spec import _chat
from .render import render_views
from .spec import Spec

_RUBRIC = (
    "You are a sci-fi hard-surface art director reviewing a PROCEDURAL GREEBLE pass on a 3D prop "
    "(panel-line grooves + recessed/raised panels that imply workmanship and convey scale). Judge ONLY "
    "the surface detail, not the base shape. Filmic greeble follows rules: strategic NON-UNIFORM "
    "distribution (busy focal points vs calmer rest areas), variation in panel size/depth, and a "
    "recess/negative-space hierarchy. 'Detail everywhere is as good as no detail.' Flag detail that is a "
    "flat uniform blanket (too_uniform), too sparse to read (too_sparse), so dense it's mush (too_busy), "
    "or random noise with no panel logic (noisy); otherwise good.\n"
    "Current greeble params: {params}. Ranges: density 0.05-1.0, focal one of none|center|edges, "
    "depth 0.5-{maxdepth}, panel 6-{maxpanel}, bevel 0-{maxbevel}.\n"
    "Reply with ONLY a JSON object, no prose:\n"
    '{{"verdict":"good|too_uniform|too_sparse|too_busy|noisy",'
    '"scores":{{"non_uniformity":0..1,"focal_clarity":0..1,"readability":0..1}},'
    '"suggest":{{"density":num,"focal":"none|center|edges","depth":num,"panel":num,"bevel":num}},'
    '"notes":"one short sentence"}}\n'
    "Put in `suggest` ONLY the params you would CHANGE (absolute new values, in range); omit the rest. "
    "If it already looks good, verdict=good and suggest={{}}."
)

_CLAMP = {  # (lo, hi-factor-of) — hi resolved against envelope below
    "density": (0.05, 1.0), "depth": (0.5, None), "panel": (6.0, None), "bevel": (0.0, None),
}
_FOCAL = {"none", "center", "edges"}


def _greeble_of(spec: Spec):
    return next((f for f in spec.features if f.type == "greeble"), None)


def _bounds(spec: Spec) -> tuple[float, float]:
    """(min face dimension, depth) bounds for clamping param suggestions to sane geometry."""
    e = spec.envelope
    if spec.shape == "box":
        dim = min(e["length"], e["width"])
    elif spec.shape == "cylinder":
        dim = min(e["diameter"], e["height"])
    else:
        dim = min(v for k, v in e.items() if isinstance(v, (int, float)) and v > 0)
    return dim, e.get("height", dim)


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (ValueError, TypeError):
        return None


def critique(spec: Spec, solid=None, base_url: str = "http://localhost:8002/v1",
             model: str = "qwen3.6-27b", timeout: float = 120.0) -> dict:
    """Render the greebled solid and ask the VLM to judge the detail → {verdict, scores, suggest, notes}.
    Returns {'verdict':'error', ...} on a failed/unparseable VLM call (never raises)."""
    g = _greeble_of(spec)
    if g is None:
        return {"verdict": "error", "notes": "no greeble feature", "suggest": {}, "scores": {}}
    if solid is None:
        solid = build(spec)
    dim, _ = _bounds(spec)
    params = {k: getattr(g, k) for k in ("panel", "depth", "density", "focal", "raised", "bevel")}
    rubric = _RUBRIC.format(params=json.dumps(params), maxdepth=round(0.4 * dim, 1),
                            maxpanel=round(dim, 1), maxbevel=round(0.3 * g.depth + 0.5, 1))
    images = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p).decode()}}
              for p in render_views(solid, n=2)]
    messages = [{"role": "user", "content": [{"type": "text", "text": rubric}, *images]}]
    for _ in range(2):                          # one reparse retry
        try:
            out = _chat(base_url, model, messages, timeout, think=False, max_tokens=500)
        except Exception as e:                  # noqa: BLE001 — VLM/network down → surface, don't crash
            return {"verdict": "error", "notes": f"vlm call failed: {type(e).__name__}", "suggest": {}, "scores": {}}
        parsed = _parse(out)
        if parsed and "verdict" in parsed:
            parsed.setdefault("suggest", {}); parsed.setdefault("scores", {}); parsed.setdefault("notes", "")
            return parsed
    return {"verdict": "error", "notes": "unparseable VLM critique", "suggest": {}, "scores": {}}


def _apply(spec: Spec, suggest: dict) -> bool:
    """Apply suggested greeble params (clamped to sane ranges) → True if anything actually changed."""
    g = _greeble_of(spec)
    dim, _ = _bounds(spec)
    hi = {"depth": 0.4 * dim, "panel": dim, "bevel": 0.3 * g.depth + 0.5}
    changed = False
    for k, (lo, _u) in _CLAMP.items():
        if k in suggest and isinstance(suggest[k], (int, float)):
            top = _CLAMP[k][1] if _CLAMP[k][1] is not None else hi[k]
            val = round(max(lo, min(float(suggest[k]), top)), 3)
            if abs(val - getattr(g, k)) > 1e-6:
                setattr(g, k, val); changed = True
    if suggest.get("focal") in _FOCAL and suggest["focal"] != g.focal:
        g.focal = suggest["focal"]; changed = True
    return changed


def refine(spec: Spec, rounds: int = 2, **kw) -> tuple[Spec, list]:
    """Build → critique → apply suggestions → rebuild, up to `rounds`. Stops early on verdict 'good',
    no suggestions, or no change. Returns (refined_spec, history) — history[i] = the critique that round."""
    spec = spec.model_copy(deep=True)
    history: list = []
    for _ in range(max(1, rounds)):
        solid = build(spec)
        c = critique(spec, solid, **kw)
        history.append(c)
        if c["verdict"] in ("good", "error") or not c.get("suggest"):
            break
        if not _apply(spec, c["suggest"]):
            break
    return spec, history
