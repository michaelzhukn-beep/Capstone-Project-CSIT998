"""Local foreground repair of the saved lake model. No city regeneration."""
import bpy, bmesh, json, hashlib, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from layout_terrain import Terrain
source = ROOT / 'city-13-lake.blend'
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
plan = json.loads((ROOT / 'city-13-shore-plan.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene
quay = bpy.data.objects['13 Closed quay walls']
ground = Terrain(plan['water_contour'])

def stable_scene():
    result = {}
    for ob in scene.objects:
        if ob.type != 'MESH' or ob == quay or ob.name == '13 Continuous foreground slope': continue
        h = hashlib.sha256()
        for row in ob.matrix_world: h.update(struct.pack('<4d', *row))
        for v in ob.data.vertices: h.update(struct.pack('<3f', *v.co))
        for face in ob.data.polygons:
            h.update(struct.pack('<' + 'I' * (len(face.vertices)+1), face.material_index, *face.vertices))
        result[ob.name] = h.hexdigest()
    return result

unchanged = stable_scene()
cameras_before = {o.name: ([list(r) for r in o.matrix_world], o.data.ortho_scale) for o in scene.objects if o.type == 'CAMERA'}
materials = list(quay.data.materials)

def closed_mesh(name, vertices, faces, smooth_top=False, top_count=0):
    me = bpy.data.meshes.new(name); me.from_pydata(vertices, [], faces)
    for m in materials: me.materials.append(m)
    for p in me.polygons:
        p.material_index = 1
        p.use_smooth = smooth_top and p.index < top_count
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.0001)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bad = [e for e in bm.edges if len(e.link_faces) != 2]
    assert not bad, f'{name}: {len(bad)} open/non-manifold edges'
    bm.to_mesh(me); bm.free(); me.update()
    return me

a = plan['foreground_apron']; n = len(a['vertices'])
vertices = a['vertices'] + [[x,y,-7.5] for x,y,z in a['vertices']]
faces = [tuple(t) for t in a['triangles']]
faces += [tuple(i+n for i in reversed(t)) for t in a['triangles']]
faces += [(i,j,j+n,i+n) for i,j in a['boundary']]
mesh = closed_mesh('13 Rounded foreground continuation', vertices, faces, True, len(a['triangles']))
apron = bpy.data.objects.new('13 Continuous foreground slope', mesh)
bpy.data.collections['01 Terrain'].objects.link(apron)
apron['purpose'] = 'Closed ground extension beyond camera; smooth descent from original terrain boundary'

vertices, faces, ids = [], [], {}
def vertex(x,y,z):
    key = (round(x,6), round(y,6), round(z,6))
    if key not in ids: ids[key] = len(vertices); vertices.append(key)
    return ids[key]
def top(x,y): return max(1.25,ground(x,y)+.10)
shape = plan['surfaces']['banks']
for tri in shape['triangles']:
    faces.append(tuple(vertex(x,y,top(x,y)) for x,y in tri))
    faces.append(tuple(vertex(x,y,-.9) for x,y in reversed(tri)))
for p in shape['polygons']:
    for ring in [p['outer']] + p.get('holes', []):
        for (x,y),(xx,yy) in zip(ring,ring[1:]+ring[:1]):
            faces.append((vertex(x,y,top(x,y)),vertex(xx,yy,top(xx,yy)),vertex(xx,yy,-.9),vertex(x,y,-.9)))
quay.data = closed_mesh('13 Quays without foreground sliver', vertices, faces)
assert stable_scene() == unchanged, 'Unrelated geometry changed'
assert cameras_before == {o.name: ([list(r) for r in o.matrix_world], o.data.ortho_scale) for o in scene.objects if o.type == 'CAMERA'}
bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / 'city-13-shore.blend'))

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
bpy.ops.export_scene.gltf(filepath=str(ROOT / 'city-13-shore.glb'), export_format='GLB', use_selection=True,
    export_cameras=False, export_lights=False, export_animations=False, export_draco_mesh_compression_enable=True,
    export_draco_mesh_compression_level=6, export_draco_position_quantization=16, export_draco_normal_quantization=12)
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
report = {'source':'city-13-shore.blend', 'source_sha256':hashlib.sha256((ROOT/'city-13-shore.blend').read_bytes()).hexdigest(),
    'original_source_sha256':source_hash, 'unchanged_existing_meshes':len(unchanged), 'all_cameras_unchanged':True,
    'bytes':(ROOT/'city-13-shore.glb').stat().st_size, 'repair':plan['shore_repair']}
(ROOT/'city-13-shore-export.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('SHORE_EXPORT_PASS',json.dumps(report),flush=True)
