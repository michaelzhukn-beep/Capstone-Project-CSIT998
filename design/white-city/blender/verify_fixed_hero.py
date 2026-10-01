"""Independent checks of actual scene footprints and the fixed-camera boundary."""
import bpy,bmesh,json,math,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
aligned='--aligned' in sys.argv
stem='city-11-aligned' if aligned else ('city-10-studio' if '--studio' in sys.argv else 'city-09-fixed')
bpy.ops.wm.open_mainfile(filepath=str(ROOT/(stem+'.blend')))
scene=bpy.context.scene
def hull(points):
    p=sorted(set(points))
    def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    a=[];b=[]
    for v in p:
        while len(a)>=2 and cross(a[-2],a[-1],v)<=0:a.pop()
        a.append(v)
    for v in reversed(p):
        while len(b)>=2 and cross(b[-2],b[-1],v)<=0:b.pop()
        b.append(v)
    return a[:-1]+b[:-1]
def overlap(a,b):
    for poly in [a,b]:
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)];axis=(q[1]-p[1],p[0]-q[0])
            aa=[x*axis[0]+y*axis[1] for x,y in a];bb=[x*axis[0]+y*axis[1] for x,y in b]
            if max(aa)<=min(bb)+1e-5 or max(bb)<=min(aa)+1e-5:return False
    return True
footprints=[]
for o in scene.objects:
    if o.type=='MESH' and o.name.endswith(' plinth'):
        pts=[o.matrix_world@v.co for v in o.data.vertices]
        footprints.append((o.name,hull([(float(p.x),float(p.y)) for p in pts])))
water=next(o for o in scene.objects if o.name.endswith('Curved river surface'));wpolys=[]
for face in water.data.polygons:
    points=[water.matrix_world@water.data.vertices[i].co for i in face.vertices]
    wpolys.append([(p.x,p.y) for p in points])
wet=[name for name,foot in footprints if any(overlap(foot,w) for w in wpolys)]
collisions=[]
for i,(name,a) in enumerate(footprints):
    for name2,b in footprints[i+1:]:
        if overlap(a,b):collisions.append([name,name2])
emitters=[o for o in scene.objects if o.get('emitter')]
leaks=[o.name for o in emitters if o.visible_camera or o.visible_glossy or o.visible_transmission]
road_conflicts=[];road_faces=[];road_heights=[];bridge_ends_in_water=[];bridge_ends_off_road=[];open_solids=[];road_folds=[];downward_surfaces=[]
if aligned:
    plan=json.loads((ROOT/(stem+'-plan.json')).read_text(encoding='utf-8'))
    for r in plan['roads']:
        ob=bpy.data.objects[r['name']]
        local=[]
        for face in ob.data.polygons:
            p=[ob.matrix_world@ob.data.vertices[i].co for i in face.vertices]
            poly=[(v.x,v.y) for v in p];local.append(poly)
            road_faces.append((ob.name,poly))
            road_heights.append(sum(v.z for v in p)/len(p))
        for i,poly in enumerate(local):
            for j in range(i+2,len(local)):
                if overlap(hull(poly),hull(local[j])):road_folds.append([ob.name,i,j])
    for ob in scene.objects:
        if ob.type=='MESH' and ob.name in [r['name'] for r in plan['roads']]+['11 Distant white rolling landforms','11 Curved river surface']:
            if any(f.area>1e-5 and f.normal.z<0 for f in ob.data.polygons):downward_surfaces.append(ob.name)
    for name,foot in footprints:
        for road_name,poly in road_faces:
            if overlap(foot,poly):road_conflicts.append([name,road_name]);break
    for bridge in plan['bridges']:
        for x,y,z in bridge['endpoints']:
            p=[(x-.1,y-.1),(x+.1,y-.1),(x+.1,y+.1),(x-.1,y+.1)]
            if any(overlap(p,w) for w in wpolys):bridge_ends_in_water.append(bridge['name'])
            connected=[i for i,(_,poly) in enumerate(road_faces) if overlap(p,poly)]
            if not connected or min(abs(z-road_heights[i]) for i in connected)>.12:bridge_ends_off_road.append(bridge['name'])
    for ob in scene.objects:
        if ob.type=='MESH' and (ob.name.startswith('11 Closed') or ob.name.endswith(' deck') or ob.name.endswith(' piers')):
            bm=bmesh.new();bm.from_mesh(ob.data);boundary=sum(e.is_boundary for e in bm.edges);bm.free()
            if boundary:open_solids.append(dict(object=ob.name,boundary_edges=boundary))
report=dict(buildings_checked=len(footprints),water_intersections=wet,building_intersections=collisions,
    camera_animation=bool(scene.camera.animation_data),hidden_emitters=len(emitters),visible_source_objects=leaks,
    image_texture_nodes=sum(n.type=='TEX_IMAGE' for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes),
    caveat='Footprints and camera flags are engineering checks, not a visual similarity score',
    road_building_intersections=road_conflicts,road_self_intersections=road_folds,downward_open_surfaces=downward_surfaces,
    bridge_ends_in_water=bridge_ends_in_water,bridge_ends_off_road=bridge_ends_off_road,unclosed_new_solids=open_solids,
    status='PASS' if not(wet or collisions or leaks or road_conflicts or road_folds or downward_surfaces or bridge_ends_in_water or bridge_ends_off_road or open_solids or scene.camera.animation_data) else 'FAIL')
(ROOT/(stem+'-audit.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print('FIXED_AUDIT',json.dumps(report),flush=True)
