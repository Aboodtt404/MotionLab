"""Error-driven retrieval for the retry loop (track-a §9).

Inspired by the `motoko-repair` discipline: *the #1 failure mode of code models is
re-guessing — emitting a different hallucination instead of looking up the truth.*
So when generated CadQuery fails, we don't just hand back the raw traceback (which
invites another guess); we parse the exception head, retrieve the canonical CadQuery
ground truth for that error class, and return a MINIMUM-FIX instruction.

Two exports:
  • error_signature(tb)  → a stable key for "have we seen this exact error before?"
  • diagnose(tb)         → the ground-truth fix hint for the matched error class (or None)

The retry loop uses both: diagnose() enriches exec-fix feedback; error_signature()
drives the "same error twice ⇒ escalate context, stop re-guessing" rule.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# (compiled pattern over the traceback text, ground-truth fix hint).
# Ordered: first match wins, so put the specific signatures before the generic ones.
_FIXES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"Multiplied\(\).*incompatible|offsetVector|normal\.normalized\(\)\.multiply", re.S),
     "`.workplane()` takes a NUMERIC offset (a float), never a plane name. "
     "Use `cq.Workplane('XY')` to start on the XY plane, and "
     "`.faces('>Z').workplane()` to put a new workplane on the top face — NOT `.workplane('XY')`."),

    (re.compile(r"No pending wires|pending wires present", re.S),
     "An extrude/cut needs a sketched wire first. Draw a profile on a workplane "
     "(`.circle(r)` / `.rect(w,h)`) BEFORE `.extrude(...)` / `.cutThruAll()`."),

    (re.compile(r"hole\(|cboreHole|counterbore", re.S),
     "`.hole(d)` cuts along the workplane normal and needs a face workplane first: "
     "`.faces('>Z').workplane().center(x,y).hole(d)`."),

    # ---- classes from the mistakes catalog (fable_run 05_mistakes), traceback-anchored ----
    (re.compile(r"exceeded [\d.]+s|TimeoutExpired|timed? ?out", re.S),
     "Execution TIMED OUT — usually a boolean doing too much work. Cut features SEQUENTIALLY "
     "(one .cut() per cutter, never a fused compound cutter), keep feature loops small, and "
     "don't call .clean() inside a loop — clean once at the end."),  # R2

    (re.compile(r"\.(cut|fuse|union|intersect)\(.*(StdFail_NotDone|command not done)", re.S),
     "A boolean (cut/fuse) failed — usually exactly-tangent or coincident faces. Extend cutters "
     "0.5–1 mm PAST the surfaces they cut (start below, end above) so no face is exactly shared."),  # C10

    (re.compile(r"Standard_DomainError|Standard_ConstructionError", re.S),
     "A dimension is zero/degenerate — every length, radius and extrude distance must be > 0. "
     "Check computed values (e.g. `extrude(H)` with H=0, `box(0,...)`) before the call."),

    (re.compile(r"Standard_NullObject", re.S),
     "An operation ran on an EMPTY shape — a selector matched nothing or `.val()` was taken "
     "from an empty Workplane. Verify the selection is non-empty before chaining the feature."),

    (re.compile(r"More than one wire or face is required", re.S),
     "`.loft()` needs BOTH profiles pending on the stack: sketch the base "
     "(`.rect(w,h)`), offset a new plane (`.workplane(offset=L)`), sketch the tip, THEN `.loft()`."),  # C14

    (re.compile(r"unexpected keyword argument|takes \d+ positional|missing \d+ required", re.S),
     "Wrong method signature. Use the documented positional forms: `.hole(d)`, "
     "`.cboreHole(d, cboreD, cboreDepth)`, `.cskHole(d, cskD, cskAngle)`, `.fillet(r)`."),

    (re.compile(r"ZeroDivisionError", re.S),
     "A derived dimension divided by zero — guard computed values (counts, spacings, ratios) "
     "so denominators are never 0."),
    # ---- end catalog additions ----

    (re.compile(r"\.fillet\(|BRep_API.*command not done|radius.*too large", re.S),
     "Fillet/chamfer radius must be smaller than the adjacent edge/face; select the "
     "edge set explicitly, e.g. vertical edges with `.edges('|Z').fillet(r)`."),  # C3

    (re.compile(r"empty|nothing selected|StopIteration|index out of range|list index", re.S),
     "A selector resolved to ZERO entities. Check the selector string — vertical "
     "edges are `'|Z'`, the top face is `'>Z'`. Don't chain a feature onto an empty selection."),

    (re.compile(r"name 'result' is not defined|'result'", re.S),
     "The final solid MUST be assigned to a variable named exactly `result`."),

    (re.compile(r"SyntaxError|invalid syntax|unexpected (token|indent|EOF)|was never closed", re.S),
     "The output was not valid Python — likely prose leaked in or the program was cut off. "
     "Emit ONLY the complete program inside a single ```python block, nothing else."),

    (re.compile(r"NameError|name '(\w+)' is not defined", re.S),
     "An undefined name was used. Use only `cadquery as cq` and standard Python; "
     "do not reference variables you didn't define."),

    (re.compile(r"AttributeError|has no attribute", re.S),
     "Called a method that does not exist on this object. Stick to documented CadQuery "
     "Workplane methods (box, circle, rect, extrude, cutThruAll, hole, fillet, chamfer, faces, edges, workplane, center)."),
]


def error_signature(tb: str) -> str:
    """A stable key for an exception: its TYPE plus a normalized message head.
    Used to detect 'the model hit the SAME error again' across retries — numbers
    and hex addresses are stripped so 'off by 13' and 'off by 28' don't look distinct."""
    if not tb:
        return ""
    last = next((ln.strip() for ln in reversed(tb.strip().splitlines()) if ln.strip()), "")
    head = last.split(":", 1)[0] if ":" in last else last           # e.g. "TypeError"
    msg = re.sub(r"0x[0-9a-fA-F]+|\d+(\.\d+)?", "#", last)            # normalize numbers/addrs
    return f"{head}|{msg[:120]}"


def diagnose(tb: str) -> Optional[str]:
    """Retrieve the ground-truth fix hint for the error class, or None if unrecognized."""
    if not tb:
        return None
    for pat, hint in _FIXES:
        if pat.search(tb):
            return hint
    return None


def exception_head(tb: str) -> str:
    """The last (most informative) line of a traceback — the actual exception, not the stack."""
    if not tb:
        return ""
    return next((ln.strip() for ln in reversed(tb.strip().splitlines()) if ln.strip()), "")[:300]
