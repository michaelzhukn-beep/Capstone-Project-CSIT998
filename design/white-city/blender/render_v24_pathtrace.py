"""v24 实验 8:同一模型、同一锁定机位的 Cycles 路径追踪对照。只读打开工程,不保存。

    blender -b --python design/white-city/blender/render_v24_pathtrace.py -- [--samples 96]

目的只有一个:回答「画面扁平是不是因为实时渲染」。灯光按实验 2 的逻辑 —— 主光从镜头左侧上方打,
镜头看得到的立面受光,看不到的一侧暗;白色环境光很弱;材质全部白色非金属,水面略带光泽。
没有任何暖光,也不做后期,和网页实时版的中性白模对比。
"""
import bpy, json, math, sys
from pathlib import Path
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'renders-v24'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
samples = int(argv[argv.index('--samples') + 1]) if '--samples' in argv else 96
def arg(k, d, cast=float):
    return cast(argv[argv.index(k) + 1]) if k in argv else d

bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-13-smooth.blend'))
scene = bpy.context.scene
LAMPS = {}
if '--fins' in argv:
    # v26 立面实验:低层楼方格窗 → 通高竖鳍片(只改内存,不保存),见 v26_fins.py
    sys.path.insert(0, str(ROOT))
    import v26_fins
    tb = tf = nb = 0
    for ob in [o for o in scene.objects if o.type == 'MESH' and o.users_collection and o.users_collection[0].name == '04 Buildings']:
        if ob.data.users > 1:
            ob.data = ob.data.copy()
        b_, f_ = v26_fins.apply(ob, spacing=arg('--finspace', 1.25), fin_w=arg('--finw', .14), fin_out=arg('--finout', .6), max_h=arg('--finmaxh', 26))
        tb += b_; tf += f_; nb += 1 if f_ else 0
    print('V26_FINS buildings', nb, 'bands_removed', tb, 'fins', tf, flush=True)
if '--trees' in argv:
    # v26 树木实验:4 个树原型换成蓬松小球团树冠 + 深色枝干(只改内存),见 v26_trees.py
    sys.path.insert(0, str(ROOT))
    import v26_trees
    print('V26_TREES polys_per_4_protos', v26_trees.apply(bpy, width=arg('--treew', 1.0), blobs=int(arg('--treeblobs', 48))), flush=True)
spec = json.loads((ROOT / 'city-14-locked-camera.json').read_text(encoding='utf-8'))

cam = next(o for o in scene.objects if o.type == 'CAMERA')
scene.camera = cam
cam.location = spec['position']
cam.rotation_euler = (Vector(spec['target']) - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam.data.type = 'ORTHO'
cam.data.clip_end = 4000
cam.data.ortho_scale = spec['captured_frustum_width'] / spec['zoom']
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1883, 1054, 100

# 材质:白色非金属,与网页 v23 同一组底色(线性值由 sRGB 换算)
def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in c]
spec_mat = {
    '13 White clay': ('#F2F2F0', .62), '13 Roof and stone': ('#F4F4F1', .7), '13 Recessed white panels': ('#E6E6E3', .45),
    '13 Pavement': ('#F0F0EC', .85), '13 Still water': ('#EEF0EF', .12), '13 Tree crowns': ('#F3F3F0', .8), '13 Branches': (arg('--branchcol', '#CFCFCA', str), .8),
}
for name, (hexc, rough) in spec_mat.items():
    m = bpy.data.materials.get(name)
    if not m or not m.use_nodes:
        continue
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*srgb(hexc), 1)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = 0
    p.inputs['Specular IOR Level'].default_value = .4

for o in [o for o in scene.objects if o.type == 'LIGHT']:
    bpy.data.objects.remove(o, do_unlink=True)

target = Vector(spec['target'])
forward = (target - Vector(spec['position'])).normalized()
left = Vector((0, 0, 1)).cross(forward).normalized()
# 主光:镜头左前上方的太阳光,角直径 2.5° 给出清楚但不生硬的阴影
sun_dir = (-forward * .35 + left * .65 + Vector((0, 0, 1)) * .75).normalized()
sun = bpy.data.objects.new('v24 key sun', bpy.data.lights.new('v24 key sun', 'SUN'))
scene.collection.objects.link(sun)
sun.data.energy = arg('--sunw', 3.2)
sun.data.angle = math.radians(2.5)
sun.rotation_euler = (-sun_dir).to_track_quat('-Z', 'Y').to_euler()

if '--uplights' in argv:
    # 暖光:8 栋靠前低层楼,朝镜头立面前的地面各两盏朝上聚光灯 + 一层玻璃后一块朝外的暖色面光
    from bpy_extras.object_utils import world_to_camera_view
    plan = json.loads((ROOT / 'city-14-studio-plan.json').read_text(encoding='utf-8'))
    bpy.context.view_layer.update()
    v2 = Vector((forward.x, forward.y, 0)).normalized()
    warm = tuple(float(x) for x in arg('--warm', '1.0,.78,.52', str).split(','))
    cands = []
    for b in plan['buildings']:
        if b['h'] >= 26 or b['kind'] == 'gable':
            continue
        q = world_to_camera_view(scene, cam, Vector((b['x'], b['y'], b['z'] + 1)))
        if -.02 < q.x < 1.02 and .05 < q.y < .55:
            cands.append((q.y, b))
    cands.sort(key=lambda t: t[0])
    chosen = []
    for _, b in cands:
        if all(math.hypot(b['x'] - c['x'], b['y'] - c['y']) > 30 for c in chosen):
            chosen.append(b)
        if len(chosen) == 8:
            break
    for b in chosen:
        fp = [Vector((p[0], p[1], 0)) for p in b['footprint']]
        c = sum(fp, Vector()) / len(fp)
        best = None
        for i, a in enumerate(fp):
            e = fp[(i + 1) % len(fp)] - a
            n = Vector((e.y, -e.x, 0)).normalized()
            if n.dot((a + e / 2) - c) < 0:
                n = -n
            facing = -n.dot(v2)
            if not best or facing > best[0]:
                best = (facing, a, e, n)
        _, a, e, n = best
        for t in (.25, .75):
            g = a + e * t
            spot = bpy.data.objects.new('v24 uplight', bpy.data.lights.new('v24 uplight', 'SPOT'))
            scene.collection.objects.link(spot)
            spot.location = (g.x + n.x * .35, g.y + n.y * .35, b['z'] + .12)
            aim = Vector((g.x - n.x * .2, g.y - n.y * .2, b['z'] + b['h'] * .55))
            spot.rotation_euler = (aim - spot.location).to_track_quat('-Z', 'Y').to_euler()
            spot.data.energy = float(argv[argv.index('--upw') + 1]) if '--upw' in argv else 900
            spot.data.color = warm
            spot.data.spot_size = math.radians(48)
            spot.data.spot_blend = 1
            spot.data.shadow_soft_size = .15
        if '--glowarea' not in argv:
            continue
        glow = bpy.data.objects.new('v24 interior glow', bpy.data.lights.new('v24 interior glow', 'AREA'))
        scene.collection.objects.link(glow)
        mid = a + e * .5
        glow.location = (mid.x - n.x * 1.6, mid.y - n.y * 1.6, b['z'] + 1.4)
        glow.rotation_euler = (Vector((glow.location)) + n - Vector(glow.location)).to_track_quat('-Z', 'Y').to_euler()
        glow.data.shape = 'RECTANGLE'
        glow.data.size = e.length * .85
        glow.data.size_y = 2.2
        glow.data.energy = float(argv[argv.index('--glow') + 1]) if '--glow' in argv else 1800
        glow.data.color = warm
    print('V24_UPLIGHTS', len(chosen), flush=True)

if '--recess' in argv:
    # 暖光实验 R:不加灯具几何,凹进竖梃之间的窗格面板本身自下而上发光(底部最亮、按米数渐隐),
    # 竖梃正面保持白色。每栋楼记录自身底标高,只点亮一部分楼。
    import random
    rng = random.Random(7)
    frac, fade = arg('--recessfrac', .45), arg('--recessh', 6.0)
    # --litmode front:按画面纵向位置挑楼,越靠镜头前排(画面越低)越可能亮灯;random:均匀随机
    from bpy_extras.object_utils import world_to_camera_view
    scene.camera = next(o for o in scene.objects if o.type == 'CAMERA')
    bpy.context.view_layer.update()
    mode = arg('--litmode', 'random', str)
    for ob in scene.objects:
        if ob.type == 'MESH':
            bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
            ob['v24_base'] = min(p_.z for p_ in bb)
            r_ = rng.random()
            if mode == 'front' and ob.users_collection and ob.users_collection[0].name == '04 Buildings':
                q = world_to_camera_view(scene, scene.camera, sum(bb, Vector()) / 8)
                if not (0 <= q.x <= 1 and 0 <= q.y <= 1):
                    ob['v24_lit'] = 0.0
                    continue
                pr = frac * 2.2 * max(0.0, 1 - q.y / .75)        # 画面底部约 2.2 倍,上 1/4 不亮
                ob['v24_lit'] = 1.0 if r_ < pr else 0.0
            else:
                ob['v24_lit'] = 1.0 if r_ < frac else 0.0
    m = bpy.data.materials['13 Recessed white panels']
    nt = m.node_tree; N = nt.nodes; L = nt.links
    pb = N['Principled BSDF']
    geo = N.new('ShaderNodeNewGeometry'); sep = N.new('ShaderNodeSeparateXYZ')
    base = N.new('ShaderNodeAttribute'); base.attribute_type = 'OBJECT'; base.attribute_name = 'v24_base'
    lit = N.new('ShaderNodeAttribute'); lit.attribute_type = 'OBJECT'; lit.attribute_name = 'v24_lit'
    sub = N.new('ShaderNodeMath'); sub.operation = 'SUBTRACT'
    div = N.new('ShaderNodeMath'); div.operation = 'DIVIDE'; div.inputs[1].default_value = fade
    inv = N.new('ShaderNodeMapRange'); inv.inputs['To Min'].default_value = 1; inv.inputs['To Max'].default_value = 0
    sq = N.new('ShaderNodeMath'); sq.operation = 'POWER'; sq.inputs[1].default_value = 2
    mul = N.new('ShaderNodeMath'); mul.operation = 'MULTIPLY'
    L.new(geo.outputs['Position'], sep.inputs[0]); L.new(sep.outputs['Z'], sub.inputs[0]); L.new(base.outputs['Fac'], sub.inputs[1])
    L.new(sub.outputs[0], div.inputs[0]); L.new(div.outputs[0], inv.inputs['Value']); L.new(inv.outputs['Result'], sq.inputs[0])
    L.new(sq.outputs[0], mul.inputs[0]); L.new(lit.outputs['Fac'], mul.inputs[1])
    stren = N.new('ShaderNodeMath'); stren.operation = 'MULTIPLY'; stren.inputs[1].default_value = arg('--recess', 3.0)
    L.new(mul.outputs[0], stren.inputs[0])
    pb.inputs['Emission Color'].default_value = (*tuple(float(x) for x in arg('--warm', '1.0,.78,.52', str).split(',')), 1)
    L.new(stren.outputs[0], pb.inputs['Emission Strength'])
    if '--lamps' in argv:
        # 楼脚地灯:亮灯楼朝镜头的两条鳍片之外(--lampout)、每 2.5 m 一个小暖色发光块(合成一个网格对象)
        import bmesh
        plan_by_id = {b['id']: b for b in json.loads((ROOT / 'city-14-studio-plan.json').read_text(encoding='utf-8'))['buildings']}
        lamp_bm = bmesh.new()
        lamp_mat = bpy.data.materials.new('v26 lamp'); lamp_mat.use_nodes = True
        ln = lamp_mat.node_tree.nodes; lo_ = ln.get('Material Output'); ln.remove(ln['Principled BSDF'])
        em = ln.new('ShaderNodeEmission'); em.inputs['Strength'].default_value = arg('--lampw', 60)
        em.inputs['Color'].default_value = (*tuple(float(x) for x in arg('--warm', '1.0,.78,.52', str).split(',')), 1)
        lamp_mat.node_tree.links.new(em.outputs[0], lo_.inputs['Surface'])
        LAMPS.update(bm=lamp_bm, mat=lamp_mat)
        for ob in scene.objects:
            if not ob.get('v24_lit'):
                continue
            b = plan_by_id.get(ob.name.split(' ')[0])
            if not b or 'footprint' not in b:
                continue
            fp = [Vector((p_[0], p_[1], 0)) for p_ in b['footprint']]
            cc = sum(fp, Vector()) / len(fp)
            LAMPS.setdefault('todo', []).append((b, fp, cc))
    print('V24_RECESS lit', sum(1 for o in scene.objects if o.get('v24_lit')), flush=True)

if LAMPS.get('todo'):
    import bmesh
    d_ = Vector(spec['target']) - Vector(spec['position'])
    fwd2 = Vector((d_.x, d_.y, 0)).normalized()
    lamp_bm, nl = LAMPS['bm'], 0
    for b, fp, cc in LAMPS['todo']:
        for i, a_ in enumerate(fp):
            e = fp[(i + 1) % len(fp)] - a_
            n = Vector((e.y, -e.x, 0)).normalized()
            if n.dot((a_ + e / 2) - cc) < 0:
                n = -n
            if n.dot(fwd2) > -.25:              # 只放朝镜头的立面
                continue
            k = max(1, int(e.length / 2.5))
            for j in range(k):
                g = a_ + e * ((j + .5) / k) + n * arg('--lampout', 1.0)
                bmesh.ops.create_cube(lamp_bm, size=arg('--lamps_size', .3), matrix=Matrix.Translation((g.x, g.y, b['z'] + .12)))
                nl += 1
    me = bpy.data.meshes.new('v26 lamps'); lamp_bm.to_mesh(me); me.materials.append(LAMPS['mat'])
    scene.collection.objects.link(bpy.data.objects.new('v26 lamps', me))
    print('V26_LAMPS', nl, flush=True)

world = scene.world
world.use_nodes = True
bg = world.node_tree.nodes['Background']
bg.inputs[0].default_value = (*tuple(float(x) for x in arg('--worldcol', '1,1,1', str).split(',')), 1)
bg.inputs[1].default_value = float(argv[argv.index('--world') + 1]) if '--world' in argv else .35

scene.render.engine = 'CYCLES'
scene.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'
prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
scene.cycles.samples = samples
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8
scene.cycles.diffuse_bounces = 4
scene.view_settings.view_transform = arg('--view', 'AgX', str)
scene.view_settings.look = arg('--look', 'None', str)
scene.view_settings.exposure = float(argv[argv.index('--exposure') + 1]) if '--exposure' in argv else 0
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.use_nodes = False
OUT.mkdir(exist_ok=True)
tag = argv[argv.index('--tag') + 1] if '--tag' in argv else 'E8'
scene.render.filepath = str(OUT / f'{tag}-cycles.png')
if '--saveas' in argv:
    # 另存为新副本(copy=True:当前会话仍指向源工程,源 .blend 不被覆盖)
    dst = ROOT / arg('--saveas', 'city-26-v26.blend', str)
    assert dst.name != 'city-13-smooth.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(dst), copy=True, compress=True)
    print('V26_SAVED', dst, flush=True)
if '--norender' not in argv:
    bpy.ops.render.render(write_still=True)
print('V24_PATHTRACE_DONE', scene.render.filepath, flush=True)
