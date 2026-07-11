"""Representation router — fable_run/out/00_manual.md §1.2 decision table, the heart of the
Track-A + Track-B merge (Option B). Choose the representation PER PART, not per project:

    dims / tolerances / fasteners / STEP / fits   → brep       (CadQuery, Track A)
    a named catalog part (bearing, screw, gear)    → library    (partlib / partlib_solids)
    organic / sculptural / creature / "looks like" → mesh       (TRELLIS, Track B, via :8770)
    "family of" / greebles / terrain / procedural  → procedural (Blender geometry-nodes / bpy)

A part carries its representation explicitly on the model_brief (`representation`); when absent the
router infers it from prompt/name signals. This module only DECIDES — engine.builders executes.
"""
from __future__ import annotations

import re
from typing import Optional

Representation = str   # "brep" | "library" | "mesh" | "procedural"

# signal → representation (order matters: earlier wins). Fable §1.2 rows.
# NB: "bolt" only as a fastener, not "bolt circle/hole/pattern" (a brep feature — a ring of holes)
_LIBRARY = re.compile(r"\b(m[2-8]\b|screw|bolt(?!\s*(?:circle|hole|pattern|pcd))|nut|washer|bearing|"
                      r"gear|standoff|dowel|pin|nema17|608|623|685|624|shcs|heat-?set|pulley|gt2|"
                      r"motor|2207|1404|n20|stepper|servo)\b", re.I)
_MESH = re.compile(r"\b(organic|sculpt|creature|character|animal|figure|statue|face|body|"
                   r"looks like|blob|hand|tree|foliage|rock|terrain-?less|natural)\b", re.I)
_PROCEDURAL = re.compile(r"\b(family of|variations?|randomi[sz]ed|greebles?|scatter|array of|"
                         r"terrain|landscape|procedural|kit of|tiling)\b", re.I)
_BREP = re.compile(r"\b(bracket|plate|flange|mount|housing|shaft|enclosure|tolerance|fit|"
                   r"manufactur|machined|cnc|chamfer|fillet|bore|counterbore|drone|frame)\b", re.I)


def choose_representation(*, representation: Optional[str] = None, prompt: str = "",
                          name: str = "", target_use: Optional[str] = None) -> Representation:
    """Return the representation for one part. An explicit `representation` on the brief always wins;
    otherwise infer from the text signals; default to brep (the verifiable, parametric fallback)."""
    # underscores are word chars → they break \b boundaries ("motor_2207"); normalise to spaces
    text = f"{name} {prompt}".replace("_", " ")
    if representation in ("brep", "mesh", "procedural"):
        # a brief that literally names a catalog part is still 'library' even if tagged brep
        if _LIBRARY.search(text) and representation == "brep":
            return "library"
        return representation
    if _LIBRARY.search(text):
        return "library"
    if _PROCEDURAL.search(text):
        return "procedural"
    if _MESH.search(text):
        return "mesh"
    if _BREP.search(text):
        return "brep"
    # target_use nudges the default: game/web/film organic-leaning → mesh; else parametric brep
    if target_use in ("game", "film") and not _BREP.search(text):
        return "mesh"
    return "brep"
