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
    "You convert a natural-language description of a HARD-SURFACE CAD part into a JSON spec. "
    "Reason briefly if needed, then output ONLY the final JSON object inside a single ```json code block.\n\n"
    "SCHEMA:\n"
    '{"object": str, "shape": "box"|"cylinder", '
    '"envelope": {box: "length","width","height"} OR {cylinder: "diameter","height"}, '
    '"features": [ ... ], "tolerance": float}\n'
    "FEATURE TYPES:\n"
    '  {"type":"through_hole","diameter":D, "from_edge":N?, "at":[x,y]?}  (origin = part center)\n'
    '  {"type":"hole_pattern","pattern":"bolt_circle"|"linear_x"|"grid","diameter":D,"count":N,'
    '"pitch_diameter":P?,"spacing":S?,"nx":?,"ny":?}\n'
    '  {"type":"fillet","radius":R}   {"type":"chamfer","distance":T}   '
    '{"type":"pocket","length":L,"width":W,"depth":Dp}\n\n'
    "RULES:\n"
    "- Units are mm. Default tolerance 0.1 if unstated.\n"
    "- A hole given by RADIUS r ⇒ diameter = 2*r. A hole given by diameter/⌀ d ⇒ diameter = d.\n"
    "- 'centered' hole ⇒ omit from_edge and at. 'N mm from the edge' ⇒ from_edge:N. "
    "An explicit (x,y) ⇒ at:[x,y]. Several holes at named spots ⇒ several through_hole entries.\n"
    "- Regular hole arrays ⇒ hole_pattern (bolt circle on a pitch-circle diameter, a linear row, or a grid).\n"
    "- 'rounded'/'filleted' edges ⇒ a fillet; 'chamfered'/'beveled' ⇒ a chamfer; a recess/cavity ⇒ a pocket.\n"
    "- fillet and chamfer apply to a BOX's vertical edges only. For a CYLINDER, do NOT emit fillet/chamfer "
    "(rim-rounding is not modeled yet) — just omit it.\n"
    "- 'A x B' for a cylinder ⇒ diameter=A, height=B. 'A x B x C' ⇒ a box length=A,width=B,height=C.\n\n"
    "EXAMPLES:\n"
    "input: rounded cylinder 40 x 25, centered hole with a radius of 5\n"
    '```json\n{"object":"rounded cylinder","shape":"cylinder","envelope":{"diameter":40,"height":25},'
    '"features":[{"type":"through_hole","diameter":10}],"tolerance":0.1}\n```\n'
    "input: 100x60x8 plate, rounded corners r5, four 6mm holes 12mm in from each corner\n"
    '```json\n{"object":"plate","shape":"box","envelope":{"length":100,"width":60,"height":8},'
    '"features":[{"type":"fillet","radius":5},'
    '{"type":"through_hole","diameter":6,"at":[-38,-18]},{"type":"through_hole","diameter":6,"at":[38,-18]},'
    '{"type":"through_hole","diameter":6,"at":[-38,18]},{"type":"through_hole","diameter":6,"at":[38,18]}],'
    '"tolerance":0.1}\n```\n'
    "input: 90mm flange, 12mm bore, six 6mm bolts on a 70mm circle\n"
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


def prompt_to_spec(prompt: str, base_url: str = "http://localhost:8002/v1",
                   model: str = "qwen3.6-27b", timeout: float = 120.0) -> Spec:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": "input: " + prompt}],
        "temperature": 0, "max_tokens": 2500,
    }).encode()
    req = urllib.request.Request(base_url + "/chat/completions", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        txt = json.loads(r.read())["choices"][0]["message"]["content"]
    data = json.loads(_extract_json(txt))
    return Spec(**data)   # pydantic validates; raises on a malformed spec
