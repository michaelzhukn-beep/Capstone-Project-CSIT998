"""河面 / 水体截面材质:按所有者的效果图从材质层面定色,供重新烘焙(取代网页运行时调色)。

    blender -b --python design/white-city/blender/water_material_v28.py -- \
        [--preview out.png | --apply]
    默认值保留 2026-09-24 校准的青绿色,水面平静,只有柔和倒影与光泽。
    可用 --water/--resin/--rough/--spec/--coat/--bump/--ripple-depth 覆盖。
    重新生成 city-28-showroom.blend(render_v27_plinth.py 里仍是旧的镜面水)后,烘焙前要先跑一次 --apply。

为什么改材质:原镜面水的楼群倒影形成白斑;上一版把粗糙度提到 .35、高光降至 .25 后又过于平整。
明显波纹版(.65 强度 / 1.4 距离)已被所有者否决,不应恢复为默认值。
当前保留已校准底色,以 .12 粗糙度、.5 高光形成柔和倒影,凹凸压到 .06 强度 / .3 距离,
水面不呈现密集条纹;水感主要来自反射,不是波纹。
波纹只改变着色法线,不改轮廓、相机、灯光或水体截面;仍走离线烘焙,不增加网页重绘。
- 水面 '13 Still water'(河道与台座湖面共用同一材质):两者同为世界原点、单位缩放,波纹跨对象连续。
- 截面 'v27 resin':竖向渐变保留形状(底略深、顶略浅),整体换成 --resin 色;清漆减弱。
--preview:用宽幅机位只渲台座包围框(25% 分辨率、低采样),不保存,供 calibrate 量色。
--apply:写回工作副本 city-28-baked.blend(改前已备份到 design/white-city/backup-before-water-material/)。
"""
import bpy, json, sys
from pathlib import Path
from mathutils import Matrix

ROOT = Path(__file__).resolve().parent
BAKE = ROOT.parent / 'bake-v28'
WORK = ROOT / 'city-28-baked.blend'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
arg = lambda k, d, cast=str: cast(argv[argv.index(k) + 1]) if k in argv else d


def srgb(hexcode):
    c = [int(hexcode.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in c]


WATER, RESIN = srgb(arg('--water', '#709797')), srgb(arg('--resin', '#9CC3CA'))
ROUGH, SPEC, COAT = arg('--rough', .12, float), arg('--spec', .5, float), arg('--coat', .15, float)
BUMP = arg('--bump', .06, float)
RIPPLE_DEPTH = arg('--ripple-depth', .3, float)

bpy.ops.wm.open_mainfile(filepath=str(WORK))
sc = bpy.context.scene

water = bpy.data.materials['13 Still water']
pw = water.node_tree.nodes['Principled BSDF']
pw.inputs['Base Color'].default_value = (*WATER, 1)
pw.inputs['Roughness'].default_value = ROUGH
pw.inputs['Specular IOR Level'].default_value = SPEC
for n in water.node_tree.nodes:
    if n.type == 'BUMP':
        n.inputs['Strength'].default_value = BUMP
        n.inputs['Distance'].default_value = RIPPLE_DEPTH

resin = bpy.data.materials['v27 resin']
rp = resin.node_tree.nodes['Principled BSDF']
rp.inputs['Coat Weight'].default_value = COAT
ramp = next(n for n in resin.node_tree.nodes if n.type == 'VALTORGB')
for el in ramp.color_ramp.elements:                       # 底 → 顶:0.90 → 1.00 → 1.06 → 1.08 倍
    k = .90 if el.position < .3 else 1.0 if el.position < .9 else 1.06 if el.position < .99 else 1.08
    el.color = (*[min(1, c * k) for c in RESIN], 1)
print('V28_WATER', arg('--water', '#709797'), ROUGH, SPEC, 'RIPPLE', BUMP, RIPPLE_DEPTH,
      'RESIN', arg('--resin', '#9CC3CA'), COAT, flush=True)

if '--preview' in argv:
    cw = json.loads((BAKE / 'web' / 'cam-wide.json').read_text(encoding='utf-8'))
    cam = sc.camera; cam.matrix_world = Matrix(cw['matrix_world'])
    cd = cam.data; cd.type = 'ORTHO'; cd.sensor_fit = 'HORIZONTAL'
    cd.ortho_scale = cw['ortho_scale']; cd.shift_x = cw['shift_x']; cd.shift_y = cw['shift_y']
    r = sc.render
    r.resolution_x, r.resolution_y = cw['resolution']; r.resolution_percentage = arg('--preview-percent', 25, int)
    box = json.loads((BAKE / 'manifest.json').read_text(encoding='utf-8'))['v27_plinth']['box']
    r.use_border = r.use_crop_to_border = True
    r.border_min_x, r.border_min_y, r.border_max_x, r.border_max_y = box
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == 'OPTIX'
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'
    sc.cycles.samples = arg('--samples', 96, int); sc.cycles.use_denoising = True
    floor = sc.objects.get('v27 floor')
    if floor:
        floor.hide_render = True                            # 与烘焙一致:桌面影子另有一层
    r.filepath = str(Path(arg('--preview', str(BAKE / 'water-preview.png'))).resolve())
    bpy.ops.render.render(write_still=True)
    print('V28_WATER_PREVIEW', r.filepath, flush=True)
elif '--apply' in argv:
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK), compress=True)
    print('V28_WATER_APPLIED', flush=True)
