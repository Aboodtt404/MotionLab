"""Confirmation eval: SFT vs DPO on the FULL spec sets (golden 27 + hard 10 + bench 14 = 51), in the
adapters' training format (NL description → code, thinking OFF, no CoT system, no RAG — what they were
trained on). Three metrics per Fable §02:
  • pass@1        — 1 sample, temp 0.2
  • pass@k (k=3)  — 3 samples, temp 0.7, any passes (averages out temperature noise)
  • pass@3-repair — the loop.run generate→verify→typed-feedback→retry (≤3), temp 0.2 (repair competence)
Reuses cad_pipeline.loop.run for the repair loop (its _feedback builds the typed retry message).
"""
import json
import random
import re
import sys
import urllib.request

sys.path.insert(0, "/home/abdelrahman/MotionLab")

from cad_pipeline.builder import build   # noqa: E402
from cad_pipeline.captions import describe   # noqa: E402
from cad_pipeline.loop import VLLMGenerator, run   # noqa: E402
from cad_pipeline.tests.bench_specs import BENCH_LEVELS   # noqa: E402
from cad_pipeline.tests.eval_baseline import EVAL_HARD   # noqa: E402
from cad_pipeline.tests.selftest import GOLDEN   # noqa: E402
from cad_pipeline.verifier import verify   # noqa: E402

URL = "http://localhost:8002/v1/chat/completions"


def _extract(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    code = m.group(1) if m else text
    return code if "import cadquery" in code else ("import cadquery as cq\n" + code)


class TrainFmtGen(VLLMGenerator):
    """The served adapter in its TRAINING format: NL description → code, no system, no RAG, thinking off,
    capped tokens (temp-0 repetition was the earlier timeout). Returns extracted code so loop.run runs."""
    def __init__(self, model: str, temp: float = 0.2):
        super().__init__(model=model, rag=False)
        self.temp = temp

    def generate(self, spec, feedback=None):
        prompt = describe(spec, random.Random(0))["l3"]
        if feedback:
            prompt += f"\n\nThe previous attempt failed verification — fix ONLY these issues, keep the rest:\n{feedback}"
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}],
                           "temperature": self.temp, "top_p": 0.9, "max_tokens": 2048,
                           "chat_template_kwargs": {"enable_thinking": False}}).encode()
        req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return _extract(json.loads(r.read())["choices"][0]["message"]["content"])


def _one_pass(model: str, spec, temp: float) -> bool:
    try:
        gen = TrainFmtGen(model, temp)
        ns = {}
        exec(gen.generate(spec), ns)   # noqa: S102
        return ns.get("result") is not None and verify(ns["result"], spec).passed
    except Exception:  # noqa: BLE001
        return False


def _pass3_repair(model: str, spec) -> bool:
    try:
        return bool(run(spec, TrainFmtGen(model, 0.2), max_attempts=3).get("passed"))
    except Exception:  # noqa: BLE001
        return False


SETS = {"golden": GOLDEN, "hard": EVAL_HARD, "bench": None}


def main():
    from cad_pipeline.tests.bench_specs import EVAL_BENCH
    SETS["bench"] = EVAL_BENCH
    specs = [(n, s) for n, lst in SETS.items() for s in lst]
    print(f"Confirmation A/B — {len(specs)} specs (golden {len(GOLDEN)} + hard {len(EVAL_HARD)} + bench {len(EVAL_BENCH)})\n")
    for model in ("sft", "dpo"):
        p1 = pk = p3 = 0
        for _set, spec in specs:
            a1 = _one_pass(model, spec, 0.2)
            samples = [a1] + [_one_pass(model, spec, 0.7) for _ in range(2)]   # pass@k, k=3
            a3 = a1 or _pass3_repair(model, spec)
            p1 += int(a1); pk += int(any(samples)); p3 += int(a3)
        n = len(specs)
        print(f"==================== {model.upper()} ====================")
        print(f"  pass@1        : {p1}/{n} = {p1/n:.0%}")
        print(f"  pass@k (k=3)  : {pk}/{n} = {pk/n:.0%}")
        print(f"  pass@3-repair : {p3}/{n} = {p3/n:.0%}\n", flush=True)
    print("CONFIRM_DONE")


if __name__ == "__main__":
    main()
