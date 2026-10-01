"""Audit the saved editable master, not just the generator's intended plan."""
import bpy,bmesh,json,math,hashlib
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent
source=ROOT/'city-12-master.blend';plan=json.loads((ROOT/'city-12-master-plan.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(source));scene=bpy.context.scene
open_meshes=[];nonfinite=[];checked=set();building_mismatches=[];footprints=[]
def overlap(a,b):
    for poly in [a,b]:
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)];axis=(q[1]-p[1],p[0]-q[0]);aa=[x*axis[0]+y*axis[1] for x,y in a];bb=[x*axis[0]+y*axis[1] for x,y in b]
            if max(aa)<=min(bb)+1e-5 or max(bb)<=min(aa)+1e-5:return False
    return True
for ob in scene.objects:
    if ob.type!='MESH':continue
    if ob.data.name not in checked:
        checked.add(ob.data.name);bm=bmesh.new();bm.from_mesh(ob.data)
        boundary=sum(e.is_boundary for e in bm.edges);wire=sum(e.is_wire for e in bm.edges);bm.free()
        if boundary or wire:open_meshes.append(dict(object=ob.name,boundary=boundary,wire=wire))
        if any(not all(math.isfinite(x) for x in v.co) for v in ob.data.vertices):nonfinite.append(ob.name)
    if ob.get('id'):
        b=next(b for b in plan['buildings'] if b['id']==ob['id'])
        # First closed solid is the foundation; inspect its actual transformed base.
        pp=[ob.matrix_world@ob.data.vertices[i].co for i in range(4)]
        footprints.append((ob.name,[(p.x,p.y) for p in pp]))
        bound=[ob.matrix_world@Vector(p) for p in ob.bound_box]
        if max(p.z for p in bound)<b['z']+b['h']-.05:building_mismatches.append(ob.name)
def actual_top_triangles(name):
    ob=bpy.data.objects[name];ob.data.calc_loop_triangles();out=[]
    for face in ob.data.loop_triangles:
        if face.normal.z<.3:continue
        pts=[ob.matrix_world@ob.data.vertices[i].co for i in face.vertices];out.append([(p.x,p.y) for p in pts])
    return out
water=actual_top_triangles('12 Continuous river');roads=actual_top_triangles('12 Connected road network')
water_hits=[name for name,poly in footprints if any(overlap(poly,w) for w in water)]
road_hits=[name for name,poly in footprints if any(overlap(poly,r) for r in roads)]
collisions=[[name,name2] for i,(name,a) in enumerate(footprints) for name2,b in footprints[i+1:] if overlap(a,b)]
report=dict(status='PASS',buildings=len(footprints),landmarks=sum(b['landmark'] for b in plan['buildings']),trees=len(plan['trees']),
    unique_meshes_checked=len(checked),unclosed_meshes=open_meshes,nonfinite_meshes=nonfinite,building_height_mismatches=building_mismatches,
    actual_water_intersections=water_hits,actual_road_intersections=road_hits,actual_building_intersections=collisions,
    cameras=sorted(o.name for o in scene.objects if o.type=='CAMERA'),camera_animation=any(o.animation_data for o in scene.objects if o.type=='CAMERA'),
    image_texture_nodes=sum(n.type=='TEX_IMAGE' for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes),
    emissive_materials=[m.name for m in bpy.data.materials if m.use_nodes and (p:=m.node_tree.nodes.get('Principled BSDF')) and p.inputs['Emission Strength'].default_value>0],
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    boundary='Geometry integrity checks do not prove exact reference reconstruction or owner acceptance')
if open_meshes or nonfinite or building_mismatches or water_hits or road_hits or collisions or report['camera_animation']:report['status']='FAIL'
(ROOT/'city-12-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('MASTER_AUDIT',json.dumps(report,ensure_ascii=True),flush=True)
if report['status']!='PASS':raise RuntimeError('Master model geometry audit failed')
