"""Low-Poly / game-ready pass: decimate a GLB to a target face budget, preserving UVs + materials so the
PBR textures (esp. the normal map) keep the silhouette readable. Also serves the "Remesh / target-polycount"
gap. CPU-only (no GPU) — fast.

  blender -b -P decimate.py -- <in.glb> <out.glb> [target_faces=5000]
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
IN, OUT = argv[0], argv[1]
TARGET = int(argv[2]) if len(argv) > 2 else 5000

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.data]


def apply_mod(o, mod):
    # headless Blender 4.x: modifier_apply needs an explicit context override or it silently no-ops
    with bpy.context.temp_override(object=o, active_object=o,
                                   selected_objects=[o], selected_editable_objects=[o]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


# weld coincident verts first — TRELLIS meshes are split at every UV seam, and those boundary edges
# block COLLAPSE decimate (it floors well above target). Welding lets it reach the budget.
# then triangulate so the budget is counted in TRIANGLES and the target is hit accurately.
for o in meshes:
    w = o.modifiers.new("weld", "WELD")
    w.merge_threshold = 1e-4
    apply_mod(o, w)
    apply_mod(o, o.modifiers.new("tri", "TRIANGULATE"))

total = sum(len(o.data.polygons) for o in meshes)
ratio = min(1.0, TARGET / max(total, 1))            # one global ratio so the budget is shared across meshes

if ratio < 1.0:
    for o in meshes:
        m = o.modifiers.new("dec", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = ratio
        apply_mod(o, m)

out_faces = sum(len(o.data.polygons) for o in meshes)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_apply=True)
print(f"DECIMATE_OK in_faces={total} out_faces={out_faces} ratio={ratio:.4f}", flush=True)
