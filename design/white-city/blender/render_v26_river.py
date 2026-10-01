"""v26 河面贴图:用锁定机位的 Cycles 渲染直接生成河面颜色(含倒影)。只读打开,不保存。

    blender -b --python design/white-city/blender/render_v26_river.py -- [--scale 200] [--samples 512]

河面用的是锁定机位投影 UV(UV = 画面坐标),所以「从相机看到的河面颜色」就是它的贴图。
烘焙(COMBINED + 相机方向镜面,384 采样无降噪)在网页里只得到一团团光斑;这里改为正常渲染 + 降噪,
得到与 Cycles 画面一致的竖向倒影条纹。
除河面外所有物体设为对相机不可见(visible_camera = False):它们仍出现在倒影里、仍投影,
而被楼挡住的那部分河面也能完整渲染出来,贴图没有空洞。
输出覆盖 bake-v26/13_Continuous_river.png(4096×2293,已套用场景 AgX 显示变换与曝光)。
"""
import bpy, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'bake-v26'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(k, d, cast=int):
    return cast(argv[argv.index(k) + 1]) if k in argv else d

bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-26-v26.blend'))
scene = bpy.context.scene
river = scene.objects['13 Continuous river']
for ob in scene.objects:
    if ob.type == 'MESH' and ob is not river:
        ob.visible_camera = False
scene.render.engine = 'CYCLES'
scene.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
scene.cycles.samples = arg('--samples', 512)
scene.cycles.use_denoising = True
scene.render.resolution_percentage = arg('--scale', 200)
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
tmp = ROOT.parent / 'renders-v24' / 'river-layer-2x.png'          # 中间图不放进 bake-v26,免得被贴图修补脚本当成贴图
scene.render.filepath = str(tmp)
bpy.ops.render.render(write_still=True)

# 渲染分辨率 → 河面贴图分辨率(UV 0–1 对应整幅画面)
img = bpy.data.images.load(str(tmp))
img.scale(4096, 2293)
img.filepath_raw = str(OUT / '13_Continuous_river.png')
img.file_format = 'PNG'
img.save()
print('V26_RIVER_DONE', img.filepath_raw, flush=True)
