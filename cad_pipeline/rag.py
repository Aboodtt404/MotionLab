"""Doc-lookup / RAG over CadQuery (track-a §5; recipe from CADSmith + Zero-to-CAD).

The dominant baseline failure is exec/API fluency (off-the-shelf scores ≈0 because
"code fluency ≠ CAD syntax"). The literature's cheapest lever — rated above blind
resampling — is **retrieval over CadQuery docs**. Corpus = the three sources both
papers use:
  • METHODS  — the installed CadQuery API, introspected (name + REAL signature + doc
               head). Version-matched, so a retrieved signature is GROUND TRUTH —
               e.g. `workplane(offset: float = 0.0, …)` directly refutes `.workplane('XY')`.
  • EXAMPLES — canonical correct snippets, mirroring builder.py's golden patterns
               (the exact `.rect(l,w).cutBlind(-d)` pocket the base model never found).
  • ERRORFIX — the repair.py error→fix table (the motoko-repair hints).

Retrieval (Zero-to-CAD): TF-IDF `lookup(query)` + regex `grep(pattern)`, pure-Python
(no sklearn). `reference_block(spec, feedback)` assembles a tight, prompt-injectable
reference: spec-driven on attempt 1, error-driven (diagnose + grep the offending
symbol) on retries. Examples are selected deterministically by feature type so the
needed recipe is ALWAYS present, not left to fuzzy ranking.
"""
from __future__ import annotations

import inspect
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional

import cadquery as cq

from .repair import _FIXES, diagnose
from .spec import Spec

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def _tokenize(s: str) -> List[str]:
    out: List[str] = []
    for w in _TOKEN.findall(s):
        lw = w.lower()
        out.append(lw)
        for p in _CAMEL.findall(w):            # split camelCase: cutThruAll → cut thru all
            lp = p.lower()
            if lp and lp != lw:
                out.append(lp)
    return out


@dataclass
class Doc:
    kind: str       # method | example | errorfix
    name: str
    text: str       # searchable body
    render: str     # what gets injected into the prompt


# --------------------------------------------------------------------------- corpus
# Canonical correct snippets — mirror builder.py (our golden reference of valid CadQuery).
# Keyed by the spec token that should pull them in, so the right recipe is guaranteed.
_EXAMPLES = {
    "box":     ('centered box', 'result = cq.Workplane("XY").box(L, W, H)  # centered at the origin'),
    "cylinder":('cylinder (extrude a circle)', 'result = cq.Workplane("XY").circle(D/2).extrude(H)'),
    "through_hole": ('through-hole on the top face',
                     'result = result.faces(">Z").workplane().hole(diameter)  # centered hole, full depth'),
    "from_edge":('hole positioned N mm from an edge (box centered at origin → x = -L/2 + N)',
                 'result = result.faces(">Z").workplane().pushPoints([(-L/2 + N, 0)]).hole(diameter)'),
    "multi_hole":('MULTIPLE holes at explicit (x,y) — place them ALL AT ONCE with pushPoints '
                  '(absolute, origin = part center). Do NOT chain .center() per hole: .center() is '
                  'RELATIVE and accumulates, so the 2nd+ holes drift off-target.',
                  'result = result.faces(">Z").workplane().pushPoints([(x1, y1), (x2, y2), (x3, y3)]).hole(diameter)'),
    "fillet":  ('fillet the VERTICAL edges', 'result = result.edges("|Z").fillet(radius)'),
    "chamfer": ('chamfer the VERTICAL edges', 'result = result.edges("|Z").chamfer(distance)'),
    "pocket":  ('rectangular pocket / panel inset cut into the top face. With a position use a FRESH '
                'workplane with centerOption="CenterOfBoundBox" so .center is absolute (no drift).',
                'result = result.faces(">Z").workplane(centerOption="CenterOfBoundBox").center(x, y).rect(length, width).cutBlind(-depth)'),
    # --- Tier 1–3 vocabulary (exact builder patterns; match these conventions so the verifier passes) ---
    "revolve": ('turned body (revolve): spin a meridian of [radius, z] points about Z. Build the profile in '
                'XY (x=radius, y=axial), revolve about the in-plane Y axis, then rotate +90° about X so it '
                'stands on Z. Solid body ⇒ start AND end at radius 0; tube ⇒ keep radius>0 throughout.',
                '_rv = cq.Workplane("XY").polyline([(r0, z0), (r1, z1)]).close().revolve(360, (0, 0, 0), (0, 1, 0))\n'
                'result = cq.Workplane(obj=_rv.val().rotate((0, 0, 0), (1, 0, 0), 90))'),
    "sweep":   ('round tube (sweep): a circle of diameter D swept along a 3D path of [x,y,z] points. Assemble '
                'the path from 3D line edges; put the profile on a plane perpendicular to the FIRST segment.',
                '_pts = [cq.Vector(*p) for p in [(x0, y0, z0), (x1, y1, z1)]]\n'
                '_path = cq.Wire.assembleEdges([cq.Edge.makeLine(_pts[i], _pts[i + 1]) for i in range(len(_pts) - 1)])\n'
                '_t0 = (_pts[1] - _pts[0]).normalized()\n'
                'result = cq.Workplane(cq.Plane(origin=_pts[0].toTuple(), normal=_t0.toTuple())).circle(D / 2).sweep(cq.Workplane(obj=_path), isFrenet=True)'),
    "loft":    ('tapered bar / adapter (loft) along X, centered: rect base (W×H) lofted to a tip. Tip = '
                '.rect(Wt, Ht) for a tapered bar, or .circle(diameter_top/2) for a round-to-rect adapter.',
                '_lf = cq.Workplane("YZ").rect(W, H).workplane(offset=L).rect(Wt, Ht).loft(ruled=True)\n'
                'result = cq.Workplane(obj=_lf.val().translate(cq.Vector(-L / 2, 0, 0)))'),
    "draft":   ('draft (box side walls tapered for molding): build the box AS A TAPERED EXTRUDE (replaces '
                '.box) — base L×W at z=-H/2, tapering inward by `angle`° up to the top. Do this FIRST, then '
                'add other features.',
                'result = cq.Workplane("XY").workplane(offset=-H / 2).rect(L, W).extrude(H, taper=angle)'),
    "counterbore": ('counterbored hole (recess for a socket-head screw): pilot ⌀ + a larger flat recess, '
                    'drilled from the top face.',
                    'result = result.faces(">Z").workplane().pushPoints([(x, y)]).cboreHole(diameter, cbore_diameter, cbore_depth)'),
    "countersink": ('countersunk hole (conical seat for a flat-head screw): csk_angle is the INCLUDED angle '
                    '(usually 90).',
                    'result = result.faces(">Z").workplane().pushPoints([(x, y)]).cskHole(diameter, csk_diameter, csk_angle)'),
    "mirror":  ('mirror to make a part symmetric: build the fully-featured part FIRST, then reflect+union '
                'across the plane (the base shape must straddle the plane so the envelope is unchanged).',
                'result = result.mirror("YZ", union=True)   # plane "YZ" | "XZ" | "XY"'),
    "shell":   ('shell (hollow a box to a thin wall): top-open ⇒ select the face to remove then shell inward; '
                'sealed hollow ⇒ shell with NO face removed. Do this before cutting holes/pockets.',
                'result = result.faces(">Z").shell(-thickness)   # top-open;  sealed: result = result.shell(-thickness)'),
    "var_fillet": ('variable-radius fillet (radius sweeps r1→r2 along each edge): the fluent .fillet() is '
                   'constant-radius only — use raw OCCT BRepFilletAPI_MakeFillet.Add(r1, r2, edge).',
                   'from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet\n'
                   '_mk = BRepFilletAPI_MakeFillet(result.val().wrapped)\n'
                   'for _e in result.edges("|Z").vals(): _mk.Add(r1, r2, _e.wrapped)\n'
                   'result = cq.Workplane(obj=cq.Shape(_mk.Shape()))'),
    "thread":  ('cosmetic thread (the helix is a callout, not modeled): internal ⇒ a nominal bore of '
                '`diameter`; external ⇒ the part cylinder ALREADY is the thread (add no extra geometry).',
                'result = result.faces(">Z").workplane().pushPoints([(x, y)]).hole(diameter)   # internal tapped bore'),
}
# Always-useful selector/coordinate cheats (cheap, high-value, counter common hallucinations).
_CHEATS = [
    ('selector: vertical edges', '`.edges("|Z")` selects edges parallel to Z (the vertical ones).'),
    ('selector: top face', '`.faces(">Z")` selects the topmost face; `.workplane()` then sketches on it.'),
    ('workplane offset is numeric', '`.workplane(offset=0.0)` takes a FLOAT offset, never a plane name. '
                                    'Start a plane with `cq.Workplane("XY")`, not `.workplane("XY")`.'),
    ('.center() is RELATIVE', '`.center(x,y)` shifts the workplane origin RELATIVE to its current position '
                              'and accumulates across calls; a fresh `.faces(">Z").workplane()` also carries '
                              'the prior origin. For absolute multi-hole placement use one '
                              '`.pushPoints([(x,y),...]).hole(d)`, NOT repeated `.center().hole()`.'),
]


@lru_cache(maxsize=1)
def _corpus() -> List[Doc]:
    docs: List[Doc] = []
    # METHODS — introspect the installed CadQuery Workplane API (ground-truth signatures).
    for name, fn in inspect.getmembers(cq.Workplane, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        try:
            sig = str(inspect.signature(fn)).replace("self: ~T, ", "").replace("self, ", "")
        except (ValueError, TypeError):
            sig = "(...)"
        doc_head = " ".join((inspect.getdoc(fn) or "").split())[:200]
        docs.append(Doc("method", name, f"{name} {doc_head}",
                        f'Workplane.{name}{sig}' + (f"\n    # {doc_head[:140]}" if doc_head else "")))
    # EXAMPLES + cheats.
    for key, (desc, code) in _EXAMPLES.items():
        docs.append(Doc("example", key, f"{key} {desc} {code}", f"# {desc}\n{code}"))
    for desc, txt in _CHEATS:
        docs.append(Doc("example", desc, f"{desc} {txt}", f"# {desc}: {txt}"))
    # ERRORFIX — the repair table.
    for pat, hint in _FIXES:
        docs.append(Doc("errorfix", pat.pattern[:40], hint, f"# fix: {hint}"))
    return docs


@lru_cache(maxsize=1)
def _idf() -> dict:
    docs = _corpus()
    df: dict = {}
    for d in docs:
        for t in set(_tokenize(d.text)):
            df[t] = df.get(t, 0) + 1
    n = len(docs)
    return {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}


def _vec(tokens: List[str]) -> dict:
    idf = _idf()
    tf: dict = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return {t: (c / len(tokens)) * idf.get(t, 0.0) for t, c in tf.items()} if tokens else {}


@lru_cache(maxsize=1)
def _doc_vecs() -> list:
    """(doc, tfidf-vector, ‖vector‖) for every corpus entry — computed once."""
    out = []
    for d in _corpus():
        v = _vec(_tokenize(d.text))
        out.append((d, v, math.sqrt(sum(x * x for x in v.values()))))
    return out


def _cosine(a: dict, da: float, b: dict, db: float) -> float:
    if not a or not b or not da or not db:
        return 0.0
    return sum(a[t] * b[t] for t in (set(a) & set(b))) / (da * db)


# --------------------------------------------------------------------------- public retrieval
def lookup(query: str, k: int = 5, kinds: Optional[tuple] = None) -> List[Doc]:
    """TF-IDF ranked retrieval (Zero-to-CAD `lookup`). Only returns docs that actually
    match the query — never pads the top-k with zero-score noise."""
    qv = _vec(_tokenize(query))
    qn = math.sqrt(sum(x * x for x in qv.values()))
    scored = [(d, _cosine(qv, qn, v, dn)) for d, v, dn in _doc_vecs()
              if kinds is None or d.kind in kinds]
    scored = [(d, s) for d, s in scored if s > 0]
    scored.sort(key=lambda ds: ds[1], reverse=True)
    return [d for d, _ in scored[:k]]


def grep(pattern: str, k: int = 8) -> List[Doc]:
    """Regex search over symbol name + doc/snippet body (Zero-to-CAD `grep`) — for exact
    symbols. Excludes the boilerplate `Workplane.` render prefix so a query like
    `workplane` matches the *method named* workplane, not every method's class prefix.
    Name matches rank ahead of body matches."""
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)
    name_hits = [d for d in _corpus() if rx.search(d.name)]
    body_hits = [d for d in _corpus() if d not in name_hits and rx.search(d.text)]
    return (name_hits + body_hits)[:k]


def _examples_for_spec(spec: Spec) -> List[Doc]:
    """Deterministically pull the canonical recipe(s) the spec needs — guaranteed present."""
    keys = [spec.shape]
    n_placed_holes = 0
    for f in spec.features:
        keys.append(f.type)
        if f.type == "through_hole" and getattr(f, "from_edge", None) is not None and spec.shape == "box":
            keys.append("from_edge")
        if f.type == "through_hole" and getattr(f, "at", None) is not None:
            n_placed_holes += 1
    # ≥2 explicitly-positioned holes ⇒ the .center()-accumulation trap (the #1 L2/L3 failure):
    # surface the absolute pushPoints idiom + the relative-center warning.
    always = ["selector: vertical edges", "selector: top face", "workplane offset is numeric"]
    if n_placed_holes >= 2:
        keys.append("multi_hole")
        always.append(".center() is RELATIVE")
    by_name = {d.name: d for d in _corpus() if d.kind == "example"}
    seen, out = set(), []
    for key in keys:
        d = by_name.get(key)
        if d and d.name not in seen:
            seen.add(d.name); out.append(d)
    out += [d for d in _corpus() if d.kind == "example" and d.name in always]
    return out


def reference_block(spec: Spec, feedback: Optional[str] = None) -> str:
    """Assemble a tight, prompt-injectable CadQuery reference. Spec-driven on the first
    attempt; error-driven (diagnose + grep the offending symbol) on retries."""
    parts: List[str] = []
    if feedback:
        hint = diagnose(feedback)
        if hint:
            parts.append(f"# fix: {hint}")
        for sym in set(re.findall(r"\.(\w+)\(", feedback)):   # method calls in the traceback
            for d in grep(rf"\b{re.escape(sym)}\b", k=2):
                if d.kind == "method" and sym.lower() in d.name.lower():
                    parts.append(d.render)
        for d in lookup(feedback, k=3, kinds=("method",)):
            parts.append(d.render)
    else:
        for d in _examples_for_spec(spec):
            parts.append(d.render)
        feat_query = f"{spec.shape} " + " ".join(f.type for f in spec.features)
        for d in lookup(feat_query, k=4, kinds=("method",)):
            parts.append(d.render)
    # dedupe, preserve order, bound size
    seen, lines = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p); lines.append(p)
    body = "\n".join(lines[:16])
    return ("## Retrieved CadQuery reference (use these exact signatures/patterns)\n" + body) if body else ""
