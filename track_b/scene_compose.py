"""Compositional scene builder (Track B · environment generation, thin slice).

A scene is an ASSEMBLY, not a baked mesh: a persistent scene-graph (JSON) of nodes (assets + transforms)
and named relationships. This headless Blender/Cycles script reads that graph and builds the scene —
procedural terrain + instanced scatter + raycast-grounded hero assets + outdoor sky light — then renders.
Because the scene is a graph, an EDIT ("put the sword in a stone") is a one-node change with the same
terrain/scatter SEED → the forest is identical, only the hero changes. See
docs/research/scene-generation-research.md.

  blender -b -P track_b/scene_compose.py -- <scene_graph.json> <out_dir> [samples] [res]

Assets: a node/scatter `asset` is either a path to a .glb, or a proxy keyword: "proxy_tree" |
"proxy_rock" | "proxy_sword" (low-poly stand-ins, so the compose/ground/edit loop can be proven before
spending minutes generating real TRELLIS assets). Output: <out_dir>/<json-stem>.png.
"""
import json
import math
import os
import random
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
GRAPH = argv[0]
OUT = argv[1].rstrip("/")
SAMPLES = int(argv[2]) if len(argv) > 2 else 160
RES = int(argv[3]) if len(argv) > 3 else 1280
cfg = json.load(open(GRAPH))
random.seed(int(cfg.get("seed", 0)))            # deterministic forest → "same forest" across edits


# ── helpers ──────────────────────────────────────────────────────────────────
def _bbox(obj):
    mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
    for c in obj.bound_box:
        w = obj.matrix_world @ Vector(c)
        mn = Vector((min(mn[i], w[i]) for i in range(3)))
        mx = Vector((max(mx[i], w[i]) for i in range(3)))
    return mn, mx


def _normalize(obj, target_h, *, base_to_zero=True):
    """Scale longest of (x,y,z) so HEIGHT≈target_h, recenter XY, drop base to z=0. TRELLIS assets come out
    unit-cube + random pose, so callers also pass yaw/tilt to stand them up."""
    mn, mx = _bbox(obj)
    h = max(mx.z - mn.z, 1e-4)
    s = target_h / h
    obj.scale = (obj.scale.x * s, obj.scale.y * s, obj.scale.z * s)
    bpy.context.view_layer.update()
    mn, mx = _bbox(obj)
    c = (mn + mx) / 2
    obj.location.x -= c.x; obj.location.y -= c.y
    if base_to_zero:
        obj.location.z -= mn.z
    bpy.context.view_layer.update()
    return obj


def _import_glb(path, name):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.context.scene.objects if o not in before and o.type == "MESH"]
    if not new:
        raise RuntimeError(f"no mesh in {path}")
    if len(new) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for o in new:
            o.select_set(True)
        bpy.context.view_layer.objects.active = new[0]
        bpy.ops.object.join()
    obj = new[0]; obj.name = name
    obj.rotation_mode = "XYZ"
    return obj


def _mat(name, color, rough=0.7, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    return m


def _proxy(kind, name):
    """Low-poly stand-ins to prove the loop before real assets exist."""
    if kind == "proxy_tree":
        bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=1.2, location=(0, 0, 0.6))
        trunk = bpy.context.active_object; trunk.data.materials.append(_mat("bark", (0.18, 0.10, 0.05), 0.9))
        bpy.ops.mesh.primitive_cone_add(radius1=0.9, depth=2.6, location=(0, 0, 2.3))
        crown = bpy.context.active_object; crown.data.materials.append(_mat("leaf", (0.06, 0.20, 0.05), 0.85))
        bpy.ops.object.select_all(action="DESELECT")
        trunk.select_set(True); crown.select_set(True); bpy.context.view_layer.objects.active = trunk
        bpy.ops.object.join(); trunk.name = name; return trunk
    if kind == "proxy_rock":
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0)
        r = bpy.context.active_object
        for v in r.data.vertices:
            v.co += Vector((random.uniform(-.15, .15), random.uniform(-.15, .15), random.uniform(-.12, .12)))
        r.scale = (1.0, 0.85, 0.6); r.data.materials.append(_mat("stone", (0.20, 0.19, 0.18), 0.8)); r.name = name
        return r
    if kind == "proxy_sword":
        bpy.ops.mesh.primitive_cube_add(size=1)
        blade = bpy.context.active_object; blade.scale = (0.04, 0.012, 0.62); blade.location = (0, 0, 0.62)
        blade.data.materials.append(_mat("steel", (0.62, 0.64, 0.67), 0.25, 1.0))
        bpy.ops.mesh.primitive_cube_add(size=1)
        guard = bpy.context.active_object; guard.scale = (0.18, 0.03, 0.03); guard.location = (0, 0, 0.02)
        guard.data.materials.append(_mat("brass", (0.45, 0.35, 0.12), 0.4, 1.0))
        bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.22, location=(0, 0, -0.13))
        grip = bpy.context.active_object; grip.data.materials.append(_mat("grip", (0.10, 0.06, 0.04), 0.8))
        bpy.ops.object.select_all(action="DESELECT")
        for o in (blade, guard, grip):
            o.select_set(True)
        bpy.context.view_layer.objects.active = blade; bpy.ops.object.join()
        blade.name = name; return blade
    raise ValueError(f"unknown proxy {kind}")


def make_asset(spec_asset, name):
    return _proxy(spec_asset, name) if str(spec_asset).startswith("proxy_") else _import_glb(spec_asset, name)


def ground_z(x, y, terrain):
    """Height of the TERRAIN surface at (x,y) — raycast the terrain mesh ONLY (object-local), so a hero
    being placed never raycasts onto itself or other assets (the bug that floated the sword)."""
    dg = bpy.context.evaluated_depsgraph_get()
    te = terrain.evaluated_get(dg)
    mwi = terrain.matrix_world.inverted()
    o = mwi @ Vector((x, y, 100.0))
    d = (mwi.to_3x3() @ Vector((0, 0, -1))).normalized()
    hit, loc, *_ = te.ray_cast(o, d)
    return (terrain.matrix_world @ loc).z if hit else 0.0


# ── scene build ──────────────────────────────────────────────────────────────
def build_terrain(t):
    n = int(t.get("subdiv", 160)); size = float(t.get("size", 24))
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=n, y_subdivisions=n, size=size)
    g = bpy.context.active_object; g.name = "terrain"
    tex = bpy.data.textures.new("terrain_noise", "CLOUDS"); tex.noise_scale = float(t.get("noise_scale", 4.0))
    m = g.modifiers.new("disp", "DISPLACE"); m.texture = tex; m.strength = float(t.get("disp", 0.6))
    bpy.ops.object.modifier_apply(modifier=m.name)            # bake so raycast hits the bumps
    g.data.materials.append(_mat("ground", t.get("color", [0.05, 0.11, 0.04]), 0.95))
    return g


def scatter(specs, terrain, cam_xy=None, cam_keepout=0.0):
    for sp in specs:
        tmpl = make_asset(sp["asset"], "scatter_tmpl")
        _normalize(tmpl, float(sp.get("target_height", 4.0)))
        tmpl.hide_render = True                                # template hidden; we render linked copies
        area = float(sp.get("area", 22)) / 2; clear = float(sp.get("clearing_radius", 4.0))
        smin, smax = sp.get("scale_jitter", [0.7, 1.4])
        placed = 0
        for _ in range(int(sp.get("count", 50)) * 6):
            if placed >= int(sp.get("count", 50)):
                break
            x, y = random.uniform(-area, area), random.uniform(-area, area)
            if math.hypot(x, y) < clear:                       # keep the hero clearing open
                continue
            if cam_xy and math.hypot(x - cam_xy[0], y - cam_xy[1]) < cam_keepout:  # don't block the lens
                continue
            inst = tmpl.copy()                                 # linked copy (shares mesh data → cheap)
            bpy.context.collection.objects.link(inst); inst.hide_render = False
            sj = random.uniform(smin, smax)
            inst.scale = tuple(c * sj for c in tmpl.scale)
            inst.location = (x, y, ground_z(x, y, terrain) - 0.05)
            inst.rotation_euler = (0, 0, random.uniform(0, 6.283))
            placed += 1


def place_nodes(nodes, terrain):
    placed = {}
    for nd in nodes:                                           # order matters: a target must exist first
        obj = make_asset(nd["asset"], nd["id"])
        _normalize(obj, float(nd.get("target_height", 1.6)))
        obj.rotation_euler = (math.radians(nd.get("tilt", 0)), 0, math.radians(nd.get("yaw", 0)))
        bpy.context.view_layer.update()
        at = nd.get("at", [0, 0])
        place = nd.get("place", "grounded")
        if isinstance(place, dict) and "embedded_in" in place:  # the EDIT: sink into another node
            host = placed[place["embedded_in"]]
            hmn, hmx = _bbox(host)
            mn, mx = _bbox(obj)
            obj.location.x += host.location.x - (mn.x + mx.x) / 2
            obj.location.y += host.location.y - (mn.y + mx.y) / 2
            obj.location.z += hmx.z - mn.z - float(place.get("by", 0.4)) * (mx.z - mn.z)  # blade buried in the rock
        else:                                                   # grounded: center XY on `at`, drop to terrain
            mn, mx = _bbox(obj)
            obj.location.x += at[0] - (mn.x + mx.x) / 2
            obj.location.y += at[1] - (mn.y + mx.y) / 2
            mn, _ = _bbox(obj)
            obj.location.z += ground_z(at[0], at[1], terrain) - mn.z - float(nd.get("sink", 0.0))
        bpy.context.view_layer.update()
        placed[nd["id"]] = obj
        mn, mx = _bbox(obj)
        print(f"NODE {nd['id']} loc=({obj.location.x:.2f},{obj.location.y:.2f},{obj.location.z:.2f}) "
              f"bbox z[{mn.z:.2f},{mx.z:.2f}] xy[{mn.x:.2f},{mx.x:.2f}]x[{mn.y:.2f},{mx.y:.2f}]", flush=True)
    return placed


def setup_sky(l):
    world = bpy.data.worlds.new("sky"); bpy.context.scene.world = world; world.use_nodes = True
    nt = world.node_tree; bg = nt.nodes["Background"]
    sky = nt.nodes.new("ShaderNodeTexSky"); sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(float(l.get("sun_elev", 28)))
    sky.sun_rotation = math.radians(float(l.get("sun_azim", 50)))
    sky.air_density = float(l.get("haze", 1.6)); sky.dust_density = float(l.get("dust", 2.0))
    nt.links.new(sky.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = float(l.get("sky_strength", 1.0))
    sd = bpy.data.lights.new("sun", "SUN"); sd.energy = float(l.get("sun_energy", 3.5)); sd.angle = math.radians(2.0)
    sun = bpy.data.objects.new("sun", sd); bpy.context.collection.objects.link(sun)
    el = math.radians(float(l.get("sun_elev", 28))); az = math.radians(float(l.get("sun_azim", 50)))
    sun.rotation_euler = (math.radians(90) - el, 0, az)   # tilt down from zenith by elevation, rotate by azimuth


def setup_camera(c):
    cam_d = bpy.data.cameras.new("cam"); cam_d.lens = float(c.get("lens", 50))
    cam = bpy.data.objects.new("cam", cam_d); bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam; cam.location = c.get("loc", [9, -9, 4.5])
    tgt = bpy.data.objects.new("camtgt", None); bpy.context.collection.objects.link(tgt)
    tgt.location = c.get("target", [0, 0, 1.0])
    con = cam.constraints.new("TRACK_TO"); con.target = tgt; con.track_axis = "TRACK_NEGATIVE_Z"; con.up_axis = "UP_Y"


def setup_cycles():
    sc = bpy.context.scene; sc.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"; prefs.refresh_devices()
        for d in prefs.devices:
            d.use = (d.type == "OPTIX")
        sc.cycles.device = "GPU"
    except Exception as e:  # noqa: BLE001
        print("GPU setup failed, CPU:", e); sc.cycles.device = "CPU"
    sc.cycles.samples = SAMPLES; sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    sc.render.resolution_x = sc.render.resolution_y = RES
    sc.render.image_settings.file_format = "PNG"


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    terrain = build_terrain(cfg.get("terrain", {}))
    cam = cfg.get("camera", {})
    scatter(cfg.get("scatter", []), terrain, cam_xy=cam.get("loc", [9, -9, 4])[:2],
            cam_keepout=float(cam.get("keepout", 6.0)))
    place_nodes(cfg.get("nodes", []), terrain)
    setup_sky(cfg.get("lighting", {}))
    setup_camera(cfg.get("camera", {}))
    setup_cycles()
    os.makedirs(OUT, exist_ok=True)
    stem = os.path.splitext(os.path.basename(GRAPH))[0]
    bpy.context.scene.render.filepath = f"{OUT}/{stem}.png"
    bpy.ops.render.render(write_still=True)
    print("SCENE_OK", f"{OUT}/{stem}.png")


main()
