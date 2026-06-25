"""GRPO reward — multiplicative exec-gate over the deterministic verifier.

Grounded in track-a-finetuning.md §3 (Stage-4 reward) + §1 (Stage-0 fast/slow split):

    R = R_exec · (W_FEAT·R_feat + W_TOPO·R_topo + W_GEO·R_geo) + W_FMT·R_fmt

- **R_exec ∈ {0,1}** — exec + single-solid + watertight/validity gate. MASKS all geometric
  reward on failure (CAD-RL 2508.10118 multiplicative gate — no reward leakage from malformed
  rollouts). `run_code` short-circuits on exec/gate failure, so we never pay for feature
  introspection on dead rollouts (the §1 fast/slow split — fast reject, slow verify only on survivors).
- **R_feat (dominant, our core IP)** — the verifier's per-feature pass fraction, INCLUDING the
  resolve-twice SELECTOR BINDING: a fillet on the wrong edges scores 0 here, which no CD/IoU
  proxy can see. This is the dense signal and the documented edge over Chamfer-only rewards.
- **R_topo** — structural integrity: single solid + no unexpected/over-count features.
- **R_geo** — a small BOUNDED volume-agreement tie-breaker vs the deterministic builder's
  reference, kept tiny so the model can't trade feature-correctness for raw volume.
- **R_fmt** — strict output contract (a fenced code block); tiny weight (format is trivial to game).

Subprocess bridge for the GRPO trainer (which runs in serve_venv, no cadquery):
    echo '{"output": "...", "spec": {...}}' | cad_pipeline/.venv/bin/python -m cad_pipeline.reward
"""
from __future__ import annotations

import json
import re
import sys
from typing import Optional

from .builder import build
from .executor import run_code
from .loop import VLLMGenerator
from .spec import Spec

W_FEAT, W_TOPO, W_GEO, W_FMT = 0.6, 0.2, 0.1, 0.1


def _fmt_score(model_output: str) -> float:
    """Strict output contract: a fenced ```python code block (CAD-Coder)."""
    return 1.0 if re.search(r"```(?:python)?\s.*?```", model_output, re.S) else 0.0


def _ref_volume(spec: Spec) -> Optional[float]:
    """Reference volume from the deterministic builder (ground truth for the bounded geo term)."""
    try:
        s = build(spec)
        s = s.val() if hasattr(s, "val") else s
        return float(s.Volume())
    except Exception:  # noqa: BLE001 — geo is a bounded extra; never let it break the reward
        return None


def compute_reward(model_output: str, spec: Spec, timeout: float = 60.0) -> dict:
    fmt = _fmt_score(model_output)
    code = VLLMGenerator._extract_code(model_output)
    res = run_code(code, spec, timeout=timeout)

    # --- fast path: exec / gate failure → geometric reward fully masked (multiplicative gate) ---
    if res.get("status") != "ok":
        return {"reward": round(W_FMT * fmt, 4), "exec": 0.0, "feat": 0.0, "topo": 0.0,
                "geo": 0.0, "fmt": fmt, "status": res.get("status"), "note": "exec/gate fail — masked"}
    rep = res["report"]
    if not (rep.get("valid") and rep.get("solids") == 1 and rep.get("volume", 0) > 0):
        return {"reward": round(W_FMT * fmt, 4), "exec": 0.0, "feat": 0.0, "topo": 0.0,
                "geo": 0.0, "fmt": fmt, "status": "gate", "note": "not a single valid positive-volume solid"}

    # --- slow path: full feature-level introspection (only reached by survivors) ---
    rows = rep["rows"]
    feat_rows = [r for r in rows if r["category"] != "dfm"]   # DFM = manufacturability advisory, not correctness
    r_feat = sum(r["within_tol"] for r in feat_rows) / len(feat_rows) if feat_rows else 1.0

    n_unexpected = sum(1 for r in rows if r["category"] == "unexpected")
    r_topo = max(0.0, 1.0 - 0.5 * n_unexpected)              # single-solid already gated above

    vref, vmod = _ref_volume(spec), rep.get("volume", 0.0)
    r_geo = 1.0 if vref is None else max(0.0, 1.0 - abs(vmod - vref) / max(vref, 1e-6))

    reward = W_FEAT * r_feat + W_TOPO * r_topo + W_GEO * r_geo + W_FMT * fmt  # R_exec == 1 here
    return {"reward": round(reward, 4), "exec": 1.0, "feat": round(r_feat, 4), "topo": round(r_topo, 4),
            "geo": round(r_geo, 4), "fmt": fmt, "passed": rep["passed"], "status": "ok"}


def _drop_nulls(v):
    """Recursively strip None-valued keys. The corpus serializes inapplicable dims as explicit
    `null` (a box envelope carries `diameter: null`), but `envelope: Dict[str, float]` rejects None
    and the model logic keys off ABSENCE (`"diameter_top" in envelope`, `e.get(...)`). Restoring the
    keys-absent convention is the correct fix; typing the dict Optional would silently break
    `loft_top_round()`. Without this, every GRPO rollout's spec fails validation → reward 0."""
    if isinstance(v, dict):
        return {k: _drop_nulls(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_drop_nulls(x) for x in v]
    return v


if __name__ == "__main__":  # GRPO trainer bridge (stdin JSON → reward JSON on stdout)
    payload = json.loads(sys.stdin.read())
    print(json.dumps(compute_reward(payload["output"], Spec(**_drop_nulls(payload["spec"])))))
