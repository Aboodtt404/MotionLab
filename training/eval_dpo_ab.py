"""Fair SFT-vs-DPO A/B on the hard set, in the format the adapters were TRAINED on: user(NL caption)
→ code, thinking OFF (the CoT+RAG eval_baseline format has thinking ON → rambles past the timeout AND
mismatches training). Generate via the served adapter, extract code, verify against the spec. Reports
pass-rate + capability_score per model — the honest read on whether DPO helped.
"""
import json
import re
import sys
import urllib.request

sys.path.insert(0, "/home/abdelrahman/MotionLab")
import random

from cad_pipeline.builder import build   # noqa: E402
from cad_pipeline.captions import describe   # noqa: E402
from cad_pipeline.tests.eval_baseline import EVAL_HARD   # noqa: E402
from cad_pipeline.verifier import verify   # noqa: E402

URL = "http://localhost:8002/v1/chat/completions"


def gen(model: str, prompt: str, timeout: int = 120) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2, "top_p": 0.9, "max_tokens": 1536,
        "chat_template_kwargs": {"enable_thinking": False},   # match training; avoid the ramble/timeout
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\s*(.*?)```", text, re.S)
    code = m.group(1) if m else text
    return code if "import cadquery" in code else ("import cadquery as cq\n" + code)


def run_one(model: str, spec) -> bool:
    rng = random.Random(0)
    prompt = describe(spec, rng)["l3"]
    try:
        code = extract_code(gen(model, prompt))
        ns = {}
        exec(code, ns)   # noqa: S102 — sandboxed eval of model output
        result = ns.get("result")
        if result is None:
            return False
        return verify(result, spec).passed
    except Exception:  # noqa: BLE001
        return False


def score(model: str):
    from cad_pipeline.tests.bench_specs import BENCH_LEVELS   # noqa
    passed = 0
    details = []
    for spec in EVAL_HARD:
        ok = run_one(model, spec)
        passed += int(ok)
        details.append((spec.object[:40], ok))
    rate = passed / len(EVAL_HARD)
    return rate, passed, details


def main():
    print(f"Fair A/B (training format, thinking OFF) — EVAL_HARD ({len(EVAL_HARD)} specs)\n")
    for model in ("sft", "dpo"):
        rate, passed, details = score(model)
        print(f"==================== {model.upper()} ====================")
        for name, ok in details:
            print(f"  [{'PASS' if ok else 'fail'}] {name}")
        print(f"  >>> {model.upper()} pass-rate: {passed}/{len(EVAL_HARD)} = {rate:.0%}\n")
    print("AB_DONE")


if __name__ == "__main__":
    main()
