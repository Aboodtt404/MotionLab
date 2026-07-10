"""Blender bpy procedural generators (fable_run §1.2 procedural row + benchmark B-category).
Dispatch by `kind`; build geometry headlessly; export a GLB the engine/benchmark verifies.

Run:  blender --background --python bpy_generate.py -- <kind> <params_json> <out.glb>
Kinds: staircase (B01), array (B02), window (B05 boolean cut), scatter (B06 seeded instances).
"""
import json
import sys

import bpy


def _reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def staircase(p):
    n = int(p.get("steps", 5)); rise = p.get("rise", 0.15); tread = p.get("tread", 0.30); w = p.get("width", 1.0)
    for i in range(n):
        bpy.ops.mesh.primitive_cube_add(size=1)
        o = bpy.context.object
        o.scale = (w, tread, rise)
        o.location = (0.0, i * tread + tread / 2, i * rise + rise / 2)   # bbox: y=n·tread, z=n·rise


def array(p):
    n = int(p.get("count", 10)); sp = p.get("spacing", 2.0); r = p.get("radius", 0.15); h = p.get("height", 3.0)
    for i in range(n):
        bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, location=(i * sp, 0, h / 2))   # x-extent=(n-1)·sp+2r


def window(p):
    W, T, H = p.get("wall", [4.0, 0.2, 3.0]); ww, wh = p.get("window", [1.0, 1.2])
    bpy.ops.mesh.primitive_cube_add(size=1); wall = bpy.context.object
    wall.scale = (W, T, H); wall.location = (0, 0, H / 2)
    bpy.ops.mesh.primitive_cube_add(size=1); win = bpy.context.object
    win.scale = (ww, T * 2, wh); win.location = (0, 0, H / 2)
    m = wall.modifiers.new("cut", "BOOLEAN"); m.operation = "DIFFERENCE"; m.object = win
    bpy.context.view_layer.objects.active = wall
    bpy.ops.object.modifier_apply(modifier="cut")
    bpy.data.objects.remove(win, do_unlink=True)


def scatter(p):
    import random
    n = int(p.get("count", 200)); seed = int(p.get("seed", 42)); size = p.get("plane", 10.0)
    random.seed(seed)                                       # R1: seeded → reproducible
    for _ in range(n):
        x = (random.random() - 0.5) * size; y = (random.random() - 0.5) * size
        bpy.ops.mesh.primitive_cube_add(size=0.2, location=(x, y, 0.1))


KINDS = {"staircase": staircase, "array": array, "window": window, "scatter": scatter}


def main():
    kind, params_json, out = sys.argv[-3], sys.argv[-2], sys.argv[-1]
    _reset()
    KINDS[kind](json.loads(params_json))
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")


if __name__ == "__main__":
    main()
