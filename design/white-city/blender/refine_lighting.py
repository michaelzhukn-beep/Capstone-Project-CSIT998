"""Build 05 lighting from the protected 04 scene; preserve all modeled geometry.

blender -b --python design/white-city/blender/refine_lighting.py [-- --draft]
Reference camera is shared with the actual WebGL viewer (city-view.json).
"""
import bpy
import hashlib
import json
import math
import sys
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
DRAFT = '--draft' in sys.argv
view = json.loads((ROOT.parent / 'city-view.json').read_text(encoding='utf-8'))
source = ROOT / 'city-04.blend'
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene

def geometry_fingerprint():
    digest = hashlib.sha256()
    for obj in sorted(scene.objects, key=lambda o: o.name):
        if obj.type not in {'MESH', 'EMPTY'}:
            continue
        digest.update(str((obj.name, [list(row) for row in obj.matrix_world],
                           obj.instance_collection.name if obj.instance_collection else None)).encode())
        if obj.type == 'MESH':
            digest.update(str([(tuple(v.co)) for v in obj.data.vertices]).encode())
    return digest.hexdigest()

geometry_before = geometry_fingerprint()
camera = scene.camera
camera.animation_data_clear()
def from_three(values):
    x, y, z = values
    return Vector((x, -z, y))

camera.location = from_three(view['position'])
target = from_three(view['target'])
camera.rotation_euler = (target-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.shift_x = camera.data.shift_y = 0
camera.data.sensor_fit = 'VERTICAL'
camera.data.sensor_height = 24
camera.data.lens = 24 / (2*math.tan(math.radians(view['verticalFov']/2)))
camera['reference_preset'] = view['id']
camera['purpose'] = 'Oblique reference view; shared with v12 WebGL. No animated camera drift.'
scene.render.resolution_x = 1400 if DRAFT else 2560
scene.render.resolution_y = round(scene.render.resolution_x / view['referenceAspect'])
scene.render.resolution_percentage = 100
scene.cycles.samples = 32 if DRAFT else 128
scene.cycles.use_denoising = True

prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'
prefs.get_devices()
for device in prefs.devices:
    device.use = device.type == 'OPTIX'
scene.cycles.device = 'GPU'

def render(name, detail=False):
    old_camera, width, height = scene.camera, scene.render.resolution_x, scene.render.resolution_y
    if detail:
        scene.camera = bpy.data.objects['Waterfront detail camera']
        scene.render.resolution_x = 1400 if DRAFT else 1600
        scene.render.resolution_y = 875 if DRAFT else 1000
    scene.render.filepath = str(ROOT / 'renders' / (name + ('-draft' if DRAFT else '') + '.png'))
    bpy.ops.render.render(write_still=True)
    scene.camera, scene.render.resolution_x, scene.render.resolution_y = old_camera, width, height
    print('LIGHTING_RENDER_COMPLETE', name, flush=True)

# Render the old light rig at the newly specified camera, for a meaningful comparison.
render('reference-lighting-04')
render('waterfront-lighting-04', detail=True)

key = bpy.data.lights['Large soft daylight key']
key.energy = 440000
key.size = 105
key.color = (1, .98, .945)
fill = bpy.data.lights['Cool broad fill']
fill.energy = 38000
fill.size = 145
bpy.data.lights['Soft daylight direction'].energy = .28
bpy.data.lights['Soft daylight direction'].angle = math.radians(18)
for light in bpy.data.lights:
    if 'recessed interior' in light.name:
        light.energy *= 1.28
        light.color = (1, .83, .61)
for node in scene.world.node_tree.nodes:
    if node.type == 'BACKGROUND' and node.inputs['Strength'].default_value < 1:
        node.inputs['Strength'].default_value = .30
warm = bpy.data.materials['Recessed warm ceiling - real emission'].node_tree.nodes.get('Principled BSDF')
warm.inputs['Emission Color'].default_value = (1, .83, .61, 1)
warm.inputs['Emission Strength'].default_value = 3.1
scene.view_settings.exposure = 1.0
scene['stage'] = '05 lighting study; actual scene, same 04 geometry; visual acceptance pending'
scene['lighting_note'] = 'Broad key, restrained sun, cool fill and recessed warm interiors. WebGL approximates this; GI is not baked.'
assert geometry_fingerprint() == geometry_before, 'Lighting refinement changed geometry'
assert not any(n.type == 'TEX_IMAGE' for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes)
scene.render.filepath = str(ROOT/'renders'/'reference-lighting-05.png')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-05.blend'))
render('reference-lighting-05')
render('waterfront-lighting-05', detail=True)
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
report = {
    'stage': 'experimental lighting refinement, visual acceptance pending',
    'source': 'city-04.blend', 'source_sha256': source_hash,
    'geometry_unchanged': True, 'geometry_sha256': geometry_before,
    'reference_camera': view, 'blender_camera': {'position': list(camera.location), 'lens': camera.data.lens,
    'sensor_fit': camera.data.sensor_fit, 'shift_x': camera.data.shift_x, 'shift_y': camera.data.shift_y},
    'image_texture_nodes': 0, 'samples': scene.cycles.samples,
    'resolution': [scene.render.resolution_x,scene.render.resolution_y],
    'rendered': ['reference-lighting-04','reference-lighting-05','waterfront-lighting-04','waterfront-lighting-05'],
    'lights': [{ 'name': l.name,'type': l.type,'power': l.energy,'color': list(l.color),
                 'size': l.size if l.type == 'AREA' else None} for l in bpy.data.lights],
    'limits': 'Cycles comparison is offline. WebGL uses filtered shadows, screen-space AO and local area fill; no baked GI.'
}
(ROOT/'lighting-verification-city-05.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('LIGHTING_VERIFIED', json.dumps({'geometry_unchanged':True,'samples':scene.cycles.samples}),flush=True)
