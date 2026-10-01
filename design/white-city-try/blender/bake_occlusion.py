# 几何可见性烘焙:对每个建筑面,在其朝向的余弦半球内发射射线,统计被邻居遮挡的比例,
# 把结果写进 CORNER 域的顶点色(逐面常量色)。这不是 Cycles 的完整 GI,但它是**真实的射线遮挡**,
# 而且正好补上实时光栅化缺的那一层:每栋楼、每个朝向各自不同的环境光量。
# 源工程只读打开,不保存;只导出到本目录。
# 用法:blender -b --python bake_occlusion.py -- <src.blend> <out.glb> <rays> <radius>
import bpy, sys, math, random
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
src, out = argv[0], argv[1]
RAYS = int(argv[2]) if len(argv) > 2 else 16
RADIUS = float(argv[3]) if len(argv) > 3 else 140.0
GAIN = float(argv[4]) if len(argv) > 4 else 2.5      # 遮挡 → 变暗的斜率
FLOOR = float(argv[5]) if len(argv) > 5 else 0.50    # 最暗留多少,不要压死
STANDOFF = float(argv[6]) if len(argv) > 6 else 1.2  # 射线起点离面距离(必须大于倒角与凹窗尺度)
SELF_EPS = 0.6                                       # 比这更近的命中算自交,不计
random.seed(20260917)

bpy.ops.wm.open_mainfile(filepath=src)
dg = bpy.context.evaluated_depsgraph_get()
scene = bpy.context.scene

buildings = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('B')]
print(f'OCCLUSION bake: buildings={len(buildings)} rays={RAYS} radius={RADIUS}')

# 余弦加权半球采样方向(局部: +Z 为法线)
def hemi_dirs(n):
    out = []
    for _ in range(n):
        u1, u2 = random.random(), random.random()
        r = math.sqrt(u1); phi = 2 * math.pi * u2
        out.append(Vector((r * math.cos(phi), r * math.sin(phi), math.sqrt(max(0.0, 1 - u1)))))
    return out

def basis(n):
    n = n.normalized()
    a = Vector((0, 0, 1)) if abs(n.z) < 0.9 else Vector((1, 0, 0))
    t = n.cross(a).normalized()
    b = n.cross(t)
    return t, b

def occlusion(origin, normal):
    t, b = basis(normal)
    hits = 0
    for d in hemi_dirs(RAYS):
        w = (t * d.x + b * d.y + normal * d.z).normalized()
        # 起点必须离面足够远:本模型的倒角只有 0.035~0.08、凹窗 0.55,
        # 起点太近会立刻与自己的细部几何自交(实测那样会让 88% 的射线"命中")。
        o = origin + normal * STANDOFF + w * STANDOFF
        ok, loc, nor, idx, obj, mat = scene.ray_cast(dg, o, w, distance=RADIUS)
        if ok and (loc - o).length > SELF_EPS:
            hits += 1
    return hits / RAYS

total_faces = 0
all_occ = []
all_v = []
for o in buildings:
    me = o.data
    mw = o.matrix_world
    nm = mw.inverted_safe().transposed().to_3x3()
    # 关键:必须显式建 CORNER 域属性并设为活动色。
    # 该模型自带旧的顶点色属性(POINT 域);取 color_attributes[0] 再用 loop 索引写会全部写飞,
    # 导出的 COLOR_0 就还是默认的纯白 —— 实测过,renderer 里 min=max=1。
    ca = me.color_attributes.get('BakedAO')
    if ca is None or ca.domain != 'CORNER':
        ca = me.color_attributes.new(name='BakedAO', type='BYTE_COLOR', domain='CORNER')
    try:
        me.color_attributes.active_color_index = list(me.color_attributes).index(ca)
    except Exception as e:
        print(f'  active_color 设置失败 {o.name}: {e}')
    for p in me.polygons:
        n = (nm @ p.normal).normalized()
        origin = mw @ p.center
        occ = occlusion(origin, n)
        all_occ.append(occ)
        v = min(1.0, max(FLOOR, 1.0 - occ * GAIN))
        all_v.append(v)
        for li in p.loop_indices:
            ca.data[li].color = (v, v, v, 1.0)
    total_faces += len(me.polygons)

def pcts(xs, qs=(0.05, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)):
    xs = sorted(xs)
    return ' '.join(f'p{int(q*100)}={xs[min(len(xs)-1, int(q*len(xs)))]:.3f}' for q in qs)

print(f'BAKED faces={total_faces}  GAIN={GAIN} FLOOR={FLOOR}')
print(f'OCC  {pcts(all_occ)}  mean={sum(all_occ)/len(all_occ):.3f}')
print(f'VAL  {pcts(all_v)}  mean={sum(all_v)/len(all_v):.3f}')

kw = dict(filepath=out, export_format='GLB', export_apply=True, export_yup=True)
# 顶点色必须显式要求导出"活动颜色":默认的 'MATERIAL' 模式只导出材质里真正被
# Color Attribute 节点引用过的顶点色,而本项目的材质都没引用 ⇒ 导出的是默认白(实测 min=max=1)。
DRACO = dict(export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
             export_draco_position_quantization=14, export_draco_normal_quantization=10,
             export_draco_color_quantization=10)
done = False
for vc_kw in ({'export_vertex_color': 'ACTIVE', 'export_all_vertex_colors': True},
              {'export_vertex_color': 'ACTIVE'},
              {'export_all_vertex_colors': True},
              {}):
    try:
        bpy.ops.export_scene.gltf(**kw, **DRACO, **vc_kw)
        print(f'EXPORTED {out}  vc_kw={vc_kw}')
        done = True
        break
    except TypeError as e:
        print(f'  vc_kw={vc_kw} 不被支持: {e}')
if not done:
    bpy.ops.export_scene.gltf(**kw)
    print(f'EXPORTED {out} (无 Draco / 无顶点色参数)')
