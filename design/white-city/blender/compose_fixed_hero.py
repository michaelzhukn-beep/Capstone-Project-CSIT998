"""11: fixed left-bank perspective, re-composed buildings, river, roads and bridges.

Loads the actual 10 asset library. Reference positions are authored estimates, not
measured real buildings or a claim to recover the original scene from one picture.
"""
import bpy, bmesh, math, random, json, sys, hashlib
from functools import lru_cache
from pathlib import Path
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

ROOT=Path(__file__).resolve().parent
source=ROOT/'city-10-studio.blend';source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source))
scene=bpy.context.scene;random.seed(1119)
old=json.loads((ROOT/'city-10-studio-plan.json').read_text(encoding='utf-8'))
camera=scene.camera;camera.animation_data_clear()
camera.data.type='PERSP';camera.data.lens=32;camera.data.sensor_width=36;camera.data.sensor_fit='HORIZONTAL'
camera.data.shift_x=0;camera.data.shift_y=.20;camera.data.clip_start=.1;camera.data.clip_end=2500
yaw=math.radians(42);pitch=math.radians(9)
forward=Vector((math.sin(yaw),math.cos(yaw),0));right=Vector((math.cos(yaw),-math.sin(yaw),0))
camera.location=(-185,-155,52)
direction=forward*math.cos(pitch)+Vector((0,0,-math.sin(pitch)))
target=camera.location+direction*300
camera.rotation_euler=direction.to_track_quat('-Z','Y').to_euler()
bpy.context.view_layer.update()

def project(p):
    q=world_to_camera_view(scene,camera,Vector(p));return Vector((q.x,1-q.y))

# Use the camera's actual frustum, including lens shift, for picking ground positions.
frame=camera.data.view_frame(scene=scene)
xmin=min(v.x for v in frame);xmax=max(v.x for v in frame)
ymin=min(v.y for v in frame);ymax=max(v.y for v in frame);zframe=frame[0].z
def ray(u,v):
    return camera.rotation_euler.to_matrix()@Vector((xmin+(xmax-xmin)*u,ymax-(ymax-ymin)*v,zframe))
def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)
def ground(x,y):
    rel=Vector((x,y,0))-Vector((camera.location.x,camera.location.y,0))
    s=rel.dot(right);d=rel.dot(forward)
    return .65+min(24,max(0,s-34)*.11)*smooth(270,520,d)
def pick(u,v,z=None):
    d=ray(u,v);height=.65 if z is None else z
    for _ in range(20 if z is None else 1):
        t=(height-camera.location.z)/d.z
        if t<=0:raise ValueError('Ground pick behind camera')
        p=camera.location+d*t
        if z is None:height=ground(p.x,p.y)
    return Vector((p.x,p.y,height))

class Mesh:
    def __init__(self):self.v=[];self.f=[]
    def add(self,v,f):
        n=len(self.v);self.v.extend(v);self.f.extend(tuple(n+i for i in face) for face in f)
    def box(self,c,s):
        x,y,z=c;a,b,d=[n/2 for n in s]
        self.add([(x-a,y-b,z-d),(x+a,y-b,z-d),(x+a,y+b,z-d),(x-a,y+b,z-d),(x-a,y-b,z+d),(x+a,y-b,z+d),(x+a,y+b,z+d),(x-a,y+b,z+d)],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    def cylinder(self,a,b,r,n=7):
        a,b=Vector(a),Vector(b);rot=(b-a).to_track_quat('Z','Y')
        self.add([tuple(p+rot@Vector((math.cos(i*math.tau/n)*r,math.sin(i*math.tau/n)*r,0))) for p in (a,b) for i in range(n)], [tuple(reversed(range(n))),tuple(range(n,n*2))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)])
    def finish(self,name,mat,bevel=0,open_surface=False):
        me=bpy.data.meshes.new(name);me.from_pydata(self.v,[],self.f);me.materials.append(mat);me.update()
        if not open_surface:
            bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free()
        ob=bpy.data.objects.new(name,me);scene.collection.objects.link(ob)
        if bevel:
            m=ob.modifiers.new('Fine closed edges','BEVEL');m.width=bevel;m.segments=2
            m=ob.modifiers.new('Face normals','WEIGHTED_NORMAL');m.keep_sharp=True
        return ob

ivory=bpy.data.materials['09 Ivory mineral white'];chalk=bpy.data.materials['09 Roof warm chalk']
terrainmat=bpy.data.materials['09 White studio terrain'];watermat=bpy.data.materials['09 Pearlescent reflective water']
metal=bpy.data.materials['09 Fine ivory frames']
roadmat=chalk.copy();roadmat.name='11 Pearl grey streets'
roadmat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.78,.796,.774,1)
roadmat.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.58

# Preserve reusable tree meshes before replacing the old scatter in this new scene.
treeparts={}
for ob in list(scene.objects):
    if ob.type=='MESH' and ob.name.startswith('T') and ('canopy' in ob.name or 'branches' in ob.name):
        treeparts[ob.data.name]=ob.data
treepairs=[]
for k in range(4):
    treepairs.append((bpy.data.meshes[f'TREE{k} branches'],bpy.data.meshes[f'TREE{k} fine canopy']))
for ob in list(scene.objects):
    if ob.type!='MESH':continue
    if ob.name.startswith('T') or ob.name.startswith('09 '):bpy.data.objects.remove(ob,do_unlink=True)

def spline(points,steps=14):
    pp=[Vector(p) for p in points];out=[]
    for i in range(len(pp)-1):
        p0,p1,p2,p3=pp[max(0,i-1)],pp[i],pp[i+1],pp[min(len(pp)-1,i+2)]
        for j in range(steps):
            t=j/steps;out.append(.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t))
    return out+[pp[-1]]
river_uv=[(-.10,.864),(.08,.839),(.23,.839),(.36,.851),(.420,.880),(.350,.914),(.390,.950),(.58,1.01),(.85,1.06),(1.2,1.11)]
river=spline([pick(u,v,0) for u,v in river_uv],20)
# Offset quays need a wider turn radius than the river centreline. Relax the two
# sharp bends before offsetting, keeping the endpoints and the overall S shape.
# Otherwise inner-bank road faces fold over each other at the hairpin.
for _ in range(160):river=[river[0]]+[river[i]*.5+(river[i-1]+river[i+1])*.25 for i in range(1,len(river)-1)]+[river[-1]]
def nearest(path,p):
    best=(1e12,None,None)
    p=Vector((p[0],p[1],0))
    for i,(a,b) in enumerate(zip(path,path[1:])):
        a=Vector((a.x,a.y,0));b=Vector((b.x,b.y,0));ab=b-a
        t=max(0,min(1,(p-a).dot(ab)/max(ab.length_squared,1e-8)));q=a+ab*t
        d=(p-q).length
        if d<best[0]:best=(d,q,i)
    return best
def river_width(p):
    return 8.2+3.4*(1-smooth(200,430,(Vector(p)-camera.location).dot(forward)))
def tangents(path):
    result=[]
    for i,p in enumerate(path):
        d=path[min(len(path)-1,i+1)]-path[max(0,i-1)];d.z=0;d.normalize();result.append(Vector((-d.y,d.x,0)))
    return result
normals=tangents(river)
water=Mesh();banks=Mesh();quaypaths=[[],[]]
for i,(a,b) in enumerate(zip(river,river[1:])):
    na,nb=normals[i],normals[i+1];wa,wb=river_width(a),river_width(b)
    corners=[a-na*wa,b-nb*wb,b+nb*wb,a+na*wa]
    water.add([tuple(p) for p in corners],[(0,1,2,3)])
    for side in (-1,1):
        pts=[a+na*wa*side,b+nb*wb*side,b+nb*(wb+2.8)*side,a+na*(wa+2.8)*side]
        upper=[(p.x,p.y,.70) for p in pts];lower=[(p.x,p.y,-.35) for p in pts]
        banks.add(upper+lower,[(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)])
for side in (-1,1):
    quaypaths[0 if side==-1 else 1]=[p+n*side*(river_width(p)+5.0) for p,n in zip(river,normals)]
water.finish('11 Curved river surface',watermat,open_surface=True)
banks.finish('11 Closed river embankments',chalk,.045)

roads=[]
def road(name,path,width):
    lift=.08+.012*(len(roads)+1)
    roads.append(dict(name=name,path=path,width=width,lift=lift))
    mesh=Mesh();ns=tangents(path)
    for i,(a,b) in enumerate(zip(path,path[1:])):
        points=[a-ns[i]*width/2,b-ns[i+1]*width/2,b+ns[i+1]*width/2,a+ns[i]*width/2]
        # Separate intersecting road surfaces by a paving-course thickness. Exactly
        # coplanar quads at the boulevard/avenue junction caused black Cycles triangles.
        mesh.add([(p.x,p.y,ground(p.x,p.y)+lift) for p in points],[(0,1,2,3)])
    mesh.finish(name,roadmat,open_surface=True)
road('11 Near bank promenade',quaypaths[0],3.0)
road('11 Far bank boulevard',quaypaths[1],3.8)
terrace_uv=[(.46,.946),(.61,.931),(.76,.908),(.92,.860),(1.07,.813)]
road('11 Diagonal terraced avenue',spline([pick(u,v) for u,v in terrace_uv]),4.3)
upper_uv=[(.51,.844),(.64,.818),(.80,.786),(.98,.744),(1.1,.73)]
road('11 Upper hillside lane',spline([pick(u,v) for u,v in upper_uv]),3.1)

# Continuous recessed river bed. A coarse cut-out left cracks between shore and terrain.
extent=[pick(u,v,0) for u in (-.30,1.30) for v in (.70,1.30)]
xlo=min(p.x for p in extent)-30;xhi=max(p.x for p in extent)+30
ylo=min(p.y for p in extent)-30;yhi=max(p.y for p in extent)+30
terrain=Mesh();step=4
@lru_cache(maxsize=None)
def terrain_z(x,y):
    dist,q,_=nearest(river,(x,y))
    bank=river_width(q)
    return -1.0+(ground(x,y)+1.0)*smooth(bank+1.4,bank+4.4,dist)
for ix in range(math.ceil((xhi-xlo)/step)):
    x=xlo+ix*step
    for iy in range(math.ceil((yhi-ylo)/step)):
        y=ylo+iy*step
        terrain.add([(xx,yy,terrain_z(xx,yy)-.015) for xx,yy in [(x,y),(x+step,y),(x+step,y+step),(x,y+step)]],[(0,1,2,3)])
terrain.finish('11 Continuous studio landscape',terrainmat,open_surface=True)

# Fade only distant unoccupied ground along the new view axis. No volume fog.
nodes=terrainmat.node_tree.nodes;links=terrainmat.node_tree.links
mapping=next(n for n in nodes if n.type=='MAP_RANGE');geo=next(n for n in nodes if n.type=='NEW_GEOMETRY')
dot=nodes.new('ShaderNodeVectorMath');dot.operation='DOT_PRODUCT';dot.inputs[1].default_value=forward
links.new(geo.outputs['Position'],dot.inputs[0]);links.new(dot.outputs['Value'],mapping.inputs['Value'])
fade0=camera.location.dot(forward)+490;fade1=camera.location.dot(forward)+650
mapping.inputs['From Min'].default_value=fade0;mapping.inputs['From Max'].default_value=fade1
scene['ground_fade_axis']=list(forward);scene['ground_fade_range']=[fade0,fade1]

# Keep the original detailed asset meshes. Relocate whole buildings and their hidden lights together.
groups={b['id']:[o for o in scene.objects if o.type=='MESH' and o.name.startswith(b['id']+' ')] for b in old['buildings']}
layout=[];occupied=[];occupied_polygons=[];skipped=[]
def rect(x,y,w,d):return [(x-w/2,y-d/2),(x+w/2,y-d/2),(x+w/2,y+d/2),(x-w/2,y+d/2)]
def overlaps(a,b):
    for poly in (a,b):
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)];nx,ny=q[1]-p[1],p[0]-q[0]
            aa=[x*nx+y*ny for x,y in a];bb=[x*nx+y*ny for x,y in b]
            if max(aa)<=min(bb) or max(bb)<=min(aa):return False
    return True
def strip_polygons(path,half_width):
    ns=tangents(path);out=[]
    for i,(a,b) in enumerate(zip(path,path[1:])):
        wa=half_width(a);wb=half_width(b)
        out.append([(p.x,p.y) for p in (a-ns[i]*wa,b-ns[i+1]*wb,b+ns[i+1]*wb,a+ns[i]*wa)])
    return out
protected=strip_polygons(river,lambda p:river_width(p)+1.1)
for r in roads:protected+=strip_polygons(r['path'],lambda p:r['width']/2+.75)
def clearance(poly):
    return not any(overlaps(poly,other) for other in protected+occupied_polygons)
def move_building(b,u,v,top,width,hero=False):
    p=pick(u,v);height=5
    lo,hi=.8,120
    for _ in range(35):
        height=(lo+hi)/2
        if project(p+Vector((0,0,height)))[1]>top:lo=height
        else:hi=height
    # Match apparent width, with two visible facades under the diagonal camera.
    unit=project(p+right)[0]-project(p)[0]
    scale=width/max(unit*(b['w']*.743+b['d']*.669),.0001)
    w=(b['w']+1)*scale;d=(b['d']+1)*scale
    origin=Vector((b['x'],b['y'],b['z']))
    transform=Matrix.Translation(p)@Matrix.Diagonal((scale,scale,height/(b['h']+1),1))@Matrix.Translation(-origin)
    # The footprint uses the same -13 degree orientation as the reusable facade geometry.
    rot=Matrix.Rotation(math.radians(-13),2)
    poly=[tuple(Vector((p.x,p.y))+rot@Vector((xx,yy))) for xx,yy in rect(0,0,w,d)]
    if not clearance(poly):return False
    for ob in groups[b['id']]:ob.matrix_world=transform@ob.matrix_world
    occupied.append((p.x,p.y,w,d));occupied_polygons.append(poly);layout.append(dict(id=b['id'],x=p.x,y=p.y,z=p.z,w=w,d=d,h=height,kind=b['kind'],hero=hero,screen_base=[u,v],screen_top=top))
    return True

hero_targets=[
 (.090,.856,.759,.017),(.118,.845,.738,.019),(.146,.850,.744,.021),
 (.221,.891,.824,.083),(.332,.828,.748,.017),(.548,.918,.845,.082),
 (.616,.836,.682,.038),(.669,.827,.675,.028),(.856,.811,.717,.030),
 (.886,.774,.641,.023),(.923,.763,.596,.025),(.957,.763,.655,.021),
 (.748,.924,.868,.092),(.781,.891,.846,.062),(.434,.862,.819,.065),(.884,.856,.810,.067)]
for b,t in zip([b for b in old['buildings'] if b['hero']],hero_targets):
    u,v,top,w=t;placed=False
    # Small bankward adjustments are explicit in the plan; do not silently tolerate collisions.
    for dv,du,factor in [(0,0,1),(-.010,0,1),(.008,0,1),(.014,-.018,.94),(-.018,.012,.92),(-.027,-.012,.85),(-.036,.022,.80),(.022,.022,.85)]:
        if move_building(b,u+du,v+dv,top+dv,w*factor,True):placed=True;break
    if not placed:skipped.append(b['id'])

# Fill skyline by district and visible height; foreground remains open around river and bridge.
filler=[b for b in old['buildings'] if not b['hero']]
for i,b in enumerate(filler):
    placed=False
    for attempt in range(200):
        u=random.uniform(-.06,1.06)
        if i%3==0:
            base=.795-.055*smooth(.64,1,u)+random.uniform(-.015,.025)
            height=random.uniform(.014,.035);width=random.uniform(.008,.020)
        else:
            base=random.uniform(.830,.920)-.045*smooth(.72,1,u)
            height=random.uniform(.020,.052);width=random.uniform(.018,.039)
        if b['kind']=='pavilion':height=min(height,.024);width*=1.20
        if move_building(b,u,base,base-height,width):placed=True;break
    if not placed:skipped.append(b['id'])
used={b['id'] for b in layout}
for tag,parts in groups.items():
    if tag not in used:
        for ob in parts:bpy.data.objects.remove(ob,do_unlink=True)

# Stronger foreground civic mass: a closed oval atrium building, mostly cropped by the left frame.
civic=Mesh();p=pick(.047,.997);rx,ry=38,23;roof=8.2
for i in range(128):
    a=i*math.tau/128;b=(i+1)*math.tau/128
    def ring(r,t,z):
        q=p+right*(math.cos(t)*rx*r)+forward*(math.sin(t)*ry*r);return (q.x,q.y,p.z+z)
    verts=[ring(1,a,0),ring(1,b,0),ring(1,b,roof),ring(1,a,roof),ring(.70,a,0),ring(.70,b,0),ring(.70,b,roof),ring(.70,a,roof)]
    civic.add(verts,[(0,1,2,3),(7,6,5,4),(0,4,5,1),(3,2,6,7),(0,3,7,4),(1,5,6,2)])
civic.finish('11 Closed oval civic building',ivory,.10)

bridges=[]
def bridge(name,u,v,half_span,width,rise):
    picked=pick(u,v,0);_,center,k=nearest(river,picked);normal=normals[k]
    half_span=river_width(center)+5.0
    a=center-normal*half_span;b=center+normal*half_span
    a.z=ground(a.x,a.y)+min(roads,key=lambda r:nearest(r['path'],a)[0])['lift']
    b.z=ground(b.x,b.y)+min(roads,key=lambda r:nearest(r['path'],b)[0])['lift']
    deck=Mesh();rails=Mesh();piers=Mesh();path=[]
    for i in range(49):
        t=i/48;p=a.lerp(b,t);p.z+=rise*math.sin(math.pi*t);path.append(p)
    ds=tangents(path)
    for i,(a1,b1) in enumerate(zip(path,path[1:])):
        pts=[a1-ds[i]*width/2,b1-ds[i+1]*width/2,b1+ds[i+1]*width/2,a1+ds[i]*width/2]
        deck.add([tuple(p) for p in pts]+[(p.x,p.y,p.z-.45) for p in pts],[(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)])
        for s in (-1,1):
            r1=a1+ds[i]*s*(width/2-.08)+Vector((0,0,.58));r2=b1+ds[i+1]*s*(width/2-.08)+Vector((0,0,.58))
            rails.cylinder(r1,r2,.045)
            if i%4==0:rails.cylinder((r1.x,r1.y,a1.z),r1,.033)
    for t in (.30,.70):
        p=path[round(t*48)];piers.box((p.x,p.y,(p.z-.45)/2),(1.05,width*.72,p.z-.45))
    deck.finish(name+' deck',chalk,.045);rails.finish(name+' railings',metal);piers.finish(name+' piers',ivory,.04)
    bridges.append(dict(name=name,endpoints=[list(a),list(b)],center=list(center),width=width,deck_rise=rise))
bridge('11 Main river arch',.361,.903,21,5.4,2.7)
bridge('11 Upstream crossing',.270,.846,17,3.4,1.2)

# Replant at real ground locations. Keep trunks outside road, water and building envelopes.
trees=[]
def plant(x,y,size):
    rd,q,_=nearest(river,(x,y))
    if rd<river_width(q)+2.4:return False
    if any(nearest(r['path'],(x,y))[0]<r['width']/2+1.0 for r in roads):return False
    if any(abs(x-a)<w/2+1.0 and abs(y-b)<d/2+1.0 for a,b,w,d in occupied):return False
    if any((x-t[0])**2+(y-t[1])**2<(1.65*size)**2 for t in trees):return False
    if any(nearest([Vector(a) for a in br['endpoints']],(x,y))[0]<br['width']/2+1 for br in bridges):return False
    q=project((x,y,ground(x,y)+3.5*size))
    if not -.07<q.x<1.07 or q.y<.72-.08*smooth(.70,1,q.x):return False
    i=len(trees);trees.append((x,y,size));parts=treepairs[i%4]
    for j,mesh in enumerate(parts):
        ob=bpy.data.objects.new(f'N{i:04d} '+('canopy' if j else 'branches'),mesh);scene.collection.objects.link(ob)
        ob.location=(x,y,ground(x,y));ob.scale=(size,size,size);ob.rotation_euler.z=i*1.61
    return True
for i in range(0,len(river),2):
    p=river[i];n=normals[i]
    for side in (-1,1):
        for row in (9.0,13.2,17.1):
            q=p+n*side*(river_width(p)+row)
            plant(q.x+random.uniform(-1,1),q.y+random.uniform(-1,1),random.uniform(.8,1.35))
for _ in range(2000):
    u=random.uniform(-.04,1.07);v=random.uniform(.775,.969)-.058*smooth(.68,1,u)
    p=pick(u,v);plant(p.x,p.y,random.uniform(.70,1.28))
    if len(trees)>780:break

# Low distant landforms, actual white geometry below the skyline, without a fog slab.
hills=Mesh()
for center_u,base_v,wide,high in [(.22,.784,.19,8.5),(.43,.770,.13,5),(.85,.763,.20,7)]:
    c=pick(center_u,base_v);radius=(pick(center_u+wide/2,base_v)-c).length
    for i in range(36):
        for j in range(12):
            def hp(ii,jj):
                a=ii/36*math.tau;r=jj/12;pt=c+right*(math.cos(a)*radius*r)+forward*(math.sin(a)*radius*.60*r)
                return (pt.x,pt.y,ground(pt.x,pt.y)+high*(1-r*r)**2)
            # Increasing angle followed by radius winds downwards. Keep the open
            # surface facing the sky so diffuse bake rays start above the hill.
            hills.add([hp(i,j),hp(i+1,j),hp(i+1,j+1),hp(i,j+1)],[(3,2,1,0)])
hills.finish('11 Distant white rolling landforms',chalk,open_surface=True)

# The oblique layout extends beyond the old studio light footprint. A broad back
# softbox illuminates that empty terrain; it is not a grey horizon or a fog layer.
back_center=Vector((camera.location.x,camera.location.y,0))+forward*490
data=bpy.data.lights.new('11 Distant studio fill','AREA');data.energy=320000;data.shape='DISK';data.size=250
data.color=(1,.985,.96)
ob=bpy.data.objects.new('11 Distant studio fill',data);scene.collection.objects.link(ob)
ob.location=back_center+Vector((0,0,170));ob.rotation_euler=(back_center-ob.location).to_track_quat('-Z','Y').to_euler()

scene.cycles.samples=40 if '--draft' in sys.argv else 192
scene.cycles.adaptive_threshold=.03 if '--draft' in sys.argv else .01
scene.render.resolution_x=1672 if '--draft' in sys.argv else 2560
scene.render.resolution_y=941 if '--draft' in sys.argv else 1441
scene.render.film_transparent=True
bpy.context.view_layer.update()
projection=camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),x=1672,y=941)
checks=[dict(name='bridge '+str(i),world=p,screen=list(project(p))) for i,br in enumerate(bridges) for p in br['endpoints']]
for b in layout:
    if b['hero']:
        p=[b['x'],b['y'],b['z']+b['h']];checks.append(dict(name=b['id'],world=p,screen=list(project(p))))
report=dict(stage='11',status='experimental; diagonal perspective and infrastructure alignment awaiting visual acceptance',buildings=layout,tree_count=len(trees),skipped_buildings=skipped,
 camera=dict(type='PERSP',position=list(camera.location),target=list(target),focal_length_mm=32,yaw_degrees=42,pitch_degrees=9,shift_y=.20,projection_matrix=[list(row) for row in projection],reference_size=[1672,941]),
 river=dict(centerline=[list(p) for p in river],surface_z=0),roads=[dict(name=r['name'],width=r['width'],lift=r['lift'],path=[list(p) for p in r['path']]) for r in roads],bridges=bridges,
 projection_checks=checks,source=source.name,source_sha256=source_hash,limits=['reference alignment is estimated','geometry remains editable','no camera motion','diffuse browser bake does not reproduce all Cycles reflections'])
assert source_hash==hashlib.sha256(source.read_bytes()).hexdigest()
(ROOT/'city-11-aligned-plan.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
scene['stage']='11 left foreground looking right / fixed perspective / riverside street and bridge composition'
scene.render.filepath=str(ROOT/'renders/city-11-aligned.png')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-11-aligned.blend'))
print('ALIGNED_READY',len(layout),len(trees),'skipped',skipped,flush=True)
if '--no-render' not in sys.argv:bpy.ops.render.render(write_still=True)
