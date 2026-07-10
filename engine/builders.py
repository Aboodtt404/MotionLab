"""Per-representation builders behind the router. Each takes a model_brief and returns a BuiltPart
(artifact + its verifier report), so the engine has ONE uniform result across every representation —
the core of the merge. brep + library build in-process (Track A); mesh calls TRELLIS over the Track-B
:8770 HTTP service; procedural runs Blender bpy. mesh/procedural degrade gracefully (ok=False + reason)
when the service/tooling is down, so the router never crashes.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

TRELLIS_URL = os.environ.get("TRELLIS_URL", "http://localhost:8770")


@dataclass
class BuiltPart:
    name: str
    representation: str
    ok: bool
    report: Dict[str, Any] = field(default_factory=dict)   # verifier_report-shaped
    artifact: Any = None                                   # cq.Workplane | trimesh | glb path
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.ok and bool(self.report.get("passed", self.ok))


# ───────────────────────────────────────────── brep (Track A CadQuery)
def build_brep(brief) -> BuiltPart:
    from cad_pipeline.builder import build
    from cad_pipeline.verifier import verify
    try:
        spec = brief.to_spec()
        wp = build(spec)
        rep = verify(wp, spec)
        return BuiltPart(brief.name, "brep", rep.passed, rep.to_dict(), wp)
    except Exception as e:  # noqa: BLE001
        return BuiltPart(brief.name, "brep", False, {"passed": False}, reason=f"{type(e).__name__}: {e}")


# ───────────────────────────────────────────── library (instantiate a catalog part by name)
def _resolve_library(name: str):
    """Map a brief name onto a library factory + parsed params. Returns (kind, fn, kwargs) or None."""
    from cad_pipeline import partlib, partlib_solids
    n = name.lower()
    size = (re.search(r"m([2-8](?:\.5)?)", n) or [None, None])[1]
    size = f"M{size}" if size else "M3"
    desig = (re.search(r"\b(6\d{2}|623|685)\b", n) or [None, None])[1]
    for key, fn in partlib_solids.SOLID_PARTS.items():
        if key.replace("_", " ") in n or key in n:
            kw = {}
            if key in ("shcs", "hex_nut", "washer"):
                kw = {"size": size}
            elif key == "bearing" and desig:
                kw = {"desig": desig}
            elif key == "involute_gear":
                mt = re.search(r"m\s*=?\s*(\d+(?:\.\d+)?).*?z\s*=?\s*(\d+)", n)
                if mt:
                    kw = {"module": float(mt.group(1)), "teeth": int(mt.group(2))}
            return ("solid", fn, kw)
    for key, fn in partlib.PARTS.items():
        if key.replace("_", " ") in n or key in n:
            return ("spec", fn, {})
    return None


def build_library(brief) -> BuiltPart:
    res = _resolve_library(brief.name + " " + (brief.prompt or ""))
    if res is None:
        return BuiltPart(brief.name, "library", False, {"passed": False},
                         reason="no matching library part")
    kind, fn, kw = res
    try:
        if kind == "solid":
            wp, _datums = fn(**kw)
            valid = bool(wp.val().isValid())
            rep = {"passed": valid, "valid": valid, "solids": 1,
                   "rows": [{"name": "library · valid golden part", "expected": True, "measured": valid,
                             "within_tol": valid, "category": "ok" if valid else "validity"}]}
            return BuiltPart(brief.name, "library", valid, rep, wp)
        # spec-backed library part flows through the normal build→verify
        from cad_pipeline.builder import build
        from cad_pipeline.verifier import verify
        spec = fn(**kw)
        rep = verify(build(spec), spec)
        return BuiltPart(brief.name, "library", rep.passed, rep.to_dict(), spec)
    except Exception as e:  # noqa: BLE001
        return BuiltPart(brief.name, "library", False, {"passed": False}, reason=f"{type(e).__name__}: {e}")


# ───────────────────────────────────────────── mesh (TRELLIS, Track B :8770)
def _post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def build_mesh(brief, *, poll_s: float = 3.0, max_wait_s: float = 900.0) -> BuiltPart:
    """Organic part → TRELLIS over :8770 (/text2mesh or /image2mesh). Async: POST → poll /job → glb_b64.
    Degrades to ok=False if the service is unreachable (the router keeps going)."""
    try:
        endpoint = "/image2mesh" if getattr(brief, "image_b64", None) else "/text2mesh"
        body = {"image_b64": brief.image_b64} if endpoint == "/image2mesh" else {"prompt": brief.prompt or brief.name}
        acc = _post_json(f"{TRELLIS_URL}{endpoint}", body)
        jid = acc.get("job_id")
        if not jid:
            return BuiltPart(brief.name, "mesh", False, {"passed": False}, reason="no job_id from TRELLIS")
        waited = 0.0
        while waited < max_wait_s:
            time.sleep(poll_s); waited += poll_s
            with urllib.request.urlopen(f"{TRELLIS_URL}/job/{jid}", timeout=10) as r:
                st = json.loads(r.read())
            if st.get("status") == "done":
                glb_b64 = (st.get("result") or {}).get("glb_b64")
                if not glb_b64:
                    return BuiltPart(brief.name, "mesh", False, {"passed": False}, reason="job done, no glb_b64")
                d = tempfile.mkdtemp(); p = os.path.join(d, "m.glb")
                open(p, "wb").write(base64.b64decode(glb_b64))
                from cad_pipeline.glb_verify import verify_web
                rep = verify_web(p)
                return BuiltPart(brief.name, "mesh", rep.passed, rep.to_dict(), p)
            if st.get("status") == "error":
                return BuiltPart(brief.name, "mesh", False, {"passed": False},
                                 reason=f"TRELLIS error: {st.get('error')}")
        return BuiltPart(brief.name, "mesh", False, {"passed": False}, reason="TRELLIS timeout")
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        return BuiltPart(brief.name, "mesh", False, {"passed": False},
                         reason=f"TRELLIS :8770 unavailable ({type(e).__name__})")


# ───────────────────────────────────────────── procedural (Blender geometry-nodes / bpy)
def build_procedural(brief) -> BuiltPart:
    """Procedural part → a Blender bpy generator. The brief supplies `procedural = {script, params}`
    (a bpy script path exporting a GLB). Degrades to ok=False if blender or a generator is absent."""
    if shutil.which("blender") is None:
        return BuiltPart(brief.name, "procedural", False, {"passed": False}, reason="blender not on PATH")
    proc = getattr(brief, "procedural", None) or {}
    # bundled generators (staircase/array/window/scatter) via `kind`, or an explicit `script`
    bundled = os.path.join(os.path.dirname(__file__), "tools", "bpy_generate.py")
    kind = proc.get("kind")
    script = proc.get("script") if proc.get("script") and os.path.exists(proc["script"]) else (
        bundled if kind else None)
    if script is None:
        return BuiltPart(brief.name, "procedural", False, {"passed": False},
                         reason="no procedural generator (need brief.procedural.kind or .script)")
    args = ([kind, json.dumps(proc.get("params", {}))] if kind else [json.dumps(proc.get("params", {}))])
    try:
        d = tempfile.mkdtemp(); glb = os.path.join(d, "p.glb")
        subprocess.run(["blender", "--background", "--python", script, "--", *args, glb],
                       capture_output=True, text=True, timeout=300)
        if not os.path.exists(glb):
            return BuiltPart(brief.name, "procedural", False, {"passed": False}, reason="generator produced no GLB")
        from cad_pipeline.glb_verify import verify_web
        rep = verify_web(glb)
        return BuiltPart(brief.name, "procedural", rep.passed, rep.to_dict(), glb)
    except Exception as e:  # noqa: BLE001
        return BuiltPart(brief.name, "procedural", False, {"passed": False}, reason=f"{type(e).__name__}: {e}")


BUILDERS = {"brep": build_brep, "library": build_library, "mesh": build_mesh, "procedural": build_procedural}
