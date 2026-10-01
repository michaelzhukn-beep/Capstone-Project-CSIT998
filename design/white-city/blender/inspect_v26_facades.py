"""只读:统计前景低层楼朝镜头立面的几何构成(按材质、进深、标高)。不保存工程。

    blender -b --python design/white-city/blender/inspect_v26_facades.py
"""
import bpy, json, math, collections
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-13-smooth.blend'))
scene = bpy.context.scene
spec = json.loads((ROOT / 'city-14-locked-camera.json').read_text(encoding='utf-8'))
plan = json.loads((ROOT / 'city-14-studio-plan.json').read_text(encoding='utf-8'))
cam = next(o for o in scene.objects if o.type == 'CAMERA')
scene.camera = cam
cam.location = spec['position']
cam.rotation_euler = (Vector(spec['target']) - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam.data.type = 'ORTHO'; cam.data.ortho_scale = spec['captured_frustum_width'] / spec['zoom']
scene.render.resolution_x, scene.render.resolution_y = 1883, 1054
bpy.context.view_layer.update()
forward = (Vector(spec['target']) - Vector(spec['position'])).normalized()
v2 = Vector((forward.x, forward.y, 0)).normalized()

# 找建筑对象:包围盒中心落在 plan 建筑足迹中心附近
objs = [o for o in scene.objects if o.type == 'MESH']
def center(o):
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return sum(bb, Vector()) / 8, min(p.z for p in bb), max(p.z for p in bb)
cent = [(o, *center(o)) for o in objs]

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

report = []
for b in chosen:
    o = min(cent, key=lambda t: (t[1].x - b['x']) ** 2 + (t[1].y - b['y']) ** 2)[0]
    mw = o.matrix_world; n3 = mw.to_3x3()
    # 找最朝镜头的水平轴向
    axes = [Vector((1, 0, 0)), Vector((-1, 0, 0)), Vector((0, 1, 0)), Vector((0, -1, 0))]
    face_ax = max(axes, key=lambda a: -a.dot(v2))
    rows = collections.defaultdict(lambda: {'n': 0, 'area': 0.0, 'z0': 1e9, 'z1': -1e9, 'w': 0.0})
    for p in o.data.polygons:
        n = (n3 @ p.normal).normalized()
        if n.dot(face_ax) < .99:
            continue
        vs = [mw @ o.data.vertices[i].co for i in p.vertices]
        depth = round(sum(v.dot(face_ax) for v in vs) / len(vs), 2)
        mat = o.material_slots[p.material_index].name if o.material_slots else '-'
        z0, z1 = min(v.z for v in vs), max(v.z for v in vs)
        k = (mat, depth)
        r = rows[k]; r['n'] += 1; r['area'] += p.area; r['z0'] = min(r['z0'], z0); r['z1'] = max(r['z1'], z1)
    top = sorted(rows.items(), key=lambda kv: -kv[1]['area'])[:10]
    # 竖向剖面:沿立面中线,每 0.25 m 记录最外层面所属材质
    report.append({'plan_id': b.get('id'), 'object': o.name, 'h': b['h'], 'base_z': b['z'], 'axis': list(face_ax),
                   'polys': len(o.data.polygons),
                   'groups': [{'mat': k[0], 'depth': k[1], **{kk: round(vv, 2) for kk, vv in v.items()}} for k, v in top]})
out = ROOT.parent / 'renders-v24' / 'facade-scope-v26.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
print('V26_FACADES', out, flush=True)
