# 彻底修共面重叠(z-fighting):检出同朝向、同平面、且真正重叠的面片对,
# 把其中**面积较小**的那一层沿法线向内推 EPS,让它退到另一层后面。
# 不删除任何面 ⇒ 没有开洞风险;被推的那层原本就被盖住,视觉上不可见。
# 只在"该顶点只被这一层用到"时移动顶点,避免撕开网格;撕不动的照实报数。
# 源工程只读,不保存;只导出到本目录。
# 用法:blender -b --python fix_coplanar.py -- <src.blend> <out.glb> <eps>
import bpy, sys, bmesh
from collections import defaultdict
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
src, out = argv[0], argv[1]
EPS = float(argv[2]) if len(argv) > 2 else 0.05
PLANE_TOL = 0.02      # 同平面判定
CENTRE_TOL = 0.15     # 面心距离
AREA_RATIO = 0.5      # AABB 重叠超过小面的这个比例才算真重叠

bpy.ops.wm.open_mainfile(filepath=src)

def axis_key(n):
    ax = max(range(3), key=lambda i: abs(n[i]))
    if abs(n[ax]) < 0.85:
        return None
    return (ax, 1 if n[ax] > 0 else -1)

def aabb2d(face, ax):
    u, v = [i for i in range(3) if i != ax]
    pts = [p.co for p in face.verts]
    return (min(p[u] for p in pts), min(p[v] for p in pts),
            max(p[u] for p in pts), max(p[v] for p in pts))

def overlap_ratio(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    small = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
    return inter / small if small > 1e-9 else 0.0

objs = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('B')]
print(f'FIX coplanar: buildings={len(objs)} eps={EPS}')
pairs_total = 0
pushed_total = 0
stuck_total = 0
deleted_total = 0
matpair = defaultdict(int)

for o in objs:
    me = o.data
    bm = bmesh.new(); bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    mats = [s.material.name if s.material else '?' for s in o.material_slots]
    groups = defaultdict(list)
    for f in bm.faces:
        k = axis_key(f.normal)
        if k is None:
            continue
        groups[(k, round(f.calc_center_median()[k[0]] * k[1], 2))].append(f)
    victims = set()
    for key, fs in groups.items():
        ax = key[0][0]      # key = ((轴, 符号), 平面偏移)
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                a, b = fs[i], fs[j]
                if (a.calc_center_median() - b.calc_center_median()).length > CENTRE_TOL:
                    continue
                if overlap_ratio(aabb2d(a, ax), aabb2d(b, ax)) < AREA_RATIO:
                    continue
                pairs_total += 1
                small, big = (a, b) if a.calc_area() <= b.calc_area() else (b, a)
                ma = mats[small.material_index] if small.material_index < len(mats) else '?'
                mb = mats[big.material_index] if big.material_index < len(mats) else '?'
                matpair[f'{ma}  ⟂(同面)  {mb}'] += 1
                victims.add(small.index)
    if not victims:
        bm.free(); continue
    # 情况一:两面的**顶点集合完全相同** ⇒ 字面意义的重复面片,直接删一个。
    # 另一份仍在,不可能开洞;材质相同才删,避免改变外观。
    dupes = set()
    for key, fs in groups.items():
        ax = key[0][0]
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                a, b = fs[i], fs[j]
                va, vb = {v.index for v in a.verts}, {v.index for v in b.verts}
                if va != vb:
                    continue
                if a.material_index != b.material_index:
                    continue
                if (a.calc_center_median() - b.calc_center_median()).length > CENTRE_TOL:
                    continue
                if overlap_ratio(aabb2d(a, ax), aabb2d(b, ax)) < AREA_RATIO:
                    continue
                dupes.add(b)
    if dupes:
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in dupes], context='FACES_ONLY')
        deleted_total += len(dupes)
        bm.faces.ensure_lookup_table()
        victims -= dupes
    if not victims:
        bm.to_mesh(me); bm.free(); me.update(); continue
    # 情况二:顶点集合不同但共面重叠 ⇒ 只能把面积小的一层向内推,且仅在该层独占顶点时
    move_ids = set()
    for idx in victims:
        f = bm.faces[idx]
        for v in f.verts:
            if all(lf.index in victims for lf in v.link_faces):
                move_ids.add(v.index)
    for idx in victims:
        f = bm.faces[idx]
        n = f.normal.copy()
        for v in f.verts:
            if v.index in move_ids:
                v.co -= n * EPS
                pushed_total += 1
    stuck = len(victims) - len({idx for idx in victims if all(v.index in move_ids for v in bm.faces[idx].verts)})
    stuck_total += max(0, stuck)
    bm.to_mesh(me); bm.free(); me.update()

print(f'PAIRS(真重叠)={pairs_total}  重复面已删除={deleted_total}  VERTS pushed={pushed_total}  未能移动的面={stuck_total}')
print('材料组合 TOP:')
for k, v in sorted(matpair.items(), key=lambda kv: -kv[1])[:6]:
    print(f'   {v:5d}  {k}')

kw = dict(filepath=out, export_format='GLB', export_apply=True, export_yup=True)
DRACO = dict(export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
             export_draco_position_quantization=14, export_draco_normal_quantization=10)
for vc_kw in ({'export_vertex_color': 'ACTIVE', 'export_all_vertex_colors': True}, {}):
    try:
        bpy.ops.export_scene.gltf(**kw, **DRACO, **vc_kw)
        print(f'EXPORTED {out}')
        break
    except TypeError:
        continue
