# 体块化:把每栋楼"同一朝向"的立面临近平面归簇,推到该簇最外侧平面。
# 消掉竖向肋、凹窗与倒角,保留真正的退台(退台间距远大于簇容差)。
# 只在 B### 建筑对象上操作,地形/道路/桥/树完全不动。不保存源工程,只导出新 GLB。
# 用法:blender -b --python massing.py -- <src.blend> <out.glb> <tol>
import bpy, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
src, out = argv[0], argv[1]
TOL = float(argv[2]) if len(argv) > 2 else 1.5

bpy.ops.wm.open_mainfile(filepath=src)
print(f'MASSING tol={TOL}')

def axis_normal(p):
    n = p.normal
    ax = max(range(3), key=lambda i: abs(n[i]))
    if abs(n[ax]) < 0.85:
        return None
    return (ax, 1 if n[ax] > 0 else -1)

def cluster(vals, tol):
    out_ = []
    for v in sorted(vals):
        if out_ and v - out_[-1][-1] <= tol:
            out_[-1].append(v)
        else:
            out_.append([v])
    return out_

buildings = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('B')]
print(f'BUILDINGS={len(buildings)}')

tot_faces_before = tot_faces_after = 0
moved_total = 0
summary = []
for o in buildings:
    me = o.data
    # 建筑对象带变换缩放:先在局部空间做,法线也是局部的,方向一致
    before = len(me.polygons)
    verts_moved = 0
    for axis in range(3):
        for sign in (1, -1):
            faces = [p for p in me.polygons if axis_normal(p) == (axis, sign)]
            if not faces:
                continue
            def outer(p):
                cs = [me.vertices[i].co[axis] for i in p.vertices]
                return max(cs) if sign > 0 else min(cs)
            vals = sorted({round(outer(p), 4) for p in faces})
            cl = cluster(vals, TOL)
            tmap = {}
            for c in cl:
                t = c[-1] if sign > 0 else c[0]
                for v in c:
                    tmap[v] = t
            vids = {i for p in faces for i in p.vertices}
            for i in vids:
                co = me.vertices[i].co[axis]
                key = round(co, 4)
                t = tmap.get(key)
                if t is None:
                    for c in cl:
                        if c[0] - 1e-3 <= key <= c[-1] + 1e-3:
                            t = c[-1] if sign > 0 else c[0]
                            break
                if t is not None and abs(t - co) > 1e-5:
                    me.vertices[i].co[axis] = t
                    verts_moved += 1
    # 归并重合顶点,去掉因推平产生的退化面
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=0.02)
    bpy.ops.mesh.dissolve_degenerate(threshold=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    o.select_set(False)
    me = o.data
    me.update()
    after = len(me.polygons)
    tot_faces_before += before
    tot_faces_after += after
    moved_total += verts_moved
    if before != after:
        summary.append((o.name, before, after))

print(f'FACES before={tot_faces_before} after={tot_faces_after}  ({tot_faces_after/max(1,tot_faces_before)*100:.1f}%)')
print(f'VERTS moved={moved_total}  objects changed={len(summary)}')
for n, b, a in summary[:8]:
    print(f'   {n}  {b} -> {a}')

kw = dict(filepath=out, export_format='GLB', export_apply=True, export_yup=True)
try:
    bpy.ops.export_scene.gltf(**kw, export_draco_mesh_compression_enable=True,
                              export_draco_mesh_compression_level=6,
                              export_draco_position_quantization=14,
                              export_draco_normal_quantization=10)
except TypeError as e:
    print(f'DRACO 参数不被支持({e}),退回未压缩导出')
    bpy.ops.export_scene.gltf(**kw)
print(f'EXPORTED {out}')
