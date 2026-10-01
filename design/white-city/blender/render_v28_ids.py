"""v28 宽幅机位的完整画面 + 「每个像素最前面是哪个对象」的 ID 图。只读打开 city-28-baked.blend,不保存。

    blender -b --python design/white-city/blender/render_v28_ids.py -- [--samples 256]

原因(所有者发现网页里多出细线):screen 贴图是「只让该对象可见」渲染的,被别的对象盖住的部分也画出来了
(例如水下的岸墙、路面下的地形)。网页里几乎共面的两个对象在深度上会互相穿插,被盖住那一层的颜色就露成细线。
post_v28_layers.py 用这两张图修正:某像素最前面是 screen 对象时,贴图该处一律用完整画面的颜色 ——
机位朝向固定,不管网页里哪一层赢,看到的都是正确颜色。
输出 bake-v28/layer-beauty.png、layer-ids.png、ids.json(颜色 → 对象名)。
"""
import bpy, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'bake-v28'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
samples = int(argv[argv.index('--samples') + 1]) if '--samples' in argv else 256

bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-28-baked.blend'))
# 宽幅机位以 web/cam-wide.json 为准(烘焙脚本不保存改过的相机到每一步之外时,这里重新套用)
_cw = json.loads((OUT / 'web' / 'cam-wide.json').read_text(encoding='utf-8'))
from mathutils import Matrix
_c = bpy.context.scene.camera; _c.matrix_world = Matrix(_cw['matrix_world']); _c.data.type = 'ORTHO'; _c.data.sensor_fit = 'HORIZONTAL'
_c.data.ortho_scale = _cw['ortho_scale']; _c.data.shift_x = _cw['shift_x']; _c.data.shift_y = _cw['shift_y']
bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = _cw['resolution']; bpy.context.scene.render.resolution_percentage = 100
sc = bpy.context.scene
floor = sc.objects.get('v27 floor')
if floor:
    floor.hide_render = True
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'
sc.render.use_border = False
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'; sc.render.image_settings.color_depth = '8'

# 1. 完整画面(与 screen 贴图同一套光照与显示变换)
if '--idsonly' not in argv:
    sc.cycles.samples = samples; sc.cycles.use_denoising = True
    sc.render.filepath = str(OUT / 'layer-beauty.png')
    bpy.ops.render.render(write_still=True)

# 2. ID 图:每个网格对象一种纯色自发光,不抗锯齿、不降噪、不做显示变换
ids = {}
mesh_objs = [o for o in sc.objects if o.type == 'MESH' and o is not floor]
for i, o in enumerate(mesh_objs, start=1):
    r, g = (i >> 8) & 255, i & 255
    ids[f'{r},{g}'] = o.name
    m = bpy.data.materials.new(f'v28 id {i}'); m.use_nodes = True
    nt = m.node_tree; nt.nodes.remove(nt.nodes['Principled BSDF'])
    lin = lambda c: c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4     # Standard 视图会做 sRGB 编码:先解码,输出才是精确整数
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = (lin(r / 255), lin(g / 255), 0, 1)
    nt.links.new(em.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    if o.particle_systems:                                   # 草丛发丝也记在草坪对象名下
        for ps in o.particle_systems:
            ps.settings.material_slot = o.material_slots[0].name if o.material_slots else ps.settings.material_slot
    o.data = o.data.copy() if o.data.users > 1 else o.data
    o.data.materials.clear(); o.data.materials.append(m)
    for s in o.material_slots:
        s.link = 'DATA'
sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'; sc.view_settings.exposure = 0
sc.cycles.samples = 1; sc.cycles.use_denoising = False; sc.render.dither_intensity = 0
sc.cycles.filter_width = .01; sc.cycles.max_bounces = 0
sc.render.filepath = str(OUT / 'layer-ids.png')
bpy.ops.render.render(write_still=True)
(OUT / 'ids.json').write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding='utf-8')
print('V28_IDS_DONE', len(ids), flush=True)
