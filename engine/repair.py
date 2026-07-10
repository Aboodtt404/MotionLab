"""Repair loop over routed builds — fable_run §1.1 REPAIR ("patch the spec or the code, regenerate —
never hand-edit output geometry") + the 05_mistakes error→fix table. ONE loop across representations:

  • every failing verifier row is mapped to its typed repair feedback (the 46-mistake catalog), so the
    caller / an LLM gets "kind + fix", not just "wrong" — the same feedback the retry prompt uses;
  • the assembly-level failures the engine can fix DETERMINISTICALLY (interference → add clearance,
    A3) are patched and the asset re-verified, closing the loop without a model in it.

Part-level regeneration (an off-spec brep re-emitting code) is the LLM loop's job (cad_pipeline.loop,
Phase 6); here the engine surfaces the exact typed feedback that loop consumes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from cad_pipeline.mistakes import BY_AREA
from cad_pipeline.schemas import normalize_category

from .assemble import HybridAsset, assemble
from .builders import BuiltPart

# category → the catalog mistake whose repair feedback fits (first match across areas)
_CATEGORY_TO_MISTAKE = {
    "interference": "A3", "integrity": "A3", "disconnected": "A1", "structure": "A2",
    "component": "A4", "dimensional": "C7", "selector_binding": "C4", "missing_feature": "C4",
    "validity": "M2", "dfm": "P1",
}


def typed_feedback(rows: List[dict]) -> List[str]:
    """Map each failing row to the catalog's typed repair string (what the retry prompt hands back)."""
    out: List[str] = []
    seen = set()
    for r in rows:
        if r.get("within_tol", True):
            continue
        cat = normalize_category(r.get("category"))
        mid = _CATEGORY_TO_MISTAKE.get(cat)
        fb = None
        if mid:
            for ms in sum(BY_AREA.values(), []):
                if ms.id == mid:
                    fb = ms.repair
                    break
        msg = f"{r['name']}: {fb}" if fb else f"{r['name']}: off-spec ({cat})"
        if msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out


@dataclass
class RepairResult:
    asset: HybridAsset
    rounds: int
    feedback: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.asset.passed


def _declump(asset: HybridAsset, clearance: float = 2.0) -> bool:
    """A3 interference repair: push each overlapping pair apart along its axis of least penetration.
    Returns True if any part moved."""
    scene = asset.scene
    names = list(scene.geometry)
    moved = False
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = scene.geometry[names[i]], scene.geometry[names[j]]
            lo = np.maximum(a.bounds[0], b.bounds[0])
            hi = np.minimum(a.bounds[1], b.bounds[1])
            pen = hi - lo
            if np.all(pen > 0):                          # overlapping box → separate on the min-penetration axis
                ax = int(np.argmin(pen))
                shift = np.zeros(3)
                shift[ax] = (pen[ax] + clearance) * (1 if b.centroid[ax] >= a.centroid[ax] else -1)
                b.apply_translation(shift)
                asset.placements.setdefault(names[j], {})["repair_shift"] = shift.tolist()
                moved = True
    return moved


def repair_asset(assembly_brief, *, max_rounds: int = 2, built: Optional[Dict[str, BuiltPart]] = None) -> RepairResult:
    """Assemble → verify → (deterministic assembly repair) → re-verify, up to max_rounds. Always returns
    the best asset + the typed feedback for whatever still fails (for an LLM/caller to act on)."""
    from .assemble import _verify_scene
    asset = assemble(assembly_brief, built=built)
    rounds = 1
    while not asset.passed and rounds <= max_rounds:
        interf = any(("interference" in r["name"]) and not r["within_tol"] for r in asset.rows)
        if interf and _declump(asset):
            # re-verify the (mutated) scene in place
            meshes = {n: g for n, g in asset.scene.geometry.items()}
            asset.rows = _verify_scene(asset.scene, meshes, asset.placements, expected=len(asset.scene.geometry))
            rounds += 1
            continue
        break
    return RepairResult(asset=asset, rounds=rounds, feedback=typed_feedback(asset.rows))
