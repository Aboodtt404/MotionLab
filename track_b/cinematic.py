"""Cinematic render pass (Phase 1 of the finishing tail) — a headless Blender/Cycles bpy script that
turns a generated GLB into a PHOTOREAL beauty still + turntable, the deterministic photoreal layer our
real-time viewport (a rasterizer) can't give. NOT imported by any venv — Blender runs it directly:

  blender -b -P track_b/cinematic.py -- <in.glb> <out_dir> [samples] [res] [turn_frames]

Output: <out_dir>/beauty.png (hero still) + <out_dir>/turntable.mp4 (if turn_frames>0).
Renders on the Blackwell GPU via OptiX (bundled kernels — no sm_120 build), spilling to RAM if VRAM is
tight. Studio setup: neutral world + 3-point area lights + a soft floor + AgX view transform (cinematic).
"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
GLB = argv[0]
OUT = argv[1].rstrip("/")
SAMPLES = int(argv[2]) if len(argv) > 2 else 128
RES = int(argv[3]) if len(argv) > 3 else 1280
TURN = int(argv[4]) if len(argv) > 4 else 36   # turntable frames; 0 = skip


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh in GLB")
    # combined world-space bbox
    mn = Vector((1e9, 1e9, 1e9)); mx = Vector((-1e9, -1e9, -1e9))
    for o in meshes:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            mn = Vector((min(mn[i], w[i]) for i in range(3)))
            mx = Vector((max(mx[i], w[i]) for i in range(3)))
    center = (mn + mx) / 2
    size = max((mx - mn))
    return meshes, center, size, mn, mx


def setup_studio(center, size, mn):
    sc = 2.0 / max(size, 1e-3)                      # normalize to ~2 world units
    pivot = bpy.data.objects.new("pivot", None)     # empty at the object's base-center; parent meshes to it
    bpy.context.collection.objects.link(pivot)
    pivot.location = (0, 0, 0)
    for o in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        o.scale = (sc, sc, sc)
        o.location = (o.location - center) * sc      # recenter
        o.location.z += (center.z - mn.z) * sc       # sit base on z=0
        o.parent = pivot                             # so the turntable spins everything together
    # neutral studio world
    world = bpy.data.worlds.new("studio"); bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.05, 0.05, 0.06, 1.0); bg.inputs[1].default_value = 0.4
    # soft floor (slightly glossy → studio sheen + contact shadow)
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
    floor = bpy.context.active_object
    m = bpy.data.materials.new("floor"); m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.12, 0.12, 0.14, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.55
    floor.data.materials.append(m)
    # 3-point area lights (key / fill / rim), scaled to the subject
    def area(name, loc, energy, sz):
        d = bpy.data.lights.new(name, "AREA"); d.energy = energy; d.size = sz
        ob = bpy.data.objects.new(name, d); ob.location = loc
        bpy.context.collection.objects.link(ob)
        # aim at origin
        dirv = Vector((0, 0, 0.8)) - Vector(loc)
        ob.rotation_euler = dirv.to_track_quat("-Z", "Y").to_euler()
        return ob
    area("key", (3.2, -3.0, 3.4), 1400, 5)
    area("fill", (-3.4, -1.6, 1.8), 400, 6)
    area("rim", (0.5, 3.6, 2.6), 900, 4)
    return pivot


def setup_camera():
    cam_d = bpy.data.cameras.new("cam"); cam_d.lens = 80
    cam = bpy.data.objects.new("cam", cam_d); bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.location = (4.0, -4.6, 2.9)
    target = bpy.data.objects.new("target", None); bpy.context.collection.objects.link(target)
    target.location = (0, 0, 0.8)
    c = cam.constraints.new("TRACK_TO"); c.target = target; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
    return cam


def setup_cycles():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "OPTIX"; prefs.refresh_devices()
        for d in prefs.devices:
            d.use = (d.type == "OPTIX")
        sc.cycles.device = "GPU"
    except Exception as e:  # noqa: BLE001 — fall back to CPU if GPU setup fails
        print("GPU setup failed, CPU:", e); sc.cycles.device = "CPU"
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"          # cinematic tone-mapping (Blender 4.x default)
    sc.render.resolution_x = sc.render.resolution_y = RES
    sc.render.image_settings.file_format = "PNG"


def main():
    reset()
    _, center, size, mn, mx = import_glb(GLB)
    pivot = setup_studio(center, size, mn)
    setup_camera()
    setup_cycles()
    sc = bpy.context.scene
    # hero beauty still
    sc.render.filepath = f"{OUT}/beauty.png"
    bpy.ops.render.render(write_still=True)
    # turntable mp4 (spin the pivot 360°)
    if TURN > 0:
        sc.frame_start = 1; sc.frame_end = TURN
        pivot.rotation_euler = (0, 0, 0); pivot.keyframe_insert("rotation_euler", frame=1)
        pivot.rotation_euler = (0, 0, math.radians(360)); pivot.keyframe_insert("rotation_euler", frame=TURN + 1)
        for fc in pivot.animation_data.action.fcurves:           # constant-speed spin
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
        sc.cycles.samples = max(32, SAMPLES // 2)                # lighter per turntable frame
        sc.render.resolution_x = sc.render.resolution_y = min(RES, 960)
        sc.render.image_settings.file_format = "FFMPEG"
        sc.render.ffmpeg.format = "MPEG4"; sc.render.ffmpeg.codec = "H264"
        sc.render.ffmpeg.constant_rate_factor = "HIGH"
        sc.render.fps = 24
        sc.render.filepath = f"{OUT}/turntable.mp4"
        bpy.ops.render.render(animation=True)
    print("RENDER_OK")


main()
