"""13 complete, camera-independent maquette. Final light/material work is deferred.

Blender -b --python build_city_layout.py [-- --no-render]
Read city-13-layout-plan.json produced by plan_city_layout.py.
"""
import bpy,bmesh,json,math,random,sys,hashlib
import numpy as np
from functools import lru_cache
from pathlib import Path
from mathutils import Vector,Matrix

ROOT=Path(__file__).resolve().parent
plan=json.loads((ROOT/'city-13-layout-plan.json').read_text(encoding='utf-8'))
if plan['unplaced_landmarks']:raise RuntimeError('Unresolved landmark placement')
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene
def collection(name):
    c=bpy.data.collections.new(name);scene.collection.children.link(c);return c
cols={k:collection(k) for k in ['01 Terrain','02 Water and banks','03 Streets and sidewalks','04 Buildings','05 Bridges','06 Civic landscape','07 Vegetation','08 Inspection cameras']}
def material(name,rgb,rough=.78):
    m=bpy.data.materials.new(name);m.use_nodes=True;m.diffuse_color=(*rgb,1)
    p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*rgb,1);p.inputs['Roughness'].default_value=rough
    return m
mats=[material('13 White clay',(.79,.785,.77)),material('13 Roof and stone',(.86,.85,.82)),material('13 Recessed white panels',(.60,.64,.63)),
      material('13 Pavement',(.66,.68,.66)),material('13 Still water',(.49,.59,.58)),material('13 Tree crowns',(.78,.80,.75)),material('13 Branches',(.51,.53,.49))]

class Mesh:
    def __init__(self):self.v=[];self.f=[];self.mi=[]
    def add(self,v,f,mat=0):
        n=len(self.v);self.v.extend(v);self.f.extend(tuple(n+i for i in face) for face in f);self.mi.extend([mat]*len(f))
    def box(self,c,s,mat=0):
        x,y,z=c;a,b,d=[n/2 for n in s]
        if min(a,b,d)<=0:raise ValueError('Invalid solid box')
        self.add([(x-a,y-b,z-d),(x+a,y-b,z-d),(x+a,y+b,z-d),(x-a,y+b,z-d),(x-a,y-b,z+d),(x+a,y-b,z+d),(x+a,y+b,z+d),(x-a,y+b,z+d)],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)],mat)
    def cylinder(self,a,b,r,n=8,mat=0,tip=None):
        a,b=Vector(a),Vector(b);q=(b-a).to_track_quat('Z','Y');tip=r if tip is None else tip
        self.add([tuple(p+q@Vector((math.cos(i*math.tau/n)*rr,math.sin(i*math.tau/n)*rr,0))) for p,rr in [(a,r),(b,tip)] for i in range(n)], [tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)],mat)
    def finish(self,name,col,bevel=0,merge=False,smooth=False):
        me=bpy.data.meshes.new(name);me.from_pydata(self.v,[],self.f)
        for m in mats:me.materials.append(m)
        for p,m in zip(me.polygons,self.mi):p.material_index=m;p.use_smooth=smooth
        me.update();bm=bmesh.new();bm.from_mesh(me)
        # Float32 world coordinates reach +/- 350. A 1e-5 tolerance leaves
        # numerically identical triangle corners unwelded at that scene scale.
        if merge:bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.001)
        if name=='13 Complete closed terrain':
            # Curved cut boundary can leave tiny 3-edge slivers after floating
            # point polygon containment. Close those local slivers explicitly.
            edge_gaps=[e for e in bm.edges if e.is_boundary]
            if edge_gaps:
                if len(edge_gaps)>24:raise RuntimeError('Unexpected large terrain boundary gap')
                bmesh.ops.holes_fill(bm,edges=edge_gaps,sides=3)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free();me.update()
        ob=bpy.data.objects.new(name,me);cols[col].objects.link(ob)
        if bevel:
            m=ob.modifiers.new('Small model edge bevel','BEVEL');m.width=bevel;m.segments=2
            m=ob.modifiers.new('Stable weighted normals','WEIGHTED_NORMAL');m.keep_sharp=True
        ob['model_phase']='geometry approval';return ob

sys.path.insert(0,str(ROOT))
from layout_terrain import Terrain
terrain_function=Terrain(plan['water_contour'])
ground=lru_cache(maxsize=None)(terrain_function)

def solid_surface(name,shape,top,bottom,col,mat):
    mesh=Mesh()
    for tri in shape['triangles']:
        mesh.add([(x,y,top(x,y)) for x,y in tri],[(0,1,2)],mat)
        mesh.add([(x,y,bottom(x,y)) for x,y in tri],[(2,1,0)],mat)
    for poly in shape['polygons']:
        for ring in [poly['outer']]+poly.get('holes',[]):
            for p,q in zip(ring,ring[1:]+ring[:1]):
                x,y=p;xx,yy=q
                mesh.add([(x,y,top(x,y)),(xx,yy,top(xx,yy)),(xx,yy,bottom(xx,yy)),(x,y,bottom(x,y))],[(0,1,2,3)],mat)
    return mesh.finish(name,col,merge=True)

terrain_shape=dict(triangles=plan['terrain_triangles'],polygons=plan['site'])
solid_surface('13 Complete closed terrain',terrain_shape,ground,lambda x,y:-7.5,'01 Terrain',1)
solid_surface('13 Continuous river',plan['surfaces']['water'],lambda x,y:0,lambda x,y:-.85,'02 Water and banks',4)
solid_surface('13 Closed quay walls',plan['surfaces']['banks'],lambda x,y:max(1.25,ground(x,y)+.10),lambda x,y:-.9,'02 Water and banks',1)
solid_surface('13 Connected road network',plan['surfaces']['roads'],lambda x,y:ground(x,y)+.14,lambda x,y:ground(x,y)+.02,'03 Streets and sidewalks',3)
solid_surface('13 Pavement and junction corners',plan['surfaces']['sidewalks'],lambda x,y:ground(x,y)+.29,lambda x,y:ground(x,y)+.04,'03 Streets and sidewalks',1)

# Complete four-sided facade modules. All panels, roof slabs and gable ends have depth.
def shell(mesh,x,y,z,w,d,h,style='office'):
    mesh.box((x,y,z+h/2),(w-.40,d-.40,h),2)
    mesh.box((x,y,z+.2),(w,d,.4),1)
    mesh.box((x,y,z+h),(w+.35,d+.35,.35),1)
    levels=max(1,round(h/3.0));pitch=1.1 if h>25 else 2.3
    if style=='fins':pitch=.80
    for axis,length,depth in [(0,w,d),(1,d,w)]:
        count=max(3,round(length/pitch))
        for side in [-1,1]:
            for i in range(count+1):
                t=-length/2+i*length/count
                xx,yy=(x+t,y+side*depth/2) if axis==0 else (x+side*depth/2,y+t)
                mesh.box((xx,yy,z+h/2),(.17,.33,h) if axis==0 else (.33,.17,h),0)
    bands=[0,h] if style=='fins' else [i*h/levels for i in range(levels+1)]
    for zz in bands:mesh.box((x,y,z+zz),(w+.20,d+.20,.20),0)

for b in plan['buildings']:
    mesh=Mesh();w,d,h,z=b['w'],b['d'],b['h'],b['z'];base=b['base'];kind=b['kind']
    mesh.box((0,0,(base+z)/2),(w+.9,d+.9,z-base),1)
    if kind.startswith('tower'):
        podium=min(5.4,h*.14);mesh.box((0,0,z+podium/2),(w,d,podium),0)
        if kind=='tower_setback':
            heights=[h*.57,h*.26,h*.17];zz=z+podium;remaining=h-podium
            for i,f in enumerate([.57,.26,.17]):
                hh=remaining*f;s=1-.15*i;shell(mesh,0,0,zz,w*s-.5,d*s-.5,hh,'fins');zz+=hh
        elif kind=='tower_crown':
            crown=3.8
            shell(mesh,0,0,z+podium,w-.7,d-.7,h-podium-crown,'fins')
            shell(mesh,0,0,z+h-crown,w*.87,d*.87,crown,'fins')
        elif kind=='tower_frame':shell(mesh,0,0,z+podium,w-.7,d-.7,h-podium,'office')
        else:shell(mesh,0,0,z+podium,w-.7,d-.7,h-podium,'fins')
        mesh.box((0,0,z+h+.35),(w*.58,d*.55,.7),1)
    elif kind=='courtyard':
        wing=min(w,d)*.25
        shell(mesh,0,(d-wing)/2,z,w,wing,h)
        shell(mesh,0,-(d-wing)/2,z,w,wing,h)
        for side in [-1,1]:shell(mesh,side*(w-wing)/2,0,z,wing,d-2*wing,h*.85)
        mesh.box((0,0,z+.12),(w-2*wing,d-2*wing,.24),1)
    elif kind=='terrace':
        zz=z
        for i,f in enumerate([.50,.30,.20]):
            ww=w*(1-.15*i);dd=d*(1-.16*i);hh=h*f
            shell(mesh,0,d*.06*i,zz,ww,dd,hh);zz+=hh
    elif kind in ('gable','sawtooth'):
        count=3 if w>12 else 2;unit=w/count;wall=h*.64
        for i in range(count):
            cx=-w/2+unit*(i+.5);mesh.box((cx,0,z+wall/2),(unit-.18,d,wall),0)
            x0,x1=cx-unit/2+.09,cx+unit/2-.09
            ridge=cx if kind=='gable' else x0+unit*.20
            mesh.add([(x0,-d/2,z+wall),(x1,-d/2,z+wall),(ridge,-d/2,z+h),(x0,d/2,z+wall),(x1,d/2,z+wall),(ridge,d/2,z+h)],[(2,1,0),(3,4,5),(0,3,5,2),(2,5,4,1),(1,4,3,0)],1)
            for side in [-1,1]:
                for k in range(2):mesh.box((cx+(k-.5)*unit*.38,side*(d/2+.025),z+wall*.49),(unit*.25,.08,wall*.50),2)
    elif kind in ('pavilion','gallery'):
        shell(mesh,0,0,z,w-.5,d-.5,h-.4)
        mesh.box((0,0,z+h),(w+.8,d+.8,.52),1)
        if kind=='gallery':mesh.box((0,0,z+h+.42),(w*.55,d*.38,.4),1)
    else:shell(mesh,0,0,z,w,d,h)
    if not kind.startswith('tower') and kind not in ('gable','sawtooth','courtyard'):
        mesh.box((w*.08,d*.13,z+h+.35),(w*.37,d*.35,.7),1)
    ob=mesh.finish(b['id']+' '+b['label'],'04 Buildings',.045)
    ob.location=(b['x'],b['y'],0);ob.rotation_euler.z=math.radians(b['angle'])
    for k in ['id','kind','landmark','h','label']:ob[k]=b[k]

for br in plan['bridges']:
    p=[Vector((x,y,0)) for x,y in br['path']];length=[0]
    for a1,b1 in zip(p,p[1:]):length.append(length[-1]+(b1-a1).length)
    za=ground(p[0].x,p[0].y)+.29;zb=ground(p[-1].x,p[-1].y)+.29
    for i,point in enumerate(p):
        t=length[i]/length[-1];point.z=za*(1-t)+zb*t+br['rise']*math.sin(math.pi*t)
    deck=Mesh();rails=Mesh();piers=Mesh();width=br['width'];normals=[]
    for i in range(len(p)):
        d1=p[min(i+1,len(p)-1)]-p[max(i-1,0)];d1.z=0;d1.normalize();normals.append(Vector((-d1.y,d1.x,0)))
    verts=[]
    for q,n in zip(p,normals):verts.extend([tuple(q-n*width/2),tuple(q+n*width/2),tuple(q-n*width/2-Vector((0,0,.6))),tuple(q+n*width/2-Vector((0,0,.6)))])
    faces=[(2,3,1,0)]
    for i in range(len(p)-1):
        a=i*4;b=(i+1)*4;faces.extend([(a,b,b+1,a+1),(a+2,a+3,b+3,b+2),(a+2,b+2,b,a),(a+1,b+1,b+3,a+3)])
        for s in [-1,1]:
            ra=p[i]+normals[i]*(width/2-.12)*s+Vector((0,0,1));rb=p[i+1]+normals[i+1]*(width/2-.12)*s+Vector((0,0,1))
            rails.cylinder(ra,rb,.065)
            if i%3==0:rails.cylinder(ra-Vector((0,0,1)),ra,.055)
    k=(len(p)-1)*4;faces.append((k,k+1,k+3,k+2));deck.add(verts,faces,1)
    for station in np.arange(12,length[-1]-9,br.get('pier_spacing',22)):
        i=min(range(len(p)),key=lambda k:abs(length[k]-station));q=p[i]
        bottom=ground(q.x,q.y)-.35;top=q.z-.6
        if top>bottom:piers.box((q.x,q.y,(top+bottom)/2),(1.4,width*.60,top-bottom),0)
    for m,n in [(deck,' deck'),(rails,' rails'),(piers,' piers')]:m.finish('13 '+br['name']+n,'05 Bridges',.035 if m==deck else 0)

# Reusable solid tree prototypes; independent from every camera and no sprites.
protos=[]
for variant in range(4):
    rr=random.Random(430+variant);m=Mesh();m.cylinder((0,0,0),(0,0,2.8),.14,7,6,tip=.05)
    bm=bmesh.new();bmesh.ops.create_icosphere(bm,subdivisions=1,radius=1);bm.verts.ensure_lookup_table();bm.verts.index_update()
    vv=[v.co.copy() for v in bm.verts];ff=[tuple(v.index for v in f.verts) for f in bm.faces];bm.free()
    for k in range(15):
        t=k*2.399+rr.random()*.3;r=rr.uniform(.35,1.60);tip=Vector((math.cos(t)*r,math.sin(t)*r,rr.uniform(2.1,4.0)))
        m.cylinder((0,0,1.8),tip,.04,5,6,tip=.022)
        size=rr.uniform(.5,.87);m.add([tuple(tip+Vector((v.x*size,v.y*size,v.z*size*.85))) for v in vv],ff,5)
    ob=m.finish(f'13 Tree prototype {variant}','07 Vegetation',smooth=True);protos.append(ob.data);bpy.data.objects.remove(ob,do_unlink=True)
for i,(x,y,z,s,variant) in enumerate(plan['trees']):
    ob=bpy.data.objects.new(f'T{i:04d}',protos[variant]);cols['07 Vegetation'].objects.link(ob);ob.location=(x,y,z);ob.scale=(s,s,s);ob.rotation_euler.z=i*1.618

# Geometry cameras share the same entire scene. Four views are not separate models.
camera_specs={
 'top':dict(position=[0,-710,1180],target=[0,55,0],up=[0,0,1],scale=770),
 'front':dict(position=[-95,-990,300],target=[0,60,20],up=[0,0,1],scale=755),
 'left':dict(position=[-680,-800,365],target=[0,60,20],up=[0,0,1],scale=750),
 'right':dict(position=[580,-850,390],target=[0,60,20],up=[0,0,1],scale=750),
 'overview':dict(position=[-500,-790,735],target=[0,60,15],up=[0,0,1],scale=790),
 'back':dict(position=[0,1030,365],target=[0,60,20],up=[0,0,1],scale=790),
 'rear_left':dict(position=[-680,780,480],target=[0,60,20],up=[0,0,1],scale=790),
 'rear_right':dict(position=[680,780,450],target=[0,60,20],up=[0,0,1],scale=790),
 'bridge':dict(position=[-100,-390,275],target=[-2,-27,5],up=[0,0,1],scale=400)}
for name,spec in camera_specs.items():
    d=bpy.data.cameras.new('13 '+name);ob=bpy.data.objects.new(d.name,d);cols['08 Inspection cameras'].objects.link(ob)
    ob.location=spec['position'];ob.rotation_euler=(Vector(spec['target'])-ob.location).to_track_quat('-Z','Y').to_euler();d.type='ORTHO';d.ortho_scale=spec['scale'];d.clip_end=2400
scene.camera=bpy.data.objects['13 overview']
scene.render.engine='CYCLES';scene.cycles.samples=40;scene.cycles.use_denoising=True;scene.cycles.diffuse_bounces=3
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for d in prefs.devices:d.use=d.type=='OPTIX'
scene.cycles.device='GPU';scene.render.resolution_x=1600;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA';scene.render.film_transparent=True
scene.view_settings.view_transform='AgX';scene.view_settings.look='AgX - Medium High Contrast';scene.view_settings.exposure=.4
w=bpy.data.worlds.new('13 Neutral geometry review');w.use_nodes=True;w.node_tree.nodes['Background'].inputs[0].default_value=(.93,.95,1,1);w.node_tree.nodes['Background'].inputs[1].default_value=.7;scene.world=w
data=bpy.data.lights.new('13 Neutral inspection key','SUN');data.energy=2.2;data.angle=.18
light=bpy.data.objects.new(data.name,data);scene.collection.objects.link(light);light.rotation_euler=(math.radians(25),math.radians(-28),math.radians(-25))
scene['stage']='13 complete geometry / four-view inspection / no final lighting or emissive sources'
scene['reference']='city-four-view-reference.png + city-additional-views-reference.png; authored interpretation, not surveyed geometry'
bpy.context.view_layer.update()
corners=[o.matrix_world@Vector(p) for o in scene.objects if o.type=='MESH' for p in o.bound_box]
for name,spec in camera_specs.items():
    if name=='bridge':continue
    cam=bpy.data.objects['13 '+name];inv=cam.matrix_world.inverted();pp=[inv@p for p in corners]
    x0,x1=min(p.x for p in pp),max(p.x for p in pp);y0,y1=min(p.y for p in pp),max(p.y for p in pp)
    width=max(x1-x0,(y1-y0)*1600/1100)*1.12
    cam.data.ortho_scale=width;cam.data.shift_x=(x0+x1)/2/width;cam.data.shift_y=(y0+y1)/2/width
    spec.update(scale=width,shift_x=cam.data.shift_x,shift_y=cam.data.shift_y)
plan['cameras']=camera_specs
(ROOT/'city-13-layout-plan.json').write_text(json.dumps(plan,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-13-layout.blend'))
source_hash=hashlib.sha256((ROOT/'city-13-layout.blend').read_bytes()).hexdigest()
print('MASTER_READY',len(plan['buildings']),len(plan['trees']),flush=True)
if '--no-render' not in sys.argv:
    for name in ['top','front','left','right','overview','bridge']:
        scene.camera=bpy.data.objects['13 '+name];scene.render.filepath=str(ROOT/f'renders/city-13-{name}.png');bpy.ops.render.render(write_still=True)

# Export merged layers from an in-memory copy, keeping editable individual buildings
# and linked vegetation in the saved Blender source.
for name,col in cols.items():
    objects=[o for o in col.objects if o.type=='MESH']
    if not objects:continue
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects:o.select_set(True)
    bpy.context.view_layer.objects.active=objects[0];bpy.ops.object.convert(target='MESH');bpy.ops.object.join();bpy.context.object.name=name
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
bpy.ops.object.select_all(action='DESELECT')
for o in scene.objects:
    if o.type=='MESH':o.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(ROOT/'city-13-layout.glb'),export_format='GLB',use_selection=True,export_cameras=False,export_lights=False,export_animations=False,
    export_draco_mesh_compression_enable=True,export_draco_mesh_compression_level=6,export_draco_position_quantization=16,export_draco_normal_quantization=12)
assert hashlib.sha256((ROOT/'city-13-layout.blend').read_bytes()).hexdigest()==source_hash
(ROOT/'city-13-export.json').write_text(json.dumps(dict(source='city-13-layout.blend',source_sha256=source_hash,bytes=(ROOT/'city-13-layout.glb').stat().st_size,cameras=camera_specs,phase='geometry only',image_textures=0,emissive_sources=0),indent=2),encoding='utf-8')
print('MASTER_EXPORT_DONE',flush=True)
