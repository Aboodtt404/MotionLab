"""Blender texture bake (§4) — bake AO + tangent-normal maps for a GLB into a UV atlas.
Run:  blender --background --python bpy_bake.py -- <in.glb> <out_dir> <res>
Cycles bake (bake needs Cycles, not Workbench/EEVEE; no denoiser required for baking).
Writes <out_dir>/ao.png and <out_dir>/normal.png.
"""
import os
import sys

import bpy

glb, out_dir, res = sys.argv[-3], sys.argv[-2], int(sys.argv[-1])
os.makedirs(out_dir, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
obj = next((o for o in bpy.context.scene.objects if o.type == "MESH"), None)
if obj is None:
    sys.exit(0)
bpy.ops.object.select_all(action="DESELECT")        # bake iterates SELECTED objects — only the mesh
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

# ensure a UV map (smart project if none)
if not obj.data.uv_layers:
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")

# a material with an image-texture node = the bake target
mat = obj.data.materials[0] if obj.data.materials else bpy.data.materials.new("bake")
if not obj.data.materials:
    obj.data.materials.append(mat)
mat.use_nodes = True
nodes = mat.node_tree.nodes

scn = bpy.context.scene
scn.render.engine = "CYCLES"
scn.cycles.device = "CPU"
scn.cycles.samples = 16
scn.render.bake.use_selected_to_active = False


def _bake(bake_type: str, name: str, non_color: bool):
    img = bpy.data.images.new(name, res, res)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    nodes.active = tex
    tex.select = True
    try:
        bpy.ops.object.bake(type=bake_type)
        img.filepath_raw = os.path.join(out_dir, f"{name}.png")
        img.file_format = "PNG"
        img.save()
    except Exception as e:  # noqa: BLE001 — a bake that can't run is a skip, not a crash
        print(f"bake {bake_type} skipped: {e}")
    finally:
        nodes.remove(tex)


_bake("AO", "ao", non_color=True)
_bake("NORMAL", "normal", non_color=True)
