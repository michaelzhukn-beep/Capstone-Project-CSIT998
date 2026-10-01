# 只读:按 polygon.material_index 分组,测出立面平面、凹窗深度、窗格间距。
# 用法:blender -b --python inspect2.py -- <blend>
import bpy, sys
from collections import defaultdict
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
src = argv[0]
bpy.ops.wm.open_mainfile(filepath=src)

meshes = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('B')]
print(f'BUILDING OBJECTS={len(meshes)}')

# 找体量最大的一栋当样本
def dz(o):
    ws = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return max(p.z for p in ws) - min(p.z for p in ws), ws

meshes.sort(key=lambda o: -dz(o)[0])
for o in meshes[:4]:
    h, ws = dz(o)
    mn = Vector((min(p.x for p in ws), min(p.y for p in ws), min(p.z for p in ws)))
    mx = Vector((max(p.x for p in ws), max(p.y for p in ws), max(p.z for p in ws)))
    print(f'  {o.name}  dx={mx.x-mn.x:.1f} dy={mx.y-mn.y:.1f} dz={h:.1f}  x[{mn.x:.1f},{mx.x:.1f}] y[{mn.y:.1f},{mx.y:.1f}]')

def axis_normal(p):
    n = p.normal
    ax = max(range(3), key=lambda i: abs(n[i]))
    if abs(n[ax]) < 0.85:
        return None
    s = 1 if n[ax] > 0 else -1
    return (ax, s)

for o in meshes[:2]:
    me = o.data
    mats = [s.material.name if s.material else '?' for s in o.material_slots]
    groups = defaultdict(list)
    offaxis = 0
    for p in me.polygons:
        groups[p.material_index].append(p)
        if axis_normal(p) is None:
            offaxis += 1
    print(f'\n=== {o.name}  faces={len(me.polygons)}  off-axis faces={offaxis} ({offaxis/len(me.polygons)*100:.1f}%) ===')
    for mi, polys in sorted(groups.items()):
        name = mats[mi] if mi < len(mats) else '?'
        dirs = defaultdict(int)
        for p in polys:
            a = axis_normal(p)
            dirs[a if a else 'off'] += 1
        print(f'  mat[{mi}] {name:32s} faces={len(polys):5d}  ' + '  '.join(f'{k}:{v}' for k, v in sorted(dirs.items(), key=lambda kv: str(kv[0]))))
    # 凹窗深度:取面板材质在那个朝向的平面偏移,与主体同朝向的平面偏移比较
    panel_mi = next((mi for mi, n in enumerate(mats) if 'Recessed' in n), None)
    body_mi = next((mi for mi, n in enumerate(mats) if 'White clay' in n), None)
    if panel_mi is None or body_mi is None:
        continue
    for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
        body_off = sorted({round(p.center[axis], 3) for p in groups[body_mi] if axis_normal(p) == (axis, sign)})
        panel_off = sorted({round(p.center[axis], 3) for p in groups[panel_mi] if axis_normal(p) == (axis, sign)})
        if not body_off or not panel_off:
            continue
        print(f'  face axis={axis} sign={sign:+d}: body planes={len(body_off)} {body_off[:6]}')
        print(f'                        panel planes={len(panel_off)} {panel_off[:6]}')
        # 面板深度 = 主体最外平面 - 面板平面(朝外为正)
        outer = max(body_off) if sign > 0 else min(body_off)
        depths = sorted({round((outer - v) * sign, 2) for v in panel_off})
        print(f'                        recess depth candidates={depths[:8]}')
