"""Leg-2 captioner: name + caption-ladder every kept Fusion assembly.

The j1.0.0 joint sets carry only hash ids (25370_adbde9bf_...), so there are NO usable metadata
names — identity comes from the VLM: render the assembled solid (render.py) and ask the served
qwen3.6-27b (:8002 — it takes images) to name it from the picture plus structural facts (joint
type, shapes, sizes). The name becomes `asm.object`, then the L1/L2/L3 caption ladder is generated
by cad_pipeline.asm_captions.asm_describe and gated per level by gate_caption (L1 digit-free,
L2/L3 numbers must map to real structure) — the same both-audiences contract as leg 1.

PARALLEL like the sweep: K worker processes (OCCT build+render is CPU-bound and can hang → killable
subprocess + timeout), and the VLM calls from the workers batch on the vLLM serve.

In:  /workspace/.hf_home/cad_corpus/fusion_joint_assemblies.jsonl              (765 keeps)
Out: /workspace/.hf_home/cad_corpus/fusion_joint_assemblies.captioned.jsonl   ({**rec, name, captions})
     resume-safe: already-captioned set ids are skipped on rerun.

Run:  cad_pipeline/.venv/bin/python -m training.caption_fusion_keeps [limit]
      (SWEEP_WORKERS=8 by default; NAME_MODEL overrides the VLM)
"""
from __future__ import annotations

import base64
import json
import os
import random
import sys
import urllib.request

IN = "/workspace/.hf_home/cad_corpus/fusion_joint_assemblies.jsonl"
OUT = "/workspace/.hf_home/cad_corpus/fusion_joint_assemblies.captioned.jsonl"
BASE_URL = "http://localhost:8002/v1"
MODEL = os.environ.get("NAME_MODEL", "qwen3.6-27b")

_NAME_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "maxLength": 48},
    "what": {"type": "string", "maxLength": 160},
    "part_a": {"type": "string", "maxLength": 28},
    "part_b": {"type": "string", "maxLength": 28},
}, "required": ["name", "what", "part_a", "part_b"]}

_NAME_PROMPT = (
    "This is a small mechanical assembly fragment from a CAD dataset (two mated parts). "
    "From the render and these facts, name what it most plausibly IS.\n"
    "facts: joint={joint}; part shapes={shapes}; sizes(mm)={sizes}; holes={holes}\n"
    "Output JSON {{\"name\": ..., \"what\": ...}}: `name` = a 2-4 word Title Case noun phrase for a "
    "parts library (e.g. 'Hinged Access Panel', 'Pivot Arm Mount', 'Clamp Block Pair') — no "
    "dimensions, no 'Fusion', no hashes; `what` = one plain sentence of what the two parts are and "
    "how they connect; `part_a` = a short snake_case name for the FIRST part, `part_b` = for the "
    "SECOND part — real nouns like 'hinge_bracket', 'pivot_arm', 'clamp_block' (never generic)."
)


def _vlm_name(png: bytes, rec: dict, sizes: list) -> dict:
    holes = "yes" if any("hole" in str(f.get("type", "")) for c in rec["assembly"]["components"]
                         for f in (c["part"].get("features") or [])) else "no"
    text = _NAME_PROMPT.format(joint=rec["joint"].replace("JointType", ""), shapes=rec["shapes"],
                               sizes=sizes, holes=holes,
                               shape_a=rec["shapes"][0], shape_b=rec["shapes"][-1])
    content = [{"type": "text", "text": text},
               {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]
    body = {"model": MODEL, "messages": [{"role": "user", "content": content}],
            "temperature": 0.3, "max_tokens": 320,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "n", "schema": _NAME_SCHEMA}}}
    req = urllib.request.Request(BASE_URL + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(json.loads(r.read())["choices"][0]["message"]["content"])


def caption_one(rec: dict) -> dict:
    """build → render → VLM name → ladder captions (gated). Raises on hard failure."""
    from cad_pipeline.asm_captions import asm_describe, gate_caption
    from cad_pipeline.assembly import Assembly, build_assembly
    from cad_pipeline.render import render_views

    asm = Assembly(**rec["assembly"])
    solid = build_assembly(asm)
    png = render_views(solid, n=1)[0]
    sizes = []
    for c in asm.components:
        e = c.part.envelope or {}
        dims = [round(v, 1) for v in e.values() if isinstance(v, (int, float))][:3]
        sizes.append(f"{c.name}:{dims}")
    named = _vlm_name(png, rec, sizes)
    name = (named.get("name") or "").strip()
    if not name or "fusion" in name.lower():
        raise ValueError(f"bad name: {named!r}")

    # rename the generic base_part/moving_part to the VLM's real nouns — captions AND the training
    # target assembly then carry realistic component names (mates/joints references included)
    def _slug(v: str, fallback: str) -> str:
        v = "_".join("".join(ch if ch.isalnum() else " " for ch in (v or "")).lower().split())[:28]
        return v or fallback
    ren = {"base_part": _slug(named.get("part_a"), "base_part"),
           "moving_part": _slug(named.get("part_b"), "moving_part")}
    if len(set(ren.values())) < 2:
        ren["moving_part"] = ren["moving_part"] + "_2"
    for c in asm.components:
        if c.name in ren:
            c.name = ren[c.name]
            c.part.object = c.name.replace("_", " ")   # _part_phrase reads part.object for the noun
    for mt in asm.mates:
        mt.a = ren.get(mt.a, mt.a); mt.b = ren.get(mt.b, mt.b)
        mt.around = ren.get(mt.around, mt.around)
        mt.parts = [ren.get(p, p) for p in (mt.parts or [])]
    for jt in asm.joints:
        jt.a = ren.get(jt.a, jt.a); jt.b = ren.get(jt.b, jt.b)
    asm.object = name.lower()
    rng = random.Random(hash(rec["set"]) & 0xFFFF)
    captions = None
    for _ in range(6):                    # reroll the ladder until every level passes its gate
        cand = asm_describe(asm, rng)
        if all(gate_caption(lv, cand[lv], asm) for lv in ("l1", "l2", "l3")):
            captions = cand
            break
    if captions is None:
        raise ValueError("caption ladder failed gates")
    return {**rec, "assembly": json.loads(asm.model_dump_json()), "name": name,
            "what": named.get("what", ""), "captions": captions}


def _iso_worker(rec_json: str, q) -> None:
    try:
        q.put(caption_one(json.loads(rec_json)))
    except Exception as e:  # noqa: BLE001
        r = json.loads(rec_json)
        q.put({"set": r["set"], "skip": f"{type(e).__name__}: {str(e)[:120]}"})


def main() -> int:
    import multiprocessing as mp
    import time

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9
    recs = [json.loads(l) for l in open(IN)]
    seen = set()
    try:
        seen = {json.loads(l)["set"] for l in open(OUT)}
    except FileNotFoundError:
        pass
    todo = [r for r in recs if r["set"] not in seen][:limit]
    print(f"captioning {len(todo)} of {len(recs)} keeps ({len(seen)} already done)", flush=True)

    K = max(1, int(os.environ.get("SWEEP_WORKERS", "8")))
    TIMEOUT = 300.0
    pending = [json.dumps(r) for r in todo]
    active: list = []
    done = ok = 0
    t_start = time.monotonic()
    while pending or active:
        while pending and len(active) < K:
            rj = pending.pop(0)
            q = mp.Queue()
            proc = mp.Process(target=_iso_worker, args=(rj, q), daemon=True)
            proc.start()
            active.append((proc, q, json.loads(rj)["set"], time.monotonic()))
        still: list = []
        for proc, q, sid, t0 in active:
            if not proc.is_alive():
                done += 1
                try:
                    r = q.get_nowait()
                except Exception:  # noqa: BLE001
                    r = {"set": sid, "skip": "worker died"}
                if "skip" in r:
                    print(f"{r['set']}: SKIP {r['skip']}", flush=True)
                else:
                    ok += 1
                    with open(OUT, "a") as f:
                        f.write(json.dumps(r) + "\n")
                    print(f"{r['set']}: {r['name']!r}  L1={r['captions']['l1'][:60]!r}", flush=True)
                proc.join()
            elif time.monotonic() - t0 > TIMEOUT:
                proc.kill(); proc.join(); done += 1
                print(f"{sid}: SKIP TIMEOUT >{int(TIMEOUT)}s", flush=True)
            else:
                still.append((proc, q, sid, t0))
        active = still
        time.sleep(0.15)
    mins = (time.monotonic() - t_start) / 60
    print(f"\ncaptioned {ok}/{done} in {mins:.1f} min → {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
