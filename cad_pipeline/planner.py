"""Planner stage — prompt → a multi-part PLAN (decompose → measurements → placement) → execute.

The CADSmith Planner→Coder→Executor→Validator pattern (sources.md): the model decomposes an
object into parametric components, gives each its dimensions and how it's placed/assembled; the
executor (assembly.build_assembly) fuses them; the deterministic assembly verifier validates
(connectivity, validity, per-component). For anything beyond a single part, this is the entry point.

Only the part vocabulary the builder/verifier support is allowed (box/cylinder + through_hole /
hole_pattern / fillet / chamfer / pocket) — so a plan is executable AND checkable by construction.
"""
from __future__ import annotations

import json
import re
import urllib.request

from .assembly import Assembly

# Short + directive (reliable under structured output), now asking for FUNCTIONAL detail.
_SYSTEM = (
    "Output a CAD assembly as JSON. Decompose the object into components — for EACH part produce one "
    "component: name; part {shape 'box'|'cylinder'|'loft'|'revolve'; envelope (box ⇒ length,width,height; "
    "cylinder ⇒ diameter,height; loft ⇒ length,width,height,width_top,height_top); features [...]; "
    "tolerance 0.1}; at [x,y,z] in mm; rotate [rx,ry,rz] in degrees.\n"
    "Use 'loft' for any arm/strut/spar/leg — it is a TAPERED bar (engineered, not a blunt block): it tapers "
    "along its length (local X) from width×height at the hub end down to width_top×height_top at the tip "
    "(typically ~half). REAL frames use tapered arms — prefer loft over box for limbs. A loft can also "
    "transition to a ROUND tip — add `diameter_top` to the envelope for a rect→circle adapter/duct.\n"
    "Use 'revolve' for any ROUND/TURNED part (shaft, hub, flange, nozzle, dome, wheel, bottle): give a "
    "`profile` = list of [radius, z] meridian points spun about Z (NO envelope needed). Start and end at "
    "radius 0 for a solid body; keep radius>0 throughout for a tube; a step in radius makes a shoulder, a "
    "slanted run makes a cone/taper. e.g. a stepped hub = [[0,0],[20,0],[20,10],[12,10],[12,30],[0,30]]. "
    "Prefer revolve over a plain cylinder when a part has steps, tapers, or a domed/flared profile.\n"
    "Use 'sweep' for a TUBE/pipe/cable/handle/curved strut: envelope {diameter} + a `path` = list of "
    "[x,y,z] points the round section follows (can bend in 3D). e.g. an L-pipe path=[[0,0,0],[60,0,0],"
    "[60,0,40]]. NO envelope length needed — the path defines the run.\n"
    "Make each part REALISTIC with the FUNCTIONAL features it needs, using these feature types (each a flat "
    "object with a \"type\"): through_hole{diameter, at:[a,b], axis}, hole_pattern{pattern 'bolt_circle'|"
    "'linear_x'|'grid', diameter, count, pitch_diameter|spacing|nx,ny}, fillet{radius, edges 'all_vertical'|"
    "'top'|'bottom'}, chamfer{distance, edges}, pocket{length,width,depth, at:[x,y]} (a recess; positioned "
    "pockets make panel insets / panel-line grooves / greeble detail), draft{angle} (box only — tilts side "
    "walls in° for molded/cast parts), counterbore{diameter, cbore_diameter, cbore_depth, at:[x,y]} (recess for "
    "a socket-head screw), countersink{diameter, csk_diameter, csk_angle, at:[x,y]} (seat for a flat-head screw, "
    "csk_angle = INCLUDED angle, usually 90), mirror{plane 'YZ'|'XZ'|'XY'} (box only — reflects the part "
    "across the plane to make it left/right symmetric), shell{thickness, open_face 'top'|'bottom'|'none'} "
    "(box only — hollow it to a thin wall, for enclosures/housings), thread{diameter, pitch, kind "
    "'internal'|'external', at:[x,y]} (a tapped hole or threaded stud — cosmetic callout), "
    "greeble{panel, depth, density 0..1, bevel, focal 'center'|'edges'|'none'} (the SCI-FI SURFACE-DETAIL "
    "pass — panel-line grooves + recessed/raised panels; add it to a hull/fuselage/engine/wing/panel part "
    "for the filmic detailed look. Works on box (top face), cylinder/revolve (side), loft (top). density≈how "
    "busy 0.5, panel≈cell size 20, bevel>0 for machined rims). Examples: a motor mount = a small "
    "cylinder boss + a bolt_circle of holes; a hub/baseplate = a center bore + a bolt pattern + corner mounting "
    "holes; an arm = a loft tapering to its motor end; lighten plates with a pocket. Don't leave parts as bare "
    "blocks — but keep to a few sensible features each. fillet/chamfer apply to BOX parts only "
    "(cylinder, loft and revolve have no straight vertical edges) — never fillet/chamfer those shapes.\n"
    "Produce ONE component per part the request implies (e.g. '4 arms' ⇒ 4 arms, and add their motor mounts "
    "and landing standoffs where appropriate) and NEVER an empty list; infer reasonable sizes for anything "
    "unstated. Center near the origin; adjacent parts MUST OVERLAP a few mm at their joints so the fused "
    "result is one connected solid; set fuse=true."
)


_FEAT_TYPES = {"through_hole", "hole_pattern", "fillet", "chamfer", "pocket", "draft",
               "counterbore", "countersink", "mirror", "shell", "var_fillet", "thread", "greeble"}


def _extract_json(txt: str) -> str:
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    if "</think>" in txt:
        txt = txt.rsplit("</think>", 1)[1]
    m = re.findall(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        return m[-1].strip()
    a, b = txt.find("{"), txt.rfind("}")
    return txt[a:b + 1] if a != -1 and b > a else txt.strip()


def _normalize(data: dict) -> dict:
    """Tolerate the model's feature-format drift: convert {"fillet":{...}} → {"type":"fillet",...}
    and strip a trailing-comma-free reparse isn't needed here. Keeps the planner robust to JSON
    style without weakening the schema (pydantic still validates the result)."""
    for c in data.get("components", []):
        part = c.get("part", {})
        out = []
        for f in part.get("features", []) or []:
            if isinstance(f, dict) and "type" not in f:
                hit = next(((k, v) for k, v in f.items() if k in _FEAT_TYPES and isinstance(v, dict)), None)
                if hit:
                    out.append({"type": hit[0], **hit[1]})
                    continue
            out.append(f)
        part["features"] = out
    return data


_EDIT_SYSTEM = (
    "You EDIT an existing parametric assembly. You are given the current assembly JSON and an edit "
    "instruction. Output ONLY the FULL modified assembly JSON (same schema) inside a single ```json block. "
    "Apply ONLY the requested change and keep everything else identical (same names/dims/placements). "
    "Preserve connectivity — adjacent parts must still OVERLAP at their joints so the fused result is one solid. "
    "Each feature is a flat object with a \"type\" key (e.g. {\"type\":\"fillet\",\"radius\":3,\"edges\":\"top\"})."
)


def _chat(system: str, user: str, base_url: str, model: str, timeout: float, temperature: float,
          schema: dict | None = None) -> str:
    # Structured output: vLLM constrains generation to the JSON schema (Assembly by default, or the
    # outline schema for stage 1) — guaranteed parseable (no truncation / reasoning-prefix failures).
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature, "max_tokens": 6000,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "out", "schema": schema or Assembly.model_json_schema()}},
    }).encode()
    req = urllib.request.Request(base_url + "/chat/completions", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def _ask(system: str, user: str, base_url: str, model: str, timeout: float) -> Assembly:
    """Call the model, parse → validated Assembly, retrying once with temperature on a JSON slip."""
    last = None
    for temp in (0.0, 0.4, 0.7):
        try:
            data = json.loads(_extract_json(_chat(system, user, base_url, model, timeout, temp)))
            asm = Assembly(**_normalize(data))
            if not asm.components:
                raise ValueError("planner returned no components")
            return asm
        except (json.JSONDecodeError, ValueError) as e:
            last = e
    raise ValueError(f"could not produce a valid assembly: {last}")


# Stage 1 of the two-stage plan (CAD-HLLM: high-level parts outline → parameter completion). One-shot
# decomposition under-detailes hero objects ("crude skeletons"); committing to a generous parts list FIRST
# fixes the part count + which surfaces carry sci-fi detail, then Stage 2 (_SYSTEM) realizes the geometry.
_OUTLINE_SYSTEM = (
    "List the PARTS of the described object as a JSON parts list. Be GENEROUS and realistic — a hero "
    "sci-fi/mechanical object has MANY parts (e.g. a gunship: fuselage, cockpit canopy, 2 wings, 2 engine "
    "nacelles, tail fin, 2 wing cannons, 2 landing skids). For EACH part give: name; role (one phrase); "
    "shape (box|cylinder|loft|revolve|sweep — loft=tapered arm/wing, revolve=round/turned, sweep=pipe/cable); "
    "greeble (true if it's a large HULL/fuselage/wing/engine SURFACE that should carry sci-fi panel detail). "
    "Output {\"parts\":[...]}. Aim for the REAL part count (often 6-14), not 2-3 blobs."
)
_OUTLINE_SCHEMA = {
    "type": "object", "properties": {"parts": {"type": "array", "items": {
        "type": "object", "properties": {
            "name": {"type": "string"}, "role": {"type": "string"},
            "shape": {"type": "string", "enum": ["box", "cylinder", "loft", "revolve", "sweep"]},
            "greeble": {"type": "boolean"}},
        "required": ["name", "shape"]}}}, "required": ["parts"],
}


def _outline(prompt: str, base_url: str, model: str, timeout: float) -> list:
    """Stage 1 → a high-level parts list (richer than one-shot tends to produce). [] on failure."""
    for temp in (0.2, 0.6):
        try:
            data = json.loads(_extract_json(_chat(_OUTLINE_SYSTEM, "object: " + prompt, base_url, model,
                                                  timeout, temp, _OUTLINE_SCHEMA)))
            parts = data.get("parts") or []
            if parts:
                return parts
        except (json.JSONDecodeError, ValueError):
            continue
    return []


def _default_joint_blend(asm: Assembly) -> None:
    """A fused frame whose joints aren't blended reads as 'blocks jammed together'. If the model
    didn't ask for a joint fillet, set one scaled to part thickness so the deterministic builder
    rounds the seams (the verifier re-checks it stays one valid solid). Capped small so it's a
    machined-radius blend, not a feasibility risk on thin plates."""
    if asm.fuse and asm.fillet_joints <= 0 and asm.components:
        # Don't auto-blend large or greebled assemblies — the seam-blend is O(edges*parts) and explodes
        # with greeble's many edges, and rounded joints add little once parts carry surface detail.
        greebled = any(any(f.type == "greeble" for f in c.part.features) for c in asm.components)
        if len(asm.components) > 5 or greebled:
            return
        hs = [c.part.envelope.get("height", 5.0) for c in asm.components]
        asm.fillet_joints = round(max(1.0, min(3.0, (sum(hs) / len(hs)) * 0.3)), 2)


def plan(prompt: str, base_url: str = "http://localhost:8002/v1",
         model: str = "qwen3.6-27b", timeout: float = 180.0) -> Assembly:
    """prompt → validated multi-part Assembly (the planner). Two-stage (CAD-HLLM): a high-level parts
    outline commits to a rich part set first, then Stage 2 realizes geometry; one-shot is the fallback."""
    parts = _outline(prompt, base_url, model, timeout)
    if parts:
        listing = "; ".join(
            f"{p['name']} ({p.get('role', '')}, {p.get('shape', 'box')}{', GREEBLED' if p.get('greeble') else ''})"
            for p in parts)
        user = (f"input: {prompt}\nRealize THIS parts list as the assembly — one component per part, each "
                f"with dimensions, the functional features it needs (GREEBLE the parts marked GREEBLED), and "
                f"placements that OVERLAP at the joints:\n{listing}")
    else:
        user = "input: " + prompt
    asm = _ask(_SYSTEM, user, base_url, model, timeout)
    _default_joint_blend(asm)
    return asm


def edit(asm: Assembly, instruction: str, base_url: str = "http://localhost:8002/v1",
         model: str = "qwen3.6-27b", timeout: float = 180.0) -> Assembly:
    """current assembly + an edit instruction → modified, re-validated Assembly (the edit-loop).
    Parametric editing is a structured JSON transform — change params/parts, keep the rest."""
    user = f"current assembly:\n{asm.model_dump_json()}\n\nedit: {instruction}"
    out = _ask(_EDIT_SYSTEM, user, base_url, model, timeout)
    _default_joint_blend(out)
    return out
