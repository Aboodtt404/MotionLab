"""The unified spec-first, verifier-looped engine — one entry point over every representation
(fable_run/out/00_manual.md §1.1 pipeline + §1.2 router). This is the Track-A + Track-B merge:
a model_brief or assembly_brief goes in, the router picks a builder PER PART, each part is built and
verified by its representation's own oracle (all built in Phase 3), and the results compose.

  build_part(brief)   → route → build → verify → BuiltPart          (one asset)
  build_asset(brief)  → decompose (assembly_brief) → build every component → per-part report + roll-up

Hybrid assembly (merging B-rep + mesh + procedural parts into one placed scene via the mate graph +
unit/axis conversion) is the next milestone; build_asset today builds+verifies every component and
reports which representation each took and whether it passed — the router's correctness, proven per part.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .builders import BUILDERS, BuiltPart
from .router import choose_representation


def build_part(brief) -> BuiltPart:
    """Route ONE model_brief to its representation and build+verify it."""
    rep = choose_representation(
        representation=getattr(brief, "representation", None),
        prompt=getattr(brief, "prompt", "") or "",
        name=getattr(brief, "name", "") or "",
        target_use=getattr(brief, "target_use", None),
    )
    return BUILDERS[rep](brief)


@dataclass
class AssetResult:
    name: str
    parts: List[BuiltPart] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.parts) and all(p.passed for p in self.parts)

    def summary(self) -> dict:
        return {"asset": self.name, "passed": self.passed,
                "parts": [{"name": p.name, "rep": p.representation, "passed": p.passed,
                           "reason": p.reason} for p in self.parts],
                "by_rep": {r: sum(1 for p in self.parts if p.representation == r)
                           for r in ("brep", "library", "mesh", "procedural")
                           if any(p.representation == r for p in self.parts)}}


def build_asset(brief) -> AssetResult:
    """Build every part of an assembly_brief (each routed to its representation) or a single model_brief."""
    comps = getattr(brief, "components", None)
    if comps is None:
        return AssetResult(name=getattr(brief, "name", "part"), parts=[build_part(brief)])
    parts: List[BuiltPart] = []
    for c in comps:
        parts.append(build_part(c.brief))
    return AssetResult(name=getattr(brief, "name", "assembly"), parts=parts)
