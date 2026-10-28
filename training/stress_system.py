"""System stress for the production stack — the SERVICES, not the model.

Hits the real HTTP APIs (CAD :8765, Track B :8770) the way the Studio does, and watches
process RSS + GPU so failures show up as numbers, not vibes.

  burst  N simultaneous /plan jobs           — queue sanity, latency spread, error rate
  soak   N sequential /plan jobs             — RSS growth per job (leak curve), stability
  chaos  Track A plan + Track B text2mesh    — GPU-lock contention + VRAM headroom under
         + /animate_clip (few iters)           the "demoing everything at once" scenario

  cad_pipeline/.venv/bin/python -m training.stress_system burst --n 10
  cad_pipeline/.venv/bin/python -m training.stress_system soak --n 200
  cad_pipeline/.venv/bin/python -m training.stress_system chaos
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

CAD = "http://127.0.0.1:8765"
TRACKB = "http://127.0.0.1:8770"
OUT_DIR = "/workspace/.hf_home/eval_asm1"

BURST_BRIEF = "a small stand: round top plate on three splayed legs"
SOAK_BRIEFS = [
    "a 4-legged stool, round seat",
    "a two-shelf rack on four posts",
    "a PCB on four corner standoffs on a base plate",
    "a small table, rectangular top on four legs",
    "a sensor mast: base plate, pole, sensor head",
]


def _post(base: str, route: str, body: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(base + route, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _poll(base: str, jid: str, timeout_s: int = 3600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        with urllib.request.urlopen(f"{base}/job/{jid}", timeout=30) as r:
            j = json.loads(r.read())
        if j.get("status") in ("done", "error"):
            return j
        time.sleep(5)
    return {"status": "timeout"}


def _rss_mb(pattern: str) -> int:
    try:
        pids = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True
                              ).stdout.split()
        total = 0
        for p in pids:
            with open(f"/proc/{p}/status") as f:
                for line in f:
                    if line.startswith("VmRSS"):
                        total += int(line.split()[1]) // 1024
        return total
    except Exception:  # noqa: BLE001
        return -1


def _vram_mb() -> int:
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    return int(r.stdout.strip().splitlines()[0])


def _plan_job(brief: str, results: list, idx: int) -> None:
    t0 = time.time()
    try:
        jid = _post(CAD, "/plan", {"prompt": brief})["job_id"]
        j = _poll(CAD, jid, timeout_s=1800)
        results[idx] = {"status": j.get("status"), "passed": j.get("passed"),
                        "seconds": round(time.time() - t0)}
    except Exception as e:  # noqa: BLE001
        results[idx] = {"status": "exc", "error": str(e)[:150],
                        "seconds": round(time.time() - t0)}


def burst(n: int) -> dict:
    rss0, vram0 = _rss_mb("cad_pipeline.server"), _vram_mb()
    results: list = [None] * n
    ts = [threading.Thread(target=_plan_job, args=(BURST_BRIEF, results, i)) for i in range(n)]
    t0 = time.time()
    for t in ts:
        t.start()
        time.sleep(0.3)                      # near-simultaneous, not a thundering herd
    for t in ts:
        t.join()
    secs = sorted(r["seconds"] for r in results if r)
    return {"n": n, "wall": round(time.time() - t0),
            "ok": sum(1 for r in results if r and r["status"] == "done"),
            "passed": sum(1 for r in results if r and r.get("passed")),
            "p50": secs[len(secs) // 2], "max": secs[-1],
            "rss_mb": [rss0, _rss_mb("cad_pipeline.server")],
            "vram_mb": [vram0, _vram_mb()], "results": results}


def soak(n: int) -> dict:
    curve = []
    ok = passed = 0
    for i in range(n):
        results: list = [None]
        _plan_job(SOAK_BRIEFS[i % len(SOAK_BRIEFS)], results, 0)
        r = results[0] or {}
        ok += r.get("status") == "done"
        passed += bool(r.get("passed"))
        if i % 10 == 0 or i == n - 1:
            pt = {"i": i, "rss_mb": _rss_mb("cad_pipeline.server"), "vram_mb": _vram_mb(),
                  "status": r.get("status"), "seconds": r.get("seconds")}
            curve.append(pt)
            print(f"[soak {i + 1}/{n}] {pt}", flush=True)
    return {"n": n, "ok": ok, "passed": passed, "curve": curve}


def chaos() -> dict:
    """Everything at once — Track A plan + Track B text2mesh + a short animate run."""
    out: dict = {"vram_start": _vram_mb()}
    results: list = [None]
    plan_t = threading.Thread(target=_plan_job, args=(BURST_BRIEF, results, 0))

    glb_path = "/workspace/.hf_home/SkinTokens/results/probe_creature_rigged.glb"
    anim_body = {"glb_b64": base64.b64encode(open(glb_path, "rb").read()).decode(),
                 "prompt": "the creature walks forward slowly", "iters": 10}

    t0 = time.time()
    plan_t.start()
    mesh_jid = _post(TRACKB, "/text2mesh", {"prompt": "a weathered sci-fi supply crate"},
                     timeout=120)["job_id"]
    anim_jid = _post(TRACKB, "/animate_clip", anim_body, timeout=300)["job_id"]

    peak = 0
    done: dict = {}
    while len(done) < 2:
        for tag, jid in (("mesh", mesh_jid), ("anim", anim_jid)):
            if tag in done:
                continue
            with urllib.request.urlopen(f"{TRACKB}/job/{jid}", timeout=30) as r:
                j = json.loads(r.read())
            if j.get("status") in ("done", "error"):
                done[tag] = {"status": j["status"], "error": (j.get("error") or "")[:150]}
                print(f"[chaos] {tag}: {done[tag]}", flush=True)
        peak = max(peak, _vram_mb())
        if time.time() - t0 > 5400:
            done.setdefault("mesh", {"status": "timeout"})
            done.setdefault("anim", {"status": "timeout"})
        time.sleep(10)
    plan_t.join(timeout=1800)
    out.update(plan=results[0], jobs=done, vram_peak=peak, wall=round(time.time() - t0),
               trackb_alive=bool(_post_health(TRACKB)), cad_alive=bool(_post_health(CAD)))
    return out


def _post_health(base: str) -> bool:
    try:
        with urllib.request.urlopen(base + "/health", timeout=10) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["burst", "soak", "chaos"])
    ap.add_argument("--n", type=int, default=10)
    a = ap.parse_args()
    fn = {"burst": lambda: burst(a.n), "soak": lambda: soak(a.n), "chaos": chaos}[a.mode]
    res = fn()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = f"{OUT_DIR}/system_{a.mode}_{time.strftime('%m%d_%H%M')}.json"
    with open(path, "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps({k: v for k, v in res.items() if k not in ("results", "curve")}, indent=2))
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
