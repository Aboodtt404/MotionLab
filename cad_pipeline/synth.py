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
from .spec import Spec
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
                   "temperature": temperature, "max_tokens": max_tokens}
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
    "primitive). Shapes: box, cylinder, loft (tapered/adapter — length,width,height[,width_top,height_top|"
    "diameter_top]), revolve (turned — `profile` of [radius,z]), sweep (tube — `path` of [x,y,z] + "
    "envelope.diameter). Features: through_hole, hole_pattern, fillet/chamfer (box only), pocket(+at for "
    "panel insets), draft (box, molding), counterbore, countersink, mirror (box), shell (box, hollow), "
    "var_fillet, thread. Prefer 2–4 features in combination. Keep dimensions manufacturable (fillet/shell/"
    "draft small vs the part; holes clear of edges and each other)."
)

_CAPTION_SYS = (
    "You write natural-language prompts a person would use to request this CAD part, at FOUR levels of "
    "detail. Output JSON {\"l0\":..,\"l1\":..,\"l2\":..,\"l3\":..}: l0 = one abstract phrase (no dims); "
    "l1 = a beginner's plain description (shape + features, no measurements); l2 = an intermediate "
    "description (geometry + rough sizes); l3 = an expert spec with precise RELATIVE dimensions. Describe "
    "the SAME part; do not mention CadQuery or code."
)


def gen_spec(engine: Engine, category: str, attempts: int = 4) -> Optional[Spec]:
    """Engine → a STRUCTURED spec for `category`, accepted only if it builds AND verifies to-spec."""
    schema = Spec.model_json_schema()
    for k in range(attempts):
        try:
            raw = engine._chat(_SPEC_SYS, f"category: {category}", schema=schema, temperature=0.5 + 0.15 * k)
            spec = Spec(**json.loads(raw))
            rep = verify(build(spec), spec)        # the accept gate (deterministic, feature-level)
            if rep.passed:
                return spec
        except Exception:  # noqa: BLE001 — invalid/ infeasible spec ⇒ try again
            continue
    return None


def caption(engine: Engine, spec: Spec) -> Optional[dict]:
    try:
        raw = engine._chat(_CAPTION_SYS, spec.model_dump_json(), temperature=0.7, max_tokens=900)
        a, b = raw.find("{"), raw.rfind("}")
        d = json.loads(raw[a:b + 1])
        return {k: str(d.get(k, "")).strip() for k in ("l0", "l1", "l2", "l3")} if all(k in d for k in ("l0", "l1", "l2", "l3")) else None
    except Exception:  # noqa: BLE001
        return None


def _level(spec: Spec) -> str:
    n = len(spec.features)
    return "L1" if n <= 1 else ("L2" if n <= 3 else "L3")


def synth_sample(engine: Engine, category: str) -> Optional[dict]:
    """One verified, captioned training sample (the 6-tuple) — or None if the gate/caption fails."""
    spec = gen_spec(engine, category)
    if spec is None:
        return None
    prompts = caption(engine, spec)
    if prompts is None:
        return None
    rep = verify(build(spec), spec)
    return {
        "category": category,
        "tags": {"capabilities": sorted({spec.shape, *[f.type for f in spec.features]}), "level": _level(spec)},
        "prompts": prompts,                       # L0–L3
        "code": emit_code(spec),                  # golden target (builder source, convention-consistent)
        "spec": json.loads(spec.model_dump_json()),
        "verifier": {"passed": rep.passed, "rows": [r.name for r in rep.rows]},
    }


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


def run(engine: Engine, total: int, out_path: str) -> dict:
    """Drive the taxonomy (weighted) to `total` verified samples; stream to JSONL."""
    cats = [c for c, w in TAXONOMY.items() for _ in range(w)]
    kept, attempted, by_cat = 0, 0, {}
    with open(out_path, "w") as fh:
        i = 0
        while kept < total:
            category = cats[i % len(cats)]
            i += 1
            attempted += 1
            s = synth_sample(engine, category)
            if s is not None:
                fh.write(json.dumps(s) + "\n"); fh.flush()
                kept += 1
                by_cat[category] = by_cat.get(category, 0) + 1
                print(f"  [{kept}/{total}] {s['tags']['level']} {category[:34]:<34} caps={s['tags']['capabilities']}", flush=True)
            if attempted > total * 6 + 30:   # safety: don't loop forever if the engine is weak
                print(f"  (stopping: yield too low — {kept}/{attempted} attempts)", flush=True)
                break
    return {"kept": kept, "attempted": attempted, "yield": round(kept / max(1, attempted), 3), "by_category": by_cat, "out": out_path}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default="/tmp/corpus.jsonl")
    ap.add_argument("--model", default="qwen3.6-27b")
    ap.add_argument("--base-url", default="http://localhost:8002/v1")
    a = ap.parse_args()
    eng = Engine(base_url=a.base_url, model=a.model)
    print(f"Synthesis — engine={a.model} target={a.n} → {a.out}\n")
    summary = run(eng, a.n, a.out)
    print("\n" + json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
