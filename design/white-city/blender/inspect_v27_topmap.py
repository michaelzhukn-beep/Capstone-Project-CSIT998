"""v27 沙盘:俯视平面图(Workbench,按集合着色),用于选择台面矩形。只读打开 city-26-v26.blend,不保存。

    blender -b --python design/white-city/blender/inspect_v27_topmap.py
输出 renders-v27/topmap.png + topmap.json(像素 ↔ 设计坐标换算)。
"""
import bpy, json, math
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'renders-v27'
bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-26-v26.blend'))
sc = bpy.context.scene
colors = {'01 Terrain': (.93, .93, .9), '02 Water and banks': (.45, .65, .9), '03 Streets and sidewalks': (.75, .75, .72),
          '04 Buildings': (.85, .35, .25), '05 Bridges': (.3, .3, .3), '07 Vegetation': (.35, .65, .35)}
for ob in sc.objects:
    if ob.type == 'MESH':
        col = ob.users_collection[0].name if ob.users_collection else ''
        ob.color = (*colors.get(col, (1, .8, 0)), 1)
lo = Vector((1e9, 1e9)); hi = Vector((-1e9, -1e9))
for ob in sc.objects:
    if ob.type == 'MESH' and ob.users_collection and ob.users_collection[0].name == '01 Terrain':
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c); lo.x = min(lo.x, p.x); lo.y = min(lo.y, p.y); hi.x = max(hi.x, p.x); hi.y = max(hi.y, p.y)
cx, cy = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
size = max(hi.x - lo.x, hi.y - lo.y) * 1.02
cam_data = bpy.data.cameras.new('top'); cam_data.type = 'ORTHO'; cam_data.ortho_scale = size; cam_data.clip_end = 5000
cam = bpy.data.objects.new('top', cam_data); sc.collection.objects.link(cam)
cam.location = (cx, cy, 2000); cam.rotation_euler = (0, 0, 0)
sc.camera = cam
sc.render.engine = 'BLENDER_WORKBENCH'
sh = sc.display.shading; sh.light = 'FLAT'; sh.color_type = 'OBJECT'; sh.show_object_outline = True
R = 2000
sc.render.resolution_x = sc.render.resolution_y = R; sc.render.resolution_percentage = 100
sc.render.film_transparent = False
sc.render.filepath = str(OUT / 'topmap.png')
bpy.ops.render.render(write_still=True)
# 当前 v26 机位在平面上的视野(相机位置、朝向)
c26 = sc.objects['13 top'] if '13 top' in sc.objects else None
info = {'center': [cx, cy], 'size': size, 'px': R, 'terrain_lo': list(lo), 'terrain_hi': list(hi)}
if c26:
    fwd = (c26.matrix_world.to_3x3() @ Vector((0, 0, -1)))
    info['cam26'] = {'pos': list(c26.location), 'fwd': list(fwd), 'ortho': c26.data.ortho_scale}
(OUT / 'topmap.json').write_text(json.dumps(info, indent=1), encoding='utf-8')
print('V27_TOPMAP', info, flush=True)
