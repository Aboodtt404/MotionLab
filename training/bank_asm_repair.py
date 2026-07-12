"""Bank assembly-repair transcripts: varied briefs → run_assembly(max_attempts=3) in-process →
RepairTranscript JSONL. Each episode also logs a one-line summary (pass, attempts, fail rows) so
the bank's quality is inspectable at a glance. Idempotent append; re-runs add new episodes.

Run:  cad_pipeline/.venv/bin/python -m training.bank_asm_repair [n_rounds]
"""
from __future__ import annotations

import json
import sys
import time

from cad_pipeline.asm_loop import VLLMAsmGenerator, asm_transcript, run_assembly

OUT = "/workspace/.hf_home/cad_corpus/asm_repair_bank.jsonl"
LOG = "/workspace/.hf_home/cad_corpus/asm_repair_bank.log"

BRIEFS = [
    "a car, about 3.6 m long: a real body silhouette (hood, windshield, roof, trunk) over a "
    "suspended chassis, four wheels 600 mm diameter x 200 mm wide at a 2300 mm wheelbase, each "
    "wheel seated in its own wheel arch, mounted on a stub axle and spinning freely about the y-axis",
    "a six-wheeled planetary rover: a flat deck chassis at ride height, six wheels 400 mm diameter "
    "in arches under a sloped instrument body, each wheel on its own stub axle spinning about y",
    "a delivery cart: rectangular tub body with a real side silhouette, four wheels 250 mm diameter "
    "at the corners in wheel arches, each on a stub axle with a revolute joint about y",
    "a pickup truck about 4.5 m long: cab-and-bed side silhouette over a suspended chassis, four "
    "wheels 700 mm diameter x 250 mm wide, 2900 mm wheelbase, wheels in arches on stub axles, "
    "spinning about the y-axis",
    "a heavy flatbed trolley: low deck 100 mm above the floor, four wheels 180 mm diameter at a "
    "900 x 500 mm footprint, each wheel in a cutout arch under the deck, revolute about y",
    "a sci-fi armored rover: angular hull with a proper side silhouette over a suspended frame, "
    "four wheels 500 mm diameter in tight 30 mm-clearance arches, stub axles, revolute joints about y",
    "a hinged toolbox: a box body resting on the ground with a lid on a revolute hinge about the "
    "x-axis, limits 0 to 100 degrees, the lid clearing the body through its whole swing",
    "a desk fan: a heavy round base on the floor, a vertical column, a motor hub on top and a "
    "three-blade rotor on a revolute joint about the y-axis spinning freely",
    "a compact car about 3 m long with a rounded fastback silhouette, four wheels 550 mm diameter "
    "at a 2000 mm wheelbase seated in arches, stub axles, spinning about y",
    "a wheelbarrow: a tapered tub, two handles, one front wheel 350 mm diameter in an arch under "
    "the nose on a stub axle with a revolute joint about y, two rear legs resting on the ground",
]


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    gen = VLLMAsmGenerator()
    meta = {"model": "qwen3.6-27b", "provider": "vllm-local", "role": "assembly-planner"}
    for rnd in range(rounds):
        for i, brief in enumerate(BRIEFS):
            t0 = time.time()
            try:
                out = run_assembly(brief, gen, max_attempts=3)
                tr = asm_transcript(brief, out, meta)
                with open(OUT, "a") as f:
                    f.write(tr.model_dump_json() + "\n")
                last = (out.get("attempt_log") or [{}])[-1].get("report", {})
                fails = [r["name"] for r in last.get("rows", []) if not r.get("within_tol")]
                line = (f"[r{rnd} b{i}] passed={out.get('passed')} attempts={len(out.get('attempt_log', []))} "
                        f"{round(time.time() - t0)}s fails={fails[:4]} :: {brief[:60]}")
            except Exception as e:  # noqa: BLE001 — one bad episode must not stop the bank
                line = f"[r{rnd} b{i}] EPISODE ERROR {type(e).__name__}: {e} :: {brief[:60]}"
            print(line, flush=True)
            with open(LOG, "a") as f:
                f.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
