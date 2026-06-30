"""Infinigen terrain .blend → a real-time GLB ground tile for the assembler.

Isolates the OpaqueTerrain mesh, welds + triangulates + decimates it to a face budget, BAKES its procedural
Cycles material to vertex colors (so it keeps the Infinigen look in a browser with no UV unwrap), assigns a
GLB-friendly material that reads those vertex colors, and exports a GLB. The full procedural material is
still available in the source .blend for a photoreal Cycles render later.

  blender -b -P terrain_export.py -- <terrain.blend> <out.glb> [target_faces=40000]
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
BLEND, OUT = argv[0], argv[1]
TARGET = int(argv[2]) if len(argv) > 2 else 40000


def apply_mod(o, mod):
    with bpy.context.temp_override(object=o, active_object=o,
                                   selected_objects=[o], selected_editable_objects=[o]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


bpy.ops.wm.open_mainfile(filepath=BLEND)
sc = bpy.context.scene

# the main full-extent terrain (skip the 0-vert LODs + colliders)
cands = [o for o in sc.objects if o.type == "MESH" and "OpaqueTerrain" in o.name
         and o.data and len(o.data.vertices) > 0 and "collider" not in o.name]
terr = next((o for o in cands if o.name == "OpaqueTerrain"), None) \
    or (max(cands, key=lambda o: len(o.data.vertices)) if cands else None)
if terr is None:
    raise RuntimeError("no OpaqueTerrain in .blend")
print("terrain:", terr.name, "verts", len(terr.data.vertices), flush=True)

# isolate the terrain — drop every other mesh so the tile is just the ground
for o in list(sc.objects):
    if o is not terr and o.type == "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
terr.hide_render = terr.hide_viewport = False
try:
    terr.hide_set(False)
except Exception:  # noqa: BLE001
    pass

# weld (Infinigen terrain can be split) + triangulate + decimate to the budget
w = terr.modifiers.new("weld", "WELD"); w.merge_threshold = 1e-4; apply_mod(terr, w)
apply_mod(terr, terr.modifiers.new("tri", "TRIANGULATE"))
total = len(terr.data.polygons)
ratio = min(1.0, TARGET / max(total, 1))
if ratio < 1.0:
    m = terr.modifiers.new("dec", "DECIMATE"); m.decimate_type = "COLLAPSE"; m.ratio = ratio
    apply_mod(terr, m)
print("decimated:", len(terr.data.polygons), "faces", flush=True)

# bake the procedural material's albedo → vertex colors (color only, no lighting)
ca = terr.data.color_attributes.new(name="Col", type="BYTE_COLOR", domain="CORNER")
terr.data.color_attributes.active_color = ca
sc.render.engine = "CYCLES"
sc.cycles.samples = 4
sc.render.bake.target = "VERTEX_COLORS"
sc.render.bake.use_pass_direct = sc.render.bake.use_pass_indirect = False
sc.render.bake.use_pass_color = True
with bpy.context.temp_override(object=terr, active_object=terr, selected_objects=[terr]):
    bpy.ops.object.bake(type="DIFFUSE")
print("baked albedo → vertex colors", flush=True)

# GLB-friendly material that reads the baked vertex colors as base color
mat = bpy.data.materials.new("terrain_baked"); mat.use_nodes = True
nt = mat.node_tree; bsdf = nt.nodes.get("Principled BSDF")
vc = nt.nodes.new("ShaderNodeVertexColor"); vc.layer_name = "Col"
nt.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.95
terr.data.materials.clear(); terr.data.materials.append(mat)

bpy.ops.object.select_all(action="DESELECT"); terr.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=True, export_apply=True)
print(f"TERRAIN_TILE_OK faces={len(terr.data.polygons)} verts={len(terr.data.vertices)}", flush=True)
