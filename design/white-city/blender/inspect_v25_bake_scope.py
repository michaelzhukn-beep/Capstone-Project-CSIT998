"""只读检查:为光照贴图烘焙估算范围。不保存工程。

    blender -b --python design/white-city/blender/inspect_v25_bake_scope.py
"""
import bpy, json, collections
from pathlib import Path
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-13-smooth.blend'))
scene = bpy.context.scene
spec = json.loads((ROOT / 'city-14-locked-camera.json').read_text(encoding='utf-8'))
cam = next(o for o in scene.objects if o.type == 'CAMERA')
cam.location = spec['position']
cam.rotation_euler = (Vector(spec['target']) - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam.data.type = 'ORTHO'
cam.data.ortho_scale = spec['captured_frustum_width'] / spec['zoom']
scene.render.resolution_x, scene.render.resolution_y = 1883, 1054
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()

groups = collections.defaultdict(lambda: {'objects': 0, 'tris': 0, 'area': 0.0, 'visible_area': 0.0, 'uv': 0, 'instanced': 0})
for ob in scene.objects:
    if ob.type != 'MESH':
        continue
    top = ob.users_collection[0].name if ob.users_collection else '-'
    g = groups[top]
    g['objects'] += 1
    me = ob.data
    g['uv'] += 1 if me.uv_layers else 0
    g['instanced'] += 1 if me.users > 1 else 0
    mw = ob.matrix_world
    for p in me.polygons:
        g['tris'] += len(p.vertices) - 2
        area = p.area * mw.to_scale().x * mw.to_scale().y  # 近似
        g['area'] += area
        c = mw @ p.center
        q = world_to_camera_view(scene, cam, c)
        n = (mw.to_3x3() @ p.normal).normalized()
        view = (Vector(spec['target']) - Vector(spec['position'])).normalized()
        if 0 <= q.x <= 1 and 0 <= q.y <= 1 and n.dot(view) < 0:
            g['visible_area'] += area
report = {'mesh_objects': sum(g['objects'] for g in groups.values()),
          'collections': {k: {kk: (round(vv) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sorted(groups.items())},
          'frustum_width': spec['captured_frustum_width'] / spec['zoom'],
          'units_per_pixel': spec['captured_frustum_width'] / spec['zoom'] / 1883}
out = ROOT.parent / 'renders-v24' / 'bake-scope.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
print('BAKE_SCOPE', json.dumps(report, ensure_ascii=False)[:3000], flush=True)
