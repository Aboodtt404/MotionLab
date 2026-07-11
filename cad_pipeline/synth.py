"""Synthetic-corpus engine — text→CadQuery training data, generated + gated locally (§6 / track-a-corpus-scope).

Design = SPEC-FIRST, verifier-gated (our edge over Zero-to-CAD's geometric-only gate):
  1. The data engine (gpt-oss-120b locally; qwen for dev) generates a diverse STRUCTURED Spec per
     category via vLLM structured output — guaranteed schema-valid, weighted toward composites/tail.
  2. Accept gate = our DETERMINISTIC builder + feature-level verifier: keep a spec only if it builds
     AND verifies to-spec. This filters the engine's infeasible hallucinations (oversize fillet,
     overlapping holes) — semantic, not just "is it a valid solid".
  3. Target code = emit_code(spec) — the golden builder source: guaranteed-correct and
     convention-consistent (revolve→Z, loft→X, …), so the fine-tune bakes the conventions the eval
     showed the model slips on. (Distilling the builder, gated by the verifier.)
  4. The engine captions each verified spec into L0–L3 prompts (Text2CAD taxonomy).
A sample is the 6-tuple track-a-corpus-scope §1 specifies: prompts · code · spec · report · tags.

Run (dev, against the qwen already on :8002):
    cad_pipeline/.venv/bin/python -m cad_pipeline.synth --n 6 --out /tmp/corpus_smoke.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

from .builder import build, emit_code
from .spec import Spec, feature_shape_conflicts
from .verifier import verify


# --------------------------------------------------------------------- the local data engine
@dataclass
class Engine:
    base_url: str = "http://localhost:8002/v1"
    model: str = "qwen3.6-27b"   # dev; swap to "gpt-oss-120b" for the production run
    timeout: float = 180.0

    def _chat(self, system: str, user: str, schema: Optional[dict] = None,
              temperature: float = 0.7, max_tokens: int = 3000) -> str:
        payload = {"model": self.model,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                   "temperature": temperature, "max_tokens": max_tokens,
                   # no-think: spec/caption generation is transcription, not reasoning. With thinking
                   # ON the un-schema'd caption call rambles a reasoning preamble that eats the whole
                   # token budget before the JSON appears → caption() returns None → 0 corpus yield.
                   "chat_template_kwargs": {"enable_thinking": False}}
        if schema is not None:   # vLLM guided decoding ⇒ schema-valid JSON, no parse failures
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]


_SPEC_SYS = (
    "You are a mechanical/sci-fi CAD designer producing TRAINING specs. Output ONE part as JSON matching "
    "the schema. Make it REALISTIC and DETAILED for the requested category — give it the functional "
    "features it needs and VARY dimensions, proportions and feature COMBINATIONS run-to-run (never a bare "
    "primitive). Shapes: box, cylinder, prism (regular N-gon bar — hex/square/octagon standoff/boss/nut, "
    "`sides`:N + envelope.diameter (circumscribed ⌀) + height), loft (tapered/adapter — length,width,"
    "height[,width_top,height_top|diameter_top]), revolve (turned — `profile` of [radius,z]), sweep "
    "(tube/beam — `path` of [x,y,z] + a round envelope.diameter OR a rectangular envelope.width+height). "
    "Features: through_hole, hole_pattern, fillet/chamfer, pocket(+at for panel insets), draft (molding), "
    "counterbore, countersink, mirror, shell (hollow), var_fillet, thread. Prefer 2–4 features in "
    "combination. Keep dimensions manufacturable (fillet/shell/draft small vs the part; holes clear of "
    "edges and each other). ALWAYS fill `envelope` with the shape's dims — box: {length,width,height} · "
    "cylinder/prism: {diameter,height} (prism also sets `sides`) · loft: {length,width,height[,width_top,"
    "height_top|diameter_top]} · sweep: {diameter} OR {width,height} + `path`; revolve uses `profile` "
    "[[r,z],…] instead (envelope {} or {angle}) and may add `profile_arcs` (sagitta per segment; "
    "0=straight, negative bows OUTWARD — domes/barrels/flares). "
    "HARD FEATURE-COMPATIBILITY RULES (violations are rejected): fillet & chamfer go on box/prism (edges "
    "+ rims) and on the top/bottom RIM of a cylinder/revolve (edges='top'|'bottom') — NOT on loft/sweep. "
    "shell hollows box/prism/cylinder. draft, var_fillet, mirror and pocket/counterbore/countersink & "
    "internal thread need a FLAT-TOP straight-walled body: box/prism (+ cylinder for shell/pocket/holes). "
    "draft NEVER combines with fillet/chamfer/var_fillet (tapered walls lose the vertical edges). "
    "through_hole and hole_pattern work on any shape. A loft/sweep part gets its character from its "
    "PROFILE/PATH and holes — not from box features."
)

_CAPTION_SYS = (
    "You write natural-language prompts a person would use to request this CAD part, at FOUR levels of "
    "detail. Output JSON {\"l0\":..,\"l1\":..,\"l2\":..,\"l3\":..}: l0 = one abstract phrase (no dims); "
    "l1 = a beginner's plain description (shape + features, no measurements); l2 = an intermediate "
    "description (geometry + rough sizes); l3 = an expert spec with precise RELATIVE dimensions. Describe "
    "the SAME part; do not mention CadQuery or code. Feature counts are LOAD-BEARING: if the part has "
    "NO holes/features, l1–l3 must SAY so ('a plain solid block, no holes'); otherwise l2/l3 state the "
    "EXACT count of each feature ('exactly two through-holes') and never imply features the spec lacks."
)


_ENV_KEYS = {"box": ("length", "width", "height"), "cylinder": ("diameter", "height"),
             "prism": ("diameter", "height"), "loft": ("length", "width", "height")}


def _spec_complete(spec: Spec) -> bool:
    """Cheap pre-build gate: the shape's structural inputs must be present, and every feature
    must be REALIZABLE on the shape (feature_shape_conflicts) — the builder silently skips
    box-only features on other shapes, which would make the spec/caption describe geometry
    that doesn't exist (the poison class the batch-1 QA caught)."""
    if feature_shape_conflicts(spec):
        return False
    if spec.shape == "revolve":
        return bool(spec.profile and len(spec.profile) >= 3)
    if spec.shape == "sweep":
        # round (diameter) OR rectangular (width+height) section, swept along a ≥2-point path
        has_section = "diameter" in spec.envelope or {"width", "height"} <= set(spec.envelope)
        return has_section and bool(spec.path and len(spec.path) >= 2)
    return all(k in spec.envelope for k in _ENV_KEYS[spec.shape])


def _code_verified(spec: Spec) -> bool:
    """THE gate that matters: execute the EMITTED code (the artifact the corpus actually ships)
    and verify the solid it produces. build(spec) alone is not enough — any builder↔emitter
    divergence would store passing labels on crashing/wrong code (batch-1: 9/12 poisoned)."""
    import cadquery as cq
    ns: dict = {}
    try:
        exec(emit_code(spec), {"__name__": "__corpus_gate__"}, ns)   # noqa: S102 — our own emitter's output
        res = ns["result"]
        wp = res if isinstance(res, cq.Workplane) else cq.Workplane(obj=res)
        return verify(wp, spec).passed
    except Exception:  # noqa: BLE001 — emitted code that crashes is exactly what we're gating out
        return False


def gen_spec(engine: Engine, category: str, attempts: int = 4,
             rejects: Optional[List[dict]] = None, hint: str = "",
             must: Optional[set] = None, max_feats: Optional[int] = None) -> Optional[Spec]:
    """Engine → a STRUCTURED spec for `category`, accepted only if it builds AND verifies to-spec.

    `hint` is a category-conditioned HARD requirement appended to the request ("shape MUST be
    'loft'...") — how batch-3 forces the starved curriculum families; the gate still decides.

    When `rejects` is given, every GATE-REJECTED candidate is appended to it as a verifier-labeled
    NEGATIVE (03_training_recipe: rejected examples are training data too — DPO/GRPO contrast
    pairs come free with the run instead of being discarded)."""
    schema = Spec.model_json_schema()
    # Guided decoding only emits keys the schema REQUIRES — pydantic marks defaulted fields
    # optional, so without this the engine can (and does) omit `envelope` entirely and every
    # candidate dies on a KeyError in build(). Require the structural fields.
    # profile/path are nullable but REQUIRED-present: guided decoding omits optional keys entirely,
    # which starves revolve (profile) and sweep (path) the same way envelope was starved.
    schema["required"] = sorted(set(schema.get("required", []))
                                | {"object", "shape", "envelope", "features", "profile", "path"})

    def _reject(stage: str, spec: Optional[Spec] = None, raw: str = "", error: str = "",
                rows: Optional[list] = None) -> None:
        if rejects is None:
            return
        rejects.append({
            "category": category, "stage": stage,
            "spec": json.loads(spec.model_dump_json()) if spec is not None else None,
            "raw_head": raw[:300] if (raw and spec is None) else None,
            "error": error or None,
            "failing_rows": rows or [],
        })

    user = f"category: {category}" + (f"\nHARD REQUIREMENT (non-negotiable): {hint}" if hint else "")
    for k in range(attempts):
        raw = ""
        try:
            raw = engine._chat(_SPEC_SYS, user, schema=schema, temperature=0.5 + 0.15 * k)
            spec = Spec(**json.loads(raw))
        except Exception as e:  # noqa: BLE001 — unparseable candidate
            _reject("parse", raw=raw, error=f"{type(e).__name__}: {str(e)[:200]}")
            continue
        conflicts = feature_shape_conflicts(spec)
        if conflicts:
            _reject("shape_conflict", spec=spec, error=f"unrealizable on shape={spec.shape}: {conflicts}")
            continue
        if not _spec_complete(spec):
            _reject("incomplete", spec=spec, error=f"missing structural inputs for shape={spec.shape}")
            continue
        if must and not must <= ({spec.shape} | {f.type for f in spec.features}):
            _reject("hint_miss", spec=spec, error=f"hinted capability {sorted(must)} not used")
            continue
        if max_feats is not None and len(spec.features) > max_feats:
            # batch-4 sparsity discipline: a "plain" category that grows features would feed the
            # exact over-decoration bias (unexpected cylinders) this batch exists to unlearn
            _reject("hint_miss", spec=spec,
                    error=f"{len(spec.features)} features on a max_feats={max_feats} category")
            continue
        try:
            rep = verify(build(spec), spec)        # the accept gate (deterministic, feature-level)
        except Exception as e:  # noqa: BLE001 — spec parses but won't build (infeasible geometry)
            _reject("build_error", spec=spec, error=f"{type(e).__name__}: {str(e)[:200]}")
            continue
        if rep.passed:
            if _code_verified(spec):     # final authority: the training TARGET must verify
                return spec
            _reject("code_gate", spec=spec, error="emit_code output failed to exec/verify (builder↔emitter divergence)")
            continue
        _reject("verify_fail", spec=spec,
                rows=[{"name": r.name, "expected": r.expected, "measured": r.measured,
                       "category": r.category} for r in rep.rows if not r.within_tol])
    return None


_CAPTION_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in ("l0", "l1", "l2", "l3")},
    "required": ["l0", "l1", "l2", "l3"],
}


def caption(engine: Engine, spec: Spec) -> Optional[dict]:
    try:
        # schema-constrained like gen_spec — guarantees parseable {l0..l3}, no free-form preamble
        raw = engine._chat(_CAPTION_SYS, spec.model_dump_json(), schema=_CAPTION_SCHEMA,
                           temperature=0.7, max_tokens=900)
        a, b = raw.find("{"), raw.rfind("}")
        d = json.loads(raw[a:b + 1])
        return {k: str(d.get(k, "")).strip() for k in ("l0", "l1", "l2", "l3")} if all(k in d for k in ("l0", "l1", "l2", "l3")) else None
    except Exception:  # noqa: BLE001
        return None


def _level(spec: Spec) -> str:
    n = len(spec.features)
    return "L1" if n <= 1 else ("L2" if n <= 3 else "L3")


def synth_sample(engine: Engine, category: str,
                 rejects: Optional[List[dict]] = None, hint: str = "",
                 must: Optional[set] = None, max_feats: Optional[int] = None) -> Optional[dict]:
    """One verified, captioned training sample — schema-validated (corpus.TrainingSample,
    the 04_schemas-derived contract) with the FULL verifier report embedded, or None if
    the gate/caption fails. Gate rejects stream into `rejects` as labeled negatives."""
    from .corpus import training_sample
    spec = gen_spec(engine, category, rejects=rejects, hint=hint, must=must, max_feats=max_feats)
    if spec is None:
        return None
    prompts = caption(engine, spec)
    if prompts is None:
        if rejects is not None:   # verified spec lost to captioning — recoverable, keep it labeled
            rejects.append({"category": category, "stage": "caption_fail",
                            "spec": json.loads(spec.model_dump_json()),
                            "raw_head": None, "error": "caption returned None", "failing_rows": []})
        return None
    rep = verify(build(spec), spec)
    sample = training_sample(
        category=category,
        tags={"capabilities": sorted({spec.shape, *[f.type for f in spec.features]}), "level": _level(spec)},
        prompts=prompts,                          # L0–L3
        code=emit_code(spec),                     # golden target (builder source, convention-consistent)
        spec=spec,
        report=rep.to_dict(),                     # full evidence, not just row names
    )
    return json.loads(sample.model_dump_json())


# the bespoke taxonomy (track-a-corpus-scope §2), weighted robotics / sci-fi / tail
TAXONOMY = {
    # robotics / mechanical (45%)
    "mounting bracket": 3, "motor mount": 2, "bolt-circle flange": 3, "turned shaft or hub": 3,
    "electronics enclosure/housing": 3, "standoff or spacer": 1, "threaded boss or tapped plate": 2,
    "round-to-rect adapter or duct": 2, "coolant line or pipe": 2,
    # sci-fi hard-surface (40%)
    "greebled hull/fuselage panel": 3, "vent or louver grille": 2, "turret or weapon body": 2,
    "antenna/sensor housing": 2, "hatch or access panel": 2, "structural truss node": 1,
    "sci-fi paneled plate with insets": 3,
    # pure-tail stress (15%) — hard combinations
    "multi-feature mechanical part (4+ features, asymmetric)": 2,
    "stepped turned body with steps and tapers": 1, "draughted thin-wall enclosure with mounting holes": 2,
}


# Batch-3 curriculum taxonomy — targets the starved no-RAG failure families measured across
# batch1+2 (170 keeps: loft 2, sweep 1, var_fillet 0, countersink 3, draft 8, chamfer 9).
# Each entry: weight, category-conditioned HARD hint, and the capability set the sample MUST
# actually use (checked post-parse — a hinted category that drifts back to plain box is a
# "hint_miss" negative, not a keep). Bench curriculum: revolve/loft/sweep/shell/csk/draft/var_fillet.
TAXONOMY_BATCH3 = {
    "round-to-rect adapter or transition duct":
        (4, "shape MUST be 'loft' (envelope length,width,height + width_top/height_top or diameter_top); "
            "features ONLY through_hole/hole_pattern or none — NO fillet/chamfer/shell/pocket", {"loft"}),
    "tapered pylon, foot or pedestal (loft)":
        (3, "shape MUST be 'loft'; features ONLY through_hole/hole_pattern or none", {"loft"}),
    "coolant line, hydraulic pipe or conduit":
        (4, "shape MUST be 'sweep' (`path` of 3+ [x,y,z] waypoints with bends + envelope.diameter); "
            "features ONLY through_hole or none — NO fillet/chamfer/shell/pocket", {"sweep"}),
    "bent tube handle or roll bar":
        (3, "shape MUST be 'sweep'; features ONLY through_hole or none", {"sweep"}),
    "injection-molded housing with draft":
        (4, "shape MUST be 'box' and features MUST include 'draft'; NO fillet/chamfer/var_fillet "
            "(tapered walls) — combine with holes/pocket instead", {"box", "draft"}),
    "draughted thin-wall enclosure":
        (3, "shape MUST be 'box', features MUST include 'draft' AND 'shell'; "
            "NO fillet/chamfer/var_fillet", {"box", "draft", "shell"}),
    "bracket with variable-radius edge blend":
        (4, "shape MUST be 'box' and features MUST include 'var_fillet'", {"box", "var_fillet"}),
    "console or cowling panel with graded blend":
        (3, "shape MUST be 'box', features MUST include 'var_fillet'", {"box", "var_fillet"}),
    "countersunk mounting or cover plate":
        (3, "features MUST include 'countersink' (flat-head screws)", {"countersink"}),
    "chamfered spacer or wear plate":
        (2, "shape MUST be 'box', features MUST include 'chamfer'", {"box", "chamfer"}),
    "stepped turned shaft, hub or bushing":
        (3, "shape MUST be 'revolve' (`profile` of 4+ [radius,z] points with steps); "
            "features ONLY through_hole/hole_pattern or none", {"revolve"}),
    "domed cap, barrel body or flared nozzle":
        (3, "shape MUST be 'revolve' and MUST use profile_arcs (curved meridian); "
            "features ONLY through_hole or none", {"revolve"}),
}


# Batch-4 — feature-PRESENCE balance. The phase21 smoke's residual failure signature was
# "unexpected cylinders": hole_pattern rode in 82% of batches 1–3, so the adapter learned
# "parts have holes" as a prior and drills unrequested ones. This batch teaches absence:
# plain parts (captioned as plain — see _CAPTION_SYS), exactly-one-feature parts, and a
# var_fillet binding slice (bench C19, the other straggler). Entry: (weight, hint, must, max_feats).
TAXONOMY_BATCH4 = {
    "plain rectangular block or spacer (no features)":
        (3, "features MUST be an empty list [] — a plain solid box, NO holes, NO cuts", {"box"}, 0),
    "plain cylindrical rod, puck or disc (no features)":
        (3, "shape MUST be 'cylinder'; features MUST be an empty list [] — NO bore, NO holes", {"cylinder"}, 0),
    "plain turned body (profile only, no features)":
        (2, "shape MUST be 'revolve' (profile of 4+ [r,z] points); features MUST be []", {"revolve"}, 0),
    "plain tapered transition (no features)":
        (2, "shape MUST be 'loft'; features MUST be an empty list []", {"loft"}, 0),
    "plain bent tube (no features)":
        (2, "shape MUST be 'sweep'; features MUST be an empty list []", {"sweep"}, 0),
    "block with exactly one through-hole":
        (2, "features MUST be exactly ONE through_hole and nothing else", {"box", "through_hole"}, 1),
    "plate with a single pocket, no holes":
        (2, "features MUST be exactly ONE pocket — NO holes of any kind", {"box", "pocket"}, 1),
    "cylinder with a single center bore":
        (2, "shape MUST be 'cylinder'; features MUST be exactly ONE through_hole", {"cylinder", "through_hole"}, 1),
    "filleted block, no holes":
        (2, "features MUST be exactly ONE fillet — NO holes", {"box", "fillet"}, 1),
    "variable-radius blended bracket, no holes":
        (3, "features MUST be exactly ONE var_fillet (edges 'all_vertical', distinct r1/r2) — NO holes",
         {"box", "var_fillet"}, 1),
    "var_fillet block with exactly two mounting holes":
        (2, "features MUST be ONE var_fillet (edges 'all_vertical') + exactly TWO through_holes, "
            "nothing else", {"box", "var_fillet", "through_hole"}, 3),
}


def run(engine: Engine, total: int, out_path: str, taxonomy: Optional[dict] = None) -> dict:
    """Drive the taxonomy (weighted) to `total` verified samples; stream to JSONL.
    Gate-rejected candidates stream to <out>.rejects.jsonl as verifier-labeled negatives.
    `taxonomy` values are weight ints (TAXONOMY), (weight, hint, must) tuples (TAXONOMY_BATCH3),
    or (weight, hint, must, max_feats) tuples (TAXONOMY_BATCH4)."""
    tax = taxonomy if taxonomy is not None else TAXONOMY
    entries = {c: ((*v, None) if isinstance(v, tuple) and len(v) == 3
                   else v if isinstance(v, tuple) else (v, "", None, None))
               for c, v in tax.items()}
    cats = [c for c, (w, *_) in entries.items() for _ in range(w)]
    rej_path = (out_path[:-6] if out_path.endswith(".jsonl") else out_path) + ".rejects.jsonl"
    kept, attempted, n_rej, by_cat = 0, 0, 0, {}
    with open(out_path, "w") as fh, open(rej_path, "w") as rfh:
        i = 0
        while kept < total:
            category = cats[i % len(cats)]
            _, hint, must, max_feats = entries[category]
            i += 1
            attempted += 1
            rejects: list = []
            s = synth_sample(engine, category, rejects=rejects, hint=hint, must=must, max_feats=max_feats)
            for r in rejects:
                rfh.write(json.dumps(r) + "\n")
            if rejects:
                rfh.flush(); n_rej += len(rejects)
            if s is not None:
                fh.write(json.dumps(s) + "\n"); fh.flush()
                kept += 1
                by_cat[category] = by_cat.get(category, 0) + 1
                print(f"  [{kept}/{total}] {s['tags']['level']} {category[:34]:<34} caps={s['tags']['capabilities']}", flush=True)
            if attempted > total * 6 + 30:   # safety: don't loop forever if the engine is weak
                print(f"  (stopping: yield too low — {kept}/{attempted} attempts)", flush=True)
                break
    return {"kept": kept, "attempted": attempted, "rejects": n_rej,
            "yield": round(kept / max(1, attempted), 3), "by_category": by_cat,
            "out": out_path, "rejects_out": rej_path}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default="/tmp/corpus.jsonl")
    ap.add_argument("--model", default="qwen3.6-27b")
    ap.add_argument("--base-url", default="http://localhost:8002/v1")
    ap.add_argument("--taxonomy", choices=["default", "batch3", "batch4"], default="default")
    a = ap.parse_args()
    eng = Engine(base_url=a.base_url, model=a.model)
    tax = {"batch3": TAXONOMY_BATCH3, "batch4": TAXONOMY_BATCH4}.get(a.taxonomy)
    print(f"Synthesis — engine={a.model} taxonomy={a.taxonomy} target={a.n} → {a.out}\n")
    summary = run(eng, a.n, a.out, taxonomy=tax)
    print("\n" + json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
