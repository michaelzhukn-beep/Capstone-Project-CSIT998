"""09 fixed-camera reconstruction study. Authored geometry, never a reference-image plane.

Blender 4.5: -b --python build_fixed_hero.py -- [--draft] [--no-render]
The single reference constrains visible composition, not hidden building dimensions.
"""
import bpy, bmesh, math, random, json, sys
from pathlib import Path
from mathutils import Vector,Matrix
from bpy_extras.object_utils import world_to_camera_view

ROOT=Path(__file__).resolve().parent
DRAFT='--draft' in sys.argv
random.seed(9106)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene
scene.render.engine='CYCLES'
scene.cycles.samples=48 if DRAFT else 192
scene.cycles.use_denoising=True
scene.cycles.max_bounces=10;scene.cycles.diffuse_bounces=5;scene.cycles.transmission_bounces=6
scene.cycles.adaptive_threshold=.035 if DRAFT else .012
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for device in prefs.devices:device.use=device.type=='OPTIX'
scene.cycles.device='GPU'
scene.render.resolution_x=1672 if DRAFT else 2560
scene.render.resolution_y=941 if DRAFT else 1441
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
scene.render.film_transparent=True
scene.view_settings.view_transform='AgX';scene.view_settings.look='AgX - Medium High Contrast';scene.view_settings.exposure=1.75

def group(name):
    c=bpy.data.collections.new(name);scene.collection.children.link(c);return c
arch=group('09 Authored fixed composition');land=group('09 River and curved promenade');plants=group('09 Fine model vegetation');lights=group('09 Concealed practical lights')
def material(name,c,rough=.4,trans=0,emit=0):
    m=bpy.data.materials.new(name);m.use_nodes=True;m.diffuse_color=(*c,1)
    p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*c,1)
    p.inputs['Roughness'].default_value=rough;p.inputs['Transmission Weight'].default_value=trans
    p.inputs['IOR'].default_value=1.45
    if emit:p.inputs['Emission Color'].default_value=(1,.71,.40,1);p.inputs['Emission Strength'].default_value=emit
    return m
ivory=material('09 Ivory mineral white',(.90,.875,.81),.34)
chalk=material('09 Roof warm chalk',(.93,.916,.877),.49)
groundmat=material('09 White studio terrain',(.93,.908,.845),.59)
glass=material('09 Low iron thin glass',(.80,.82,.795),.15,.70)
recess=material('09 Light recess satin',(.71,.725,.70),.38)
metal=material('09 Fine ivory frames',(.865,.864,.84),.27)
leaf=material('09 Fine chalk foliage',(.90,.883,.839),.69)
branch=material('09 Small warm white branches',(.73,.722,.681),.70)
watermat=material('09 Pearlescent reflective water',(.63,.70,.68),.13,.15)
practical=material('09 Hidden warm cove source',(.91,.79,.61),.5,emit=7)

class Mesh:
    def __init__(self):self.v=[];self.f=[]
    def add(self,v,f):
        n=len(self.v);self.v.extend(v);self.f.extend(tuple(n+i for i in face) for face in f)
    def box(self,c,s):
        x,y,z=c;a,b,d=[n/2 for n in s]
        self.add([(x-a,y-b,z-d),(x+a,y-b,z-d),(x+a,y+b,z-d),(x-a,y+b,z-d),
                  (x-a,y-b,z+d),(x+a,y-b,z+d),(x+a,y+b,z+d),(x-a,y+b,z+d)],
                 [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    def cylinder(self,start,end,r,sides=6,tip=None):
        a,b=Vector(start),Vector(end);q=(b-a).to_track_quat('Z','Y');tip=r*.7 if tip is None else tip
        v=[tuple(p+q@Vector((math.cos(i*math.tau/sides)*rr,math.sin(i*math.tau/sides)*rr,0))) for p,rr in [(a,r),(b,tip)] for i in range(sides)]
        self.add(v,[tuple(reversed(range(sides))),tuple(range(sides,sides*2))]+[(i,(i+1)%sides,(i+1)%sides+sides,i+sides) for i in range(sides)])
    def finish(self,name,mat,col=arch,bevel=0,smooth=False):
        if not self.v:return None
        me=bpy.data.meshes.new(name);me.from_pydata(self.v,[],self.f);me.materials.append(mat);me.update()
        if mat not in (groundmat,watermat):
            bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free();me.update()
        ob=bpy.data.objects.new(name,me);col.objects.link(ob)
        if bevel:
            mod=ob.modifiers.new('Fine manufactured edges','BEVEL');mod.width=bevel;mod.segments=2
            mod=ob.modifiers.new('Weighted face normals','WEIGHTED_NORMAL');mod.keep_sharp=True
        for p in me.polygons:p.use_smooth=smooth
        return ob

WIDTH=400;HEIGHT=WIDTH*941/1672;ELEV=math.radians(14);CENTER=84
def ground(x,y):return max(0,x+15)*.032+max(y-30,0)*.012
def project_ground(u,v):
    x=(u-.5)*WIDTH
    # Solve y numerically because the shallow right-bank rise is piecewise.
    lo,hi=-500,700
    for _ in range(50):
        y=(lo+hi)/2;up=y*math.sin(ELEV)+ground(x,y)*math.cos(ELEV)
        if up<CENTER-(v-.5)*HEIGHT:lo=y
        else:hi=y
    return x,(lo+hi)/2
camdata=bpy.data.cameras.new('09 fixed reference camera');cam=bpy.data.objects.new(camdata.name,camdata);scene.collection.objects.link(cam)
target=Vector((0,0,CENTER/math.cos(ELEV)))
cam.location=target+Vector((0,-math.cos(ELEV)*600,math.sin(ELEV)*600))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();camdata.type='ORTHO';camdata.ortho_scale=WIDTH;camdata.clip_end=1500;scene.camera=cam

# A hand-shaped S bend occupies the opening in the composition; not a recycled straight canal.
control=[(-235,92),(-140,51),(-96,25),(-37,8),(-27,-9),(-60,-27),(-61,-48),(-26,-67),(48,-80),(230,-96)]
river=[]
for i in range(len(control)-1):
    p0=Vector(control[max(0,i-1)]);p1=Vector(control[i]);p2=Vector(control[i+1]);p3=Vector(control[min(len(control)-1,i+2)])
    for j in range(18):
        t=j/18;p=.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t);river.append(p)
river.append(Vector(control[-1]))
def river_distance(x,y):
    p=Vector((x,y));return min((p-q).length for q in river)
water=Mesh();banks=Mesh()
for i in range(len(river)-1):
    a,b=river[i],river[i+1];d=(b-a).normalized();n=Vector((-d.y,d.x));half=6.8
    def q(p,side,width,z):
        v=p+n*side*width;return (v.x,v.y,ground(v.x,v.y)+z)
    water.add([q(a,-1,half,.08),q(b,-1,half,.08),q(b,1,half,.08),q(a,1,half,.08)],[(0,1,2,3)])
    for s in [-1,1]:
        vv=[q(a,s,half,.36),q(b,s,half,.36),q(b,s,half+2.3,.38),q(a,s,half+2.3,.38)]
        banks.add(vv+[(x,y,z-.46) for x,y,z in vv],[(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)])
water.finish('09 Curved river surface',watermat,land);banks.finish('09 Solid ivory river banks',chalk,land,.04)
terrain=Mesh()
for ix in range(90):
    x=-280+ix*7
    for iy in range(58):
        y=-200+iy*9
        terrain.add([(xx,yy,ground(xx,yy)-.03) for xx,yy in [(x,y),(x+7,y),(x+7,y+9),(x,y+9)]],[(0,1,2,3)])
terrain.finish('09 Continuous studio landscape',groundmat,land)

layout=[];occupied=[];lamps=[]
def building(tag,x,y,w,d,h,kind='fins',hero=False):
    z=ground(x,y);body=Mesh();glazing=Mesh();trim=Mesh();warm=Mesh();floor=Mesh()
    floor.box((x,y,z+.18),(w+.65,d+.65,.36));base=z+.36
    if kind=='pavilion':
        roof=base+h;floor.box((x,y,base+.10),(w,d,.20))
        body.box((x,y,roof),(w+1,d+1,.38));body.box((x,y,roof+.22),(w*.78,d*.70,.12))
        # Real hollow interior, thin glazing, concealed ceiling strips and solid baffle.
        for side in [-1,1]:
            glazing.box((x,y+side*(d/2-.20),base+h/2),(w-.4,.024,h-.30))
            glazing.box((x+side*(w/2-.20),y,base+h/2),(.024,d-.4,h-.30))
        for i in range(max(3,round(w/1.45))+1):
            xx=x-w/2+i*w/max(3,round(w/1.45));trim.box((xx,y-d/2+.1,base+h/2),(.075,.12,h))
        body.box((x,y+d*.2,base+h/2),(w*.7,.17,h-.4))
        for side in [-1,1]:
            yy=y+side*d*.33
            warm.box((x,yy,roof-.24),(w*.72,.13,.035))
            body.box((x,yy-.12,roof-.24),(w*.76,.08,.28))
        lamps.append(tag)
    else:
        # Pale reveals, closely spaced vertical solid fins: avoid broad charcoal stripes.
        tiers=2 if kind=='stepped' and h<18 else 1
        for tier in range(tiers):
            ww=w*(1-.15*tier);dd=d*(1-.13*tier);hh=h/tiers;zz=base+tier*hh
            lobby=2.0 if tier==0 else 0
            body.box((x,y,zz+(hh+lobby)/2),(ww-.36,dd-.36,hh-lobby))
            if tier==0:
                body.box((x,y+dd*.18,zz+1),(ww-.4,.18,2))
                glazing.box((x,y-dd/2+.14,zz+1),(ww-.35,.024,1.9))
            for side in [-1,1]:
                glazing.box((x,y+side*(dd/2-.12),zz+(hh+lobby)/2),(ww-.35,.035,hh-lobby-.30))
                glazing.box((x+side*(ww/2-.12),y,zz+(hh+lobby)/2),(.035,dd-.35,hh-lobby-.30))
            pitch=.62 if hero else .90
            for axis,length in [(0,ww),(1,dd)]:
                count=max(3,round(length/pitch))
                for side in [-1,1]:
                    for k in range(count+1):
                        off=-length/2+length*k/count
                        cx,cy=(x+off,y+side*dd/2) if axis==0 else (x+side*ww/2,y+off)
                        trim.box((cx,cy,zz+hh/2),(.11,.32,hh) if axis==0 else (.32,.11,hh))
            levels=max(1,round(hh/2.9))
            for level in range(levels+1):
                trim.box((x,y,zz+level*hh/levels),(ww+.18,dd+.18,.12 if kind=='fins' else .23))
            body.box((x,y,zz+hh+.12),(ww+.26,dd+.26,.23))
        body.box((x,y,base+h+.38),(w*.84,d*.82,.52));body.box((x,y,base+h+.72),(w*.70,d*.66,.20))
        # Discrete warm lobby behind the front colonnade, not yellow strips on every floor.
        if hero or random.random()<.45:
            warm.box((x,y-d*.25,base+1.88),(w*.66,d*.32,.035))
            body.box((x,y-d/2-.10,base+1.86),(w*.85,.34,.24))
            for k in range(6):trim.box((x-w*.34+k*w*.136,y-d/2-.18,base+.74),(.11,.15,1.45))
            lamps.append(tag)
    for mesh,suffix,mat in [(body,'solid closed shells',ivory),(floor,'plinth',chalk),(glazing,'thin recess glazing',glass if kind=='pavilion' else recess),(trim,'fine vertical frames',metal),(warm,'concealed warm source',practical)]:
        ob=mesh.finish(tag+' '+suffix,mat,arch,.035 if mesh is body or mesh is floor else 0)
        if ob and mesh is warm:ob.visible_camera=False;ob.visible_glossy=False;ob.visible_transmission=False;ob['emitter']=True
        if ob:
            rotation=Matrix.Translation(Vector((x,y,0)))@Matrix.Rotation(math.radians(-13),4,'Z')@Matrix.Translation(Vector((-x,-y,0)))
            ob.data.transform(rotation)
    layout.append(dict(id=tag,x=x,y=y,z=z,w=w,d=d,h=h,kind=kind,hero=hero))
    occupied.append((x,y,w/2+1.6,d/2+1.6))

# Explicit screen-space landmarks measured from the provided 1672 x 941 reference.
# Positions refer to the building base; no camera fitting against generated geometry.
heroes=[
 ('left slim tower',.090,.856,.759,4.4,5.2,'fins'),
 ('left paired tower A',.118,.845,.738,5.5,6.1,'stepped'),
 ('left paired tower B',.146,.850,.744,6.4,5.6,'fins'),
 ('left waterfront block',.231,.891,.834,13.4,8.3,'fins'),
 ('central slim marker',.332,.835,.748,4.7,4.9,'stepped'),
 ('central foreground block',.548,.912,.845,13.7,9.4,'stepped'),
 ('central skyline A',.616,.836,.682,8.2,8.5,'fins'),
 ('central skyline B',.664,.823,.675,6.6,7.0,'stepped'),
 ('right middle tower',.856,.811,.717,7.3,7.6,'fins'),
 ('right ridge A',.886,.774,.641,6.4,6.8,'stepped'),
 ('right ridge crown',.923,.763,.596,6.8,7.4,'stepped'),
 ('right ridge B',.957,.763,.655,5.4,5.8,'fins'),
 ('right foreground low',.748,.924,.883,20.8,12.0,'stepped'),
 ('right gallery',.781,.891,.850,18.0,9.1,'pavilion'),
 ('central gallery',.420,.851,.810,14.0,8.0,'pavilion'),
 ('right terrace gallery',.884,.856,.821,19.0,8.0,'pavilion'),
]
landmarks=[]
for i,(label,u,v,top,w,d,kind) in enumerate(heroes):
    x,y=project_ground(u,v);h=(v-top)*HEIGHT/math.cos(ELEV)-1.0
    building(f'H{i:02d} {label}',x,y,w,d,h,kind,True)
    landmarks.append(dict(id=f'H{i:02d}',label=label,u=u,base_v=v,top_v=top,world=[x,y,ground(x,y)+h+1]))

def free(x,y,w,d,margin=1.8):
    if river_distance(x,y)<8+math.hypot(w,d)/2:return False
    return all(abs(x-a)>w/2+ww+margin or abs(y-b)>d/2+dd+margin for a,b,ww,dd in occupied)
# Curated clusters fill around landmarks; height follows each side's silhouette envelope.
clusters=[(-160,17,49,34),(-105,39,43,30),(-5,67,66,40),(90,102,52,65),(166,135,48,76),(93,-18,67,33)]
envelope=[(-.1,.795),(.0,.787),(.18,.800),(.28,.824),(.38,.799),(.48,.770),(.59,.755),(.69,.754),(.77,.765),(.85,.735),(.93,.699),(1.1,.738)]
def silhouette(u):
    for (a,v),(b,w) in zip(envelope,envelope[1:]):
        if a<=u<=b:return v+(w-v)*(u-a)/(b-a)
    return .79
def top_v(x,y,h):return .5+(CENTER-y*math.sin(ELEV)-(ground(x,y)+h)*math.cos(ELEV))/HEIGHT
for ci,(cx,cy,rx,ry) in enumerate(clusters):
    for attempt in range(290):
        x=random.gauss(cx,rx*.60);y=random.gauss(cy,ry*.62)
        if not -218<x<230 or y>235 or y<-55:continue
        w=random.uniform(4.2,10);d=random.uniform(4.4,9)
        if not free(x,y,w,d):continue
        h=random.uniform(4,12)
        if y>70:h+=random.uniform(0,6)
        if x>125 and y>100:h+=random.uniform(0,8)
        if abs(x)<88 and y>130:h=min(h,9)
        kind='pavilion' if y<40 and random.random()<.48 else random.choice(['fins','fins','stepped'])
        if kind=='pavilion':h=3.7;w*=1.3
        if top_v(x,y,h+1)<silhouette(x/WIDTH+.5):continue
        if not free(x,y,w,d):continue
        building(f'C{ci}-{attempt:03d}',x,y,w,d,h,kind)

# Foreground circular civic building, cropped by the left edge as in the reference.
curved=Mesh();curvedglass=Mesh()
cx,cy=-179,-112
for i in range(100):
    a=i*math.tau/100;b=(i+1)*math.tau/100
    def ring(r,t,z):return (cx+math.cos(t)*r,cy+math.sin(t)*r*.57,z)
    verts=[ring(58,a,.5),ring(58,b,.5),ring(58,b,6),ring(58,a,6),ring(57,a,.5),ring(57,b,.5),ring(57,b,6),ring(57,a,6)]
    curved.add(verts,[(0,1,2,3),(7,6,5,4),(0,4,5,1),(3,2,6,7),(0,3,7,4),(1,5,6,2)])
    vv=[ring(58.7,a,6),ring(58.7,b,6),ring(41,b,6),ring(41,a,6)]
    curved.add(vv+[(x,y,z-.25) for x,y,z in vv],[(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)])
curved.finish('09 foreground curved civic roof and shell',ivory,arch,.06)

# One elegant skewed arch across the river bend. All segments have deck thickness.
bridge=Mesh();rail=Mesh()
a=Vector((-78,-43));b=Vector((-32,-8));steps=44
for i in range(steps):
    t=i/steps;t2=(i+1)/steps
    pa=a.lerp(b,t);pb=a.lerp(b,t2);delta=(pb-pa).normalized();n=Vector((-delta.y,delta.x))
    za=ground(*pa)+.8+2.5*math.sin(math.pi*t);zb=ground(*pb)+.8+2.5*math.sin(math.pi*t2)
    v=[(p.x+n.x*s*2,p.y+n.y*s*2,z) for p,z in [(pa,za),(pb,zb)] for s in [-1,1]]
    bridge.add(v+[(x,y,z-.38) for x,y,z in v],[(0,2,3,1),(5,7,6,4),(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3)])
    for s in [-1,1]:
        ra=(pa.x+n.x*s*1.94,pa.y+n.y*s*1.94,za+.58);rb=(pb.x+n.x*s*1.94,pb.y+n.y*s*1.94,zb+.58)
        rail.cylinder(ra,rb,.04,6,tip=.04)
        if i%4==0:rail.cylinder((ra[0],ra[1],za),ra,.035)
bridge.finish('09 arched river footbridge',chalk,land,.03);rail.finish('09 fine bridge balustrades',metal,land)

# Four reusable fine-canopied geometries, then linked mesh instances; no texture sprites.
prototypes=[]
for k in range(4):
    trunk=Mesh();crown=Mesh();rr=random.Random(761+k)
    trunk.cylinder((0,0,0),(0,0,2.5),.09,7,tip=.035)
    bm=bmesh.new();bmesh.ops.create_icosphere(bm,subdivisions=1,radius=1);bm.verts.ensure_lookup_table();bm.verts.index_update()
    spherev=[v.co.copy() for v in bm.verts];spheref=[tuple(v.index for v in f.verts) for f in bm.faces];bm.free()
    for j in range(18):
        angle=rr.random()*math.tau;rad=rr.uniform(.2,1.3);zz=rr.uniform(1.8,3.5)
        tip=Vector((math.cos(angle)*rad,math.sin(angle)*rad,zz));trunk.cylinder((0,0,1.3),tip,.027,5,tip=.012)
        for q in range(5):
            offset=Vector((rr.uniform(-.35,.35),rr.uniform(-.35,.35),rr.uniform(-.2,.3)))
            scale=rr.uniform(.19,.40)
            crown.add([tuple(tip+offset+Vector((v.x*scale,v.y*scale*.88,v.z*scale*.80))) for v in spherev],spheref)
    ob1=trunk.finish(f'TREE{k} branches',branch,plants);ob2=crown.finish(f'TREE{k} fine canopy',leaf,plants,smooth=True)
    prototypes.append((ob1.data,ob2.data));bpy.data.objects.remove(ob1,do_unlink=True);bpy.data.objects.remove(ob2,do_unlink=True)
treepositions=[]
def tree(x,y,s):
    if top_v(x,y,3.8*s)<silhouette(x/WIDTH+.5)+.010:return
    if river_distance(x,y)<8.2:return
    if any(abs(x-a)<ww+.5 and abs(y-b)<dd+.5 for a,b,ww,dd in occupied):return
    if any((x-a)**2+(y-b)**2<1.7**2 for a,b in treepositions):return
    treepositions.append((x,y));idx=len(treepositions);meshpair=prototypes[idx%4];z=ground(x,y)
    for j,data in enumerate(meshpair):
        o=bpy.data.objects.new(f'T{idx:04d} '+('canopy' if j else 'branches'),data);plants.objects.link(o);o.location=(x,y,z);o.scale=(s,s,s);o.rotation_euler.z=idx*1.63
for i in range(2,len(river)-2,2):
    p=river[i];d=(river[i+1]-river[i-1]).normalized();n=Vector((-d.y,d.x))
    for side in [-1,1]:
        for layer in range(2):
            q=p+n*side*(10+layer*2.8);tree(q.x+random.uniform(-1,1),q.y+random.uniform(-1,1),random.uniform(.9,1.40))
for _ in range(1600):
    x=random.uniform(-215,229);y=random.uniform(-58,238)
    if random.random()<.64 and y<100:tree(x,y,random.uniform(.6,1.10))
    elif y>70:tree(x,y,random.uniform(.60,.95))

def area(name,location,target,power,size,color):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size;data.color=color
    ob=bpy.data.objects.new(name,data);lights.objects.link(ob);ob.location=location;ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
area('09 broad warm key',(-150,-120,170),(0,45,0),550000,90,(1,.95,.84))
area('09 neutral rim',(120,120,130),(0,20,5),400000,90,(.96,.98,1))
area('09 frontal bounce',(-20,-150,80),(20,40,5),20000,140,(1,.99,.97))
world=bpy.data.worlds.new('09 Neutral studio illumination');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.94,.96,1,1);world.node_tree.nodes['Background'].inputs[1].default_value=.16;scene.world=world

# Distant ground dissolves only at the unoccupied perimeter. Geometry itself has no depth fog.
n=groundmat.node_tree.nodes;l=groundmat.node_tree.links;p=n.get('Principled BSDF');out=n.get('Material Output')
geo=n.new('ShaderNodeNewGeometry');sep=n.new('ShaderNodeSeparateXYZ');l.new(geo.outputs['Position'],sep.inputs[0])
mapn=n.new('ShaderNodeMapRange');mapn.clamp=True;mapn.inputs['From Min'].default_value=42;mapn.inputs['From Max'].default_value=170;l.new(sep.outputs['Y'],mapn.inputs['Value'])
path=n.new('ShaderNodeLightPath');mul=n.new('ShaderNodeMath');mul.operation='MULTIPLY';l.new(path.outputs['Is Camera Ray'],mul.inputs[0]);l.new(mapn.outputs[0],mul.inputs[1])
transparent=n.new('ShaderNodeBsdfTransparent');mix=n.new('ShaderNodeMixShader');l.new(mul.outputs[0],mix.inputs[0]);l.new(p.outputs[0],mix.inputs[1]);l.new(transparent.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],out.inputs['Surface'])
scene.use_nodes=True;n=scene.node_tree.nodes;n.clear();l=scene.node_tree.links
rl=n.new('CompositorNodeRLayers');glow=n.new('CompositorNodeGlare');glow.glare_type='FOG_GLOW';glow.quality='HIGH';glow.threshold=3;glow.size=8;glow.mix=-.93
out=n.new('CompositorNodeComposite');l.new(rl.outputs['Image'],glow.inputs['Image']);l.new(glow.outputs['Image'],out.inputs[0])
scene['stage']='09 fixed-view reference reconstruction study; no cruise or image-plane city'
scene['reference']='4577477d-1f22-4956-9fc9-ccdafcbd3c00.png; visible composition only; not exact source geometry'
bpy.context.view_layer.update()
for a in landmarks:
    p=world_to_camera_view(scene,cam,Vector(a['world']));a['projected']=[p.x,1-p.y];a['error_px']=math.hypot((p.x-a['u'])*1672,((1-p.y)-a['top_v'])*941)
report=dict(stage='09',status='experimental; similarity must be visually reviewed',buildings=layout,tree_count=len(treepositions),light_buildings=len(lamps),
    camera=dict(position=list(cam.location),target=list(target),ortho_width=WIDTH,reference_size=[1672,941]),landmarks=landmarks,
    limits=['hidden geometry inferred','fixed camera alone does not change light transport','Cycles and runtime are separate validation targets'])
(ROOT/'city-09-fixed-plan.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
scene.render.filepath=str(ROOT/'renders'/'city-09-fixed.png');bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-09-fixed.blend'))
print('FIXED_SCENE_READY',len(layout),len(treepositions),flush=True)
if '--no-render' not in sys.argv:bpy.ops.render.render(write_still=True)
