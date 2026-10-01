"""v28 桌面影子层拆分:城市沙盘 / 户型样板各一张。只读打开 city-28-baked.blend,不保存。

    blender -b --python design/white-city/blender/render_v28_shadows.py -- [--samples 96]

原因:网页的城市视角会把户型样板整组隐藏(两组模型相距只有十几米,不隐藏就会在首屏露出一角),
但影子层原本是一整张,隐藏模型后它们投在桌面上的影子还在。拆成两张,各自跟着淡入。
同时输出两组的轮廓层(alpha),供 post_v28_layers.py 分别生成接触阴影。
输出 bake-v28/:layer-shadow-city.png、layer-shadow-house.png、layer-alpha-city.png、layer-alpha-house.png。
"""
import bpy, json, sys
from pathlib import Path
from mathutils import Matrix

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'bake-v28'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
samples = int(argv[argv.index('--samples') + 1]) if '--samples' in argv else 96

bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-28-baked.blend'))
sc = bpy.context.scene
cw = json.loads((OUT / 'web' / 'cam-wide.json').read_text(encoding='utf-8'))
cam = sc.camera
cam.matrix_world = Matrix(cw['matrix_world'])
cd = cam.data; cd.type = 'ORTHO'; cd.sensor_fit = 'HORIZONTAL'
cd.ortho_scale = cw['ortho_scale']; cd.shift_x = cw['shift_x']; cd.shift_y = cw['shift_y']
sc.render.resolution_x, sc.render.resolution_y = cw['resolution']; sc.render.resolution_percentage = 100

prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'
sc.render.use_border = False
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'; sc.render.image_settings.color_depth = '8'

floor = sc.objects['v27 floor']
is_house = lambda o: o.name.startswith('v28')
meshes = [o for o in sc.objects if o.type == 'MESH' and o is not floor]
groups = {'city': [o for o in meshes if not is_house(o)], 'house': [o for o in meshes if is_house(o)]}
print('V28_SHADOW_GROUPS', {k: len(v) for k, v in groups.items()}, flush=True)

for name, objs in groups.items():
    others = [o for o in meshes if o not in objs]
    # 影子层:本组照常投影,其余对象完全不参与;只有影子接收面出现在画面里 → alpha = 影子浓度
    for o in others:
        o.hide_render = True
    for o in objs:
        o.hide_render = False; o.is_holdout = True
    floor.hide_render = False
    sc.cycles.samples = samples; sc.cycles.use_denoising = True
    sc.render.filepath = str(OUT / f'layer-shadow-{name}.png')
    bpy.ops.render.render(write_still=True)
    # 轮廓层:本组的不透明范围,供接触阴影用
    for o in objs:
        o.is_holdout = False
    floor.hide_render = True
    sc.cycles.samples = 4; sc.cycles.use_denoising = False
    sc.render.filepath = str(OUT / f'layer-alpha-{name}.png')
    bpy.ops.render.render(write_still=True)
    for o in meshes:
        o.hide_render = False; o.is_holdout = False
print('V28_SHADOWS_DONE', flush=True)
