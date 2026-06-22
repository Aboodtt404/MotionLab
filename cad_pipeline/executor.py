"""Track A — sandboxed executor (track-a-design.md §7).

Runs generated CadQuery in an ISOLATED subprocess with a wall-clock timeout, never
in-process. The child applies the layered gates + verifier and returns a JSON
report; this parent parses it. Failures are typed so the retry loop (§9) can route.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from .spec import Spec

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_code(code: str, spec: Spec, timeout: float = 60.0) -> dict:
    """Execute `code` against `spec` in a sandboxed subprocess.

    Returns a dict with `status` in {ok, gate_fail, error, timeout} plus a typed
    `category` ({exec-fix, validity, ...}) and, on success, a `report` dict.
    """
    with tempfile.TemporaryDirectory() as d:
        code_path = os.path.join(d, "code.py")
        spec_path = os.path.join(d, "spec.json")
        with open(code_path, "w") as f:
            f.write(code)
        with open(spec_path, "w") as f:
            f.write(spec.model_dump_json())
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "cad_pipeline._exec_child", code_path, spec_path, d],
                capture_output=True, text=True, timeout=timeout, cwd=_REPO_ROOT,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "category": "exec-fix", "error": f"exceeded {timeout}s"}

        # the child prints exactly one JSON line; tolerate stray prints from generated code
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {"status": "error", "category": "exec-fix", "error": "no JSON from child", "stderr": proc.stderr[-1500:]}
