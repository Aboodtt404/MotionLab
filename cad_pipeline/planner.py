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

from .assembly import Assembly, AsmPatch, apply_patch, repair_connectivity, solve_layout

# Short + directive (reliable under structured output), now asking for FUNCTIONAL detail.
_SYSTEM = (
    "Output a CAD assembly as JSON {object, components:[...], mates:[...], fuse:true}. For EACH part produce one "
    "component: name; role (one of 'seat','top','base','leg','support','arm','panel','body','hub','fastener','other'); "
    "part {shape 'box'|'cylinder'|'loft'|'revolve'; envelope (box ⇒ length,width,height; "
    "cylinder ⇒ diameter,height; loft ⇒ length,width,height,width_top,height_top); features [...]; "
    "tolerance 0.1}.\n"
    "Do NOT set coordinates — describe HOW PARTS CONNECT with `mates` (named relationships); a deterministic "
    "solver computes positions. Mate kinds:\n"
    "  ground {kind:'ground', a:'part'} — the part rests on the floor (z=0).\n"
    "  stack {kind:'stack', a:'upper', b:'lower', overlap:3} — a sits on top of b (a 1–4 mm overlap fuses them).\n"
    "  radial {kind:'radial', parts:['leg1','leg2','leg3','leg4'], around:'seat', count:4, radius:55, splay_deg:10} — "
    "the parts arranged evenly AROUND the vertical axis of `around` (legs of a stool/table, spokes, drone arms, "
    "landing gear); splay_deg leans each one outward; radial legs auto-touch the floor.\n"
    "  coaxial {kind:'coaxial', a, b} — a shares b's vertical axis (a hub/boss/disc centered on another).\n"
    "  flush {kind:'flush', a, b, side:'+x'|'-x'|'+y'|'-y'|'+z'|'-z', overlap:3} — a butted against that face of b.\n"
    "  mirror {kind:'mirror', a, b, plane:'YZ'|'XZ'|'XY'} — a is the mirror image of b (left/right pairs).\n"
    "  attach {kind:'attach', a, b} — generic: a snaps to the nearest face of b (use only when none of the above fit).\n"
    "EVERY component must be reachable through mates (no floating parts); the structure must rest on the floor.\n"
    "PROPORTIONS: a leg/support spans MOST of the object's height — a ~120 mm-tall stool has ~100 mm legs and "
    "a thin seat, NOT short stubs under a thick disc. Size parts so the whole reaches the requested overall size.\n"
    "WORKED EXAMPLES (placement is ALL via mates, never coordinates):\n"
    "  • 4-legged stool → components: seat(role 'seat', cylinder ⌀140×16), leg1..leg4(role 'leg', box 16×16×110). "
    "mates: [radial(parts=[leg1..4], around='seat', count=4, radius=55, splay_deg=10), stack(a='seat', b='leg1', overlap=4)].\n"
    "  • shelf bracket (L) → vertical(role 'support', box) + horizontal(role 'top', box); mates: [ground(vertical), "
    "flush(a='horizontal', b='vertical', side='+z')].\n"
    "  • quadcopter frame → body(role 'body', cylinder) + arm1..4(role 'arm', loft tapering to the motor end); "
    "mates: [radial(parts=[arm1..4], around='body', count=4, radius=70)].\n"
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
    "Produce ONE component per part the request implies (e.g. '4 arms' ⇒ 4 arms, '4 legs' ⇒ 4 legs) and NEVER "
    "an empty list; infer reasonable sizes for anything unstated. SCALE the part count to the object — a stool "
    "is ~5 parts (seat + 4 legs), a hero ship is 8–14; don't pad simple objects or under-build complex ones. "
    "Give every part a `role` and connect ALL of them with `mates` (never coordinates); set fuse=true."
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
    "You EDIT a parametric assembly. Given the current assembly JSON and an instruction, output ONLY a "
    "small PATCH (NOT the whole assembly): "
    "`upsert` = the components to ADD or REPLACE — give each in full (name; role; part {shape, envelope, "
    "features [...], tolerance 0.1}); to REPLACE an existing part reuse its EXACT name, to add a new one use a "
    "new name. Do NOT set coordinates — placement is computed from mates. "
    "`remove` = names of components to delete. "
    "`mates` = include the FULL updated mate list ONLY if the edit changes how parts connect (e.g. you added a "
    "part that must be mated, using radial/stack/ground/coaxial/flush/mirror); otherwise omit it. "
    "Apply ONLY the requested change — do NOT echo unchanged components. Each feature is a flat object with a "
    "\"type\" key (e.g. {\"type\":\"greeble\",\"panel\":20,\"density\":0.6})."
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
    "List the PARTS of the described object as a JSON parts list, realistic for THAT object — scale the count "
    "to its real structure, don't pad or under-build. A stool ≈ 5 (seat + 4 legs); a chair ≈ 6; a table ≈ 5; "
    "a bracket ≈ 2–3; a hero sci-fi ship ≈ 8–14 (fuselage, cockpit, wings, nacelles, fin, cannons, skids). "
    "For EACH part give: name; role (one of 'seat','top','base','leg','support','arm','panel','body','hub',"
    "'fastener','other'); shape (box|cylinder|loft|revolve|sweep — loft=tapered arm/wing/leg, revolve=round/"
    "turned, sweep=pipe/cable); greeble (true ONLY for a large HULL/fuselage/wing/engine SURFACE that should "
    "carry sci-fi panel detail — never for furniture/simple props). Output {\"parts\":[...]}."
)
_OUTLINE_SCHEMA = {
    "type": "object", "properties": {"parts": {"type": "array", "items": {
        "type": "object", "properties": {
            "name": {"type": "string"},
            "role": {"type": "string", "enum": ["seat", "top", "base", "leg", "support", "arm", "panel", "body", "hub", "fastener", "other"]},
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


def _ask_patch(system: str, user: str, base_url: str, model: str, timeout: float) -> AsmPatch:
    """Call the model for an edit PATCH (small delta), validated → AsmPatch; retry with temperature."""
    last = None
    for temp in (0.0, 0.4, 0.7):
        try:
            raw = json.loads(_extract_json(_chat(system, user, base_url, model, timeout, temp,
                                                 AsmPatch.model_json_schema())))
            norm = _normalize({"components": raw.get("upsert", [])})   # tolerate feature-format drift
            return AsmPatch(upsert=norm["components"], remove=raw.get("remove", []))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            last = e
    raise ValueError(f"could not produce a valid edit patch: {last}")


def _default_joint_blend(asm: Assembly) -> None:
    """A fused frame whose joints aren't blended reads as 'blocks jammed together'. If the model
    didn't ask for a joint fillet, set one scaled to part thickness so the deterministic builder
    rounds the seams (the verifier re-checks it stays one valid solid). Capped small so it's a
    machined-radius blend, not a feasibility risk on thin plates."""
    if asm.fuse and asm.fillet_joints <= 0 and asm.components:
        # Don't auto-blend large or greebled assemblies — the seam-blend is O(edges*parts) and explodes
        # with greeble's many edges, and rounded joints add little once parts carry surface detail.
        greebled = any(any(f.type == "greeble" for f in c.part.features) for c in asm.components)
        # Only blend ALL-BOX assemblies: filleting boolean seams on curved/tapered parts (loft/revolve/
        # cylinder/sweep) makes OCCT SEGFAULT (crashes the process, uncatchable) — the blend is cosmetic,
        # so skip it the moment any part isn't a box. Box-box seams are the safe, designed case.
        non_box = any(c.part.shape != "box" for c in asm.components)
        if len(asm.components) > 5 or greebled or non_box:
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
            f"{p['name']} (role {p.get('role', 'other')}, {p.get('shape', 'box')}{', GREEBLED' if p.get('greeble') else ''})"
            for p in parts)
        user = (f"input: {prompt}\nRealize THIS parts list as the assembly — one component per part with its "
                f"role, dimensions, and the functional features it needs (GREEBLE the parts marked GREEBLED); "
                f"connect every part with `mates` (radial/stack/ground/coaxial/flush/mirror), NOT coordinates:\n{listing}")
    else:
        user = "input: " + prompt
    asm = _ask(_SYSTEM, user, base_url, model, timeout)
    asm = solve_layout(asm)          # resolve the mate graph → placements (legs splay, seat on top, etc.)
    asm = repair_connectivity(asm)   # bounded fallback: close any small remaining gaps (won't collapse spread)
    _default_joint_blend(asm)
    return asm


def edit(asm: Assembly, instruction: str, base_url: str = "http://localhost:8002/v1",
         model: str = "qwen3.6-27b", timeout: float = 180.0) -> Assembly:
    """current assembly + an edit instruction → modified, re-validated Assembly (the edit-loop).
    Parametric editing is a structured JSON transform — change params/parts, keep the rest."""
    user = f"current assembly:\n{asm.model_dump_json()}\n\nedit: {instruction}"
    patch = _ask_patch(_EDIT_SYSTEM, user, base_url, model, timeout)   # a small delta, not the whole asm
    out = apply_patch(asm, patch)
    out = solve_layout(out)          # re-resolve placement from the (possibly edited) mate graph
    out = repair_connectivity(out)   # bounded fallback for any small remaining gaps
    _default_joint_blend(out)
    return out
