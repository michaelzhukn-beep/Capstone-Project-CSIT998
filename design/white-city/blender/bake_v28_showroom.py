"""v28 沙盘 + 户型样板:整段镜头平移范围的光照 → 贴图,供网页加载真实模型。

    blender -b --python design/white-city/blender/bake_v28_showroom.py -- [--density 7] [--samples 256] [--only KEY,..] [--mode smart|screen|layer]

输入 city-28-showroom.blend(render_v27_plinth.py --houses --saveas 生成,只读);工作副本 city-28-baked.blend
每处理完一个对象保存一次,崩溃后重跑从工作副本继续(本机内存不稳定,BUG-16)。

镜头只在固定朝向下平移 + 缩放(正交),所以用一台「宽幅机位」覆盖起点、终点两个画框的并集:
- smart(楼、户型房子、信息牌、地灯、船):独立 smart UV,背对 / 被遮挡的面缩小,Cycles COMBINED 烘焙。
- screen(地形、道路、河、岸墙、桥、台身、草坪):UV = 该对象在宽幅画框中的位置;贴图不是烘焙,而是
  「只让这个对象对相机可见」的 Cycles 渲染(其他对象仍投影、仍反射、仍出现在倒影里)——
  河面倒影、草丛发丝、台身剖面都与离线渲染一致。只对该对象包围框做裁切渲染。
- layer:树木着色层(网页里树是实例几何,按宽幅机位投影取色)、桌面影子层(alpha = 影子浓度)、模型轮廓层。
输出 design/white-city/bake-v28/:<key>.png + manifest.json + web/cam-wide.json。PNG 已套用场景 AgX 显示变换。
"""
import bpy, bmesh, json, math, sys, time
from pathlib import Path
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'bake-v28'
WEB = OUT / 'web'
SRC, WORK = ROOT / 'city-28-showroom.blend', ROOT / 'city-28-baked.blend'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(k, d, cast=float):
    return cast(argv[argv.index(k) + 1]) if k in argv else d
DENSITY = arg('--density', 7.0)                     # 每米像素(网页 2 倍像素密度下约 7–9 px/m 才不糊)
SAMPLES = int(arg('--samples', 256))
ONLY = set(arg('--only', '', str).split(',')) - {''}
MODE = arg('--mode', '', str)
REBAKE = '--rebake' in argv                     # 机位改变后:忽略已烘标记重做(配合 --mode screen / layer)
MAXTEX = 8192

bpy.ops.wm.open_mainfile(filepath=str(WORK if WORK.exists() else SRC))
sc = bpy.context.scene
cam = sc.camera
col = lambda o: o.users_collection[0].name if o.users_collection else ''

# ---------------------------------------------------------------- 宽幅机位
cams = [json.loads((WEB / f'cam-{k}.json').read_text(encoding='utf-8')) for k in ('start', 'end')]
R = Matrix(cams[0]['matrix_world']).to_3x3()
right, up = R @ Vector((1, 0, 0)), R @ Vector((0, 1, 0))
loc0 = Matrix(cams[0]['matrix_world']).to_translation()
rects = []
for c in cams:
    loc = Matrix(c['matrix_world']).to_translation()
    w = c['ortho_scale']; rx, ry = c['resolution']; h = w * ry / rx
    cu = loc.dot(right) + c['shift_x'] * w; cv = loc.dot(up) + c['shift_y'] * w
    rects.append((cu - w / 2, cv - h / 2, cu + w / 2, cv + h / 2))
u0 = min(r[0] for r in rects); v0 = min(r[1] for r in rects); u1 = max(r[2] for r in rects); v1 = max(r[3] for r in rects)
# 左右不对称留白:宽屏时画面按「保持高度、左右加宽」适配,起点画框左侧会多露出一截,
# 所以左边多留(按起点画框宽度的 8%),其余 2%
pad = .02 * (u1 - u0); u0 -= pad + .08 * cams[0]['ortho_scale']; u1 += pad; v0 -= pad; v1 += pad
UW, VH = u1 - u0, v1 - v0
px_per_m = min(DENSITY, MAXTEX / UW)
RX, RY = int(round(UW * px_per_m)), int(round(VH * px_per_m))
cam.matrix_world = Matrix(cams[0]['matrix_world'])
cd = cam.data; cd.type = 'ORTHO'; cd.sensor_fit = 'HORIZONTAL'; cd.ortho_scale = UW
cd.shift_x = ((u0 + u1) / 2 - loc0.dot(right)) / UW
cd.shift_y = ((v0 + v1) / 2 - loc0.dot(up)) / UW
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = RX, RY, 100
bpy.context.view_layer.update()
WEB.mkdir(parents=True, exist_ok=True)
(WEB / 'cam-wide.json').write_text(json.dumps({'matrix_world': [list(r) for r in cam.matrix_world], 'ortho_scale': UW,
    'shift_x': cd.shift_x, 'shift_y': cd.shift_y, 'resolution': [RX, RY], 'px_per_m': px_per_m}, indent=1), encoding='utf-8')
view = (R @ Vector((0, 0, -1))).normalized()
print('V28_WIDE', RX, RY, 'px/m', round(px_per_m, 2), flush=True)

sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
sc.cycles.samples = SAMPLES
bk = sc.render.bake
bk.use_pass_direct = bk.use_pass_indirect = True
bk.use_pass_diffuse = bk.use_pass_emit = True
bk.use_pass_glossy = bk.use_pass_transmission = False
bk.margin, bk.margin_type, bk.use_clear, bk.target = 6, 'EXTEND', True, 'IMAGE_TEXTURES'
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'; sc.render.image_settings.color_depth = '8'
floor = sc.objects.get('v27 floor')

SCREEN_COLS = {'01 Terrain', '02 Water and banks', '03 Streets and sidewalks', '05 Bridges'}


def is_tree(o):
    return o.type == 'MESH' and (col(o) == '07 Vegetation' or o.data.name.startswith('13 Tree prototype'))


def kind(o):
    if o.type != 'MESH' or o is floor or is_tree(o):
        return None
    if col(o) in SCREEN_COLS or o.name == 'v27 plinth' or o.name.endswith(' lawn'):
        return 'screen'
    return 'smart'


def frame_box(o):
    """对象在宽幅画框中的包围框(0–1,左下原点),只算朝镜头的面。"""
    mw, n3 = o.matrix_world, o.matrix_world.to_3x3()
    xs, ys = [], []
    me = o.data
    for p in me.polygons:
        if (n3 @ p.normal).normalized().dot(view) >= 0:
            continue
        for vi in p.vertices:
            q = world_to_camera_view(sc, cam, mw @ me.vertices[vi].co)
            xs.append(q.x); ys.append(q.y)
    if not xs:
        return None
    x0, x1 = max(0, min(xs)), min(1, max(xs)); y0, y1 = max(0, min(ys)), min(1, max(ys))
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
        return None
    return x0, y0, x1, y1


def uv_screen(o, box):
    me = o.data
    uv = me.uv_layers.get('lightmap') or me.uv_layers.new(name='lightmap')
    me.uv_layers.active = uv
    mw, n3 = o.matrix_world, o.matrix_world.to_3x3()
    x0, y0, x1, y1 = box
    qv = [world_to_camera_view(sc, cam, mw @ v.co) for v in me.vertices]
    for p in me.polygons:
        facing = (n3 @ p.normal).normalized().dot(view) < 0
        for li in p.loop_indices:
            q = qv[me.loops[li].vertex_index]
            uv.data[li].uv = ((q.x - x0) / (x1 - x0), (q.y - y0) / (y1 - y0)) if facing else (2.0, 2.0)


def uv_smart(o):
    me = o.data
    uv = me.uv_layers.get('lightmap') or me.uv_layers.new(name='lightmap')
    me.uv_layers.active = uv
    bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.002, area_weight=0, scale_to_bounds=False)
    bm = bmesh.from_edit_mesh(me); uvl = bm.loops.layers.uv.verify(); n3 = o.matrix_world.to_3x3()
    for f in bm.faces:
        if (n3 @ f.normal).normalized().dot(view) > -.05:
            c = sum((l[uvl].uv for l in f.loops), Vector((0, 0))) / len(f.loops)
            for l in f.loops:
                l[uvl].uv = c + (l[uvl].uv - c) * .1
    bmesh.update_edit_mesh(me)
    bpy.ops.uv.select_all(action='SELECT'); bpy.ops.uv.pack_islands(rotate=False, scale=True, margin=.003)
    bpy.ops.object.mode_set(mode='OBJECT')


def isolated_render(visible, path, box=None, holdout_others=False, samples=None):
    """只让 visible 中的对象对相机可见(或其余对象 holdout),可选按包围框裁切渲染。"""
    saved = []
    for o in sc.objects:
        if o.type != 'MESH':
            continue
        saved.append((o, o.visible_camera, o.is_holdout))
        if o in visible:
            continue
        if holdout_others:
            o.is_holdout = True
        else:
            o.visible_camera = False
    r = sc.render
    r.use_border = box is not None; r.use_crop_to_border = box is not None
    if box:
        r.border_min_x, r.border_min_y, r.border_max_x, r.border_max_y = box
    if samples:
        sc.cycles.samples = samples
    r.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    sc.cycles.samples = SAMPLES
    r.use_border = False
    for o, vc, ho in saved:
        o.visible_camera, o.is_holdout = vc, ho


def key_of(o):
    return (o.name.split(' ')[0] if o.name[:1] == 'B' and o.name[1:4].isdigit() else o.name).replace(' ', '_')


manifest_path = OUT / 'manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
objs = [(o, kind(o)) for o in sc.objects]
objs = [(o, k) for o, k in objs if k]
print('V28_JOBS', len(objs), 'done', sum(1 for o, _ in objs if o.get('v28_baked')), flush=True)
t_all, n = time.time(), 0
if floor:
    floor.hide_render = True
for o, k in objs:
    key = key_of(o)
    if (o.get('v28_baked') and not REBAKE) or (ONLY and key not in ONLY) or (MODE and MODE != k):
        continue
    t = time.time()
    if o.data.users > 1:
        o.data = o.data.copy()
    if k == 'screen':
        box = frame_box(o)
        if not box:
            o['v28_baked'] = 1; continue
        uv_screen(o, box)
        bpx = ((box[2] - box[0]) * RX, (box[3] - box[1]) * RY)
        isolated_render({o}, OUT / f'{key}.png', box=box)
        manifest[key] = {'object': o.name, 'mode': k, 'box': box, 'px': [round(v) for v in bpx]}
    else:
        uv_smart(o)
        w, h = frame_box(o) and (lambda b: ((b[2] - b[0]) * RX, (b[3] - b[1]) * RY))(frame_box(o)) or (64, 64)
        res = 1 << max(9, min(11, math.ceil(math.log2(max(w, h, 1) * 3))))
        img = bpy.data.images.new(f'v28 lm {key}', res, res, float_buffer=True)
        for slot in o.material_slots:
            src = slot.material
            if not src:
                continue
            m = src.copy(); m.name = f'{src.name} | {key}'
            slot.link = 'OBJECT'; slot.material = m
            node = m.node_tree.nodes.new('ShaderNodeTexImage'); node.image = img; node.name = 'v28 lightmap'
            m.node_tree.nodes.active = node
        bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active = o
        bpy.ops.object.bake(type='COMBINED')
        img.save_render(str(OUT / f'{key}.png'), scene=sc)
        bpy.data.images.remove(img)
        manifest[key] = {'object': o.name, 'mode': k, 'res': res}
    o['v28_baked'] = 1
    manifest[key]['seconds'] = round(time.time() - t, 1)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK), compress=True)
    n += 1
    print('V28_BAKED', key, k, manifest[key].get('px') or manifest[key].get('res'), manifest[key]['seconds'], 's', flush=True)

# ---------------------------------------------------------------- 图层
if (not MODE or MODE == 'layer') and (REBAKE or not sc.get('v28_layers')):
    trees = {o for o in sc.objects if is_tree(o)}
    isolated_render(trees, OUT / 'layer-trees.png', holdout_others=True)
    if floor:
        floor.hide_render = False
        isolated_render({floor}, OUT / 'layer-shadow.png', holdout_others=True, samples=96)
        floor.hide_render = True
    models = {o for o in sc.objects if o.type == 'MESH' and o is not floor}
    isolated_render(models, OUT / 'layer-alpha.png', samples=4)
    sc['v28_layers'] = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK), compress=True)
    print('V28_LAYERS_DONE', flush=True)
print('V28_DONE', n, 'objects', round(time.time() - t_all, 1), 's', flush=True)
