"""Phase-1 conformance: the 5 canonical schemas (cad_pipeline/schemas.py) match fable_run/out/
04_schemas.md. Every example instance from the doc must (a) parse through the pydantic model and
(b) validate against the exported draft-2020-12 JSON Schema. Plus: enum conformance, the
category-normalisation boundary, and the Spec→model_brief adapter.
"""
from __future__ import annotations

import sys

import jsonschema

from cad_pipeline.schemas import (CHECK_CATEGORY_CORE, FAILURE_CATEGORY, FAILURE_STATUS,
                                   AssemblyBrief, FailureReport, ModelBrief, RepairTranscript,
                                   VerifierReport, all_schemas, json_schema, normalize_category,
                                   normalize_failure_category)
from cad_pipeline.spec import Spec

PASS = FAIL = 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok ] {msg}")
    else:
        FAIL += 1
        print(f"  [FAIL] {msg}")


# ─────────────────────────────── the exact example instances from 04_schemas.md
MODEL_BRIEF = {
    "brief_id": "mb-000123", "name": "bolt_circle_flange",
    "prompt": "a 90mm mounting flange, 12mm thick, 20mm bore, 8 bolt holes on a 70mm circle",
    "target_use": "cad", "representation": "brep", "units": "mm", "up_axis": "z", "shape": "cylinder",
    "envelope_mm": {"diameter": 90, "height": 12},
    "features": [
        {"type": "through_hole", "params": {"diameter": 20}},
        {"type": "hole_pattern", "params": {"pattern": "bolt_circle", "count": 8, "pitch_diameter": 70, "diameter": 6}},
    ],
    "tolerance_mm": 0.1, "budgets": {"min_wall_mm": 2.0}, "output_formats": ["step", "stl"],
}

ASSEMBLY_BRIEF = {
    "brief_id": "ab-000042", "name": "four_leg_stool",
    "prompt": "a 4-legged stool, 120mm tall, round 140mm seat, legs splayed 10 degrees", "units": "mm",
    "components": [
        {"component_id": "seat", "role": "seat",
         "brief": {"brief_id": "mb-s1", "name": "seat_disc", "target_use": "cad", "representation": "brep",
                   "units": "mm", "up_axis": "z", "shape": "cylinder",
                   "envelope_mm": {"diameter": 140, "height": 16}, "output_formats": ["step"]}},
        {"component_id": "leg", "role": "leg", "count": 4,
         "brief": {"brief_id": "mb-l1", "name": "leg_bar", "target_use": "cad", "representation": "brep",
                   "units": "mm", "up_axis": "z", "shape": "box",
                   "envelope_mm": {"length": 16, "width": 16, "height": 110}, "output_formats": ["step"]}},
    ],
    "mates": [
        {"kind": "radial", "parts": ["leg"], "around": "seat", "count": 4, "radius_mm": 55, "splay_deg": 10},
        {"kind": "stack", "a": "seat", "b": "leg", "overlap_mm": 4},
    ],
    "fuse": True, "overall_envelope_mm": {"height": 120},
}

VERIFIER_REPORT = {
    "report_id": "vr-77812", "subject_ref": "mb-000123", "passed": False, "valid": True, "solids": 1,
    "volume_mm3": 71545.2,
    "rows": [
        {"name": "envelope · ⌀", "expected": 90, "measured": 90.0, "delta": 0.0, "within_tol": True, "category": "ok"},
        {"name": "holes · count", "expected": 9, "measured": 9, "delta": 0, "within_tol": True, "category": "ok"},
        {"name": "holes · position (worst)", "expected": 0.0, "measured": 3.2, "delta": 3.2, "within_tol": False, "category": "selector_binding"},
    ],
    "failure_categories": ["selector_binding"], "toolchain": {"cadquery": "2.7.0", "verifier": "2.3"},
}

FAILURE_REPORT = {
    "failure_id": "fl-19022", "subject_ref": "mb-000123", "attempt": 1, "status": "verify_fail",
    "category": "selector_binding_fix", "error_signature": None, "traceback_head": None,
    "failed_rows": [{"name": "holes · position (worst)", "expected": 0.0, "measured": 3.2, "delta": 3.2,
                     "within_tol": False, "category": "selector_binding"}],
    "feedback": "holes · position (worst): feature is MISPLACED — 3.2 mm from its intended location (tol ±0.1); re-check which edge/datum the offset is measured from",
    "repeated_error": False, "regressed": False,
}

REPAIR_TRANSCRIPT = {
    "transcript_id": "rt-00087", "brief_ref": "mb-000123",
    "generator": {"model": "qwen3.6-27b", "config": {"temperature": 0, "rag": True}},
    "attempts": [
        {"attempt": 1, "code": "import cadquery as cq\nresult = ...",
         "verifier_report": {"report_id": "vr-77812", "subject_ref": "mb-000123", "passed": False,
                             "valid": True, "solids": 1,
                             "rows": [{"name": "holes · position (worst)", "expected": 0.0, "measured": 3.2,
                                       "delta": 3.2, "within_tol": False, "category": "selector_binding"}]},
         "failure_report": {"failure_id": "fl-19022", "subject_ref": "mb-000123", "attempt": 1,
                            "status": "verify_fail", "category": "selector_binding_fix",
                            "feedback": "holes · position (worst): MISPLACED 3.2 mm"},
         "feedback_to_next": "holes · position (worst): MISPLACED 3.2 mm", "edit_distance_lines": None},
        {"attempt": 2, "code": "import cadquery as cq\nresult = ...  # pushPoints",
         "verifier_report": {"report_id": "vr-77813", "subject_ref": "mb-000123", "passed": True,
                             "valid": True, "solids": 1,
                             "rows": [{"name": "holes · position (worst)", "expected": 0.0, "measured": 0.02,
                                       "delta": 0.02, "within_tol": True, "category": "ok"}]},
         "failure_report": None, "feedback_to_next": None, "edit_distance_lines": 2},
    ],
    "outcome": {"passed": True, "attempts_used": 2, "first_valid_attempt": 1, "final_category": None},
    "created": "2026-07-06T12:40:00Z",
}

CASES = [
    ("model_brief", ModelBrief, MODEL_BRIEF),
    ("assembly_brief", AssemblyBrief, ASSEMBLY_BRIEF),
    ("verifier_report", VerifierReport, VERIFIER_REPORT),
    ("failure_report", FailureReport, FAILURE_REPORT),
    ("repair_transcript", RepairTranscript, REPAIR_TRANSCRIPT),
]


def test_pydantic_roundtrip():
    print("\n■ pydantic round-trip of every 04_schemas example instance")
    for name, model, inst in CASES:
        obj = model(**inst)
        redump = obj.model_dump(exclude_none=True)
        check(redump.get(list(inst.keys())[0]) == inst[list(inst.keys())[0]], f"{name}: parses + re-dumps")


def test_jsonschema_validation():
    print("\n■ every example validates against the exported draft-2020-12 JSON Schema")
    for name, _model, inst in CASES:
        sch = json_schema(name)
        try:
            jsonschema.validate(inst, sch)
            check(True, f"{name}: instance validates against exported schema")
        except jsonschema.ValidationError as e:
            check(False, f"{name}: schema validation FAILED — {e.message}")


def test_schema_export_shape():
    print("\n■ exported schemas carry stable $id + draft-2020-12")
    schemas = all_schemas()
    check(len(schemas) == 5, "5 schemas exported")
    for name, sch in schemas.items():
        check(sch.get("$id", "").endswith(f"/{name}/1.json"), f"{name}: versioned $id present")
        check("draft/2020-12" in sch.get("$schema", ""), f"{name}: draft-2020-12 declared")


def test_enums_conform():
    print("\n■ enum conformance to 04_schemas §Shared enums")
    fable_core = {"ok", "dimensional", "selector_binding", "missing_feature", "integrity",
                  "dfm", "validity", "structure", "disconnected", "component"}
    check(set(CHECK_CATEGORY_CORE) == fable_core, "check_category core = Fable's 10 (append-only extras allowed)")
    check(set(FAILURE_STATUS) == {"exec_error", "timeout", "gate_fail", "verify_fail", "refused"},
          "failure_status = Fable's 5")
    check(set(FAILURE_CATEGORY) == {"exec_fix", "validity", "dimensional_fix", "selector_binding_fix",
                                    "dfm_fix", "structure_fix", "escalate"}, "failure category = Fable's 7")


def test_normalization():
    print("\n■ live→canonical category normalisation (the emit boundary)")
    check(normalize_category("selector-binding") == "selector_binding", "selector-binding → selector_binding")
    check(normalize_category("boolean-loss") == "boolean_loss", "boolean-loss → boolean_loss")
    check(normalize_category("recon-fit") == "recon_fit", "recon-fit → recon_fit")
    check(normalize_category("dimensional") == "dimensional", "dimensional passthrough")
    check(normalize_category(None) == "ok", "None → ok")
    check(normalize_category("some_new_thing") == "integrity", "unknown folds to integrity (never dropped)")
    check(normalize_failure_category("exec-fix") == "exec_fix", "exec-fix → exec_fix")
    check(normalize_failure_category("selector-binding-fix") == "selector_binding_fix", "…-fix normalised")


def test_spec_adapter():
    print("\n■ Spec → model_brief adapter (router precondition)")
    spec = Spec(object="bolt flange", shape="cylinder", envelope={"diameter": 90, "height": 12},
                features=[{"type": "through_hole", "diameter": 20}], tolerance=0.1)
    brief = ModelBrief.from_spec(spec, brief_id="mb-x1")
    check(brief.representation == "brep" and brief.units == "mm" and brief.up_axis == "z",
          "CAD conventions set (brep/mm/z)")
    check(brief.shape == "cylinder" and brief.envelope_mm == {"diameter": 90, "height": 12}, "shape+envelope carried")
    check(brief.features and brief.features[0].type == "through_hole"
          and brief.features[0].params.get("diameter") == 20, "features → {type, params}")
    jsonschema.validate(brief.model_dump(exclude_none=True), json_schema("model_brief"))
    check(True, "adapter output validates against model_brief schema")


def main() -> int:
    print("=" * 64)
    print("SCHEMAS — 5 Fable contracts (04_schemas.md) conformance")
    print("=" * 64)
    for fn in (test_pydantic_roundtrip, test_jsonschema_validation, test_schema_export_shape,
               test_enums_conform, test_normalization, test_spec_adapter):
        fn()
    print("\n" + "=" * 64)
    print(f"SCHEMAS {PASS}/{PASS + FAIL}")
    print("ALL GOOD ✓" if FAIL == 0 else "FAILURES ✗")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
