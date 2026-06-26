"""Natural-language → Spec, via the served model (Track A's text→spec front-end).

A regex parser can't handle real user phrasing ("a hole with a radius of 5", "rounded",
"40 x 25", "six bolt holes on a 50mm circle"). The model can — converting free text to our
typed Spec is an easy, reliable task for it (NL → fixed JSON schema), and it's exactly the
text→spec capability the Track A design calls for. The generated geometry is still gated by
the deterministic verifier downstream; this only produces the *intent*.
"""
from __future__ import annotations

import json
import re
import urllib.request

from .spec import Spec

_SYSTEM = (
    "You convert a natural-language description of a HARD-SURFACE CAD part into a JSON spec.\n"
    "FIRST write a short `Plan:` in prose — (1) pick the SHAPE CLASS, (2) read off the dimensions, "
    "(3) list each feature and WHERE it sits — THEN output the final JSON object inside a single "
    "```json code block. Reason before you emit; do not start the JSON until the Plan is done.\n\n"
    "SHAPE CLASSES (pick exactly one — do NOT default to box):\n"
    '  box      — a prismatic block/plate/bracket. envelope {"length","width","height"}.\n'
    '  cylinder — a plain round body/disc/rod. envelope {"diameter","height"}.\n'
    '  loft     — a TAPERED BAR/ARM/STRUT/wedge: a rectangular section that CHANGES along its length. '
    'envelope {"length","width","height","width_top","height_top"} — length is the taper axis, '
    '(width,height) is the BASE/hub end, (width_top,height_top) is the TIP end. (Round tip ⇒ add '
    '"diameter_top" instead of width_top/height_top.) Use this whenever the part tapers/narrows/widens '
    "between two ends.\n"
    '  revolve  — a TURNED body (shaft/hub/nozzle/flange/bottle/cup): a meridian "profile" of [radius,z] '
    'points spun about the Z axis. Set "profile":[[r0,z0],...], envelope {} (or {"angle":deg} for a '
    "partial revolve). Straight axis-parallel runs ⇒ cylinder sections, slants ⇒ cones, arcs ⇒ "
    "spheres/tori. Start and end on the axis (r=0) for a solid body.\n"
    '  sweep    — a TUBE/PIPE/CHANNEL/handle/coolant-line/spar: a round section of '
    'envelope {"diameter":D} swept along a 3D "path":[[x,y,z],...] polyline.\n\n'
    "FEATURE TYPES (origin = part center; top-face XY for `at`):\n"
    '  {"type":"through_hole","diameter":D, "at":[x,y]? | "from_edge":N?, "axis":"x"|"y"|"z"?}  '
    "(at > from_edge > centered; from_edge is box-only, mm from the −X face). axis DEFAULTS to z "
    "(drilled vertically down through the top face) — OMIT it for normal mounting/bolt holes. Only set "
    'axis:"x"/"y" for an explicitly CROSS-DRILLED hole through a side ("a hole through the side", "a '
    'cross-hole"). "a hole at each end / at both ends" = vertical (z) holes at the end POSITIONS — '
    "omit axis; the END is encoded in `at` (x = ±along the length), NOT by axis.\n"
    '  {"type":"hole_pattern","diameter":D,"pattern":"bolt_circle"|"linear_x"|"grid","count":N,'
    '"pitch_diameter":P?,"spacing":S?,"nx":?,"ny":?}\n'
    '  {"type":"fillet","radius":R}   {"type":"chamfer","distance":T}   '
    '{"type":"var_fillet","r1":A,"r2":B}   (these apply to a BOX\'s vertical edges only)\n'
    '  {"type":"pocket","length":L,"width":W,"depth":Dp,"at":[x,y]?}   '
    '{"type":"draft","angle":deg}  (box-only)   {"type":"shell","thickness":T,"open_face":"top"|"bottom"|"none"}  (box-only)\n'
    '  {"type":"counterbore","diameter":D,"cbore_diameter":Dc,"cbore_depth":Hc,"at":[x,y]?}\n'
    '  {"type":"countersink","diameter":D,"csk_diameter":Dc,"csk_angle":deg,"at":[x,y]?}\n'
    '  {"type":"thread","diameter":D,"pitch":P,"kind":"internal"|"external"}   '
    '{"type":"mirror","plane":"XY"|"XZ"|"YZ"}\n'
    '  {"type":"greeble","panel":mm?,"depth":mm?,"density":0..1?,"seed":int?} — a procedural '
    'sci-fi DETAIL pass: panel-line grid + recessed panels. Works on a BOX (top face) or a CYLINDER '
    '(lateral/side face — for hull tubes, fuel tanks, pods: shape it as a cylinder with diameter+height). '
    'Use for "greebled / detailed / panelled / industrial / hull-panel / sci-fi-surface" parts. '
    'panel≈cell size (default 20), density≈how busy (default 0.5), depth default 2.\n\n'
    "RULES:\n"
    "- Units are mm. Default tolerance 0.1 if unstated. Output ONE json block, nothing after it.\n"
    "- RADIUS r ⇒ diameter = 2*r. diameter/⌀ d ⇒ diameter = d.\n"
    "- A part that TAPERS / NARROWS / 'X×Y at one end to A×B at the other' ⇒ shape:loft (NOT box). "
    "A TURNED / spun / nozzle / domed / bottle profile ⇒ shape:revolve. A TUBE / PIPE / routed line ⇒ shape:sweep.\n"
    "- HOLE PLACEMENT: holes must lie INSIDE the footprint. 'a hole at each end' of an L-long part ⇒ "
    "INSET from each end: at:[-(L/2 − m),0] and at:[(L/2 − m),0] with margin m ≥ the hole diameter. "
    "NEVER put a hole center on the edge (never at:±L/2) — that makes a half-hole notch.\n"
    "- 'centered' ⇒ omit at/from_edge. 'N mm from the edge' ⇒ from_edge:N. Explicit (x,y) ⇒ at:[x,y]. "
    "Several named holes ⇒ several through_hole entries. Regular arrays ⇒ hole_pattern.\n"
    "- 'rounded'/'filleted' ⇒ fillet; 'chamfered'/'beveled' ⇒ chamfer; recess/cavity ⇒ pocket; "
    "hollow/shelled enclosure ⇒ shell; threaded bore ⇒ thread; left/right symmetric ⇒ mirror.\n"
    "- fillet/chamfer/var_fillet/draft/shell are BOX-only; do not emit them on cylinder/loft/revolve/sweep.\n"
    "- 'A x B' (cylinder) ⇒ diameter=A,height=B. 'A x B x C' ⇒ box length=A,width=B,height=C.\n\n"
    "EXAMPLES:\n"
    "input: rounded cylinder 40 x 25, centered hole with a radius of 5\n"
    'Plan: round body ⇒ cylinder ⌀40 h25; one centered through-hole ⌀10.\n'
    '```json\n{"object":"rounded cylinder","shape":"cylinder","envelope":{"diameter":40,"height":25},'
    '"features":[{"type":"through_hole","diameter":10}],"tolerance":0.1}\n```\n'
    "input: 100x60x8 plate, rounded corners r5, four 6mm holes 12mm in from each corner\n"
    'Plan: prismatic ⇒ box 100×60×8; fillet r5; 4 holes inset 12 from corners ⇒ ±38, ±18.\n'
    '```json\n{"object":"plate","shape":"box","envelope":{"length":100,"width":60,"height":8},'
    '"features":[{"type":"fillet","radius":5},'
    '{"type":"through_hole","diameter":6,"at":[-38,-18]},{"type":"through_hole","diameter":6,"at":[38,-18]},'
    '{"type":"through_hole","diameter":6,"at":[-38,18]},{"type":"through_hole","diameter":6,"at":[38,18]}],'
    '"tolerance":0.1}\n```\n'
    "input: a tapered strut 60mm long, 24x16mm at the base narrowing to 12x8mm at the tip, an 8mm hole at each end\n"
    'Plan: tapers between two ends ⇒ loft; length 60, base 24×16, tip 12×8; "hole at each end" = '
    "vertical (z, axis omitted) holes at the end positions, inset from ±30 ⇒ at ±22.\n"
    '```json\n{"object":"tapered strut","shape":"loft","envelope":{"length":60,"width":24,"height":16,'
    '"width_top":12,"height_top":8},"features":[{"type":"through_hole","diameter":8,"at":[-22,0]},'
    '{"type":"through_hole","diameter":8,"at":[22,0]}],"tolerance":0.1}\n```\n'
    "input: a turned nozzle that tapers from a 30mm base to a 12mm neck over 40mm tall\n"
    'Plan: turned/round profile ⇒ revolve; meridian from axis: base r15@z0, neck r6@z40, capped on axis.\n'
    '```json\n{"object":"turned nozzle","shape":"revolve","envelope":{},'
    '"profile":[[0,0],[15,0],[6,40],[0,40]],"tolerance":0.1}\n```\n'
    "input: an 8mm coolant line running from the origin 50mm along X then 30mm along Y\n"
    'Plan: a routed tube ⇒ sweep; ⌀8 along the path (0,0,0)->(50,0,0)->(50,30,0).\n'
    '```json\n{"object":"coolant line","shape":"sweep","envelope":{"diameter":8},'
    '"path":[[0,0,0],[50,0,0],[50,30,0]],"tolerance":0.1}\n```\n'
    "input: 90mm flange, 12mm bore, six 6mm bolts on a 70mm circle\n"
    'Plan: round disc ⇒ cylinder ⌀90; centered ⌀12 bore; 6-hole bolt circle ⌀6 on 70 PCD.\n'
    '```json\n{"object":"flange","shape":"cylinder","envelope":{"diameter":90,"height":10},'
    '"features":[{"type":"through_hole","diameter":12},'
    '{"type":"hole_pattern","pattern":"bolt_circle","count":6,"pitch_diameter":70,"diameter":6}],"tolerance":0.1}\n```'
)


def _extract_json(txt: str) -> str:
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    if "</think>" in txt:
        txt = txt.rsplit("</think>", 1)[1]
    m = re.findall(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        return m[-1].strip()
    a, b = txt.find("{"), txt.rfind("}")
    return txt[a:b + 1] if a != -1 and b > a else txt.strip()


# The schema hint the dedicated parser (training/build_nl_spec.py) was fine-tuned with — MUST stay
# byte-identical to the training prompt. The fine-tune internalized the mapping, so no few-shot block
# or thinking is needed: ~5s/parse + 8/8 held-out vs the few-shot base's ~55s + 5/8 (Stage-2 eval).
PARSER_HINT = (
    "Convert the part description to a CadQuery spec JSON. shape is one of box|cylinder|loft|"
    "revolve|sweep. box:{length,width,height} cylinder:{diameter,height} loft:{length,width,"
    "height,width_top,height_top} revolve:profile=[[r,z],..] sweep:{diameter}+path=[[x,y,z],..]. "
    "features: through_hole/hole_pattern/fillet/chamfer/var_fillet/pocket/counterbore/countersink/"
    "draft/shell/thread/mirror/greeble. greeble{panel,depth,density,seed}=procedural sci-fi detail pass "
    "(panel grid + recessed panels) for greebled/detailed/panelled/industrial parts — on a box (top face), "
    "cylinder/revolve (side face: hull tubes/tanks/pods/nozzles/domes), or loft (top face). "
    "A STRAIGHT round body (just diameter + length/height, no bent path) is a CYLINDER, not a sweep; "
    "use sweep ONLY for a tube that follows a 3D path. greeble.bevel>0 for beveled/chamfered/machined-rim panels. "
    "Holes default to the z axis. Output ONLY the JSON.\nDescription: ")


def _chat(base_url, model, messages, timeout, think, max_tokens=2500):
    body = {"model": model, "messages": messages, "temperature": 0.0 if think else 0.4,
            "max_tokens": max_tokens}
    if not think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def _inset_holes(spec: Spec) -> Spec:
    """Nudge any box/loft z-hole that lands on/outside the footprint back fully inside (|x|≤L/2−d/2).
    A hole on the boundary is degenerate (half-hole, fails the hole↔edge check), so clamping is always
    the right correction. Fixes the parser's bare "hole at each end" → ±L/2; harmless when already inside."""
    e = spec.envelope
    if spec.shape == "box":
        L, W = e.get("length", 0.0), e.get("width", 0.0)
    elif spec.shape == "loft":
        L, W = e.get("length", 0.0), max(e.get("width", 0.0), e.get("width_top", e.get("width", 0.0)))
    else:
        return spec
    for f in spec.features:
        if f.type == "through_hole" and f.at is not None and getattr(f, "axis", "z") == "z":
            x, y = f.at; r = f.diameter / 2.0
            xm, ym = L / 2 - r - 0.5, W / 2 - r - 0.5
            nx = (xm if x > xm else -xm if x < -xm else x) if xm > 0 else x
            ny = (ym if y > ym else -ym if y < -ym else y) if ym > 0 else y
            if (nx, ny) != (x, y):
                f.at = (round(nx, 2), round(ny, 2))
    return spec


def prompt_to_spec(prompt: str, base_url: str = "http://localhost:8002/v1",
                   model: str = "parser3", timeout: float = 60.0, max_tries: int = 3) -> Spec:
    """NL → typed Spec via the fine-tuned parser adapter (research Stage 2.1). Direct mapping, no
    few-shot, no thinking: ~4s vs the few-shot base's ~50s, and higher semantic accuracy (27/28 vs 25/28
    held-out, incl. correct positioned holes after the positioned-hole corpus augment). PARSER_HINT carries
    the schema vocab; a validator-retry repairs the rare malformed JSON; `_inset_holes` clamps any
    boundary-placed hole inside. `model` must be a served adapter ('parser2') — the vLLM launch loads it
    from training/nl_spec_parser_v2. (Set model='qwen3.6-27b' + _SYSTEM + think=True for the few-shot fallback.)"""
    user = PARSER_HINT + prompt
    messages = [{"role": "user", "content": user}]
    last_err: Exception = RuntimeError("no attempt made")
    for attempt in range(max_tries):
        txt = _chat(base_url, model, messages, timeout, think=False)
        raw = _extract_json(txt)
        try:
            return _inset_holes(Spec(**json.loads(raw)))   # pydantic validates; clamp boundary holes inside
        except Exception as e:   # noqa: BLE001 — JSONDecodeError or pydantic ValidationError → repair
            last_err = e
            messages = [{"role": "user", "content": user},
                        {"role": "assistant", "content": raw[:1500]},
                        {"role": "user", "content": f"That is not valid ({type(e).__name__}: {e}). Output "
                         "ONLY a single corrected JSON object that parses and matches the schema."}]
    raise last_err
