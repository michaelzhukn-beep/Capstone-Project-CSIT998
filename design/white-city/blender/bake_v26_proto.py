"""v26 光照贴图烘焙小样:6 栋前排亮灯楼,UV 光照贴图(不是顶点色)。只读打开 city-26-v26.blend,不保存。

    blender -b --python design/white-city/blender/bake_v26_proto.py -- [--res 2048] [--samples 512] [--n 6]

为什么是 UV 贴图:楼是轴对齐盒子 + 鳍片,每个面只有 4 个角点,顶点色装不下阴影与槽内渐隐;
此前 FIXED_VIEW / FIXED_STUDIO 记录里顶点烘焙在相交处出过暗条、黑斑。
烘焙 COMBINED(直射 + 间接 + 自发光,关掉镜面与透射,保证与视角无关)。

验收:把这 6 栋楼的材质换成「只输出烘焙贴图的自发光」,同机位重渲,和原 Cycles 渲染逐像素比较。
"""
import bpy, json, math, sys, time
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'renders-v24' / ('bake-proto-' + (sys.argv[sys.argv.index('--tag') + 1] if '--tag' in sys.argv else 'tmp'))
OUT.mkdir(parents=True, exist_ok=True)
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(k, d, cast=float):
    return cast(argv[argv.index(k) + 1]) if k in argv else d
RES, SAMPLES, N = int(arg('--res', 2048)), int(arg('--samples', 512)), int(arg('--n', 6))

bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-26-v26.blend'))
scene = bpy.context.scene
cam = scene.camera
bpy.context.view_layer.update()

# 挑楼:亮灯、在画面内、越靠前越优先,彼此相距 > 25 m
cands = []
for ob in scene.objects:
    if ob.type != 'MESH' or not ob.users_collection or ob.users_collection[0].name != '04 Buildings' or not ob.get('v24_lit'):
        continue
    bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    q = world_to_camera_view(scene, cam, sum(bb, Vector()) / 8)
    if .08 < q.x < .92 and 0 < q.y < 1:
        cands.append((q.y, ob, sum(bb, Vector()) / 8))
cands.sort(key=lambda t: t[0])
chosen = []
for _, ob, c in cands:
    if all((c - c2).length > 25 for _, c2 in chosen):
        chosen.append((ob, c))
    if len(chosen) == N:
        break
objs = [o for o, _ in chosen]
print('V26_BAKE_OBJECTS', [o.name for o in objs], flush=True)

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
bk.use_pass_glossy = bk.use_pass_transmission = False
bk.margin, bk.margin_type, bk.use_clear, bk.target = 8, 'EXTEND', True, 'IMAGE_TEXTURES'

images = {}
t0 = time.time()
for ob in objs:
    # UV:每栋独立展开
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True); bpy.context.view_layer.objects.active = ob
    me = ob.data
    uv = me.uv_layers.get('lightmap') or me.uv_layers.new(name='lightmap')
    me.uv_layers.active = uv
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.002, area_weight=0, scale_to_bounds=False)
    if '--weighted' in argv:
        # 按相机可见度分配贴图面积:背对镜头的面各自缩到 1/10 再重新打包,朝镜头的面分到绝大部分像素
        import bmesh
        view = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
        bm = bmesh.from_edit_mesh(me); uvl = bm.loops.layers.uv.verify(); n3 = ob.matrix_world.to_3x3()
        shrunk = 0
        for f in bm.faces:
            if (n3 @ f.normal).normalized().dot(view) > -.05:
                c = sum((l[uvl].uv for l in f.loops), Vector((0, 0))) / len(f.loops)
                for l in f.loops:
                    l[uvl].uv = c + (l[uvl].uv - c) * arg('--backscale', .1)
                shrunk += 1
        bmesh.update_edit_mesh(me)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pack_islands(rotate=False, scale=True, margin=.003)
        print('V26_UV_WEIGHTED', ob.name, 'back faces', shrunk, 'of', len(bm.faces), flush=True)
    bpy.ops.object.mode_set(mode='OBJECT')
    img = bpy.data.images.new(f'lm {ob.name}', RES, RES, float_buffer=True)
    images[ob.name] = img
    # 材质:本栋独占副本,插入选中的贴图节点作为烘焙目标
    for slot in ob.material_slots:
        src = slot.material
        if not src:
            continue
        m = src.copy()
        m.name = f'{src.name} | {ob.name}'
        slot.link = 'OBJECT'
        slot.material = m
        n = m.node_tree.nodes.new('ShaderNodeTexImage'); n.image = img; n.name = 'v26 lightmap'
        m.node_tree.nodes.active = n
    t = time.time()
    bpy.ops.object.bake(type='COMBINED')
    img.filepath_raw = str(OUT / f'lm-{ob.name.split(" ")[0]}.exr')
    img.file_format = 'OPEN_EXR'
    img.save()
    print('V26_BAKED', ob.name, round(time.time() - t, 1), 's', flush=True)
print('V26_BAKE_TOTAL', round(time.time() - t0, 1), 's', flush=True)

# 验收渲染 1:原材质(同一份内存场景,等价 U16)
scene.cycles.samples = 256
scene.render.filepath = str(OUT / 'check-cycles.png')
bpy.ops.render.render(write_still=True)
# 验收渲染 2:6 栋楼只显示烘焙贴图
for ob in objs:
    for slot in ob.material_slots:
        m = slot.material
        if not m:
            continue
        nt = m.node_tree; N_ = nt.nodes
        tex = N_['v26 lightmap']
        uvn = N_.new('ShaderNodeUVMap'); uvn.uv_map = 'lightmap'
        nt.links.new(uvn.outputs[0], tex.inputs['Vector'])
        em = N_.new('ShaderNodeEmission')
        nt.links.new(tex.outputs['Color'], em.inputs['Color'])
        outn = next(n for n in N_ if n.bl_idname == 'ShaderNodeOutputMaterial')
        nt.links.new(em.outputs[0], outn.inputs['Surface'])
scene.render.filepath = str(OUT / 'check-baked.png')
bpy.ops.render.render(write_still=True)

# 每栋楼在画面中的包围框,供比较脚本裁切
boxes = {}
for ob in objs:
    qs = [world_to_camera_view(scene, cam, ob.matrix_world @ Vector(c)) for c in ob.bound_box]
    boxes[ob.name.split(' ')[0]] = [min(q.x for q in qs), 1 - max(q.y for q in qs), max(q.x for q in qs), 1 - min(q.y for q in qs)]
(OUT / 'boxes.json').write_text(json.dumps(boxes, indent=1), encoding='utf-8')
print('V26_PROTO_DONE', flush=True)
