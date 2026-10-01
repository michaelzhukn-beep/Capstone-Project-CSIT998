"""Derive a lake extension from the saved model, without regenerating the city."""
import bpy, bmesh, json, hashlib, struct
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
source = ROOT / 'city-13-layout.blend'
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
plan = json.loads((ROOT / 'city-13-lake-plan.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene
water = bpy.data.objects['13 Continuous river']

def stable_scene():
    """Fingerprint all geometry/transforms other than the deliberately edited water."""
    result = {}
    for ob in scene.objects:
        if ob.type != 'MESH' or ob == water:
            continue
        h = hashlib.sha256()
        for row in ob.matrix_world:
            h.update(struct.pack('<4d', *row))
        for v in ob.data.vertices:
            h.update(struct.pack('<3f', *v.co))
        for face in ob.data.polygons:
            h.update(struct.pack('<' + 'I' * (len(face.vertices) + 1), face.material_index, *face.vertices))
        result[ob.name] = h.hexdigest()
    return result

unchanged = stable_scene()
vertices, faces, indices = [], [], {}
def vertex(x, y, z):
    key = (round(x, 6), round(y, 6), z)
    if key not in indices:
        indices[key] = len(vertices)
        vertices.append(key)
    return indices[key]
shape = plan['surfaces']['water']
for tri in shape['triangles']:
    faces.append(tuple(vertex(x, y, 0) for x, y in tri))
    faces.append(tuple(vertex(x, y, -.85) for x, y in reversed(tri)))
for poly in shape['polygons']:
    for ring in [poly['outer']] + poly.get('holes', []):
        for p, q in zip(ring, ring[1:] + ring[:1]):
            faces.append((vertex(*p, 0), vertex(*q, 0), vertex(*q, -.85), vertex(*p, -.85)))
mesh = bpy.data.meshes.new('13 Continuous extended lake')
mesh.from_pydata(vertices, [], faces)
for m in water.data.materials:
    mesh.materials.append(m)
for face in mesh.polygons:
    face.material_index = 4
bm = bmesh.new(); bm.from_mesh(mesh)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.001)
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
assert not any(e.is_boundary or e.is_wire or len(e.link_faces) > 2 for e in bm.edges), 'Water mesh must be closed'
bm.to_mesh(mesh); bm.free(); mesh.update(); water.data = mesh
assert stable_scene() == unchanged, 'A non-water mesh changed'

spec = plan['composition_camera']
cam_data = bpy.data.cameras.new('13 Selected composition')
cam = bpy.data.objects.new(cam_data.name, cam_data)
bpy.data.collections['08 Inspection cameras'].objects.link(cam)
cam.location = spec['position']
cam.rotation_euler = (Vector(spec['target']) - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam_data.type = 'ORTHO'; cam_data.clip_end = 2500
# Blender ortho_scale is horizontal; use the exact browser viewport ratio.
scene.render.resolution_x = 1883; scene.render.resolution_y = 1054
cam_data.ortho_scale = spec['scale'] * max(1, (1883 / 1054) / spec['reference_aspect']) / spec['zoom']
scene.camera = cam
bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / 'city-13-lake.blend'))

# Merge only the export copy; the saved source keeps individual buildings.
for name in ['01 Terrain', '02 Water and banks', '03 Streets and sidewalks', '04 Buildings', '05 Bridges', '06 Civic landscape', '07 Vegetation']:
    objects = [o for o in bpy.data.collections[name].objects if o.type == 'MESH']
    if not objects:
        continue
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objects:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.convert(target='MESH'); bpy.ops.object.join()
    bpy.context.object.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.select_all(action='DESELECT')
for ob in scene.objects:
    if ob.type == 'MESH': ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(ROOT / 'city-13-lake.glb'), export_format='GLB', use_selection=True,
    export_cameras=False, export_lights=False, export_animations=False, export_draco_mesh_compression_enable=True,
    export_draco_mesh_compression_level=6, export_draco_position_quantization=16, export_draco_normal_quantization=12)
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
report = {'source': 'city-13-lake.blend', 'source_sha256': hashlib.sha256((ROOT / 'city-13-lake.blend').read_bytes()).hexdigest(),
          'original_source_sha256': source_hash, 'unchanged_non_water_meshes': len(unchanged),
          'bytes': (ROOT / 'city-13-lake.glb').stat().st_size, 'camera': spec, 'water_extension': plan['lake_extension']}
(ROOT / 'city-13-lake-export.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('LAKE_EXPORT_PASS', json.dumps(report), flush=True)
