"""In-subprocess harness for the sandboxed executor (track-a-design.md §7).

Runs UNTRUSTED generated CadQuery, applies the cheap→expensive gates, runs the
deterministic verifier, exports STEP/STL, and prints ONE JSON line back to the
parent. Untrusted code never runs in the parent process; only JSON crosses back.

Invoked as:  python -m cad_pipeline._exec_child <code.py> <spec.json> <outdir>
(v0 isolation = subprocess + wall-clock timeout; seccomp/container hardening is a
later step, noted in §7.)
"""
import json
import os
import sys
import traceback


def main() -> None:
    code_path, spec_path, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        from cad_pipeline.spec import Spec
        from cad_pipeline.verifier import measure, verify

        code = open(code_path).read()
        spec = Spec(**json.load(open(spec_path)))

        ns: dict = {}
        exec(compile(code, "<generated>", "exec"), ns)  # noqa: S102 — sandboxed subprocess
        result = ns.get("result")
        if result is None:
            print(json.dumps({"status": "error", "category": "exec-fix", "error": "code did not assign `result`"}))
            return

        import cadquery as cq

        # cheap→expensive gates (short-circuit) — §7
        m = measure(result)
        gates = {"single_solid": m.solids == 1, "positive_volume": m.volume > 0, "watertight": m.valid}
        if not all(gates.values()):
            failed = [k for k, v in gates.items() if not v]
            print(json.dumps({"status": "gate_fail", "category": "validity", "gates": gates, "failed": failed}))
            return

        # STEP/STL export round-trip (fabricate path)
        exports = {}
        try:
            step = os.path.join(outdir, "part.step"); cq.exporters.export(result, step); exports["step"] = os.path.getsize(step) > 0
            stl = os.path.join(outdir, "part.stl"); cq.exporters.export(result, stl); exports["stl"] = os.path.getsize(stl) > 0
        except Exception as ex:  # noqa: BLE001
            print(json.dumps({"status": "gate_fail", "category": "validity", "error": "export round-trip failed: " + str(ex)}))
            return

        # feature-level deterministic verify
        rep = verify(result, spec)
        print(json.dumps({"status": "ok", "gates": gates, "exports": exports, "report": rep.to_dict()}))
    except Exception:  # noqa: BLE001
        print(json.dumps({"status": "error", "category": "exec-fix", "error": traceback.format_exc()}))


if __name__ == "__main__":
    main()
