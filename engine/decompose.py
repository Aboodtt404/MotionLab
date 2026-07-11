"""Part-tree decomposition — fable_run/out/00_manual.md §1.3. Decompose a prompt top-down into a
part tree, stopping when a node is (a) a primitive with ≤3 features, (b) a library part, or (c) one
organic mesh — assigning a representation PER PART (§1.2). Output = an assembly_brief the router builds.

This is the DETERMINISTIC decomposer: a small library of part-tree templates for common composite
objects (drone, stool, gimbal, gripper), plus a single-part fallback. The open-ended case (arbitrary
prompt → novel part tree) is the LLM planner's job (cad_pipeline.planner, GPU); this covers the known
compositions deterministically so the engine runs prompt→assembly with no model in the loop.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from cad_pipeline.schemas import AssemblyBrief, BriefComponent, BriefMate, ModelBrief


def _mb(bid: str, name: str, rep: str, env: dict, *, shape: Optional[str] = None,
        prompt: str = "", target: str = "cad", feats: Optional[list] = None) -> ModelBrief:
    return ModelBrief(brief_id=bid, name=name, target_use=target, representation=rep, units="mm",
                      up_axis="z", shape=shape, envelope_mm=env, prompt=prompt,
                      features=[{"type": f["type"], "params": {k: v for k, v in f.items() if k != "type"}}
                                for f in (feats or [])])


# ── part-tree templates (each → AssemblyBrief with per-part representation) ──────────────────────
def _drone(prompt: str) -> AssemblyBrief:
    frame = _mb("f", "quad frame plate", "brep", {"length": 120, "width": 120, "height": 4}, shape="box",
                feats=[{"type": "hole_pattern", "pattern": "grid", "diameter": 3, "nx": 2, "ny": 2, "spacing": 30.5}])
    comps: List[BriefComponent] = [BriefComponent(component_id="frame", role="base", brief=frame)]
    for i in range(4):                                    # 4 library motors — rep stays 'brep'; the router
        comps.append(BriefComponent(component_id=f"motor{i}", role="hub",   # sees the catalog name → library
                     brief=_mb(f"m{i}", "motor_2207", "brep", {"diameter": 27.7, "height": 18})))
    comps.append(BriefComponent(component_id="canopy", role="panel",       # organic shell → mesh
                 brief=_mb("c", "canopy", "mesh", {"length": 80, "width": 40, "height": 30},
                           prompt="organic sculpted drone canopy", target="film")))
    mates = [BriefMate(kind="radial", parts=[f"motor{i}" for i in range(4)], around="frame",
                       count=4, radius_mm=60),
             BriefMate(kind="stack", a="canopy", b="frame", overlap_mm=2)]
    return AssemblyBrief(brief_id="drone", name="quadcopter", units="mm", components=comps, mates=mates)


def _stool(prompt: str) -> AssemblyBrief:
    seat = _mb("s", "seat", "brep", {"diameter": 140, "height": 16}, shape="cylinder")
    legs = [BriefComponent(component_id=f"leg{i}", role="leg",
            brief=_mb(f"l{i}", "leg", "brep", {"length": 16, "width": 16, "height": 110}, shape="box"))
            for i in range(4)]
    comps = [BriefComponent(component_id="seat", role="seat", brief=seat), *legs]
    mates = [BriefMate(kind="radial", parts=[f"leg{i}" for i in range(4)], around="seat",
                       count=4, radius_mm=55, splay_deg=10),
             BriefMate(kind="stack", a="seat", b="leg0", overlap_mm=4)]
    return AssemblyBrief(brief_id="stool", name="four-leg stool", units="mm", components=comps, mates=mates)


def _gimbal(prompt: str) -> AssemblyBrief:
    base = _mb("b", "gimbal base", "brep", {"length": 60, "width": 60, "height": 10}, shape="box")
    yoke = _mb("y", "gimbal yoke", "brep", {"length": 50, "width": 40, "height": 40}, shape="box")
    cam = _mb("c", "camera pod", "brep", {"length": 30, "width": 30, "height": 25}, shape="box")
    comps = [BriefComponent(component_id="base", role="base", brief=base),
             BriefComponent(component_id="yoke", role="support", brief=yoke),
             BriefComponent(component_id="cam", role="body", brief=cam)]
    mates = [BriefMate(kind="stack", a="yoke", b="base", overlap_mm=2),
             BriefMate(kind="coaxial", a="cam", b="yoke")]
    return AssemblyBrief(brief_id="gimbal", name="2-axis gimbal", units="mm", components=comps, mates=mates)


TEMPLATES: Dict[str, Callable[[str], AssemblyBrief]] = {
    r"\b(drone|quad(copter)?|uav|multirotor)\b": _drone,
    r"\b(stool|4[- ]?leg|four[- ]?leg)\b": _stool,
    r"\b(gimbal|camera mount|pan[- ]?tilt)\b": _gimbal,
}


def _single_part(prompt: str) -> ModelBrief:
    """Atomic prompt → one part; guess a base shape from keywords (the router picks the representation)."""
    p = prompt.lower()
    shape = "cylinder" if re.search(r"\b(cylinder|disc|shaft|flange|bore|ring|pulley|bearing)\b", p) else "box"
    return _mb("part", prompt.strip()[:40] or "part", "brep", {"length": 50, "width": 50, "height": 20}
               if shape == "box" else {"diameter": 40, "height": 20}, shape=shape, prompt=prompt)


def decompose(prompt: str):
    """Prompt → assembly_brief (known composite) or model_brief (atomic). The engine builds either."""
    for pat, fn in TEMPLATES.items():
        if re.search(pat, prompt, re.I):
            return fn(prompt)
    return _single_part(prompt)
