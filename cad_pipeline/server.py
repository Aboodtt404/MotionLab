"""Dev HTTP bridge: Studio frontend → Track A pipeline. Stdlib only (no new deps, so it
can't disturb a running eval; self-hostable).

POST /generate  {spec: <backend Spec dict>, use_model?: bool, max_attempts?: int}
  → {passed, attempts, history, code, inspection:[{name,expected,measured,delta,within_tol,category}],
     mesh_stl_b64}

Two generator paths:
  • use_model=false (default) — GoldenGenerator: deterministic build(spec) → exact geometry.
    No model call, so it's safe to demo while the GPU is busy.
  • use_model=true — the live model via VLLMGenerator, through a thin generate→verify→retry
    loop (mirrors loop.run but also keeps the winning CODE so we can export its geometry).

Run:  cad_pipeline/.venv/bin/python -m cad_pipeline.server  [port]   (default 8765)
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cadquery as cq

from .builder import build
from .executor import run_code
from .loop import GoldenGenerator, VLLMGenerator, _feedback
from .nl_spec import prompt_to_spec
from .spec import Spec
from .verifier import verify


def _stl_b64(solid) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "part.stl")
        cq.exporters.export(solid.val() if isinstance(solid, cq.Workplane) else solid, p)
        with open(p, "rb") as fh:
            return base64.b64encode(fh.read()).decode()


def _inspection(report: dict) -> list:
    """Verifier rows → the flat shape the Studio ResultCard renders."""
    return [{"name": r["name"], "expected": r["expected"], "measured": r["measured"],
             "delta": r["delta"], "within_tol": r["within_tol"], "category": r["category"]}
            for r in report["rows"]]


def _run_golden(spec: Spec) -> dict:
    solid = build(spec)
    rep = verify(solid, spec).to_dict()
    return {"passed": rep["passed"], "attempts": 1,
            "history": [{"attempt": 1, "status": "ok", "category": "ok"}],
            "code": None, "report": rep, "solid": solid}


def _run_model(spec: Spec, max_attempts: int) -> dict:
    """Thin generate→verify→retry that ALSO keeps the winning code+solid (loop.run discards
    them). Re-execs the model's code in-process to export its geometry — dev-only, trusted."""
    # greeble is a PROCEDURAL, deterministic feature — the builder is exact and ~instant, while asking
    # the LLM to regenerate the (long) greeble program is slow (seen: 150s+) and adds no value. Build it.
    if any(f.type == "greeble" for f in spec.features):
        from .builder import emit_code
        solid = build(spec); rep = verify(solid, spec).to_dict()
        return {"passed": rep["passed"], "attempts": 1, "history": [{"attempt": 1, "status": "ok",
                "category": "ok" if rep["passed"] else "fail"}], "code": emit_code(spec),
                "report": rep, "solid": solid, "fallback": True}
    gen = VLLMGenerator(model=os.environ.get("CAD_MODEL", "qwen3.6-27b"))
    feedback = None
    history, best = [], None
    for attempt in range(1, max_attempts + 1):
        code = gen.generate(spec, feedback)
        res = run_code(code, spec)
        ok = res["status"] == "ok"
        history.append({"attempt": attempt, "status": res["status"], "category": "ok" if ok and res["report"]["passed"] else res["status"]})
        if ok:
            ns = {"cq": cq}
            try:
                exec(code, ns)  # noqa: S102 — dev server, re-exec to capture geometry
                solid = ns.get("result")
            except Exception:  # noqa: BLE001
                solid = None
            cand = {"passed": res["report"]["passed"], "report": res["report"], "code": code, "solid": solid, "attempt": attempt}
            if best is None or (cand["passed"] and not best["passed"]):
                best = cand
            if res["report"]["passed"]:
                break
        feedback = _feedback(res, spec)
    if best is not None and best["passed"]:
        return {"passed": True, "attempts": best["attempt"], "history": history,
                "code": best["code"], "report": best["report"], "solid": best["solid"]}
    # Model codegen failed verification after all retries. The spec is typed + validated, so fall back
    # to the DETERMINISTIC builder — build(spec) renders any valid spec correctly by construction. The
    # model's loft/revolve codegen is occasionally non-deterministic (freelances instead of the loft
    # idiom); this guarantees the frontend always gets correct geometry for a correct spec.
    from .builder import emit_code
    try:
        solid = build(spec)
        rep = verify(solid, spec).to_dict()
        history.append({"attempt": len(history) + 1, "status": "builder_fallback",
                        "category": "ok" if rep["passed"] else "fail"})
        return {"passed": rep["passed"], "attempts": len(history), "history": history,
                "code": emit_code(spec), "report": rep, "solid": solid, "fallback": True}
    except Exception:  # noqa: BLE001 — builder failed too (degenerate spec); return model best-effort
        if best is not None:
            return {"passed": best["passed"], "attempts": best["attempt"], "history": history,
                    "code": best["code"], "report": best["report"], "solid": best["solid"]}
        return {"passed": False, "attempts": len(history), "history": history, "code": None, "report": None, "solid": None}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204); self._cors(); self.end_headers()

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        route = self.path.rstrip("/")
        if route not in ("/generate", "/plan", "/edit", "/critique"):
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            if route == "/generate":
                self._json(200, self._generate(body))
            elif route == "/critique":   # render → VLM look-critique of a greeble spec (Stage C)
                self._json(200, self._critique(body))
            else:   # /plan and /edit operate on multi-part assemblies (the planner)
                self._json(200, self._assembly(route, body))
        except Exception as e:  # noqa: BLE001
            self._json(400, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]})

    def _spec_of(self, body: dict) -> Spec:
        # text→spec via the model (Track A front-end) when a raw prompt is given; else a typed spec.
        return prompt_to_spec(body["prompt"]) if (body.get("prompt") and not body.get("spec")) else Spec(**body["spec"])

    def _generate(self, body: dict) -> dict:
        spec = self._spec_of(body)
        refine_hist = None
        if body.get("refine"):   # Stage C: render→VLM critique loop nudges the greeble params first
            from .critique import refine
            spec, refine_hist = refine(spec, rounds=int(body.get("rounds", 2)))
        out = (_run_model(spec, int(body.get("max_attempts", 3))) if body.get("use_model") else _run_golden(spec))
        resp = {"passed": out["passed"], "attempts": out["attempts"], "history": out["history"], "code": out["code"],
                "spec": spec.model_dump(exclude_none=True),
                "inspection": _inspection(out["report"]) if out["report"] else [],
                "mesh_stl_b64": _stl_b64(out["solid"]) if out.get("solid") is not None else None}
        if refine_hist is not None:
            resp["refine_history"] = refine_hist
            if out.get("solid") is not None:
                from .render import render_views
                resp["render_png_b64"] = base64.b64encode(render_views(out["solid"], 1)[0]).decode()
        return resp

    def _critique(self, body: dict) -> dict:
        from .critique import critique
        from .render import render_views
        spec = self._spec_of(body)
        solid = build(spec)
        c = critique(spec, solid)
        return {"verdict": c["verdict"], "scores": c.get("scores", {}), "suggest": c.get("suggest", {}),
                "notes": c.get("notes", ""), "spec": spec.model_dump(exclude_none=True),
                "render_png_b64": base64.b64encode(render_views(solid, 1)[0]).decode()}

    def _assembly(self, route: str, body: dict) -> dict:
        from .assembly import Assembly, build_assembly, verify_assembly
        from .planner import edit, plan
        asm = (plan(body["prompt"]) if route == "/plan"
               else edit(Assembly(**body["assembly"]), body["instruction"]))
        refine_hist = None
        if route == "/plan" and body.get("refine"):   # render→VLM critique loop improves the blockout
            from .critique import refine_assembly
            asm, refine_hist = refine_assembly(asm, asm.object, rounds=int(body.get("rounds", 2)))
        rep = verify_assembly(asm)
        insp = [{"name": r["name"], "expected": r["expected"], "measured": r["measured"],
                 "delta": None, "within_tol": r["within_tol"], "category": r["category"]} for r in rep["rows"]]
        for c in rep["components"]:
            insp.append({"name": f"part · {c['name']}", "expected": "ok",
                         "measured": "ok" if c["passed"] else ", ".join(c["fails"]) or "fail",
                         "delta": None, "within_tol": c["passed"], "category": "component"})
        out = {"passed": rep["passed"], "assembly": asm.model_dump(), "components": len(asm.components),
               "object": asm.object, "inspection": insp, "mesh_stl_b64": _stl_b64(build_assembly(asm))}
        if refine_hist is not None:
            out["refine_history"] = refine_hist
            from .render import render_views
            out["render_png_b64"] = base64.b64encode(render_views(build_assembly(asm), 1)[0]).decode()
        return out

    def log_message(self, *_):  # quiet
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"cad_pipeline API on http://127.0.0.1:{port}  (POST /generate)")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
