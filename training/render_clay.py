"""Blender headless clay render of a GLB — one 3/4 view, neutral material, to eyeball geometry.
Usage: blender -b -P render_clay.py -- --glb in.glb --out out.png"""
import bpy, sys, math, os
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
glb = argv[argv.index("--glb") + 1]
out = argv[argv.index("--out") + 1]

# clean scene
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    print("no mesh"); sys.exit(0)

# clay material on everything (isolate geometry from texture)
clay = bpy.data.materials.new("clay"); clay.use_nodes = True
bsdf = clay.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.62, 0.63, 0.66, 1.0)
bsdf.inputs["Roughness"].default_value = 0.55
if "Metallic" in bsdf.inputs: bsdf.inputs["Metallic"].default_value = 0.0
for m in meshes:
    m.data.materials.clear(); m.data.materials.append(clay)

# combined bbox center + size
mn = Vector((1e9, 1e9, 1e9)); mx = Vector((-1e9, -1e9, -1e9))
for m in meshes:
    for c in m.bound_box:
        w = m.matrix_world @ Vector(c)
        mn = Vector((min(mn[i], w[i]) for i in range(3)))
        mx = Vector((max(mx[i], w[i]) for i in range(3)))
center = (mn + mx) / 2
size = max((mx - mn)) or 1.0

# camera at a front-3/4 beauty angle
cam_data = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_data)
bpy.context.scene.collection.objects.link(cam)
az, el, dist = math.radians(35), math.radians(22), size * 2.1
cam.location = center + Vector((dist*math.cos(el)*math.sin(az),
                                -dist*math.cos(el)*math.cos(az),
                                dist*math.sin(el)))
# look at center
d = center - cam.location
cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

# lighting: key sun + soft world
sun_d = bpy.data.lights.new("sun", "SUN"); sun_d.energy = 4.0
sun = bpy.data.objects.new("sun", sun_d); bpy.context.scene.collection.objects.link(sun)
sun.rotation_euler = (math.radians(55), math.radians(15), math.radians(40))
world = bpy.data.worlds.new("w"); bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.06, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.6

sc = bpy.context.scene
sc.render.engine = "CYCLES"          # headless: no display needed (EEVEE needs OpenGL)
sc.cycles.samples = 48
sc.cycles.device = "CPU"
sc.render.resolution_x = sc.render.resolution_y = 768
sc.render.film_transparent = False
sc.render.filepath = out
os.makedirs(os.path.dirname(out), exist_ok=True)
bpy.ops.render.render(write_still=True)
print("rendered", out)
