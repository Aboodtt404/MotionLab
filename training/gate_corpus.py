"""Exec-gate a (prompt, code) CadQuery corpus down to a clean, executable subset.

Phase-2 data prep (track-a-corpus-scope.md §5b: "verifier/exec-gated high-quality subset
of CAD-Coder (233K → keep clean)"). The pairs carry NO typed Spec, so we cannot run the
feature-level verifier — we apply the GEOMETRIC-VALIDITY gate instead, exactly Zero-to-CAD's
accept gate (track-a-finetuning.md §2): exec → single solid → positive volume → watertight
→ STEP/STL export round-trip. Programs that clear it are CadQuery the engine can actually
build; the rest is noise that would only teach the model to emit garbage.

Design notes:
- Spec-free mirror of cad_pipeline/_exec_child.py's gate ladder (same order, same checks).
- Robust result extraction: CAD-Coder names its solid `r` and calls show_object(r), NOT
  `result` — so we look through a known name list, then a captured show_object() arg, then
  any Workplane/Shape left in the namespace.
- Parallel across cores (CPU-only — no GPU contention with Phase-1 training).
- Resumable by construction (per the VPS-stop concern): every processed index is journaled
  to a verdicts file; a restart skips what's done. Passers append to the gated file.
- Face count is RECORDED, not gated on hard, so the "drop trivial primitives" threshold can
  be re-tuned downstream WITHOUT re-running the expensive pass.

Run (must use the CadQuery venv, from repo root):
  cad_pipeline/.venv/bin/python training/gate_corpus.py \
      --data /workspace/.hf_home/cad_corpus/cadcoder.jsonl \
      --out  /workspace/.hf_home/cad_corpus/cadcoder_gated.jsonl \
      --workers 24
  # add --limit 1000 for a smoke pass first.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import tempfile
from collections import Counter
from multiprocessing import Pool

# Imported once per worker process (and in the parent) — ~1-2s, paid once.
import cadquery as cq
from cad_pipeline.verifier import _to_shape, measure
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

# Names a generator might bind its final solid to, in priority order.
_RESULT_NAMES = ("result", "r", "res", "solid", "part", "model", "obj", "shape", "body")
_TIMEOUT = 20  # seconds per program; CAD-Coder parts are tiny, a hang means a pathological loop

_TMPDIR = None  # lazy per-worker scratch dir for the export round-trip


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout()


def _is_cq(v) -> bool:
    return isinstance(v, (cq.Workplane, cq.Shape))


def _raw_volume(obj) -> float:
    """RAW solid volume. measure().volume is rounded to 2 dp for verifier tolerance, which
    falsely zeroes the sub-unit (DeepCAD-normalized) parts that dominate CAD-Coder — so the
    positivity gate MUST use the unrounded Mass, not measure()'s value."""
    shape = _to_shape(obj)
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


def _face_count(obj) -> int:
    shape = _to_shape(obj)
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    n = 0
    while ex.More():
        n += 1
        ex.Next()
    return n


def _find_result(ns: dict, shown: list):
    for name in _RESULT_NAMES:
        v = ns.get(name)
        if _is_cq(v):
            return v, name
    for v in reversed(shown):           # last object handed to show_object()
        if _is_cq(v):
            return v, "show_object"
    for name, v in reversed(list(ns.items())):  # last cq object left in scope
        if _is_cq(v):
            return v, name
    return None, None


def _gate(code: str, min_faces: int) -> dict:
    """Run ONE program through the validity ladder. Returns a verdict dict (no full record)."""
    global _TMPDIR
    if _TMPDIR is None:
        _TMPDIR = tempfile.mkdtemp(prefix="gate_")

    shown: list = []
    ns: dict = {"show_object": lambda o=None, *a, **k: shown.append(o)}
    real_export = cq.exporters.export
    cq.exporters.export = lambda *a, **k: None  # neutralize in-program exports (cwd/IO traps)

    signal.alarm(_TIMEOUT)
    try:
        with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn), contextlib.redirect_stderr(dn):
            exec(compile(code, "<corpus>", "exec"), ns)  # noqa: S102 — sandboxed: separate proc, alarm-bounded
    except _Timeout:
        return {"status": "timeout"}
    except BaseException as ex:  # noqa: BLE001 — any failure to build is a reject, not a crash
        return {"status": "exec_error", "reason": type(ex).__name__}
    finally:
        signal.alarm(0)
        cq.exporters.export = real_export

    obj, var = _find_result(ns, shown)
    if obj is None:
        return {"status": "no_result"}

    try:
        signal.alarm(_TIMEOUT)
        m = measure(obj)                 # valid (bool) + solids (int) are exact; volume is 2dp-rounded
        vol = _raw_volume(obj)           # raw Mass — the only trustworthy volume at sub-unit scale
        faces = _face_count(obj)
        signal.alarm(0)
    except _Timeout:
        return {"status": "timeout", "var": var}
    except BaseException as ex:  # noqa: BLE001
        signal.alarm(0)
        return {"status": "measure_error", "reason": type(ex).__name__, "var": var}

    if m.solids == 0:
        return {"status": "no_solid", "var": var}
    if m.solids > 1:
        return {"status": "multi_solid", "solids": m.solids, "var": var}
    if vol <= 0:
        return {"status": "nonpositive_volume", "var": var}
    if not m.valid:
        return {"status": "not_watertight", "faces": faces, "volume": round(vol, 6), "var": var}
    if faces < min_faces:
        return {"status": "too_few_faces", "faces": faces, "volume": round(vol, 6), "var": var}

    # STEP + STL export round-trip (fabricate path) — same as _exec_child.py
    try:
        signal.alarm(_TIMEOUT)
        step = os.path.join(_TMPDIR, "p.step")
        stl = os.path.join(_TMPDIR, "p.stl")
        cq.exporters.export(obj, step)
        cq.exporters.export(obj, stl)
        ok = os.path.getsize(step) > 0 and os.path.getsize(stl) > 0
        signal.alarm(0)
    except BaseException as ex:  # noqa: BLE001
        signal.alarm(0)
        return {"status": "export_fail", "reason": type(ex).__name__, "faces": faces, "var": var}
    if not ok:
        return {"status": "export_fail", "reason": "empty", "faces": faces, "var": var}

    return {"status": "pass", "faces": faces, "volume": round(vol, 6), "var": var}


def _worker(task):
    idx, code, min_faces = task
    signal.signal(signal.SIGALRM, _on_alarm)
    v = _gate(code, min_faces)
    v["idx"] = idx
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True, help="gated passers JSONL (append; resumable)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--min-faces", type=int, default=6, help="recorded regardless; soft floor for pass")
    ap.add_argument("--limit", type=int, default=-1, help="process only the first N records (smoke)")
    a = ap.parse_args()

    verdicts_path = a.out + ".verdicts.jsonl"
    processed = set()
    if os.path.exists(verdicts_path):
        with open(verdicts_path) as f:
            for line in f:
                try:
                    processed.add(json.loads(line)["idx"])
                except Exception:  # noqa: BLE001
                    pass

    records = []
    with open(a.data) as f:
        for line in f:
            records.append(json.loads(line))
    n_total = len(records) if a.limit < 0 else min(a.limit, len(records))
    tasks = [(i, records[i].get("code", ""), a.min_faces)
             for i in range(n_total) if i not in processed]

    print(f"[gate] data={a.data} total={n_total} already_done={len(processed)} "
          f"to_process={len(tasks)} workers={a.workers} min_faces={a.min_faces}", flush=True)
    if not tasks:
        print("[gate] nothing to do.", flush=True)
        _summarize(verdicts_path)
        return

    counts: Counter = Counter()
    passed = 0
    done = 0
    vf = open(verdicts_path, "a")
    gf = open(a.out, "a")
    with Pool(a.workers, maxtasksperchild=300) as pool:
        for v in pool.imap_unordered(_worker, tasks, chunksize=8):
            idx = v["idx"]
            vf.write(json.dumps(v) + "\n")
            counts[v["status"]] += 1
            if v["status"] == "pass":
                rec = records[idx]
                gf.write(json.dumps({
                    "source": rec.get("source", "cad-coder"),
                    "prompt": rec.get("prompt", ""),
                    "code": rec.get("code", ""),
                    "meta": {"faces": v.get("faces"), "volume": v.get("volume"), "var": v.get("var")},
                }) + "\n")
                passed += 1
            done += 1
            if done % 2000 == 0:
                vf.flush(); gf.flush()
                print(f"[gate] {done}/{len(tasks)}  pass={passed} ({100*passed/done:.1f}%)  "
                      f"top={counts.most_common(4)}", flush=True)
    vf.flush(); vf.close(); gf.flush(); gf.close()
    print(f"[gate] DONE this run: processed={done} passed={passed}", flush=True)
    _summarize(verdicts_path)


def _summarize(verdicts_path: str) -> None:
    counts: Counter = Counter()
    face_hist: Counter = Counter()
    total = 0
    with open(verdicts_path) as f:
        for line in f:
            try:
                v = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            counts[v["status"]] += 1
            total += 1
            if v["status"] == "pass":
                fc = v.get("faces") or 0
                face_hist["<=8" if fc <= 8 else "9-20" if fc <= 20 else "21-50" if fc <= 50 else ">50"] += 1
    p = counts.get("pass", 0)
    print(f"\n[gate] ===== SUMMARY ({verdicts_path}) =====", flush=True)
    print(f"  processed total : {total}", flush=True)
    print(f"  PASS            : {p}  ({100*p/max(total,1):.1f}%)", flush=True)
    for status, c in counts.most_common():
        if status == "pass":
            continue
        print(f"  {status:<20}: {c}  ({100*c/max(total,1):.1f}%)", flush=True)
    print(f"  pass face-count : {dict(face_hist)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
