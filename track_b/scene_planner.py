"""LLM scene-planner — text prompt → 3D scene-graph for scene_compose.py.

The Track-B counterpart to cad_pipeline/planner.py, one scale up (objects-in-a-scene, not parts-in-an-
object). Same pattern: an LLM on the local vLLM (:8002) emits a HIGH-LEVEL scene under a constrained JSON
schema (reason-then-constrain), then a deterministic COMPILER lowers it to the scene_compose graph (param
defaults + asset resolution + placement presets). Edits are deltas that keep the SAME seed → same forest.
See docs/research/scene-planner-design.md.

  from track_b.scene_planner import plan, edit
  g = plan("a fantasy sword planted in a misty pine forest clearing")   # → scene_compose graph (dict)
  g2 = edit(g, "put the sword in a mossy stone")                        # → same forest, sword in a stone
  # then: json.dump(g, ...) ; blender -b -P scene_compose.py -- graph.json out

Stdlib only (urllib/json/re) — talks to vLLM over HTTP; no heavy deps.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

VLLM_URL = os.environ.get("SCENE_LLM_URL", "http://localhost:8002/v1")
VLLM_MODEL = os.environ.get("SCENE_LLM_MODEL", "qwen3.6-27b")
ASSET_DIR = os.environ.get("SCENE_ASSET_DIR", "/workspace/.hf_home/scene_assets")
SEED = 7  # fixed → the forest is identical across edits ("same forest, move the sword")

# ── high-level scene schema (what the LLM emits; reason-then-constrain) ───────────────────────────
SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "scene": {
            "type": "object",
            "properties": {
                "biome": {"type": "string",
                          "enum": ["pine_forest", "autumn_forest", "jungle", "rocky", "meadow", "snow"]},
                "time_of_day": {"type": "string",
                                "enum": ["dawn", "midday", "golden_hour", "dusk", "night"]},
                "scatter": {"type": "array", "items": {"type": "object", "properties": {
                    "asset_class": {"type": "string"},
                    "density": {"type": "string", "enum": ["sparse", "medium", "dense"]}},
                    "required": ["asset_class", "density"]}},
                "heroes": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "string"},
                    "asset_desc": {"type": "string"},
                    "placement": {"type": "string",
                                  "enum": ["planted_clearing", "standing_clearing", "on_ground", "in_stone"]},
                    "relation_target": {"type": "string"}},
                    "required": ["id", "asset_desc", "placement"]}},
                "camera": {"type": "string", "enum": ["hero_closeup", "hero_3quarter", "wide_establishing"]},
            },
            "required": ["biome", "time_of_day", "scatter", "heroes", "camera"],
        },
    },
    "required": ["reasoning", "scene"],
}

_SYSTEM = (
    "You are a 3D scene art director. Turn the user's prompt into a SCENE plan for an outdoor shot.\n"
    "Think in the 'reasoning' field, then emit 'scene':\n"
    "- biome: the ground+foliage setting. time_of_day: drives the lighting.\n"
    "- scatter: background vegetation/clutter as CLASSES with density (never individual objects). "
    "e.g. {asset_class:'pine tree', density:'dense'}.\n"
    "- heroes: the focal objects, each with an id, a short asset_desc (what to generate), and a placement:\n"
    "    planted_clearing = stuck upright in the open center (e.g. a sword planted blade-down);\n"
    "    standing_clearing = standing in the center; on_ground = resting on the ground;\n"
    "    in_stone = embedded INTO another hero — set relation_target to that hero's id.\n"
    "  To make 'a sword in a stone', emit TWO heroes: a boulder (on_ground) and a sword "
    "(in_stone, relation_target=the boulder's id).\n"
    "- camera: PREFER hero_3quarter (or hero_closeup) so the focal object is clearly framed and prominent; "
    "use wide_establishing ONLY when the prompt is about landscape/atmosphere rather than a hero object.\n"
    "Keep heroes to 1-3. Output ONLY the JSON object."
)

# ── deterministic lowering tables (the composer holds the procedural defaults) ────────────────────
_BIOME = {
    "pine_forest": {"color": [0.05, 0.11, 0.045], "scatter_default": "pine tree"},
    "autumn_forest": {"color": [0.12, 0.09, 0.04], "scatter_default": "tree"},
    "jungle": {"color": [0.03, 0.10, 0.03], "scatter_default": "tree"},
    "rocky": {"color": [0.10, 0.10, 0.09], "scatter_default": "rock"},
    "meadow": {"color": [0.08, 0.14, 0.05], "scatter_default": "bush"},
    "snow": {"color": [0.55, 0.58, 0.62], "scatter_default": "pine tree"},
}
_LIGHT = {  # sun_elev, sun_azim, energy, sky_strength, haze, dust
    "dawn": dict(sun_elev=8, sun_azim=80, sun_energy=3.5, sky_strength=1.0, haze=2.4, dust=3.0),
    "midday": dict(sun_elev=62, sun_azim=40, sun_energy=5.0, sky_strength=1.0, haze=1.0, dust=1.0),
    "golden_hour": dict(sun_elev=12, sun_azim=60, sun_energy=4.5, sky_strength=1.0, haze=2.0, dust=2.8),
    "dusk": dict(sun_elev=4, sun_azim=300, sun_energy=3.0, sky_strength=0.9, haze=2.6, dust=3.2),
    "night": dict(sun_elev=-4, sun_azim=300, sun_energy=0.6, sky_strength=0.3, haze=2.0, dust=2.0),
}
_DENSITY = {"sparse": 40, "medium": 80, "dense": 115}
_CAMERA = {
    "hero_closeup": {"loc": [3.6, -5.0, 2.2], "target": [0, 0, 1.0], "lens": 80, "keepout": 7.0},
    "hero_3quarter": {"loc": [5.5, -7.5, 3.4], "target": [0, 0, 1.1], "lens": 65, "keepout": 7.0},
    "wide_establishing": {"loc": [9, -12, 5.5], "target": [0, 0, 1.0], "lens": 45, "keepout": 8.0},
}
# desc keyword → cached GLB (extend by generating via TRELLIS; trees use the proxy for now)
_ASSET_CACHE = {"sword": "sword.glb", "blade": "sword.glb",
                "stone": "stone.glb", "boulder": "stone.glb", "rock": "stone.glb"}


TRACKB_URL = os.environ.get("SCENE_TRACKB_URL", "http://localhost:8770")


def _slug(desc: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", desc.lower()).strip("_")[:48] or "asset"


def _generate_asset(desc: str, slug: str, tier: str = "1024_cascade") -> str:
    """Generate a hero GLB on demand via Track B (FLUX→TRELLIS), cache it in ASSET_DIR. Blocks ~1-2min."""
    import base64
    import time
    body = json.dumps({"prompt": desc + ", a single isolated object, plain neutral background, studio product shot",
                       "pipeline_type": tier, "seed": 11}).encode()
    jid = json.loads(urllib.request.urlopen(urllib.request.Request(
        TRACKB_URL + "/text2mesh", data=body, headers={"Content-Type": "application/json"}),
        timeout=30).read())["job_id"]
    while True:
        time.sleep(4)
        j = json.loads(urllib.request.urlopen(f"{TRACKB_URL}/job/{jid}", timeout=20).read())
        if j["status"] == "done":
            path = os.path.join(ASSET_DIR, slug + ".glb")
            os.makedirs(ASSET_DIR, exist_ok=True)
            open(path, "wb").write(base64.b64decode(j["glb_b64"]))
            return path
        if j["status"] == "error":
            raise RuntimeError(j.get("error", "generation failed"))


def _resolve_asset(desc: str, kind: str = "hero", generate: bool = True) -> str:
    """asset description → a GLB path or a scene_compose proxy keyword. Heroes are GENERATED via TRELLIS on
    a cache miss; scatter classes use proxies (instancing hundreds of generated meshes is for later/Infinigen)."""
    d = desc.lower()
    for kw, fn in _ASSET_CACHE.items():                    # fast keyword cache (sword/stone we already have)
        if kw in d and os.path.exists(os.path.join(ASSET_DIR, fn)):
            return os.path.join(ASSET_DIR, fn)
    if kind == "scatter":                                  # forests: proxy (cheap, instanced); real trees = Infinigen later
        if any(t in d for t in ("tree", "pine", "fir", "conifer")):
            return "proxy_tree"
        return "proxy_rock"
    cached = os.path.join(ASSET_DIR, _slug(desc) + ".glb")  # persistent per-description cache
    if os.path.exists(cached):
        return cached
    if generate:
        try:
            return _generate_asset(desc, _slug(desc))
        except Exception as e:  # noqa: BLE001 — fall back to a proxy rather than failing the whole scene
            print(f"[scene_planner] asset gen failed for {desc!r}: {e}; using proxy")
    return "proxy_rock"


def compile_scene(scene: dict, seed: int = SEED) -> dict:
    """High-level scene → low-level scene_compose graph (deterministic; the composer's procedural defaults)."""
    biome = _BIOME.get(scene.get("biome", "pine_forest"), _BIOME["pine_forest"])
    light = dict(_LIGHT.get(scene.get("time_of_day", "golden_hour"), _LIGHT["golden_hour"]))
    cam = dict(_CAMERA.get(scene.get("camera", "hero_3quarter"), _CAMERA["hero_3quarter"]))

    scatter = []
    for s in scene.get("scatter", []):
        cls = s.get("asset_class") or biome["scatter_default"]
        asset = _resolve_asset(cls, "scatter")
        th = 4.5 if asset == "proxy_tree" else 1.2
        scatter.append({"asset": asset, "count": _DENSITY.get(s.get("density", "medium"), 80),
                        "area": 28, "clearing_radius": 6.0, "target_height": th,
                        "scale_jitter": [0.7, 1.7]})

    nodes = []
    for h in scene.get("heroes", []):
        asset = _resolve_asset(h.get("asset_desc", ""), "hero")
        place = h.get("placement", "standing_clearing")
        node = {"id": h["id"], "asset": asset, "target_height": 1.7, "tilt": 0, "yaw": 20}
        if place == "in_stone" and h.get("relation_target"):
            node["place"] = {"embedded_in": h["relation_target"], "by": 0.42}
        elif place == "planted_clearing":
            node.update({"at": [0, 0], "place": "grounded", "sink": 0.08})  # sword is tip-down by nature
        elif place == "on_ground":
            node.update({"at": [0, 0], "place": "grounded", "target_height": 1.0})
        else:  # standing_clearing
            node.update({"at": [0, 0], "place": "grounded"})
        nodes.append(node)
    # ensure a referenced relation_target is placed before its dependent (stone before sword)
    nodes.sort(key=lambda n: isinstance(n.get("place"), dict))

    return {
        "seed": seed,
        "terrain": {"size": 30, "subdiv": 200, "disp": 0.7, "noise_scale": 3.5, "color": biome["color"]},
        "scatter": scatter,
        "lighting": light,
        "camera": cam,
        "nodes": nodes,
        "_scene": scene,  # keep the high-level scene attached for edits
    }


def _extract_json(txt: str) -> str:
    m = re.findall(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        return m[-1].strip()
    a, b = txt.find("{"), txt.rfind("}")
    return txt[a:b + 1] if a >= 0 and b > a else txt


def _chat(system: str, user: str, schema: dict | None, timeout: float = 180.0, temp: float = 0.2) -> str:
    payload = json.dumps({
        "model": VLLM_MODEL, "temperature": temp, "max_tokens": 1500,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        **({"response_format": {"type": "json_schema",
                                "json_schema": {"name": "scene", "schema": schema}}} if schema else {}),
    }).encode()
    req = urllib.request.Request(VLLM_URL + "/chat/completions", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def plan(prompt: str, retries: int = 2) -> dict:
    """Text prompt → a ready-to-render scene_compose graph."""
    last = None
    for _ in range(retries + 1):
        try:
            data = json.loads(_extract_json(_chat(_SYSTEM, "prompt: " + prompt, SCENE_SCHEMA)))
            return compile_scene(data["scene"])
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last = e
    raise RuntimeError(f"scene plan failed: {last}")


_EDIT_SYSTEM = (
    "You edit a 3D scene. Given the current high-level scene JSON and an instruction, return the FULL updated "
    "scene JSON (same schema). Change ONLY what the instruction asks; keep biome, time_of_day, scatter, camera "
    "and untouched heroes identical. To put an existing hero into a stone: add a boulder hero (on_ground) and "
    "set the hero's placement to in_stone with relation_target = the boulder's id. Output ONLY the JSON."
)


def edit(graph: dict, instruction: str, retries: int = 2) -> dict:
    """Apply an NL edit; recompiles with the SAME seed → the forest is unchanged, only heroes recompose."""
    scene = graph.get("_scene")
    if scene is None:
        raise ValueError("graph has no attached _scene to edit")
    user = f"current scene:\n{json.dumps(scene)}\n\ninstruction: {instruction}"
    last = None
    for _ in range(retries + 1):
        try:
            data = json.loads(_extract_json(_chat(_EDIT_SYSTEM, user, SCENE_SCHEMA)))
            return compile_scene(data["scene"], seed=graph.get("seed", SEED))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last = e
    raise RuntimeError(f"scene edit failed: {last}")


if __name__ == "__main__":
    import sys
    out = sys.argv[2] if len(sys.argv) > 2 else "scene_graph.json"
    g = plan(sys.argv[1] if len(sys.argv) > 1 else "a sword planted in a misty pine forest clearing")
    json.dump(g, open(out, "w"), indent=2)
    print("PLAN_OK ->", out)
    print("  heroes:", [(n["id"], n["asset"].split("/")[-1], n.get("place")) for n in g["nodes"]])
