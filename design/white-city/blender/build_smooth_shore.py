"""Create a bounded derivative; only the foreground slope mesh may change."""
import bpy, bmesh, json, hashlib, struct, math
from pathlib import Path
ROOT = Path(__file__).resolve().parent
source = ROOT/'city-13-shore.blend'
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
plan = json.loads((ROOT/'city-13-smooth-plan.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene
apron = bpy.data.objects['13 Continuous foreground slope']

def fingerprints():
    result = {}
    for ob in scene.objects:
        if ob.type != 'MESH' or ob == apron: continue
        h = hashlib.sha256()
        for row in ob.matrix_world: h.update(struct.pack('<4d', *row))
        for v in ob.data.vertices: h.update(struct.pack('<3f', *v.co))
        for f in ob.data.polygons: h.update(struct.pack('<'+'I'*(len(f.vertices)+1), f.material_index, *f.vertices))
        result[ob.name] = h.hexdigest()
    return result
def camera_state():
    return {o.name:([list(r) for r in o.matrix_world], o.data.type, o.data.ortho_scale, o.data.lens)
            for o in scene.objects if o.type == 'CAMERA'}
def light_state():
    return {o.name:([list(r) for r in o.matrix_world], o.data.type, o.data.energy, list(o.data.color))
            for o in scene.objects if o.type == 'LIGHT'}
before, cameras, lights = fingerprints(), camera_state(), light_state()
a = plan['foreground_apron']; n = len(a['vertices'])
verts = a['vertices'] + [[x,y,-7.5] for x,y,z in a['vertices']]
faces = [tuple(t) for t in a['triangles']]
faces += [tuple(i+n for i in reversed(t)) for t in a['triangles']]
faces += [(i,j,j+n,i+n) for i,j in a['boundary']]
me = bpy.data.meshes.new('13 Smooth contour-conforming foreground')
me.from_pydata(verts, [], faces)
for m in apron.data.materials: me.materials.append(m)
for p in me.polygons:
    p.material_index = 1
    p.use_smooth = p.index < len(a['triangles'])
bm = bmesh.new(); bm.from_mesh(me)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.00001)
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
assert not [e for e in bm.edges if len(e.link_faces) != 2], 'Foreground must be a closed manifold'
bm.to_mesh(me); bm.free(); me.update()
apron.data = me
apron['purpose'] = 'Smooth shoreline to low foreground; explicit water contour; original city unchanged'
assert fingerprints() == before
assert camera_state() == cameras and light_state() == lights
bpy.context.view_layer.update()
target = ROOT/'city-13-smooth.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(target))
# Audit every saved mesh, not only the changed apron.
checked, invalid = set(), []
for ob in scene.objects:
    if ob.type != 'MESH' or ob.data.name in checked: continue
    checked.add(ob.data.name); bm = bmesh.new(); bm.from_mesh(ob.data)
    bad = sum(len(e.link_faces) != 2 for e in bm.edges); bm.free()
    if bad or any(not all(math.isfinite(v) for v in p.co) for p in ob.data.vertices): invalid.append(ob.name)
audit = dict(status='PASS' if not invalid else 'FAIL', source=target.name,
    unique_meshes_checked=len(checked), invalid_meshes=invalid, unchanged_existing_meshes=len(before),
    cameras_unchanged=True, lights_unchanged=True, buildings_unchanged=True, quays_unchanged=True,
    original_source_sha256=source_hash, source_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    waterline_vertices=len([v for v in a['vertices'] if v[2] == 0]),
    boundary='Geometry pass; rendered shoreline and user acceptance are separate checks')
(ROOT/'city-13-smooth-audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
assert not invalid
for name in ['01 Terrain','02 Water and banks','03 Streets and sidewalks','04 Buildings','05 Bridges','06 Civic landscape','07 Vegetation']:
    objects = [o for o in bpy.data.collections[name].objects if o.type == 'MESH']
    if not objects: continue
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objects: ob.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.convert(target='MESH'); bpy.ops.object.join()
    bpy.context.object.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.select_all(action='DESELECT')
for ob in scene.objects:
    if ob.type == 'MESH': ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(ROOT/'city-13-smooth.glb'), export_format='GLB', use_selection=True,
    export_cameras=False, export_lights=False, export_animations=False, export_draco_mesh_compression_enable=True,
    export_draco_mesh_compression_level=6, export_draco_position_quantization=20, export_draco_normal_quantization=14)
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
report = dict(audit, bytes=(ROOT/'city-13-smooth.glb').stat().st_size,
    glb_sha256=hashlib.sha256((ROOT/'city-13-smooth.glb').read_bytes()).hexdigest(), smoothing=plan['shore_smoothing'])
(ROOT/'city-13-smooth-export.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('SMOOTH_EXPORT_PASS', json.dumps(report), flush=True)
