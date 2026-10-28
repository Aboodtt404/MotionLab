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
import os
import re
import time
import urllib.request

from .assembly import Assembly, AsmPatch, apply_patch, repair_connectivity, solve_layout
from .partlib import _STANDARDS_LINE

# Short + directive (reliable under structured output), now asking for FUNCTIONAL detail.
_SYSTEM = (
    "Output a CAD assembly as JSON {object, components:[...], mates:[...], fuse:true}. For EACH part produce one "
    "component: name; role (one of 'seat','top','base','leg','support','arm','panel','body','hub','fastener','other'); "
    "part {shape 'box'|'cylinder'|'loft'|'revolve'|'sweep'|'profile_extrude'; envelope (box ⇒ length,"
    "width,height; cylinder ⇒ diameter,height; loft ⇒ length,width,height,width_top,height_top; "
    "profile_extrude ⇒ side_profile[[x,z],…] + optional plan_profile[[x,y],…]); features [...]; "
    "tolerance 0.1}.\n"
    "Do NOT set coordinates — describe HOW PARTS CONNECT with `mates` (named relationships); a deterministic "
    "solver computes positions. Mate kinds:\n"
    "  ground {kind:'ground', a:'part'} — the part rests on the floor (z=0).\n"
    "  stack {kind:'stack', a:'upper', b:'lower', overlap:3} — a sits on top of b (a 1–4 mm overlap fuses them). "
    "Add fraction:0..1 to fix a PARTWAY UP b (or up b's whole post/leg group) instead of on top: a's center "
    "lands at that share of the support's height — a rack's middle shelf = {kind:'stack', a:'mid_shelf', "
    "b:'post0', fraction:0.5}; a low shelf ≈ 0.15. Omit fraction for the normal on-top stack.\n"
    "  radial {kind:'radial', parts:['leg1','leg2','leg3','leg4'], around:'seat', count:4, radius:55, splay_deg:10} — "
    "the parts arranged evenly AROUND the vertical axis of `around` IN A CIRCLE (stool/table legs, spokes, drone "
    "arms, landing gear); splay_deg leans each one outward; radial legs auto-touch the floor.\n"
    "  corners {kind:'corners', parts:['front_left_wheel','front_right_wheel','rear_left_wheel','rear_right_wheel'], "
    "around:'chassis', dx:1300, dy:880, axis:'y'} — the parts at the CORNERS of a rectangle on `around`: "
    "dx = half the front↔rear spacing (wheelbase/2), dy = half the left↔right spacing (track/2). Use corners, "
    "NOT radial, whenever positions are front/rear + left/right (car wheels, rover wheels, table at 4 corners, "
    "bed posts). Parts are matched to corners BY NAME (front→+x, rear→−x, left→+y, right→−y). axis:'y' lays each "
    "part's own axis SIDEWAYS (a wheel is a cylinder spinning about y — lying on its side, not flat); omit axis "
    "for upright parts (posts, legs). Corner parts auto-touch the floor.\n"
    "  coaxial {kind:'coaxial', a, b, axis:'z'} — a shares b's axis (a hub/boss/disc centered on another); "
    "axis:'x'|'y' for a HORIZONTAL shared axis (wheel on a sideways axle).\n"
    "  flush {kind:'flush', a, b, side:'+x'|'-x'|'+y'|'-y'|'+z'|'-z', overlap:3} — a butted against that face of b. "
    "On lateral sides (±x/±y) add fraction:0..1 to ALSO fix a's HEIGHT: a's center at that share of b's height — "
    "a camera pod on the front edge, raised 60% up = {kind:'flush', a:'cam_pod', b:'plate', side:'+x', fraction:0.6}. "
    "Without fraction a lateral flush keeps a's current z — set it whenever the part must sit at a specific height.\n"
    "  port {kind:'port', a, b, a_port, b_port, overlap:2} — the PRECISION mate: pick one of six named "
    "attachment faces on EACH part (top|bottom|front|back|left|right; front=+x, left=+y) and a's face-center "
    "lands exactly on b's, pinning a on ALL THREE axes. THE way to hang a below b: a_port:'top', b_port:'bottom' "
    "— a cable tray under a desktop = {kind:'port', a:'cable_tray', a_port:'top', b:'desktop', b_port:'bottom', "
    "offset:[-500,0]} (offset shifts across a top/bottom face); a side pod at 60% height = a_port:'back', "
    "b_port:'front', fraction:0.6. Prefer port over flush whenever the part must sit at a POSITION, not just "
    "against a face.\n"
    "  mirror {kind:'mirror', a, b, plane:'YZ'|'XZ'|'XY'} — a is the mirror image of b (left/right pairs).\n"
    "  attach {kind:'attach', a, b} — generic: a snaps to the nearest face of b (use only when none of the above fit).\n"
    "  cutout {kind:'cutout', a:'front_left_wheel', b:'body_shell', clearance:40} — CARVE a's volume (grown by "
    "`clearance` mm) OUT of b: a wheel ARCH in a car body, a cockpit opening, a pocket for an insert. `a` is NOT "
    "moved or welded by this — it keeps its own mates/joints and sits INSIDE the carved well with `clearance` of "
    "air all round. Give every car/rover wheel a cutout from the body (clearance ≈ 40) so wheels sit IN arches, "
    "not beside the body.\n"
    "For a MOVING connection (hinged lid/door/hatch, swiveling turret, folding arm) add a `joints` entry instead of "
    "mating the moving part to what it swings on: {kind:'revolute', a:'lid', b:'body', axis:'x'|'y'|'z', "
    "limits:[0,90]} — `a` is the MOVING part. Do NOT also mate a to b (a mate WELDS them and freezes the hinge); "
    "the solver places a with a running clearance and the verifier sweeps the motion range for collisions. "
    "Everything else still connects with mates. JOINTS MUST CHAIN TO THE STRUCTURE: `b` must itself be mated "
    "(or be the base) — never joint two parts that are both floating, or the mechanism floats in space.\n"
    "EVERY component must be reachable through mates (or hang on a joint); the structure must rest on the floor.\n"
    "PROPORTIONS: a leg/support spans MOST of the object's height — a ~120 mm-tall stool has ~100 mm legs and "
    "a thin seat, NOT short stubs under a thick disc. Size parts so the whole reaches the requested overall size.\n"
    "WORKED EXAMPLES (placement is ALL via mates, never coordinates):\n"
    "  • 4-legged stool → components: seat(role 'seat', cylinder ⌀140×16), leg1..leg4(role 'leg', box 16×16×110). "
    "mates: [radial(parts=[leg1..4], around='seat', count=4, radius=55, splay_deg=10), stack(a='seat', b='leg1', overlap=4)].\n"
    "  • shelf bracket (L) → vertical(role 'support', box) + horizontal(role 'top', box); mates: [ground(vertical), "
    "flush(a='horizontal', b='vertical', side='+z')].\n"
    "  • two-tier rack → post0..post3(role 'leg', box 16×16×180) + top_shelf + mid_shelf(role 'top', box 200×120×10). "
    "mates: [corners(parts=[post0..3], around='top_shelf', dx=(200−16)/2−5, dy=(120−16)/2−5 — posts INSET inside "
    "the shelf footprint), stack(a='top_shelf', b='post0', overlap=3), stack(a='mid_shelf', b='post0', fraction=0.5)] "
    "— fraction fixes the middle shelf halfway up the posts; every extra tier is one more stack+fraction.\n"
    "  • desk with under-mounted parts (the SUSPEND pattern — copy for anything hung BELOW a surface: trays, "
    "under-shelves, hooks) → top(role 'top') + leg1..4(role 'leg') + cable_tray; mates: [corners(parts=[leg1..4], "
    "around='top', dx=740, dy=290), stack(a='top', b='leg1', overlap=3), port(a='cable_tray', a_port='top', "
    "b='top', b_port='bottom', overlap=2, offset=[0,-250])] — the tray's TOP face pins to the desktop's BOTTOM "
    "face; never leave suspended parts to raw coordinates.\n"
    "  • quadcopter frame → body(role 'body', cylinder) + arm1..4(role 'arm', loft tapering to the motor end); "
    "mates: [radial(parts=[arm1..4], around='body', count=4, radius=70)].\n"
    "  • car / wheeled rover (the RIDE-HEIGHT pattern — copy this structure) → chassis(role 'base', box "
    "3600×700×80, at z = wheel_radius: a car chassis is SUSPENDED at axle height, it does NOT rest on the "
    "ground — the wheels do) + body(role 'body', profile_extrude with a real side_profile: nose→hood→"
    "windshield→roof→trunk, and a plan_profile; the body is WIDER than the chassis, out over the wheels) + "
    "front_left_axle..rear_right_axle(role 'support', cylinder ⌀60×160) + front_left_wheel..rear_right_wheel"
    "(role 'other', revolve wheel: rim + tire with an arc bulge + hub bore + bolt_circle hole_pattern — or a "
    "plain cylinder ⌀600×200). mates: [stack(a='body', b='chassis', overlap=3), "
    "corners(parts=[the 4 axles], around='chassis', dx=wheelbase/2, dy=chassis_width/2+axle_len/2−10, "
    "axis='y', z=wheel_radius), corners(parts=[the 4 wheels], around='chassis', dx=wheelbase/2, "
    "dy=dy_axle+axle_len/2+wheel_width/2, axis='y' — NO z: wheels rest on the floor), "
    "cutout(a=each wheel, b='body', clearance=40) — one arch per wheel so wheels sit IN the body, "
    "not beside it]; joints: one revolute per wheel {a:wheel, b:'chassis', axis:'y', limits:[0,360]}. "
    "ARITHMETIC THAT MUST HOLD: chassis z-center = wheel ⌀/2 (axles poke out of the chassis FLANK at wheel "
    "center height and reach the wheels); dy_wheel = dy_axle + axle_len/2 + wheel_width/2 (wheel inner face "
    "MEETS the axle tip); body_width/2 > dy_wheel − wheel_width/2 (the body overhangs the wheels — the "
    "cutout arches clear them). Do NOT ground the chassis or the body.\n"
    "Use 'loft' for any arm/strut/spar/leg — it is a TAPERED bar (engineered, not a blunt block): it tapers "
    "along its length (local X) from width×height at the hub end down to width_top×height_top at the tip "
    "(typically ~half). REAL frames use tapered arms — prefer loft over box for limbs. A loft can also "
    "transition to a ROUND tip — add `diameter_top` to the envelope for a rect→circle adapter/duct.\n"
    "Use 'revolve' for any ROUND/TURNED part (shaft, hub, flange, nozzle, dome, wheel, bottle): give a "
    "`profile` = list of [radius, z] meridian points spun about Z (NO envelope needed). Start and end at "
    "radius 0 for a solid body; keep radius>0 throughout for a tube; a step in radius makes a shoulder, a "
    "slanted run makes a cone/taper. e.g. a stepped hub = [[0,0],[20,0],[20,10],[12,10],[12,30],[0,30]]. "
    "For CURVED profiles (dome, barrel, flare, bottle shoulder) add `profile_arcs` — one sagitta per profile "
    "segment (0 = straight line; on an upward run a NEGATIVE sagitta bows OUTWARD): a dome cap or a barrel "
    "bulge is one arc segment, not many tiny lines. "
    "Prefer revolve over a plain cylinder when a part has steps, tapers, or a domed/flared profile.\n"
    "Use 'sweep' for a TUBE/pipe/cable/handle/curved strut: envelope {diameter} + a `path` = list of "
    "[x,y,z] points the round section follows (can bend in 3D). e.g. an L-pipe path=[[0,0,0],[60,0,0],"
    "[60,0,40]]. NO envelope length needed — the path defines the run.\n"
    "Use 'profile_extrude' for a SILHOUETTE body — a car/vehicle body, aircraft fuselage, boat hull, "
    "furniture side-frame: anything whose IDENTITY is its side outline (a shape a box or loft cannot "
    "express). Give `side_profile` = list of [x,z] outline points (the SIDE view: e.g. a car goes "
    "nose→hood→windshield→roof→trunk→tail) — a CLOSED simple polygon, extruded across the width. "
    "Optionally add `plan_profile` = list of [x,y] points (the TOP view outline: narrows the nose/tail, "
    "rounds the body) — the body is the INTERSECTION of the two, giving a real car shape from every view. "
    "Add `side_arcs`/`plan_arcs` (one sagitta per segment, 0=straight, like revolve) to CURVE a roofline "
    "or fender (a windshield→roof segment with a negative sagitta bows the roof up). Without plan_profile, "
    "set envelope{width} for a straight-sided silhouette. e.g. a car body: side_profile=[[0,300],[900,0],"
    "[4200,0],[4200,650],[3300,720],[2500,1250],[1200,1300],[300,950],[0,650]], plan_profile=[[0,-560],"
    "[3600,-700],[4200,0],[3600,700],[0,560]]. Prefer profile_extrude over a plain box/loft for any road/"
    "air/water vehicle body — it is the difference between a slab and a recognizable vehicle. A wheel "
    "ARCH is the `cutout` mate carving the body — NEVER a separate 'arch'/'fender' component (an added "
    "arch part just collides with the body).\n"
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
    "'internal'|'external', at:[x,y]} (a tapped hole or threaded stud — cosmetic callout; ONLY when a "
    "threaded interface is requested, never decoration; an EXTERNAL thread on a cylinder must have "
    "diameter = the cylinder's own diameter — a thinner thread floating on a fat axle is unrealizable), "
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
    "Give every part a `role` and connect ALL of them with `mates` (never coordinates); set fuse=true.\n"
    + _STANDARDS_LINE
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
    "`joints` = include the FULL updated joint list ONLY if the edit changes MOVING connections (adding/removing "
    "a hinge: {kind:'revolute', a:moving, b:base, axis, limits:[lo,hi]}); otherwise omit it. "
    "Apply ONLY the requested change — do NOT echo unchanged components. Each feature is a flat object with a "
    "\"type\" key (e.g. {\"type\":\"greeble\",\"panel\":20,\"density\":0.6})."
)


def _asm_schema() -> dict:
    """Assembly schema with the hardened $defs (see _harden_defs)."""
    s = Assembly.model_json_schema()
    # joints/mates are droppable optionals at the TOP level — require them present (empty list legal)
    s["required"] = sorted(set(s.get("required", [])) | {"components", "mates", "joints"})
    return _harden_defs(s)


def _patch_schema() -> dict:
    """AsmPatch schema with the SAME hardened $defs — repair/edit patches carry Mates and Specs
    too, and an unhardened patch grammar quietly reintroduces every failure class the plan grammar
    forbids (live: a coaxial mate carrying the full field soup arrived via a repair patch)."""
    return _harden_defs(AsmPatch.model_json_schema())


def _patch_schema_scoped(fields: set, must: str | None = None,
                         part_names: list | None = None) -> dict:
    """Targeted-repair patch grammar (ArtiCAD routing, placement research §3): the verifier's
    failure class decides WHICH patch fields exist at all. A disconnected assembly gets a
    mates-only grammar; a broken part gets an upsert-only grammar whose component `name` is an
    ENUM of the failing parts — an out-of-scope edit (the flat-repair 'patch broke working parts'
    regression) is unrepresentable at token level, same principle as the port enum."""
    s = _patch_schema()
    props = s["properties"]
    dead = {"upsert": {"type": "array", "maxItems": 0},
            "remove": {"type": "array", "maxItems": 0},
            "mates": {"type": "null"}, "joints": {"type": "null"},
            "fillet_joints": {"type": "null"}}
    for f, off in dead.items():
        if f not in fields:
            props[f] = off
    if part_names:
        # scope-by-name: upsert replaces BY NAME, so an enum on `name` pins the patch to the
        # failing parts; `remove` gets the same fence (deleting a healthy part is never the fix)
        if "upsert" in fields:
            s["$defs"]["Component"]["properties"]["name"] = {"enum": sorted(part_names)}
        if "remove" in fields:
            props["remove"] = {"type": "array", "items": {"enum": sorted(part_names)}}
    if must:
        # the route's primary field must carry real content, not the null/empty escape —
        # an empty patch re-verifies the identical assembly (a wasted attempt)
        if must in ("mates", "joints"):
            props[must] = next(v for v in props[must]["anyOf"] if v.get("type") == "array")
            props[must]["minItems"] = 1
        elif must == "upsert":
            props[must] = {**props[must], "minItems": 1}
        elif must == "fillet_joints":
            props[must] = {"type": "number"}
    # guided decoding drops non-required keys entirely (corpus zero-yield lesson): require every
    # allowed field so the model emits null/[] where inapplicable, never silently omits the fix
    s["required"] = sorted(fields)
    return s


def _harden_defs(s: dict) -> dict:
    """Shared $defs hardening. Guided decoding
    omits optional keys entirely (the corpus engine's zero-yield lesson), which starved
    hole_pattern of spacing/pitch_diameter → parts that verify-fail on hole count. Requiring the
    keys lets the model emit null where inapplicable but never silently drop the load-bearing one.
    Same treatment for Mate: corners needs dx/dy/axis, radial needs radius — droppable optionals
    would quietly degrade a corner layout to defaults."""
    hp = s.get("$defs", {}).get("HolePattern")
    if hp:
        hp["required"] = sorted(set(hp.get("required", [])) | {"pattern", "count", "spacing",
                                                               "pitch_diameter", "nx", "ny"})
    # Mate is POLYMORPHIC (8 kinds sharing one model) — requiring every pattern field on every
    # kind makes the engine junk-fill them (observed live: a `ground` mate carrying dx/dy/axis/
    # parts, a stack with a corner offset, the corners mate itself dropped). The right guided
    # shape is a DISCRIMINATED UNION: one variant per kind, each requiring exactly its own
    # fields and forbidding the rest (AIDL: typed, few, human-named predicates).
    mt = s.get("$defs", {}).get("Mate")
    if mt:
        props = mt["properties"]
        # (required, optional) per kind. z is deliberately OPTIONAL, never required: a forced-
        # present z gets emitted as 0 (not null), which reads as "explicit height 0" and buries
        # floor-resting parts (wheels/legs) half underground.
        kind_fields = {
            "ground": (["a"], []),
            # fraction stays OPTIONAL (same hazard as z: required-but-null gets emitted as 0,
            # which reads "at the very bottom" and buries a classic top-stack underground)
            "stack": (["a", "b", "overlap", "offset"], ["fraction"]),
            "coaxial": (["a", "b", "axis"], ["offset"]),   # offset = axis-perpendicular shift (posts on a base)
            "radial": (["parts", "around", "count", "radius", "splay_deg"], ["z"]),
            "corners": (["parts", "around", "dx", "dy", "axis"], ["z"]),
            "flush": (["a", "b", "side", "overlap"], ["fraction"]),   # lateral flush: optional height share
            "port": (["a", "b", "a_port", "b_port", "overlap"], ["fraction", "offset"]),
            "mirror": (["a", "b", "plane"], []),
            "attach": (["a", "b", "overlap"], []),
            "cutout": (["a", "b", "clearance"], []),
        }
        s["$defs"]["Mate"] = {"anyOf": [
            {"type": "object",
             "properties": {"kind": {"const": k}, **{f: props[f] for f in req + opt}},
             "required": ["kind", *req],
             "additionalProperties": False}
            for k, (req, opt) in kind_fields.items()]}
    # Spec is polymorphic on `shape` the same way Mate is on `kind` — and got the same live failure
    # (a revolve with profile:null crashed the seat build; 3 repair rounds burned on it). Same cure:
    # a DISCRIMINATED UNION per shape, each variant REQUIRING its geometry so shape-without-its-
    # geometry is impossible AT GENERATION TIME, not caught 8 minutes later by the verifier.
    sp = s.get("$defs", {}).get("Spec")
    if sp:
        props = sp["properties"]
        base_req = list(sp.get("required", []))

        def _arr(field: str, min_items: int) -> dict:
            # strip the null branch and demand real content
            arr = next(v for v in props[field]["anyOf"] if v.get("type") == "array")
            return {**arr, "minItems": min_items}

        def _env(req_keys: list) -> dict:
            return {"type": "object",
                    "properties": {k: {"type": "number"} for k in req_keys},
                    "required": req_keys,
                    "additionalProperties": {"type": "number"}}

        # per-shape required geometry (the 6 shapes the planner offers; prism/loft_sections are
        # part-lane vocabulary the assembly prompts never ask for)
        shape_geo: dict = {
            "box": {"envelope": _env(["length", "width", "height"])},
            "cylinder": {"envelope": _env(["diameter", "height"])},
            "loft": {"envelope": _env(["length", "width", "height"])},
            "revolve": {"profile": _arr("profile", 3)},
            "sweep": {"path": _arr("path", 2)},
            "profile_extrude": {"side_profile": _arr("side_profile", 3), "envelope": _env(["width"])},
        }
        s["$defs"]["Spec"] = {"anyOf": [
            {"type": "object",
             "properties": {**props, "shape": {"const": k}, **geo},
             "required": sorted(set(base_req) | set(geo))}
            for k, geo in shape_geo.items()]}
    return s


def _resolve(node: dict, defs: dict) -> dict:
    """Follow a local $ref one hop (the only form _asm_schema/_patch_schema produce)."""
    ref = node.get("$ref")
    if ref and ref.startswith("#/$defs/"):
        return defs.get(ref.split("/")[-1], {})
    return node


def _pick_variant(value: dict, schema: dict, defs: dict) -> dict | None:
    """Which anyOf branch does this value belong to? Chosen by the branch's `const` discriminators
    (Mate.kind / Spec.shape) — the same thing the decoder keys off."""
    best = None
    for v in schema.get("anyOf", []):
        v = _resolve(v, defs)
        props = v.get("properties", {})
        consts = {k: p["const"] for k, p in props.items() if isinstance(p, dict) and "const" in p}
        if consts and all(value.get(k) == c for k, c in consts.items()):
            return v
        if not consts and best is None and v.get("type") == "object":
            best = v
    return best


def _empty_for(node: dict, defs: dict):
    """A schema-legal placeholder for a REQUIRED key the value doesn't carry (the scoped patch
    grammar requires every in-route field present, null where inapplicable)."""
    node = _resolve(node, defs)
    branches = [_resolve(b, defs) for b in node.get("anyOf", [])] or [node]
    types = {b.get("type") for b in branches}
    if "null" in types:
        return None
    if "array" in types:
        return []
    if "object" in types:
        return {}
    return None


def conform_to_grammar(value, schema: dict, defs: dict | None = None):
    """Reshape a JSON value into the EXACT form the guided-decoding grammar accepts.

    Three things the decoder enforces that a plain pydantic dump violates (all measured
    2026-08-02, whole-corpus audit):
      1. `additionalProperties: false` on each discriminated-union variant — pydantic's non-None
         DEFAULTS (Mate.clearance=5.0, parts=[], splay_deg=0.0) survive exclude_none and are
         forbidden keys. 1,217/1,217 port targets failed on this alone.
      2. xgrammar enforces the schema's DECLARED PROPERTY ORDER; pydantic emits field-declaration
         order. 736/1,217 stayed unproducible after (1) was fixed, purely on key order.
      3. `required` keys must be PRESENT (null where inapplicable) — the scoped patch grammar
         requires every in-route field, but exclude_none strips them.
    A target that skips this is a string the decoder masks to zero probability: the model is
    trained to emit something it can never produce. Same family as the gate-on-artifact lesson —
    gate on what SHIPS, not on what the builder happens to hold in memory.
    """
    defs = schema.get("$defs", defs or {})
    node = _resolve(schema, defs)
    if isinstance(value, dict):
        if "anyOf" in node:
            node = _pick_variant(value, node, defs) or {}
        props = node.get("properties")
        if not props:
            return value
        out = {}
        for key, sub in props.items():          # SCHEMA order, not pydantic order
            if key in value:
                out[key] = conform_to_grammar(value[key], sub, defs)
            elif key in node.get("required", []):
                out[key] = _empty_for(sub, defs)
        if node.get("additionalProperties") is not False:
            for key, v in value.items():        # variant permits extras (Spec) — keep them last
                if key not in out:
                    out[key] = v
        return out
    if isinstance(value, list):
        item = node.get("items", {})
        return [conform_to_grammar(v, item, defs) for v in value]
    if isinstance(value, float):
        # NEGATIVE ZERO is schema-legal JSON but xgrammar rejects the leading '-' on a field
        # declared minimum:0 (measured: 4/300 port targets died on "fraction":-0.0 alone).
        return value + 0.0 if value else abs(value)
    return value


def dump_for_grammar(obj, schema: dict) -> str:
    """Model/dict -> compact JSON string the decoder can actually emit. Use for EVERY training
    target; pair it with a jsonschema assert in the builder (gate on the shipped artifact)."""
    data = json.loads(obj.model_dump_json(exclude_none=True)) if hasattr(obj, "model_dump_json") else obj
    return json.dumps(conform_to_grammar(data, schema), separators=(",", ":"))


def _chat(system: str, user: str, base_url: str, model: str, timeout: float, temperature: float,
          schema: dict | None = None) -> str:
    # Structured output: vLLM constrains generation to the JSON schema (Assembly by default, or the
    # outline schema for stage 1) — guaranteed parseable (no truncation / reasoning-prefix failures).
    from . import progress
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature, "max_tokens": 6000,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "out", "schema": schema or _asm_schema()}},
    }
    if not progress.active():        # evals/training: the original non-streaming request, unchanged
        req = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    # Generation theater: stream the tokens (SSE) and publish the growing spec text so the user
    # watches the assembly spec being written in real time. Same guided decoding, same final text.
    body["stream"] = True
    req = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    chunks: list[str] = []
    last_pub = 0.0
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta:
                chunks.append(delta)
                now = time.monotonic()
                if now - last_pub > 0.25:
                    progress.publish(spec_stream="".join(chunks))
                    last_pub = now
    text = "".join(chunks)
    if text:
        progress.publish(spec_stream=text)
    return text


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
    "'fastener','other'); shape (box|cylinder|loft|revolve|sweep|profile_extrude — loft=tapered arm/wing/leg, "
    "revolve=round/turned, sweep=pipe/cable, profile_extrude=SILHOUETTE body for a vehicle/fuselage/hull/"
    "furniture side-frame); greeble (true ONLY for a large HULL/fuselage/wing/engine SURFACE that should "
    "carry sci-fi panel detail — never for furniture/simple props). Output {\"parts\":[...]}."
)
_OUTLINE_SCHEMA = {
    "type": "object", "properties": {"parts": {"type": "array", "items": {
        "type": "object", "properties": {
            "name": {"type": "string"},
            "role": {"type": "string", "enum": ["seat", "top", "base", "leg", "support", "arm", "panel", "body", "hub", "fastener", "other"]},
            "shape": {"type": "string", "enum": ["box", "cylinder", "loft", "revolve", "sweep", "profile_extrude"]},
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


def _ask_patch(system: str, user: str, base_url: str, model: str, timeout: float,
               schema: dict | None = None) -> AsmPatch:
    """Call the model for an edit PATCH (small delta), validated → AsmPatch; retry with temperature.
    `schema` narrows the patch grammar (targeted repair routes pass _patch_schema_scoped)."""
    last = None
    for temp in (0.0, 0.4, 0.7):
        try:
            raw = json.loads(_extract_json(_chat(system, user, base_url, model, timeout, temp,
                                                 schema or _patch_schema())))
            norm = _normalize({"components": raw.get("upsert", [])})   # tolerate feature-format drift
            # pass mates/joints REPLACEMENTS through — they were silently dropped, which stripped the
            # model's fix for the two DOMINANT repair classes (disconnected + welded-joint are mate edits)
            return AsmPatch(upsert=norm["components"], remove=raw.get("remove", []),
                            mates=raw.get("mates"), joints=raw.get("joints"),
                            fillet_joints=raw.get("fillet_joints"))
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
         model: str = os.environ.get("PLAN_MODEL", "qwen3.6-27b"), timeout: float = 300.0) -> Assembly:
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
         model: str = os.environ.get("PLAN_MODEL", "qwen3.6-27b"), timeout: float = 300.0) -> Assembly:
    """current assembly + an edit instruction → modified, re-validated Assembly (the edit-loop).
    Parametric editing is a structured JSON transform — change params/parts, keep the rest."""
    user = f"current assembly:\n{asm.model_dump_json()}\n\nedit: {instruction}"
    patch = _ask_patch(_EDIT_SYSTEM, user, base_url, model, timeout)   # a small delta, not the whole asm
    out = apply_patch(asm, patch)
    out = solve_layout(out)          # re-resolve placement from the (possibly edited) mate graph
    out = repair_connectivity(out)   # bounded fallback for any small remaining gaps
    _default_joint_blend(out)
    return out
