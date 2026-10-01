# 模型体检:找"细黑线"的几何来源。只读,不修改源工程。
# 查四类:①开放边/裂缝 ②非流形边 ③退化面(面积≈0) ④细长面片(高长宽比) ⑤近共面重叠面
# 用法:blender -b --python audit_mesh.py -- <blend>
import bpy, sys, bmesh
from collections import defaultdict

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
src = argv[0]
bpy.ops.wm.open_mainfile(filepath=src)

def axis_key(n):
    ax = max(range(3), key=lambda i: abs(n[i]))
    if abs(n[ax]) < 0.85:
        return None
    return (ax, 1 if n[ax] > 0 else -1)

objs = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('B')]
print(f'AUDIT buildings={len(objs)}')

tot = defaultdict(int)
worst = []
for o in objs:
    bm = bmesh.new(); bm.from_mesh(o.data)
    bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    nonman = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    degen = sum(1 for f in bm.faces if f.calc_area() < 1e-5)
    # 细长面:最长边 / sqrt(面积) 很大 ⇒ 视觉上就是一条线
    sliver = 0
    for f in bm.faces:
        ls = [e.calc_length() for e in f.edges]
        if not ls: continue
        a = f.calc_area()
        if a > 1e-9 and max(ls) / (a ** 0.5) > 25:
            sliver += 1
    # 近共面重叠:同朝向、同平面、中心距离很近的不同面
    planes = defaultdict(list)
    for f in bm.faces:
        k = axis_key(f.normal)
        if k is None: continue
        planes[(k, round(f.calc_center_median()[k[0]] * k[1], 2))].append(f.calc_center_median())
    coplanar = 0
    for key, pts in planes.items():
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                if (pts[i] - pts[j]).length < 0.15:
                    coplanar += 1
    tot['boundary'] += boundary; tot['nonmanifold'] += nonman
    tot['degenerate'] += degen; tot['sliver'] += sliver; tot['coplanar'] += coplanar
    if boundary or degen or coplanar:
        worst.append((boundary + degen * 3 + coplanar, o.name, boundary, nonman, degen, sliver, coplanar))
    bm.free()

print(f'TOTAL boundary_edges(裂缝)={tot["boundary"]}  nonmanifold={tot["nonmanifold"]}  '
      f'degenerate_faces(退化面)={tot["degenerate"]}  sliver_faces(细长面)={tot["sliver"]}  '
      f'coplanar_overlap_pairs(近共面重叠)={tot["coplanar"]}')
worst.sort(reverse=True)
print('TOP 12 问题楼栋: score | name | boundary | nonman | degen | sliver | coplanar')
for w in worst[:12]:
    print('   ', w)
