"""Assembly → the L1/L2/L3 caption ladder, generated FROM verified structure (so a caption can never
describe geometry that isn't there — the batch-1 poison class is impossible by construction).

  L1  simple   — no numbers at all (gated): parts + relationships in plain words. Trains/serves the
                 casual prompt ("a four-wheeled cart") where the model INVENTS plausible dims.
  L2  rough    — the 1-2 governing dimensions, rounded ("about 20 cm long"): the middle user.
  L3  metric   — full transcription: every dim, count, joint axis + limits: the power user.

Identity (what the thing IS) comes from asm.object — real designer metadata for the Fusion leg,
family names for the synthetic leg; a VLM render-naming pass can override it upstream.
Lexical variety comes from seeded template picks (same discipline as captions._pick).
"""
from __future__ import annotations

import random
import re
from collections import Counter
from typing import Dict, List

from .assembly import Assembly, Component, Joint, Mate


def _pick(rng: random.Random, *opts: str) -> str:
    return opts[rng.randrange(len(opts))]


def _n(x: float, rough: bool = False) -> str:
    if rough:
        base = 5 if x < 60 else 10
        return f"{round(x / base) * base:g}"
    return f"{x:g}"


def _part_phrase(c: Component, level: int) -> str:
    """One part, at ladder level (1=no numbers, 2=rough headline dim, 3=exact)."""
    e = c.part.envelope or {}
    s = c.part.shape
    holes = [f for f in c.part.features if f.type in ("through_hole", "hole_pattern")]
    if level == 1:
        noun = {"box": "block", "cylinder": "round part", "prism": "faceted post", "revolve": "turned part",
                "sweep": "beam", "loft": "tapered arm", "profile_extrude": "profiled body",
                "loft_sections": "lofted body"}.get(s, "part")
        return f"a {c.part.object or noun}"
    if s == "box":
        dims = f"{_n(e.get('length', 0), level == 2)}×{_n(e.get('width', 0), level == 2)}×{_n(e.get('height', 0), level == 2)} mm"
    elif s in ("cylinder", "prism"):
        dims = f"⌀{_n(e.get('diameter', 0), level == 2)}×{_n(e.get('height', 0), level == 2)} mm"
    elif s == "revolve":
        d, h = c.part.revolve_extents()
        dims = f"⌀{_n(d, level == 2)}×{_n(h, level == 2)} mm turned"
    elif s == "sweep":
        if "width" in e:
            dims = f"{_n(e['width'], level == 2)}×{_n(e['height'], level == 2)} mm section"
        else:
            dims = f"⌀{_n(e.get('diameter', 0), level == 2)} mm"
    else:
        dims = ""
    out = f"a {dims} {c.part.object}".replace("  ", " ").strip()
    if level == 3 and holes:
        hp = []
        for f in c.part.features:
            if f.type == "through_hole":
                hp.append(f"a ⌀{f.diameter:g} mm through-hole")
            elif f.type == "hole_pattern" and f.pattern == "bolt_circle":
                hp.append(f"{f.count}×⌀{f.diameter:g} mm on a {f.pitch_diameter:g} mm bolt circle")
        if hp:
            out += f" ({', '.join(hp)})"
    return out


def _group(components: List[Component]) -> List[tuple]:
    """(count, representative) per identical-part group, preserving order of first appearance."""
    seen: Dict[str, list] = {}
    order = []
    for c in components:
        key = c.part.model_dump_json()
        if key not in seen:
            seen[key] = [0, c]
            order.append(key)
        seen[key][0] += 1
    return [(seen[k][0], seen[k][1]) for k in order]


_ORD = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 8: "eight"}


def _mate_phrases(asm: Assembly, level: int, rng: random.Random) -> List[str]:
    out = []
    _hn = lambda n: _humanize(n, asm)  # noqa: E731
    for m in asm.mates:
        if m.kind == "radial":
            p = f"arranged evenly around the {m.around or 'center'}"
            if level == 3 and m.radius:
                p += f" at radius {m.radius:g} mm"
                if m.splay_deg:
                    p += f", splayed {m.splay_deg:g}°"
            out.append(p)
        elif m.kind == "corners":
            p = f"at the corners of the {m.around or 'base'}"
            if level == 3 and m.dx:
                p += f" ({2 * m.dx:g}×{2 * (m.dy or 0):g} mm spacing)"
            out.append(p)
        elif m.kind == "stack":
            if m.fraction is not None:
                # mid-height dialect: the part is fixed PARTWAY UP its support, not on top
                if level == 1:
                    out.append(_pick(rng, f"the {_hn(m.a)} fixed partway up the {_hn(m.b)}",
                                     f"the {_hn(m.a)} mounted part-way up the {_hn(m.b)}"))
                elif level == 2:
                    word = ("near the bottom of" if m.fraction < 0.34
                            else "about halfway up" if m.fraction < 0.67 else "near the top of")
                    out.append(f"the {_hn(m.a)} {word} the {_hn(m.b)}")
                else:
                    out.append(f"the {_hn(m.a)} at {round(m.fraction * 100):g}% of the {_hn(m.b)} height")
            else:
                out.append(_pick(rng, f"the {_hn(m.a)} resting on the {_hn(m.b)}", f"the {_hn(m.a)} stacked on the {_hn(m.b)}"))
        elif m.kind == "ground":
            out.append(f"the {_hn(m.a)} sitting on the floor")
        elif m.kind == "coaxial":
            out.append(f"the {_hn(m.a)} coaxial with the {_hn(m.b)}")
        elif m.kind == "flush":
            out.append(f"the {_hn(m.a)} flush against the {_hn(m.b)}")
        elif m.kind == "port":
            # The brief MUST name the face, or port selection is unlearnable from the caption
            # (the whole point of FIX 2 is that placement becomes a discrete CHOICE). Faces are
            # bbox-frame but deterministic, so caption -> port is a learnable mapping.
            face = {"top": "on top of", "bottom": "underneath",
                    "front": "on the front face of", "back": "on the back face of",
                    "left": "on the left face of", "right": "on the right face of"}.get(m.b_port, "on")
            p = f"the {_hn(m.a)} mounted {face} the {_hn(m.b)}"
            if m.fraction is not None and m.b_port not in ("top", "bottom"):
                if level == 2:
                    word = ("low on" if m.fraction < 0.34 else "midway up"
                            if m.fraction < 0.67 else "high on")
                    p += f", {word} it"
                elif level == 3:
                    p += f", at {round(m.fraction * 100):g}% of its height"
            if level == 3 and m.b_port in ("top", "bottom") and m.offset and any(m.offset):
                p += f", offset ({m.offset[0]:g}, {m.offset[1]:g}) mm"
            out.append(p)
        elif m.kind == "mirror":
            out.append(f"the {_hn(m.a)} mirrored across from the {_hn(m.b)}")
    return out


def _joint_phrase(joints: List[Joint], level: int) -> str:
    if not joints:
        return ""
    by = Counter((j.axis, tuple(j.limits)) for j in joints)
    parts = []
    for (axis, (lo, hi)), cnt in by.items():
        who = f"{_ORD.get(cnt, str(cnt))} revolute joints" if cnt > 1 else "a revolute joint"
        if level == 1:
            parts.append(f"{who} letting {'them' if cnt > 1 else 'it'} "
                         + ("spin freely" if hi - lo >= 355 else "swing"))
        else:
            rng_txt = "spinning freely (0–360°)" if hi - lo >= 355 else f"limited {lo:g}–{hi:g}°"
            ax = {"x": "along the length", "y": "across the width", "z": "vertical"}[axis]
            parts.append(f"{who} ({ax} axis, {rng_txt})")
    return "; ".join(parts)


def _humanize(name: str, asm: Assembly) -> str:
    """Internal part names → speech: 'leg0' → 'legs' (when it's one of a group), 'seat' unchanged."""
    stem = re.sub(r"\d+$", "", name)
    if stem != name and sum(1 for c in asm.components if re.sub(r"\d+$", "", c.name) == stem) > 1:
        return stem + ("s" if not stem.endswith("s") else "")
    return name


def asm_describe(asm: Assembly, rng: random.Random) -> Dict[str, str]:
    """Assembly → {'l1','l2','l3'}. l1 is digit-free by construction + gated."""
    obj = asm.object or "assembly"
    # digit-free object variant for L1 ("5-leg stool" → "five-leg stool")
    obj_l1 = re.sub(r"\b(\d+)\b", lambda m: _ORD.get(int(m.group(1)), "multi"), obj)
    groups = _group(asm.components)

    def parts_at(level: int) -> str:
        bits = []
        for cnt, rep in groups:
            ph = _part_phrase(rep, level)
            if cnt > 1:
                ph = f"{_ORD.get(cnt, str(cnt))} {ph.split(' ', 1)[1] if ph.startswith('a ') else ph}"
                ph = re.sub(r"\ba\b ", "", ph) if False else ph
                # naive plural: "two ... wheel" reads fine as "two ... wheels"
                if ph.endswith("f") and not ph.endswith("ff"):   # shelf → shelves (not "shelfs")
                    ph = ph[:-1] + "ves"
                elif not ph.endswith("s"):
                    ph += "s"
            bits.append(ph)
        return ", ".join(bits)

    mates1 = _mate_phrases(asm, 1, rng)
    j1 = _joint_phrase(asm.joints, 1)
    l1 = f"A {obj_l1}: {parts_at(1)}"
    if mates1:
        # up to 3 phrases so a DEFINING third relationship (a rack's mid-height shelf) isn't dropped
        l1 += f" — {mates1[0]}" if len(mates1) == 1 else f" — {'; '.join(mates1[:3])}"
    if j1:
        l1 += f", with {j1}"
    l1 += "."
    l1 = re.sub(r"\d+(\.\d+)?", "", l1).replace(" ×× mm", "").replace("⌀× mm", "")  # belt-and-braces
    l1 = re.sub(r"\s{2,}", " ", l1).replace(" ,", ",").replace(" .", ".")

    mates2 = _mate_phrases(asm, 2, rng)
    j2 = _joint_phrase(asm.joints, 2)
    l2 = f"A {obj}: {parts_at(2)}"
    if mates2:
        l2 += f" — {'; '.join(mates2[:3])}"
    if j2:
        l2 += f"; {j2}"
    l2 += "."

    mates3 = _mate_phrases(asm, 3, rng)
    j3 = _joint_phrase(asm.joints, 3)
    l3 = f"Model a {obj}: {parts_at(3)}"
    if mates3:
        l3 += f" — {'; '.join(mates3)}"
    if j3:
        l3 += f"; {j3}"
    l3 += "."

    return {"l1": l1, "l2": l2, "l3": l3}


def gate_caption(level: str, text: str, asm: Assembly) -> bool:
    """Per-level honesty gate. L1: NO digits allowed. L2/L3: every number in the text must map to a
    structural quantity (dim/coordinate-derived/count/limit, with rough rounding tolerance for L2)."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if level == "l1":
        return not nums
    pool: List[float] = []
    for c in asm.components:
        pool.extend(v for v in (c.part.envelope or {}).values() if isinstance(v, (int, float)))
        for f in c.part.features:
            for k in ("diameter", "pitch_diameter", "count", "spacing", "radius", "distance", "thickness"):
                v = getattr(f, k, None)
                if isinstance(v, (int, float)):
                    pool.append(float(v))
        if c.part.shape == "revolve":
            d, h = c.part.revolve_extents()
            pool.extend([d, h])
    for m in asm.mates:
        for k in ("radius", "splay_deg", "dx", "dy", "z"):
            v = getattr(m, k, None)
            if isinstance(v, (int, float)):
                pool.extend([float(v), 2 * float(v)])
        if getattr(m, "fraction", None) is not None:   # mid-height share, spoken as a percentage
            pool.extend([float(m.fraction), float(round(m.fraction * 100))])
    for j in asm.joints:
        pool.extend([float(j.limits[0]), float(j.limits[1])])
    pool.extend(float(x) for x in range(0, 10))          # counts/ordinals
    pool.append(360.0)
    tol = 6.0 if level == "l2" else 0.51
    return all(any(abs(n - p) <= tol for p in pool) for n in nums)
