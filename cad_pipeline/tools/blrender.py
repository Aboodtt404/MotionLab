"""Blender headless GLB render smoke (Fable §6.5: "render the GLB ... assert non-empty framebuffers"
— the Blender-re-import path the manual explicitly allows instead of three.js+puppeteer).

Run:  blender --background --python blrender.py -- <in.glb> <out_basename>
Uses BLENDER_WORKBENCH (no lights, no denoiser → reliable headless; CYCLES needs OpenImageDenoiser
which the system build lacks). Writes <out_basename>.png.
"""
import sys

import bpy
import mathutils

glb, out = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)

bpy.ops.object.camera_add(location=(0.4, -0.4, 0.3))
cam = bpy.context.object
scn = bpy.context.scene
scn.camera = cam
cam.rotation_euler = (mathutils.Vector((0, 0, 0.0)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scn.render.engine = "BLENDER_WORKBENCH"
scn.render.resolution_x = scn.render.resolution_y = 128
scn.render.filepath = out
bpy.ops.render.render(write_still=True)
