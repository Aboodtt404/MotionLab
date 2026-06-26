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


_ASM_RUBRIC = (
    "You are a concept artist reviewing a grey 3D BLOCKOUT of a '{obj}' (a fused multi-part hard-surface "
    "model). Judge whether the assembled FORM reads as a '{obj}': are the major parts present, sensibly "
    "PROPORTIONED, and placed? Is it richly built or a few plain blocks? Flag: missing_parts (key parts "
    "absent), wrong_proportion (a part too big/small/long), misplaced (a part in the wrong spot), too_plain "
    "(reads as bare blocks, lacks sci-fi surface detail), or good.\n"
    "Reply with ONLY a JSON object, no prose:\n"
    '{{"verdict":"good|missing_parts|wrong_proportion|misplaced|too_plain",'
    '"issues":["short phrase", ...],'
    '"edits":["one concrete change instruction", ...]}}\n'
    "Each `edits` item must be a SINGLE concrete parametric change an editor can apply, e.g. "
    "'make the wings 1.5x longer', 'add a cockpit canopy box at the front', 'greeble the fuselage', "
    "'move the engines outward'. Give 1-3 edits; if it already reads well, verdict=good and edits=[]."
)


def critique_assembly(asm, object_name: str | None = None, base_url: str = "http://localhost:8002/v1",
                      model: str = "qwen3.6-27b", timeout: float = 120.0) -> dict:
    """Render the fused assembly and ask the VLM whether it reads as the named object → {verdict, issues,
    edits}. `edits` are natural-language single-change instructions for the planner's edit loop."""
    from .assembly import build_assembly
    obj = object_name or getattr(asm, "object", "object")
    try:
        solid = build_assembly(asm)
    except Exception as e:  # noqa: BLE001
        return {"verdict": "error", "issues": [f"build failed: {type(e).__name__}"], "edits": []}
    images = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(p).decode()}}
              for p in render_views(solid, n=2)]
    messages = [{"role": "user", "content": [{"type": "text", "text": _ASM_RUBRIC.format(obj=obj)}, *images]}]
    for _ in range(2):
        try:
            out = _chat(base_url, model, messages, timeout, think=False, max_tokens=500)
        except Exception as e:  # noqa: BLE001
            return {"verdict": "error", "issues": [f"vlm call failed: {type(e).__name__}"], "edits": []}
        parsed = _parse(out)
        if parsed and "verdict" in parsed:
            parsed.setdefault("issues", []); parsed.setdefault("edits", [])
            return parsed
    return {"verdict": "error", "issues": ["unparseable VLM critique"], "edits": []}


def refine_assembly(asm, object_name: str | None = None, rounds: int = 2,
                    base_url: str = "http://localhost:8002/v1", model: str = "qwen3.6-27b",
                    timeout: float = 180.0) -> tuple:
    """Render → critique → apply each suggested edit via the planner, KEEPING an edit only if the assembly
    stays valid + a single connected solid (a VLM edit that breaks the fuse is discarded). Bounded loop;
    stops on 'good'/no edits/no kept change. Returns (asm, history) — history[i] = that round's critique."""
    from .assembly import verify_assembly
    from .planner import edit as _edit
    obj = object_name or getattr(asm, "object", "object")
    history: list = []
    cur_solids = verify_assembly(asm)["solids"]
    for _ in range(max(1, rounds)):
        c = critique_assembly(asm, obj, base_url, model, timeout)
        history.append(c)
        if c["verdict"] in ("good", "error") or not c.get("edits"):
            break
        kept = False
        for instr in c["edits"][:3]:
            try:
                cand = _edit(asm, instr, base_url, model, timeout)
                rep = verify_assembly(cand)
                ok_valid = next((r["within_tol"] for r in rep["rows"] if "valid" in r["name"]), False)
                # keep an edit only if it stays valid and does NOT worsen fragmentation (fewer/equal
                # disconnected solids) — improvements toward one connected body are accepted, edits that
                # shatter the model are discarded. (Requiring solids==1 outright would reject every step
                # on a still-fragmented blockout.)
                if ok_valid and rep["solids"] <= cur_solids:
                    asm = cand; cur_solids = rep["solids"]; kept = True
            except Exception:  # noqa: BLE001 — a bad edit is skipped, not fatal
                continue
        if not kept:
            break
    return asm, history


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
