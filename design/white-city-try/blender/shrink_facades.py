# 弱化立面分格深度(不是推平!):把每个朝向的进深向该朝向最外平面压缩 SHRINK 倍。
# 分格几何仍在(精细感保留),但每条缝吃到的明暗差按比例变小 —— 白模里就不会再读成"黑线"。
# 与 massing.py 的区别:massing 把所有平面推到同一平面(分格消失);这里只压缩深度。
# 只在 B### 建筑对象上操作;源工程只读,不保存,只导出到本目录。
# 用法:blender -b --python shrink_facades.py -- <src.blend> <out.glb> <shrink> <protect>
import bpy, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
src, out = argv[0], argv[1]
SHRINK = float(argv[2]) if len(argv) > 2 else 0.30      # 保留多少进深(0=全推平, 1=原样)
PROTECT = float(argv[3]) if len(argv) > 3 else 1.6      # 大于此深度的算真实退台,不动

bpy.ops.wm.open_mainfile(filepath=src)
print(f'SHRINK facades: shrink={SHRINK} protect={PROTECT}')

def axis_normal(p):
    n = p.normal
    ax = max(range(3), key=lambda i: abs(n[i]))
    if abs(n[ax]) < 0.85:
        return None
    return (ax, 1 if n[ax] > 0 else -1)

buildings = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('B')]
moved = 0
for o in buildings:
    me = o.data
    for axis in range(3):
        for sign in (1, -1):
            faces = [p for p in me.polygons if axis_normal(p) == (axis, sign)]
            if not faces:
                continue
            def outer(p):
                cs = [me.vertices[i].co[axis] for i in p.vertices]
                return max(cs) if sign > 0 else min(cs)
            vals = sorted({round(outer(p), 4) for p in faces})
            top = vals[-1] if sign > 0 else vals[0]     # 最外平面
            # 逐平面:深度 d = 到最外平面的距离;超过 PROTECT 的视为真实退台,保持不动
            remap = {}
            for v in vals:
                d = (top - v) * sign
                if d <= 1e-6:
                    remap[v] = top
                elif d > PROTECT:
                    remap[v] = v
                else:
                    remap[v] = top - d * SHRINK * sign
            vids = {i for p in faces for i in p.vertices}
            for i in vids:
                co = me.vertices[i].co[axis]
                key = round(co, 4)
                t = remap.get(key)
                if t is None:
                    for v, tv in remap.items():
                        if abs(v - key) < 1e-3:
                            t = tv
                            break
                if t is not None and abs(t - co) > 1e-6:
                    me.vertices[i].co[axis] = t
                    moved += 1
    me.update()

print(f'SHRINK verts moved={moved}')

kw = dict(filepath=out, export_format='GLB', export_apply=True, export_yup=True)
DRACO = dict(export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
             export_draco_position_quantization=14, export_draco_normal_quantization=10)
for vc_kw in ({'export_vertex_color': 'ACTIVE', 'export_all_vertex_colors': True}, {'export_all_vertex_colors': True}, {}):
    try:
        bpy.ops.export_scene.gltf(**kw, **DRACO, **vc_kw)
        print(f'EXPORTED {out}')
        break
    except TypeError:
        continue
