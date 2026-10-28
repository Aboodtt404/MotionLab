"""Build the TEXT→CAD SFT corpus: caption each part (render → VLM describe) and pair the description
with its feature-program. This is the input side text→CAD needs (the corpus only had target-side
programs). Uses the SERVING vLLM (qwen3.6, a VLM) — no training GPU window required.

Sources: Fusion (partlevel_recon_v2.jsonl, simple+some complex, has thumbnails) + DeepCAD complex
(the 22k+ complex parts). Complexity-BALANCED subset (quality>quantity for a cold-start).
Target format = feature-program JSON string (no code emitter for v1; eval builds via build_part).

Record: {prompt: <caption>, code: <part JSON str>, stem, n_extrudes, source}.
Run:  cad_pipeline/.venv/bin/python -m training.build_textcad_corpus [--n N] [--workers W]
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import json
import random
import sys
import urllib.request

from cad_pipeline.builder import build_part
from cad_pipeline.render import render_views
from cad_pipeline.spec import Part

FUS = "/workspace/.hf_home/cad_corpus/partlevel_recon_v2.jsonl"
DC = "/workspace/.hf_home/cad_corpus/partlevel_deepcad_complex.jsonl"
OUT = "/workspace/.hf_home/cad_corpus/textcad_sft.jsonl"
ENDPOINT = "http://localhost:8002/v1/chat/completions"
CAP_PROMPT = ("Describe this CAD part in ONE sentence, the way a user would request it to be modeled: "
              "overall shape, notable features (holes, bosses, slots, steps), and rough proportions. "
              "Factual and concise, no preamble, start with a noun phrase.")


def _load(path):
    try:
        return [json.loads(l) for l in open(path)]
    except FileNotFoundError:
        return []


def _caption(rec) -> dict | None:
    """Build → render → VLM-caption one record → a (prompt, program) SFT row, or None on failure."""
    try:
        part = Part.model_validate(rec["part"])
        solid = build_part(part).val()
        imgs = [{"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + base64.b64encode(p).decode()}}
                for p in render_views(solid, n=2)]
        body = json.dumps({
            "model": "qwen3.6-27b",
            "messages": [{"role": "user", "content": [{"type": "text", "text": CAP_PROMPT}, *imgs]}],
            "temperature": 0.3, "max_tokens": 120,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode()
        req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
        cap = json.load(urllib.request.urlopen(req, timeout=90))["choices"][0]["message"]["content"].strip()
        if len(cap) < 15:
            return None
        return {"prompt": cap, "code": json.dumps(rec["part"]), "stem": rec["stem"],
                "n_extrudes": rec["n_extrudes"], "source": rec.get("source", "fusion")}
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    args = sys.argv[1:]
    n = int(args[args.index("--n") + 1]) if "--n" in args else 4000
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 8
    random.seed(7)

    # RESUMABLE: skip stems already captioned (a prior run was interrupted mid-corpus) and APPEND.
    done_stems = set()
    try:
        done_stems = {json.loads(l)["stem"] for l in open(OUT)}
    except FileNotFoundError:
        pass
    fus, dc = _load(FUS), _load(DC)
    simple = [r for r in fus if r["n_extrudes"] <= 2 and r["stem"] not in done_stems]
    complex_ = ([r for r in fus if r["n_extrudes"] >= 3 and r["stem"] not in done_stems]
                + [r for r in dc if r["stem"] not in done_stems])       # DeepCAD is all 3+
    random.shuffle(simple); random.shuffle(complex_)
    # complexity-balanced, complex-leaning (complex is the point): ~55% complex
    remaining = max(0, n - len(done_stems))
    n_cx = min(len(complex_), int(remaining * 0.55))
    n_sp = min(len(simple), remaining - n_cx)
    picked = simple[:n_sp] + complex_[:n_cx]
    random.shuffle(picked)
    print(f"already captioned: {len(done_stems)} | captioning {len(picked)} more "
          f"({n_sp} simple + {n_cx} complex) with {workers} workers", flush=True)

    kept = done = 0
    with open(OUT, "a") as f, cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for row in ex.map(_caption, picked):
            done += 1
            if row is not None:
                f.write(json.dumps(row) + "\n"); f.flush(); kept += 1
            if done % 200 == 0:
                print(f"  ...{done}/{len(picked)} captioned={kept}", flush=True)
    print(f"\nTEXT→CAD CORPUS: {kept}/{len(picked)} captioned → {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
