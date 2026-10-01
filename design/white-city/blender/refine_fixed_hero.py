"""10 fixed studio lighting study. Keep the 09 camera and geometry unchanged.

Blender -b --python refine_fixed_hero.py -- [--draft] [--no-render]
Only material/light settings change. The original scene and render remain available.
"""
import bpy, hashlib, json, sys
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
source = ROOT / 'city-09-fixed.blend'
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene
camera_before = [list(row) for row in scene.camera.matrix_world]

def geometry_fingerprint():
    digest = hashlib.sha256()
    for ob in sorted(scene.objects, key=lambda ob: ob.name):
        if ob.type != 'MESH':
            continue
        digest.update(ob.name.encode())
        digest.update(str([tuple(v.co) for v in ob.data.vertices]).encode())
        digest.update(str([tuple(p.vertices) for p in ob.data.polygons]).encode())
        digest.update(str([list(row) for row in ob.matrix_world]).encode())
    return digest.hexdigest()

geometry_before = geometry_fingerprint()

# White remains a family of materials: satin walls, chalk roofs, fine metal and glass.
settings = {
    '09 Ivory mineral white': ((.91, .888, .838), .30),
    '09 Roof warm chalk': ((.95, .936, .904), .44),
    '09 White studio terrain': ((.945, .930, .895), .53),
    '09 Low iron thin glass': ((.89, .91, .887), .12),
    '09 Light recess satin': ((.79, .806, .776), .29),
    '09 Fine ivory frames': ((.92, .910, .877), .24),
    '09 Fine chalk foliage': ((.92, .911, .880), .60),
    '09 Small warm white branches': ((.77, .761, .728), .65),
    '09 Pearlescent reflective water': ((.74, .795, .766), .095),
}
for name, (color, roughness) in settings.items():
    mat = bpy.data.materials[name]
    mat.diffuse_color = (*color, 1)
    p = mat.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = roughness
    if name in ('09 Ivory mineral white', '09 Fine ivory frames'):
        p.inputs['Coat Weight'].default_value = .08
        p.inputs['Coat Roughness'].default_value = .28

# Concealed sources illuminate interior receivers; they never become visible quads.
plan = json.loads((ROOT / 'city-09-fixed-plan.json').read_text(encoding='utf-8'))
for ob in scene.objects:
    if not ob.get('emitter'):
        continue
    mat = ob.data.materials[0].copy()
    mat.name = ob.name + ' ivory interior light'
    ob.data.materials[0] = mat
    p = mat.node_tree.nodes.get('Principled BSDF')
    p.inputs['Emission Color'].default_value = (1, .69, .35, 1)
    # Wide low pavilions need more indirect illumination than shallow tower lobbies.
    tag = ob.name.removesuffix(' concealed warm source')
    building = next((b for b in plan['buildings'] if b['id'] == tag), {})
    p.inputs['Emission Strength'].default_value = 22 if building.get('kind') == 'pavilion' else 16
    ob.visible_camera = ob.visible_glossy = ob.visible_transmission = False

def area(name, location, target, power, size, color):
    ob = bpy.data.objects[name]
    ob.location = location
    ob.rotation_euler = (Vector(target) - ob.location).to_track_quat('-Z', 'Y').to_euler()
    ob.data.energy = power
    ob.data.size = size
    ob.data.color = color

# A more lateral key gives legible side faces. A broad fill keeps recesses open.
# Exposure is held at 09's value, so an apparent improvement cannot be a global lift.
area('09 broad warm key', (-145, -95, 145), (0, 45, 0), 380000, 112, (1, .90, .74))
area('09 neutral rim', (100, 105, 160), (20, 15, 5), 300000, 88, (1, .985, .95))
area('09 frontal bounce', (-20, -150, 95), (20, 40, 5), 30000, 145, (1, .985, .955))
scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.96, .98, 1, 1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value = .16
scene.view_settings.exposure = 1.75
scene.view_settings.look = 'AgX - Medium High Contrast'
scene.cycles.samples = 48 if '--draft' in sys.argv else 256
scene.cycles.adaptive_threshold = .03 if '--draft' in sys.argv else .008
scene.cycles.diffuse_bounces = 6
scene.cycles.max_bounces = 12
scene.render.resolution_x = 1672 if '--draft' in sys.argv else 2560
scene.render.resolution_y = 941 if '--draft' in sys.argv else 1441
for node in scene.node_tree.nodes:
    if node.type == 'GLARE':
        node.threshold = 2.5
        node.mix = -.92

assert camera_before == [list(row) for row in scene.camera.matrix_world]
assert geometry_before == geometry_fingerprint()
assert not scene.camera.animation_data
assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
scene['stage'] = '10 fixed camera / unchanged layout / refined satin whites and concealed warm illumination'
scene.render.filepath = str(ROOT / 'renders/city-10-studio.png')
plan = json.loads((ROOT / 'city-09-fixed-plan.json').read_text(encoding='utf-8'))
plan['stage'] = '10'
plan['source'] = source.name
plan['camera_unchanged'] = True
plan['geometry_sha256'] = geometry_before
plan['geometry_unchanged'] = True
plan['source_sha256'] = source_hash
plan['lighting_exposure'] = scene.view_settings.exposure
plan['status'] = 'experimental; fixed-view material and lighting refinement, environment awaiting review'
(ROOT / 'city-10-studio-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / 'city-10-studio.blend'))
print('REFINED_FIXED_READY', flush=True)
if '--no-render' not in sys.argv:
    bpy.ops.render.render(write_still=True)
