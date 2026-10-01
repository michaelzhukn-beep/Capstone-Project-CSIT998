"""v26 树木着色层:锁定机位下只渲染树(其余物体设为 holdout,仍参与投影与反弹光)。只读打开,不保存。

    blender -b --python design/white-city/blender/render_v26_trees.py -- [--scale 200] [--samples 256]

网页里树仍是真实几何(4 个原型、1,394 个实例);因为机位锁定,树的每个像素按其画面位置从这张图取色,
与 Cycles 画面一致。被楼挡住的树在图里是透明(holdout),网页里同样被楼的几何挡住,互不影响。
输出 design/white-city/bake-v26/trees-2x.png(RGBA,已套用场景 AgX 显示变换与曝光)。
"""
import bpy, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(k, d, cast=int):
    return cast(argv[argv.index(k) + 1]) if k in argv else d

bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-26-v26.blend'))
scene = bpy.context.scene
n = 0
for ob in scene.objects:
    if ob.type == 'MESH':
        tree = ob.users_collection and ob.users_collection[0].name == '07 Vegetation'
        ob.is_holdout = not tree
        n += 0 if tree else 1
scene.render.engine = 'CYCLES'
scene.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
scene.cycles.samples = arg('--samples', 256)
scene.cycles.use_denoising = True
scene.render.resolution_percentage = arg('--scale', 200)
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.filepath = str(ROOT.parent / 'bake-v26' / 'trees-2x.png')
print('V26_TREES_HOLDOUT', n, flush=True)
bpy.ops.render.render(write_still=True)
print('V26_TREES_DONE', scene.render.filepath, flush=True)
