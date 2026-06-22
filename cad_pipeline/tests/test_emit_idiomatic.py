"""Regression: emit_idiomatic must be geometrically faithful to build().

The Phase-2 targeted layer ships emit_idiomatic(spec) as the fine-tune TARGET code (idiomatic,
matching rag._EXAMPLES — see docs/research/track-a-targeted-layer.md §2). For that to be safe,
the EMITTED string must exec to a verifier-PASS for every known-good spec. We reuse the GOLDEN
set (every shape + feature) as the fidelity fixture.

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.tests.test_emit_idiomatic
"""
import sys

from ..emit_idiomatic import emit_idiomatic
from ..executor import run_code
from .selftest import GOLDEN


def main() -> int:
    npass = 0
    fails = []
    for s in GOLDEN:
        rep = run_code(emit_idiomatic(s), s, timeout=60)
        ok = rep.get("status") == "ok" and rep.get("report", {}).get("passed", False)
        if ok:
            npass += 1
        else:
            fails.append((s.object, rep.get("status"), rep.get("error", "")[:160]))
    print(f"EMIT_IDIOMATIC vs GOLDEN: {npass}/{len(GOLDEN)} exec+verify pass")
    for f in fails:
        print("  FAIL", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
