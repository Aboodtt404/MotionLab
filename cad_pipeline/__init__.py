"""MotionLab — Track A (hard-surface text/image → parametric CAD) pipeline.

Verifier-first build. Public surface:
    Spec      — the typed structured contract
    build()   — deterministic spec → CadQuery solid (golden reference)
    verify()  — deterministic feature-level BRep verifier → structured Report
"""
from .builder import build, emit_code
from .executor import run_code
from .loop import GoldenGenerator, MockRetryGenerator, VLLMGenerator, run
from .spec import Spec
from .verifier import Report, Row, measure, verify

__all__ = [
    "Spec", "build", "emit_code", "verify", "measure", "Report", "Row",
    "run_code", "run", "GoldenGenerator", "MockRetryGenerator", "VLLMGenerator",
]
