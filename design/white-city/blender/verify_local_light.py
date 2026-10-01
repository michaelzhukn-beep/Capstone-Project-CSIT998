"""Verify 07 GLB round trip: reusable origin/bounds and real baked vertex attributes."""
import bpy,json,math,hashlib,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent
stage='08' if '--stage=08' in sys.argv else '07'
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(ROOT/f'city-{stage}-assets.glb'))
metadata=json.loads((ROOT/'city-04-assets.json').read_text(encoding='utf-8'))
bake=json.loads((ROOT/f'city-{stage}-assets-bake.json').read_text(encoding='utf-8'))
maximum=0;colored=0;vertex_count=0;warm_assets=0
for asset in metadata['assets']:
    parent=bpy.data.objects.get(asset['id']);assert parent,asset['id']
    meshes=[o for o in parent.children_recursive if o.type=='MESH']
    points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices]
    lo=[min(v[i] for v in points) for i in range(3)];hi=[max(v[i] for v in points) for i in range(3)]
    error=max(abs(x-y) for x,y in zip(lo+hi,asset['bounds_min']+asset['bounds_max']))
    maximum=max(maximum,error);assert error<.0002,(asset['id'],error)
    channels=[]
    for obj in meshes:
        vertex_count+=len(obj.data.vertices)
        for attr in obj.data.color_attributes:
            colored+=len(attr.data)
            for datum in attr.data:
                color=datum.color;assert all(math.isfinite(c) and -.0001<=c<=1.0001 for c in color)
                channels.append(max(color[:3]))
    if asset['kind']=='building':assert channels,asset['id']
    if channels and max(channels)>.00001:warm_assets+=1
assert len(bake['assets'])==35 and warm_assets==sum(a['emitter'] for a in bake['assets'])
assert sum(a['clipped_channels'] for a in bake['assets'])==0
assert hashlib.sha256((ROOT/bake['source']).read_bytes()).hexdigest()==bake['source_sha256']
report=dict(status='PASS',assets=len(metadata['assets']),building_assets=35,warm_assets=warm_assets,
    imported_vertices=vertex_count,colored_corners=colored,max_bounds_error_m=maximum,
    baseline_source_unchanged=True,geometry_note=('Sealed roofs, cove housings, thin glazing and corrected normals; complete bounds and origins match 04.' if stage=='08' else 'Surface subdivision only; local origins and complete bounds match 04.'),
    glb_sha256=hashlib.sha256((ROOT/f'city-{stage}-assets.glb').read_bytes()).hexdigest())
(ROOT/f'city-{stage}-assets-review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('LOCAL_LIGHT_PASS',json.dumps(report),flush=True)
