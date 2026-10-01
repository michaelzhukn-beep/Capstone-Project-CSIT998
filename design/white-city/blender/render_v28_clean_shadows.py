"""Render unoccluded house floor shadows, leaving visibility to WebGL depth testing.

blender -b --python design/white-city/blender/render_v28_clean_shadows.py
Reads the existing scene; does not save it or replace the original shadow renders.
Holdout masks include grass hairs absent from the exported lawn planes. Projecting
those punched-out masks onto the floor leaves noisy white outlines behind trees.
Camera-invisible shadow casters produce a continuous shadow receiver instead.
"""
import json
from pathlib import Path
import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'bake-v28'
bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-28-baked.blend'))
sc = bpy.context.scene
cw = json.loads((OUT / 'web' / 'cam-wide.json').read_text(encoding='utf-8'))
cam = sc.camera
cam.matrix_world = Matrix(cw['matrix_world'])
cam.data.type = 'ORTHO'
cam.data.sensor_fit = 'HORIZONTAL'
cam.data.ortho_scale = cw['ortho_scale']
cam.data.shift_x, cam.data.shift_y = cw['shift_x'], cw['shift_y']
sc.render.resolution_x, sc.render.resolution_y = cw['resolution']
sc.render.resolution_percentage = 100
sc.render.use_border = False
sc.render.engine = 'CYCLES'
sc.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'
prefs.get_devices()
for device in prefs.devices:
    device.use = device.type == 'OPTIX'
sc.cycles.samples = 96
sc.cycles.use_denoising = True
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
sc.render.image_settings.color_depth = '8'
floor = sc.objects['v27 floor']
casters = []
for obj in sc.objects:
    if obj.type != 'MESH' or obj is floor:
        continue
    obj.hide_render = not obj.name.startswith('v28')
    obj.is_holdout = False
    if not obj.hide_render:
        obj.visible_camera = False
        casters.append(obj.name)
floor.hide_render = False
floor.visible_camera = True
floor.is_holdout = False
floor.is_shadow_catcher = True
print('CLEAN_SHADOW_CASTERS', len(casters), flush=True)
sc.render.filepath = str(OUT / 'layer-shadow-house-clean.png')
bpy.ops.render.render(write_still=True)
print('CLEAN_SHADOW_DONE', sc.render.filepath, flush=True)
