"""v26 全城光照烘焙:Cycles 光照 → UV 贴图,网页加载真实模型 + 烘焙贴图(无光照材质)。

    blender -b --python design/white-city/blender/bake_v26_city.py -- [--samples 384] [--only B019,B076] [--limit 3]

输入 city-26-v26.blend(只读,不保存);工作副本 city-26-baked.blend 每烘完一个对象保存一次,
崩溃后重跑会从工作副本继续,已烘过的对象(自定义属性 v26_baked)跳过。本机内存不稳定(BUG-16),必须可续跑。

贴图分配(实验 12 验证):
- 楼 / 地灯:每栋独立 smart UV,背对镜头的面缩到 1/10 后重新打包;分辨率按画面包围框大小取 512–2048。
- 地形 / 道路 / 河 / 岸墙 / 桥:锁定机位投影 UV —— 朝镜头的面 UV = 该点在画面中的位置,
  背对镜头的面收缩到贴图右上角(那里是天空,不会被可见地面用到)。贴图 4096×2293,约为画面 2.2 倍。
  UV 不夹到 0–1:画框外部分超出范围即可,夹边会扭曲跨画框大三角形的插值。
- 水面:从相机方向烘焙并保留镜面(倒影);其余对象关闭镜面,只烘与视角无关的光照。

输出 design/white-city/bake-v26/:<对象>.png(已套用场景的 AgX 显示变换与曝光,网页直接当颜色贴图用)+ manifest.json。
不保留 EXR(每张 4096×2293 浮点约 112 MB);要重新调色就重烘,全城约十几分钟。
"""
import bpy, bmesh, json, math, sys, time
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'bake-v26'
OUT.mkdir(exist_ok=True)
SRC, WORK = ROOT / 'city-26-v26.blend', ROOT / 'city-26-baked.blend'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(k, d, cast=float):
    return cast(argv[argv.index(k) + 1]) if k in argv else d
SAMPLES = int(arg('--samples', 384))
ONLY = set(arg('--only', '', str).split(',')) - {''}
LIMIT = int(arg('--limit', 0))
MODE = arg('--mode', '', str)                   # 只处理某类对象:screen / smart
REBAKE = '--rebake' in argv                     # 配合 --only:忽略 v26_baked 标记,重烘指定对象

bpy.ops.wm.open_mainfile(filepath=str(WORK if WORK.exists() else SRC))
scene = bpy.context.scene
cam = scene.camera
bpy.context.view_layer.update()
W, H = scene.render.resolution_x, scene.render.resolution_y
view = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()

scene.render.engine = 'CYCLES'
scene.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
scene.cycles.samples = SAMPLES
bk = scene.render.bake
bk.use_pass_direct = bk.use_pass_indirect = True
bk.use_pass_diffuse = bk.use_pass_emit = True
bk.use_pass_transmission = False
bk.margin, bk.margin_type, bk.use_clear, bk.target = 6, 'EXTEND', True, 'IMAGE_TEXTURES'

SCREEN_COLS = {'01 Terrain', '02 Water and banks', '03 Streets and sidewalks', '05 Bridges'}


def screen_box(ob):
    qs = [world_to_camera_view(scene, cam, ob.matrix_world @ Vector(c)) for c in ob.bound_box]
    x0, x1 = max(0, min(q.x for q in qs)), min(1, max(q.x for q in qs))
    y0, y1 = max(0, min(q.y for q in qs)), min(1, max(q.y for q in qs))
    return max(0, x1 - x0) * W, max(0, y1 - y0) * H


def plan():
    jobs = []
    for ob in scene.objects:
        if ob.type != 'MESH' or not ob.users_collection:
            continue
        col = ob.users_collection[0].name
        if col == '07 Vegetation':
            continue
        w, h = screen_box(ob)
        if w * h < 4:
            continue                                    # 画面外(例如上游小桥)
        if col in SCREEN_COLS:
            jobs.append((ob, 'screen', (4096, 2293)))
        else:
            r = 1 << max(9, min(11, math.ceil(math.log2(max(w, h, 1) * 5))))
            jobs.append((ob, 'smart', (r, r)))
    return jobs


def uv_smart(ob):
    me = ob.data
    uv = me.uv_layers.get('lightmap') or me.uv_layers.new(name='lightmap')
    me.uv_layers.active = uv
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.002, area_weight=0, scale_to_bounds=False)
    bm = bmesh.from_edit_mesh(me); uvl = bm.loops.layers.uv.verify(); mw = ob.matrix_world; n3 = mw.to_3x3()
    dg = bpy.context.evaluated_depsgraph_get()
    hidden = 0
    for f in bm.faces:
        k = None
        if (n3 @ f.normal).normalized().dot(view) > -.05:
            k = .1                                      # 背对镜头
        else:
            # 朝镜头但被遮挡(如被屋顶盖住的面板盒顶面):面中心与四个内缩角点都朝相机方向打射线,全被挡才算隐藏
            wc = mw @ f.calc_center_median(); nrm = (n3 @ f.normal).normalized()
            pts = [wc] + [wc + (mw @ v.co - wc) * .8 for v in f.verts]
            if all(scene.ray_cast(dg, p_ + nrm * .02 - view * .02, -view)[0] for p_ in pts):
                k = .05; hidden += 1
        if k:
            c = sum((l[uvl].uv for l in f.loops), Vector((0, 0))) / len(f.loops)
            for l in f.loops:
                l[uvl].uv = c + (l[uvl].uv - c) * k
    print('V26_UV_HIDDEN', ob.name, hidden, 'of', len(bm.faces), flush=True)
    bmesh.update_edit_mesh(me)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=False, scale=True, margin=.003)
    bpy.ops.object.mode_set(mode='OBJECT')


def uv_screen(ob):
    me = ob.data
    uv = me.uv_layers.get('lightmap') or me.uv_layers.new(name='lightmap')
    me.uv_layers.active = uv
    mw, n3 = ob.matrix_world, ob.matrix_world.to_3x3()
    qv = [world_to_camera_view(scene, cam, mw @ v.co) for v in me.vertices]
    back = 0
    for p in me.polygons:
        facing = (n3 @ p.normal).normalized().dot(view) < 0
        back += 0 if facing else 1
        for li in p.loop_indices:
            if facing:
                q = qv[me.loops[li].vertex_index]
                uv.data[li].uv = (q.x, q.y)       # 不夹边:画框外的顶点 UV 超出 0–1;夹边会扭曲跨画框大三角形的插值(实测出黑楔)
            else:
                uv.data[li].uv = (.9995, .9995)
    return back


manifest_path = OUT / 'manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
jobs = plan()
print('V26_CITY_JOBS', len(jobs), 'done', sum(1 for o, _, _ in jobs if o.get('v26_baked')), flush=True)
t_all, n = time.time(), 0
for ob, mode, (rw, rh) in jobs:
    key = ob.name.split(' ')[0] if ob.name.startswith('B') else ob.name.replace(' ', '_')
    if (ob.get('v26_baked') and not REBAKE) or (ONLY and key not in ONLY) or (MODE and mode != MODE):
        continue
    if LIMIT and n >= LIMIT:
        break
    t = time.time()
    if ob.data.users > 1:
        ob.data = ob.data.copy()
    back = uv_screen(ob) if mode == 'screen' else (uv_smart(ob) or 0)
    img = bpy.data.images.new(f'v26 lm {key}', rw, rh, float_buffer=True)
    water = ob.name.endswith('Continuous river')
    bk.use_pass_glossy = water
    bk.view_from = 'ACTIVE_CAMERA' if water else 'ABOVE_SURFACE'
    for slot in ob.material_slots:
        src = slot.material
        if not src:
            continue
        m = src.copy(); m.name = f'{src.name} | {key}'
        slot.link = 'OBJECT'; slot.material = m
        node = m.node_tree.nodes.new('ShaderNodeTexImage'); node.image = img; node.name = 'v26 lightmap'
        m.node_tree.nodes.active = node
    # 地形被道路 / 人行道压住的部分烘焙时是暗的,高分辨率下双线性过滤会把暗色渗到露出的地形边缘(网页 1 px 黑线)。
    # 烘地形时临时隐藏这两层铺装:它们几乎平贴地面,对地形光照影响可忽略
    covers = [o for o in scene.objects if o.type == 'MESH' and o.users_collection and o.users_collection[0].name == '03 Streets and sidewalks']         if ob.users_collection[0].name == '01 Terrain' else []
    for o in covers:
        o.hide_render = True
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True); bpy.context.view_layer.objects.active = ob
    bpy.ops.object.bake(type='COMBINED')
    for o in covers:
        o.hide_render = False
    img.save_render(str(OUT / f'{key}.png'), scene=scene)          # 套用场景 AgX + 曝光 → 显示色
    ob['v26_baked'] = 1
    manifest[key] = {'object': ob.name, 'mode': mode, 'res': [rw, rh], 'back_faces': back,
                     'glossy': water, 'samples': SAMPLES, 'seconds': round(time.time() - t, 1)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    bpy.data.images.remove(img)
    bpy.ops.wm.save_as_mainfile(filepath=str(WORK), compress=True)
    n += 1
    print('V26_CITY_BAKED', key, mode, rw, rh, round(time.time() - t, 1), 's', flush=True)
print('V26_CITY_DONE', n, 'objects', round(time.time() - t_all, 1), 's', flush=True)
