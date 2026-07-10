"""The five composable pipeline schemas — `fable_run/out/04_schemas.md`, adopted verbatim as the
canonical data contract for Track A (and, from Phase 5, the whole router).

    model_brief   — what to build for ONE asset (representation, envelope, features, budgets)
    assembly_brief— a multi-part assembly: components (each a model_brief) + named mates
    verifier_report — the oracle's structured verdict, row by row (the ONLY authoritative pass signal)
    failure_report— one attempt's typed failure + the exact feedback issued
    repair_transcript — a full generate→verify→retry episode (the unit of repair-training data)

They compose by `$ref`: an assembly_brief embeds component model_briefs; a failure_report embeds
verifier check-rows; a repair_transcript embeds a verifier_report (+ optional failure_report) per attempt.
Field names are snake_case and stable; enum values + required fields are APPEND-ONLY (Fable's stability
rule) — a breaking change bumps the `$id` version segment.

Conformance strategy (why this module and not just corpus.py): the live verifier/loop use their own
internal category strings (hyphenated: `selector-binding`, `exec-fix`). Rather than destabilise the
retry-routing by renaming them at every call site, we NORMALISE at the emit boundary — `normalize_category`
/ `normalize_failure_category` map the live values onto Fable's exact snake_case enums, so every EMITTED
report / sample is fully conformant while the running pipeline is untouched. The schema is the interchange
contract; internal variable names are an implementation detail.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1
SCHEMA_BASE_ID = "https://schemas.motionlab.dev/3d"


def _sid(name: str) -> str:
    return f"{SCHEMA_BASE_ID}/{name}/{SCHEMA_VERSION}.json"


# ─────────────────────────────────────────────────────────────── shared enums (single source)
# Fable's closed check_category (04_schemas §Shared enums) …
CHECK_CATEGORY_CORE: Tuple[str, ...] = (
    "ok", "dimensional", "selector_binding", "missing_feature", "integrity",
    "dfm", "validity", "structure", "disconnected", "component",
)
# … + our append-only extensions (documented; never removes a core value):
CHECK_CATEGORY_EXT: Tuple[str, ...] = ("blend", "boolean_loss", "boolean_noop", "recon_fit")
CHECK_CATEGORY: Tuple[str, ...] = CHECK_CATEGORY_CORE + CHECK_CATEGORY_EXT

FAILURE_STATUS: Tuple[str, ...] = ("exec_error", "timeout", "gate_fail", "verify_fail", "refused")
FAILURE_CATEGORY: Tuple[str, ...] = (
    "exec_fix", "validity", "dimensional_fix", "selector_binding_fix",
    "dfm_fix", "structure_fix", "escalate",
)

# live → canonical maps (hyphen→underscore + a few semantic folds onto Fable's core enum)
_CATEGORY_MAP: Dict[str, str] = {
    "selector-binding": "selector_binding",
    "boolean-loss": "boolean_loss",
    "boolean-noop": "boolean_noop",
    "recon-fit": "recon_fit",
}
_FAILURE_CATEGORY_MAP: Dict[str, str] = {
    "exec-fix": "exec_fix",
    "selector-binding-fix": "selector_binding_fix",
    "dimensional-fix": "dimensional_fix",
    "dfm-fix": "dfm_fix",
    "structure-fix": "structure_fix",
}


def normalize_category(live: Optional[str]) -> str:
    """Map a live verifier row-category onto the conformant `check_category` vocabulary."""
    if not live:
        return "ok"
    c = _CATEGORY_MAP.get(live, live.replace("-", "_"))
    return c if c in CHECK_CATEGORY else "integrity"   # unknowns fold to integrity (never silently drop)


def normalize_failure_category(live: Optional[str]) -> str:
    """Map a live loop failure-category onto the conformant `failure_report.category` vocabulary."""
    if not live:
        return "escalate"
    c = _FAILURE_CATEGORY_MAP.get(live, live.replace("-", "_"))
    return c if c in FAILURE_CATEGORY else "escalate"


# ───────────────────────────────────────────────────────────────────────── 1. model_brief
TargetUse = Literal["render", "game", "web", "print", "cad", "film"]
Representation = Literal["brep", "mesh", "procedural", "sdf"]
Units = Literal["mm", "m"]
UpAxis = Literal["z", "y"]
BriefShape = Literal["box", "cylinder", "loft", "revolve", "sweep", "freeform"]
FeatureType = Literal["through_hole", "hole_pattern", "fillet", "chamfer", "pocket", "draft",
                      "counterbore", "countersink", "mirror", "shell", "var_fillet", "thread", "greeble"]
OutputFormat = Literal["step", "stl", "obj", "glb", "fbx", "blend", "3mf", "usdz"]


class BriefFeature(BaseModel):
    type: FeatureType
    params: Dict[str, Any] = Field(default_factory=dict)


class Budgets(BaseModel):
    max_triangles: Optional[int] = None
    max_file_mb: Optional[float] = None
    min_wall_mm: Optional[float] = None
    max_overhang_deg: Optional[float] = None


class ModelBrief(BaseModel):
    """What to build for ONE asset. `representation`/`target_use` are what let a single brief drive
    CAD *or* mesh *or* print — the precondition for the Phase-5 representation router."""
    brief_id: str
    name: str
    prompt: Optional[str] = None
    target_use: TargetUse
    representation: Representation
    units: Units
    up_axis: UpAxis
    shape: Optional[BriefShape] = None
    envelope_mm: Dict[str, float] = Field(default_factory=dict)
    features: List[BriefFeature] = Field(default_factory=list)
    tolerance_mm: float = 0.1
    budgets: Optional[Budgets] = None
    output_formats: List[OutputFormat] = Field(default_factory=lambda: ["step"])
    style: Optional[str] = None
    acceptance: List[str] = Field(default_factory=list)

    # ---- adapters: brief ↔ internal Spec (our B-rep build model) -----------------------------
    @classmethod
    def from_spec(cls, spec: Any, *, brief_id: str, target_use: TargetUse = "cad",
                  output_formats: Optional[List[OutputFormat]] = None) -> "ModelBrief":
        """Lift an internal Spec into a conformant model_brief (representation=brep, CAD conventions)."""
        env = dict(getattr(spec, "envelope", {}) or {})
        feats = [BriefFeature(type=f.type, params={k: v for k, v in f.model_dump().items() if k != "type"})
                 for f in getattr(spec, "features", []) if hasattr(f, "type")]
        sh = getattr(spec, "shape", None)
        return cls(
            brief_id=brief_id, name=getattr(spec, "object", "part"),
            target_use=target_use, representation="brep", units="mm", up_axis="z",
            shape=sh if sh in ("box", "cylinder", "loft", "revolve", "sweep") else "freeform",
            envelope_mm=env, features=feats, tolerance_mm=float(getattr(spec, "tolerance", 0.1) or 0.1),
            output_formats=output_formats or ["step"],
        )


# ───────────────────────────────────────────────────────────────────────── 2. assembly_brief
MateKind = Literal["ground", "stack", "radial", "coaxial", "flush", "mirror", "attach",
                   "corners", "cutout"]   # last two are our append-only extensions
ComponentRole = Literal["seat", "top", "base", "leg", "support", "arm", "panel", "body", "hub",
                        "fastener", "other"]


class BriefMate(BaseModel):
    """A named structural relationship — placement is RELATIONSHIPS, never coordinates; the
    deterministic solver (assembly.solve_layout) computes positions."""
    kind: MateKind
    a: Optional[str] = None
    b: Optional[str] = None
    parts: Optional[List[str]] = None
    around: Optional[str] = None
    count: Optional[int] = None
    radius_mm: Optional[float] = None
    splay_deg: Optional[float] = None
    side: Optional[Literal["+x", "-x", "+y", "-y", "+z", "-z"]] = None
    overlap_mm: Optional[float] = None
    plane: Optional[Literal["YZ", "XZ", "XY"]] = None


class BriefComponent(BaseModel):
    component_id: str
    role: ComponentRole = "other"
    brief: ModelBrief
    count: int = 1


class AssemblyBrief(BaseModel):
    """A multi-part assembly: components (each a model_brief) + named mates. Every component must be
    reachable through mates."""
    brief_id: str
    name: str
    prompt: Optional[str] = None
    units: Units = "mm"
    components: List[BriefComponent]
    mates: List[BriefMate] = Field(default_factory=list)
    fuse: bool = True
    clearance_mm: Optional[float] = None
    overall_envelope_mm: Dict[str, float] = Field(default_factory=dict)


# ───────────────────────────────────────────────────────────────────────── 3. verifier_report
class CheckRow(BaseModel):
    """One verifier measurement — expected · measured · Δ · within_tol · category."""
    name: str
    expected: Union[float, str, bool, None] = None
    measured: Union[float, str, bool, None] = None
    delta: Optional[float] = None
    within_tol: bool
    category: str = "ok"   # a value from CHECK_CATEGORY (normalized at construction via from_live)

    @classmethod
    def from_live(cls, row: Dict[str, Any]) -> "CheckRow":
        return cls(name=row["name"], expected=row.get("expected"), measured=row.get("measured"),
                   delta=row.get("delta"), within_tol=bool(row.get("within_tol")),
                   category=normalize_category(row.get("category")))


class VerifierReport(BaseModel):
    """The oracle's verdict — the ONLY authoritative pass signal. `passed` iff valid AND single-solid
    contract met AND every row within_tol."""
    report_id: str
    subject_ref: str
    passed: bool
    valid: bool
    solids: int
    volume_mm3: Optional[float] = None
    rows: List[CheckRow]
    failure_categories: List[str] = Field(default_factory=list)
    toolchain: Dict[str, str] = Field(default_factory=dict)


# ───────────────────────────────────────────────────────────────────────── 4. failure_report
class FailureReport(BaseModel):
    failure_id: str
    subject_ref: str
    attempt: int
    status: Literal["exec_error", "timeout", "gate_fail", "verify_fail", "refused"]
    category: Literal["exec_fix", "validity", "dimensional_fix", "selector_binding_fix",
                      "dfm_fix", "structure_fix", "escalate"]
    error_signature: Optional[str] = None
    traceback_head: Optional[str] = None
    failed_rows: List[CheckRow] = Field(default_factory=list)
    feedback: str
    repeated_error: bool = False
    regressed: bool = False


# ───────────────────────────────────────────────────────────────────────── 5. repair_transcript
class Attempt(BaseModel):
    attempt: int
    code: str
    verifier_report: Optional[VerifierReport] = None
    failure_report: Optional[FailureReport] = None
    feedback_to_next: Optional[str] = None
    edit_distance_lines: Optional[int] = None


class Outcome(BaseModel):
    passed: bool
    attempts_used: int
    first_valid_attempt: Optional[int] = None
    final_category: Optional[str] = None


class RepairTranscript(BaseModel):
    transcript_id: str
    brief_ref: str
    generator: Dict[str, Any]
    attempts: List[Attempt]
    outcome: Outcome
    created: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None   # our extension: the attempted brief/spec, verbatim


# ───────────────────────────────────────────────────────────────────── JSON-Schema export
_MODELS: Dict[str, type] = {
    "model_brief": ModelBrief, "assembly_brief": AssemblyBrief,
    "verifier_report": VerifierReport, "failure_report": FailureReport,
    "repair_transcript": RepairTranscript,
}


def json_schema(name: str) -> Dict[str, Any]:
    """Draft-2020-12 JSON Schema for one contract, with the stable versioned `$id` injected."""
    sch = _MODELS[name].model_json_schema()
    sch["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    sch["$id"] = _sid(name)
    sch["title"] = name
    return sch


def all_schemas() -> Dict[str, Dict[str, Any]]:
    return {name: json_schema(name) for name in _MODELS}
