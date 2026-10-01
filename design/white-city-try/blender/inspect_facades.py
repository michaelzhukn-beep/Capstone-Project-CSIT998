# 只读探明:建筑立面到底由什么构成,凹窗面板能否沿自身法线推平。
# 不保存、不导出,只打印。用法:blender -b --python inspect_facades.py -- <blend>
import bpy, sys, math
from collections import defaultdict
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
src = argv[0] if argv else 'design/white-city-try/blender/city-src.blend'
bpy.ops.wm.open_mainfile(filepath=src)

def q(v, step=0.02):
    return tuple(round(c / step) * step for c in v)

meshes = [o for o in bpy.data.objects if o.type == 'MESH']
print(f'OBJECTS total={len(meshes)}')
by_mat = defaultdict(list)
for o in meshes:
    for slot in o.material_slots:
        if slot.material:
            by_mat[slot.material.name].append(o)
for name, objs in sorted(by_mat.items(), key=lambda kv: -len(kv[1])):
    print(f'MAT  {name:38s} objects={len(objs):5d}  e.g. {objs[0].name}')

# 取一栋有代表性的楼:名字以 B### 开头,且带凹窗面板材质
panel_mat = next((n for n in by_mat if 'Recessed' in n), None)
body_mat = next((n for n in by_mat if 'White clay' in n), None)
print(f'PANEL_MAT={panel_mat}  BODY_MAT={body_mat}')

def sample_for(mat_name):
    for o in by_mat.get(mat_name, []):
        if o.name.startswith('B'):
            return o
    return by_mat.get(mat_name, [None])[0]

for label, mat_name in (('BODY', body_mat), ('PANEL', panel_mat)):
    o = sample_for(mat_name)
    if not o:
        print(f'{label}: 无')
        continue
    me = o.data
    me.calc_loop_triangles()
    normals = defaultdict(int)
    for p in me.polygons:
        normals[q(tuple(p.normal))] += 1
    top = sorted(normals.items(), key=lambda kv: -kv[1])[:14]
    print(f'\n{label} object={o.name} verts={len(me.vertices)} faces={len(me.polygons)} tris={len(me.loop_triangles)}')
    print(f'  distinct face-normal directions (quantised 0.02): {len(normals)}')
    for n, c in top:
        ax = '  '.join(f'{v:+.2f}' for v in n)
        print(f'    n=({ax})  faces={c}')
    # 每个法线方向上的平面偏移分布 —— 判断"同一个朝向的窗面是否共面"
    offs = defaultdict(list)
    for p in me.polygons:
        offs[q(tuple(p.normal))].append(p.center.dot(Vector(p.normal)))
    print('  planarity of the two largest normal groups (offset spread along normal):')
    for n, c in top[:2]:
        v = sorted(offs[n])
        print(f'    n={tuple(round(x,2) for x in n)} faces={c} offset min={v[0]:.2f} max={v[-1]:.2f} spread={v[-1]-v[0]:.2f}')

# 楼高/包围盒,确认单位尺度
o = sample_for(body_mat)
if o:
    ws = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = Vector((min(p.x for p in ws), min(p.y for p in ws), min(p.z for p in ws)))
    mx = Vector((max(p.x for p in ws), max(p.y for p in ws), max(p.z for p in ws)))
    print(f'\nSAMPLE building {o.name} world bbox min={tuple(round(v,2) for v in mn)} max={tuple(round(v,2) for v in mx)} dx={mx.x-mn.x:.2f} dy={mx.y-mn.y:.2f} dz={mx.z-mn.z:.2f}')
