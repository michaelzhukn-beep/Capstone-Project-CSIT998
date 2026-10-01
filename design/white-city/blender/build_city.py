"""Editable architectural model; all visible city content is real geometry.

Blender 4.5 LTS: blender -b --python build_city.py -- --draft
No screenshot planes, image textures, AI depth reprojection or image deformation.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT = Path(__file__).resolve().parent
ARGS = argparse.ArgumentParser()
ARGS.add_argument('--draft', action='store_true')
ARGS.add_argument('--no-render', action='store_true')
ARGS.add_argument('--cpu', action='store_true')
ARGS.add_argument('--name', default='city-01')
ARGS.add_argument('--refine', action='store_true')
ARGS.add_argument('--diverse', action='store_true')
ARGS.add_argument('--curated', action='store_true')
options = ARGS.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
if not options.name.replace('-', '').isalnum():
    raise ValueError('Output name must contain only letters, digits and hyphens')
if options.refine and options.name=='city-01':
    raise ValueError('Preserve the accepted city-01 baseline; use --name city-02 with --refine')
if options.diverse and (not options.refine or options.name in ('city-01','city-02')):
    raise ValueError('Diversity requires --refine and a new output name such as city-03')
if options.curated and (not options.diverse or options.name in ('city-01','city-02','city-03')):
    raise ValueError('Curated composition requires --diverse and a new name such as city-04')
sys.path.insert(0,str(ROOT))
rng = random.Random(84)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 32 if options.draft else 128
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 10
scene.cycles.diffuse_bounces = 5
scene.cycles.glossy_bounces = 5
scene.cycles.transmission_bounces = 8
scene.cycles.transparent_max_bounces = 8
scene.cycles.adaptive_threshold = 0.035 if options.draft else 0.015
scene.render.resolution_x = 1400 if options.draft else 2560
scene.render.resolution_y = 788 if options.draft else 1440
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.fps = 24
scene.frame_start, scene.frame_end = 1, 240
scene.view_settings.view_transform = 'AgX'
scene.view_settings.look = 'AgX - Medium High Contrast'
scene.view_settings.exposure = 1.0
devices = []
if not options.cpu:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    try:
        prefs.compute_device_type = 'OPTIX'
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == 'OPTIX'
            if device.use:
                devices.append(device.name)
        if devices:
            scene.cycles.device = 'GPU'
    except Exception as error:
        print('GPU setup fallback:', error)
print('RENDER_DEVICE', devices or ['CPU'], flush=True)

def collection(name):
    item = bpy.data.collections.new(name)
    scene.collection.children.link(item)
    return item

landscape = collection('01 Landscape and river')
architecture = collection('02 Architecture - editable building meshes')
vegetation = collection('03 Trees - linked geometric instances')
lighting = collection('04 Lighting - daylight and real interior emitters')
cameras = collection('05 Cameras')

def material(name, color, roughness=0.5, metallic=0.0, transmission=0.0, emission=None):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Transmission Weight'].default_value = transmission
    if transmission:
        bsdf.inputs['IOR'].default_value = 1.45
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*emission[0], 1)
        bsdf.inputs['Emission Strength'].default_value = emission[1]
    return mat

porcelain = material('Ivory white architectural ceramic', (0.79, 0.80, 0.775), 0.42)
limestone = material('Fine pale limestone', (0.73, 0.735, 0.70), 0.65)
glass = material('Recessed neutral low-iron glazing', (0.78, 0.83, 0.81), 0.13, transmission=0.72)
frame_mat = material('White satin metal mullions', (0.69, 0.715, 0.70), 0.32, metallic=0.12)
leaf_mat = material('Matte white model foliage', (0.77, 0.785, 0.75), 0.72)
bark_mat = material('Pale miniature branches', (0.53, 0.55, 0.51), 0.8)
earth_mat = material('Seamless warm-white ground', (0.79, 0.785, 0.75), 0.72)
warm_mat = material('Recessed warm ceiling - real emission', (0.86, 0.78, 0.63), 0.6,
                    emission=((1.0, 0.76, 0.43), 2.5))
water_mat = material('Pale river - physical reflection', (0.46, 0.56, 0.53), 0.16, metallic=0.16, transmission=0.22)
nodes = water_mat.node_tree.nodes
noise = nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 160
noise.inputs['Detail'].default_value = 2
bump = nodes.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = 0.13
bump.inputs['Distance'].default_value = 0.03
water_mat.node_tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
water_mat.node_tree.links.new(bump.outputs['Normal'], nodes.get('Principled BSDF').inputs['Normal'])

class Mesh:
    def __init__(self):
        self.vertices, self.faces = [], []

    def add(self, vertices, faces):
        offset = len(self.vertices)
        self.vertices.extend(vertices)
        self.faces.extend(tuple(offset + i for i in face) for face in faces)

    def box(self, center, size):
        x, y, z = center
        a, b, c = (v / 2 for v in size)
        self.add([(x-a,y-b,z-c),(x+a,y-b,z-c),(x+a,y+b,z-c),(x-a,y+b,z-c),
                  (x-a,y-b,z+c),(x+a,y-b,z+c),(x+a,y+b,z+c),(x-a,y+b,z+c)],
                 [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])

    def cylinder(self, start, end, radius, sides=8, tip=None):
        start, end = Vector(start), Vector(end)
        rotation = (end-start).to_track_quat('Z', 'Y')
        tip = radius if tip is None else tip
        vertices = []
        for origin, r in [(start, radius), (end, tip)]:
            for i in range(sides):
                angle = i * math.tau / sides
                vertices.append(tuple(origin + rotation @ Vector((math.cos(angle)*r, math.sin(angle)*r, 0))))
        faces = [tuple(reversed(range(sides))), tuple(range(sides, sides*2))]
        faces += [(i,(i+1)%sides,(i+1)%sides+sides,i+sides) for i in range(sides)]
        self.add(vertices, faces)

    def finish(self, name, mat, group, bevel=0.0, smooth=False):
        if not self.vertices:
            return None
        data = bpy.data.meshes.new(name)
        data.from_pydata(self.vertices, [], self.faces)
        data.materials.append(mat)
        data.update()
        obj = bpy.data.objects.new(name, data)
        group.objects.link(obj)
        if bevel:
            mod = obj.modifiers.new('Real edge radii', 'BEVEL')
            mod.width, mod.segments = bevel, 3
            mod.limit_method = 'ANGLE'
            mod = obj.modifiers.new('Architectural face normals', 'WEIGHTED_NORMAL')
            mod.keep_sharp = True
        for face in data.polygons:
            face.use_smooth = smooth
        return obj

def area(name, location, target, power, size, color=(1.0, 0.96, 0.89), size_y=None):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy, data.color, data.size = power, color, size
    if size_y is not None:
        data.shape, data.size_y = 'RECTANGLE', size_y
    obj = bpy.data.objects.new(name, data)
    lighting.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z', 'Y').to_euler()
    return obj

def ground_z(x, y):
    return 0.7 + 0.035*max(y-22, 0) + 17*(max(x+5, 0)/190)**1.6

# Catmull-Rom river: lower-right foreground to the left rear, not a rectangular canal.
river_control = [(235,-100),(175,-75),(90,-43),(20,-17),(-39,4),(-73,31),(-108,69),(-155,118),(-218,163)]
river = []
for index in range(len(river_control)-1):
    p0 = Vector(river_control[max(0,index-1)])
    p1 = Vector(river_control[index])
    p2 = Vector(river_control[index+1])
    p3 = Vector(river_control[min(len(river_control)-1,index+2)])
    for j in range(18):
        t = j/18
        river.append(0.5*((2*p1)+(-p0+p2)*t+(2*p0-5*p1+4*p2-p3)*t*t+(-p0+3*p1-3*p2+p3)*t*t*t))
river.append(Vector(river_control[-1]))
normals = []
for i in range(len(river)):
    d = (river[min(i+1,len(river)-1)]-river[max(i-1,0)]).normalized()
    normals.append(Vector((-d.y,d.x)))
layout=None
if options.diverse:
    from city_layout import Layout
    layout=Layout(river,normals)

def river_distance(x, y):
    p = Vector((x, y))
    return min((p-center).length for center in river)

# Dense ground surface is lowered beneath actual water; banks and distant hills are geometry.
terrain = Mesh()
count_x, count_y = 170, 155
for j in range(count_y+1):
    y = -150 + j*3
    for i in range(count_x+1):
        x = -260 + i*3
        distance = river_distance(x, y)
        shore = min(1, max(0, (distance-17)/6))
        z = -2 + (ground_z(x,y)+2)*shore
        terrain.vertices.append((x,y,z))
for j in range(count_y):
    for i in range(count_x):
        k = j*(count_x+1)+i
        terrain.faces.append((k,k+1,k+count_x+2,k+count_x+1))
terrain.finish('Sculpted river valley and rising urban terrain', earth_mat, landscape, smooth=True)
base = Mesh(); base.box((0,20,-3.3),(2400,2400,2)); base.finish('Continuous ground beyond camera', earth_mat, landscape)

def ribbon(name, a, b, z, mat):
    mesh = Mesh()
    for p,n in zip(river,normals):
        for width in [a,b]:
            q = p+n*width
            height = z(q.x,q.y) if callable(z) else z
            mesh.vertices.append((q.x,q.y,height))
    for i in range(len(river)-1):
        mesh.faces.append((2*i,2*i+1,2*i+3,2*i+2))
    return mesh.finish(name, mat, landscape)

ribbon('River surface - reflective geometry', -19.5,19.5,0.1,water_mat)
for sign in [-1,1]:
    ribbon('Continuous riverside promenade '+str(sign), sign*20,sign*24, lambda x,y: ground_z(x,y)+0.05, limestone)
    ribbon('Limestone river edge '+str(sign), sign*19.5,sign*20, lambda x,y: ground_z(x,y)+0.11, porcelain)

def bridge(index=77):
    center, direction = river[index], normals[index]
    cross = Vector((-direction.y,direction.x))
    mesh = Mesh()
    steps, span, width = 48, 52, 5.0
    def point(t, side, down=0):
        xy = center+direction*((t-.5)*span)+cross*side
        if options.diverse:
            a=center-direction*span/2; b=center+direction*span/2
            z=(1-t)*(ground_z(a.x,a.y)+.12)+t*(ground_z(b.x,b.y)+.12)+3.1*math.sin(math.pi*t)-down
        else:
            z = 2.2+3.1*math.sin(math.pi*t)-down
        return (xy.x,xy.y,z)
    for j in range(steps+1):
        for side,down in [(-width/2,0),(width/2,0),(-width/2,.38),(width/2,.38)]:
            mesh.vertices.append(point(j/steps,side,down))
    for j in range(steps):
        k = 4*j
        mesh.faces += [(k,k+4,k+5,k+1),(k+2,k+3,k+7,k+6),(k,k+2,k+6,k+4),(k+1,k+5,k+7,k+3)]
    for sign in [-1,1]:
        for j in range(steps):
            a=Vector(point(j/steps,sign*width/2)); b=Vector(point((j+1)/steps,sign*width/2))
            mesh.cylinder(a+Vector((0,0,.9)),b+Vector((0,0,.9)),.065,8)
        for j in range(0,steps+1,3):
            a=Vector(point(j/steps,sign*width/2))
            mesh.cylinder(a,a+Vector((0,0,.9)),.048,6)
    for t in [.24,.76]:
        p=point(t,0)
        mesh.box((p[0],p[1],(p[2]-2)/2),(1.0,2.7,p[2]+2))
    mesh.finish('Slender arched bridge - deck rails and piers',porcelain,landscape,bevel=.025)
bridge()

footprints=[]
building_tops=[]
building_records=[]
build_count=0

def building(x,y,w,d,h,kind='tower',lit=False,seed=0,relocate=False):
    global build_count
    if layout:
        parcel=layout.place(x,y,w,d,relocate)
        if parcel is None:
            return False
        x,y=parcel
    lod='near'
    form=kind
    if options.diverse:
        distance=math.hypot(x-55,y+340)
        lod='near' if lit or (distance<440 and y<100) else 'mid' if distance<560 else 'far'
        if kind=='tower':
            form={0:'tower',1:'rounded',2:'stepped'}[seed%3]
        elif kind=='terrace':
            form=['terrace','courtyard','slab','gabled'][seed%4]
            if form=='gabled' and h>11:
                form='slab'
    if options.curated:
        from city_composition import choose_form
        form=choose_form(kind,h,x,y,seed,building_records)
    local=random.Random(seed)
    build_count+=1
    tag=f'{build_count:03d} {kind}'
    z=max(ground_z(x+sx*w/2,y+sy*d/2) for sx in [-1,1] for sy in [-1,1])+.12
    stone,glazing,metal,emit=Mesh(),Mesh(),Mesh(),Mesh()
    low=min(ground_z(x+sx*w/2,y+sy*d/2) for sx in [-1,1] for sy in [-1,1])
    stone.box((x,y,(z+low)/2),(w+.7,d+.7,max(.25,z-low)))
    if options.diverse and (lod!='near' or form not in ('tower','terrace','pavilion')):
        from city_typologies import model_form
        model_form(globals(),stone,glazing,metal,x,y,z,w,d,h,form,lod)
    elif kind=='pavilion':
        roof=5.1
        if options.refine:
            # Four roof pieces leave a genuine skylight opening through the slab.
            ox,oy,ow,od=x-w*.18,y+d*.12,w*.33,d*.35
            left,right=x-(w+3)/2,x+(w+3)/2
            front,back=y-(d+2)/2,y+(d+2)/2
            for a,b in [(left,ox-ow/2),(ox+ow/2,right)]:
                stone.box(((a+b)/2,y,z+roof),(b-a,d+2,.5))
            for a,b in [(front,oy-od/2),(oy+od/2,back)]:
                stone.box((ox,(a+b)/2,z+roof),(ow,b-a,.5))
        else:
            stone.box((x,y,z+roof),(w+3,d+2,.5))
        stone.box((x,y,z+.18),(w+1,d+1,.36))
        glazing.box((x,y,z+roof/2),(w-.5,d-.5,roof-.5))
        for side in [-1,1]:
            for j in range(int(w/2.4)+1):
                px=x-w/2+j*w/int(w/2.4)
                stone.box((px,y+side*d/2,z+roof/2),(.18,.24,roof))
            for j in range(1,int(d/2.4)):
                py=y-d/2+j*d/int(d/2.4)
                metal.box((x+side*w/2,py,z+roof/2),(.13,.15,roof))
        stone.box((x,y+d*.26,z+roof/2),(w*.86,.38,roof))
        h=roof+.25
    else:
        floors=max(2,round(h/3.1))
        floor_h=h/floors
        setback=kind=='terrace'
        for level in range(floors):
            step=max(0,level-floors//2)*.68 if setback else (max(0,level-floors+3)*.4 if seed%3==1 else 0)
            ww,dd=w-step*2,d-step*1.6
            zz=z+level*floor_h
            if kind!='tower':
                stone.box((x,y,zz+.16),(ww+.4,dd+.4,.30))
            # Mostly ceramic wall area, with narrow inset glazing: not a grey glass curtain wall.
            stone.box((x,y,zz+floor_h/2),(ww-.30,dd-.30,floor_h if kind=='tower' else floor_h-.22))
            for side in [-1,1]:
                for j in range(max(2,round(ww/2.5))):
                    px=x-ww*.4+j*ww*.8/max(1,round(ww/2.5)-1)
                    glazing.box((px,y+side*(dd/2-.08),zz+floor_h/2),(.72 if options.refine and kind!='tower' else .38,.05,floor_h if kind=='tower' else floor_h-.75))
                for j in range(max(2,round(dd/2.5))):
                    py=y-dd*.4+j*dd*.8/max(1,round(dd/2.5)-1)
                    glazing.box((x+side*(ww/2-.08),py,zz+floor_h/2),(.05,.72 if options.refine and kind!='tower' else .38,floor_h if kind=='tower' else floor_h-.75))
            for side in [-1,1]:
                bay=(1.35 if options.refine and seed%3==0 else 1.0) if kind=='tower' else 2.5
                n=max(3,round(ww/bay))
                for j in range(n+1):
                    px=x-ww/2+j*ww/n
                    thickness=.16 if kind=='tower' else .25
                    stone.box((px,y+side*dd/2,zz+floor_h/2),(thickness,.34,floor_h))
                n=max(3,round(dd/bay))
                for j in range(n+1):
                    py=y-dd/2+j*dd/n
                    stone.box((x+side*ww/2,py,zz+floor_h/2),(.34,.17 if kind=='tower' else .25,floor_h))
            if kind!='tower':
                stone.box((x,y-dd/2-.42,zz+.3),(ww+1,1.2,.19))
        step=max(0,floors-1-floors//2)*.68 if setback else 0
        ww,dd=w-step*2,d-step*1.6
        stone.box((x,y,z+h+.2),(ww+.6,dd+.6,.4))
        # Roof crown, parapets and rooftop service elements are real geometry.
        for side in [-1,1]:
            stone.box((x,y+side*dd/2,z+h+.7),(ww,.22,1.0))
            stone.box((x+side*ww/2,y,z+h+.7),(.22,dd,1.0))
        stone.box((x+w*.1,y+d*.1,z+h+1.0),(ww*.36,dd*.35,1.6))
        if kind=='tower':
            stone.box((x,y,z+h+1.3),(ww*.78,dd*.78,1.8))
            stone.box((x,y,z+h+2.5),(ww*.62,dd*.6,.7))
    if lit:
        emit.box((x,y,z+2.8),(w*.67,d*.55,.08))
        area(tag+' recessed interior', (x,y,z+2.65),(x,y,z), 125 if kind=='pavilion' else 70,w*.65,(1,.79,.51),d*.55)
        # Walls obstruct the emitter: warm illumination comes through glazing and openings.
        stone.box((x,y+d*.32,z+1.4),(w*.8,.2,2.8))
    structure=stone.finish(tag+' ceramic structure',porcelain,architecture,bevel=.045 if lod=='near' else .025 if lod=='mid' else 0)
    structure['building_form']=form
    structure['detail_level']=lod
    structure['parcel_center']=[x,y]
    structure['footprint_size']=[w,d]
    glazing.finish(tag+' recessed glass',glass,architecture,bevel=.018 if lod=='near' else 0)
    metal.finish(tag+' fine frames',frame_mat,architecture,bevel=.014 if lod=='near' else 0)
    emit.finish(tag+' interior ceiling',warm_mat,architecture)
    footprints.append((x,y,w/2+2.1,d/2+2.1))
    building_tops.append(Vector((x,y,z+h+3)))
    building_records.append(dict(x=x,y=y,z=z,w=w,d=d,h=h,kind=kind,seed=seed,tag=tag,lod=lod,form=form))
    return True

# Deliberately placed foreground and skyline groups, rather than repeating a city grid.
hero_buildings=[
    (-148,-24,17,12,43,'tower',False),(-123,-16,15,12,35,'tower',False),
    (-103,-13,24,14,5,'pavilion',True),(-82,0,18,14,14,'terrace',False),
    (-39,29,26,15,5,'pavilion',True),(-7,27,22,16,11,'terrace',False),
    (25,18,29,17,5,'pavilion',True),(61,5,22,16,13,'terrace',False),
    (95,-4,29,19,5,'pavilion',True),(126,13,25,18,12,'terrace',False),
    (4,59,13,12,43,'tower',False),(27,66,15,12,53,'tower',True),
    (50,50,23,17,18,'terrace',False),(79,42,14,12,38,'tower',False),
    (100,65,17,13,58,'tower',False),(124,76,14,12,72,'tower',False),
    (150,91,16,13,60,'tower',False),(177,77,14,13,45,'tower',False),
    (156,37,30,20,5,'pavilion',True),(-91,40,17,15,20,'terrace',False),
    (-131,75,13,12,37,'tower',False),(-105,87,14,13,31,'tower',False),
    (-177,-59,26,20,5,'pavilion',False),(173,-50,25,18,5,'pavilion',False),
    (-116,-61,31,20,5,'pavilion',True),(-60,-62,22,17,8,'terrace',False),
]
for i, entry in enumerate(hero_buildings):
    building(*entry,seed=i,relocate=options.diverse)

for row in range(6):
    for column in range(12):
        x=-185+column*33+rng.uniform(-7,7)
        y=40+row*31+rng.uniform(-7,7)
        if not options.diverse and river_distance(x,y)<28:
            continue
        w,d=rng.uniform(12,22),rng.uniform(10,17)
        if any(abs(x-bx)<w/2+bw+4 and abs(y-by)<d/2+bd+4 for bx,by,bw,bd in footprints):
            continue
        h=rng.uniform(6,16)
        kind='terrace'
        if (x>60 and y>85 and rng.random()<.25) or (x<-100 and y>60 and rng.random()<.16):
            h=rng.uniform(28,48); kind='tower'; w=min(w,15)
        building(x,y,w,d,h,kind,False,row*100+column)
if options.diverse:
    # Small distant volumes fill the city beyond the detailed waterfront, at low mesh cost.
    fill_rng=random.Random(303)
    for row in range(10):
        for column in range(20):
            x=-235+column*24+fill_rng.uniform(-3,3)
            y=65+row*25+fill_rng.uniform(-3,3)
            w,d=fill_rng.uniform(10,16),fill_rng.uniform(9,15)
            h=fill_rng.uniform(7,20)
            kind='terrace'
            if y>150 and x>65 and fill_rng.random()<.13:
                kind='tower';h=fill_rng.uniform(25,42)
            building(x,y,w,d,h,kind,False,1000+row*20+column)
    for row in range(2):
        for column in range(10):
            x=-200+column*43+fill_rng.uniform(-6,6)
            y=-93+row*35+fill_rng.uniform(-4,4)
            building(x,y,fill_rng.uniform(16,24),fill_rng.uniform(10,15),fill_rng.uniform(6,11),'terrace',False,2000+row*10+column)
print('BUILDINGS',build_count,flush=True)

# Eight geometric tree prototypes; their collections are instanced, never image billboards.
ico=bmesh.new()
bmesh.ops.create_icosphere(ico,subdivisions=2,radius=1)
ico.verts.ensure_lookup_table()
ico_data=[tuple(v.co) for v in ico.verts]
ico_faces=[tuple(v.index for v in face.verts) for face in ico.faces]
ico.free()
tree_collections=[]
for variant in range(8):
    local=random.Random(variant+150)
    group=bpy.data.collections.new(f'Tree prototype {variant:02d}')
    branches,crown=Mesh(),Mesh()
    branches.cylinder((0,0,0),(0,0,3.2),.095,9,.045)
    for branch in range(9):
        angle=branch*2.399+local.uniform(-.3,.3)
        length=local.uniform(1.15,2.05) * (.92 if options.refine else 1)
        tip=Vector((math.cos(angle)*length,math.sin(angle)*length,local.uniform(3.2,5.1)))
        start=Vector((0,0,local.uniform(1.3,2.8)))
        branches.cylinder(start,tip,.045,7,.015)
        for twig in range(3):
            end=tip+Vector((local.uniform(-.65,.65),local.uniform(-.65,.65),local.uniform(-.1,.7)))
            branches.cylinder(tip,end,.019,6,.008)
            for leaf in range(4):
                p=end+Vector((local.uniform(-.45,.45),local.uniform(-.45,.45),local.uniform(-.25,.45)))
                radius=local.uniform(.30,.56) * (1.14 if options.refine else 1)
                verts=[]
                for k,(a,b,c) in enumerate(ico_data):
                    jitter=1+local.uniform(-.13,.13)
                    verts.append(tuple(p+Vector((a*radius*jitter,b*radius*jitter,c*radius*jitter*.85))))
                crown.add(verts,ico_faces)
    branches.finish(f'Branch structure {variant}',bark_mat,group,smooth=True)
    crown.finish(f'Fine canopy clusters {variant}',leaf_mat,group,smooth=True)
    tree_collections.append(group)

trees=[]
far_tree_collections=[]
if options.diverse:
    for variant in range(3):
        group=bpy.data.collections.new(f'Distant Tree prototype {variant}')
        trunk,crown=Mesh(),Mesh()
        trunk.cylinder((0,0,0),(0,0,3.5),.10,6,.035)
        for i in range(7):
            angle=i*2.399
            p=Vector((math.cos(angle)*1.0,math.sin(angle)*1.0,3.5+(i%3)*.40))
            crown.add([tuple(p+Vector((a*.9,b*.9,c*1.05))) for a,b,c in ico_data],ico_faces)
        trunk.finish(f'Distant tree trunk {variant}',bark_mat,group)
        crown.finish(f'Distant tree canopy {variant}',leaf_mat,group,smooth=True)
        far_tree_collections.append(group)
def tree(x,y,scale=1):
    if layout and not layout.bridge_clear(x,y,4.5*scale):
        return
    if any(abs(x-bx)<bw+1.0 and abs(y-by)<bd+1.0 for bx,by,bw,bd in footprints):
        return
    if river_distance(x,y)<26:
        return
    obj=bpy.data.objects.new(f'Tree {len(trees):04d}',None)
    obj.instance_type='COLLECTION'
    obj.instance_collection=tree_collections[rng.randrange(len(tree_collections))]
    if far_tree_collections and y>130:
        obj.instance_collection=far_tree_collections[len(trees)%3]
    obj.location=(x,y,ground_z(x,y))
    obj.scale=(scale,scale,scale*rng.uniform(.9,1.13))
    obj.rotation_euler.z=rng.uniform(0,math.tau)
    vegetation.objects.link(obj)
    trees.append((x,y))

for i in range(3,len(river)-3,2):
    for sign in [-1,1]:
        p=river[i]+normals[i]*(sign*rng.uniform(27,31))
        tree(p.x,p.y,rng.uniform(.95,1.55))
        if rng.random()<.7:
            q=p+normals[i]*(sign*rng.uniform(3,7))
            tree(q.x,q.y,rng.uniform(.9,1.3))
for _ in range(120):
    tree(rng.uniform(-170,160),rng.uniform(-118,-60),rng.uniform(1.25,1.75))
for _ in range(850):
    x,y=rng.uniform(-210,210),rng.uniform(-60,240)
    if any((x-tx)**2+(y-ty)**2<7 for tx,ty in trees):
        continue
    tree(x,y,rng.uniform(.6,1.05))
print('TREE_INSTANCES',len(trees),flush=True)
detail_report={}
if options.refine:
    sys.path.insert(0,str(ROOT))
    from city_details import add_details
    detail_report=add_details(globals())

world=bpy.data.worlds.new('Neutral studio environment')
scene.world=world
world.use_nodes=True
wn=world.node_tree.nodes
wn.clear()
ambient=wn.new('ShaderNodeBackground'); ambient.inputs['Color'].default_value=(.92,.95,1,1); ambient.inputs['Strength'].default_value=.25
camera_bg=wn.new('ShaderNodeBackground'); camera_bg.inputs['Color'].default_value=(1,.985,.96,1); camera_bg.inputs['Strength'].default_value=3.0
ray=wn.new('ShaderNodeLightPath'); mix=wn.new('ShaderNodeMixShader'); out=wn.new('ShaderNodeOutputWorld')
world.node_tree.links.new(ray.outputs['Is Camera Ray'],mix.inputs[0])
world.node_tree.links.new(ambient.outputs[0],mix.inputs[1]); world.node_tree.links.new(camera_bg.outputs[0],mix.inputs[2]); world.node_tree.links.new(mix.outputs[0],out.inputs[0])
area('Large soft daylight key',(-155,-25,170),(0,55,0),500000,70,(1,.98,.94))
area('Cool broad fill',(125,55,150),(0,55,15),15000,120,(.91,.95,1))
sun=bpy.data.lights.new('Soft daylight direction','SUN'); sun.energy=.55; sun.angle=math.radians(12)
sun_obj=bpy.data.objects.new('Soft daylight direction',sun); lighting.objects.link(sun_obj)
sun_obj.rotation_euler=(math.radians(24),math.radians(-28),math.radians(-32))

def camera(name, location, target, lens):
    data=bpy.data.cameras.new(name)
    obj=bpy.data.objects.new(name,data)
    cameras.objects.link(obj)
    obj.location=location
    obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
    data.lens=lens
    data.clip_end=3000
    return obj

cam=camera('Hero camera - editable real perspective',(55,-340,104),(0,50,10),38)
scene.camera=cam
bpy.context.view_layer.update()
# Reserve upper space for actual HTML copy. Use projected building tops to solve lens shift.
tops=[world_to_camera_view(scene,cam,p).y for p in building_tops if 0 < world_to_camera_view(scene,cam,p).x < 1]
top=max(tops)
cam.data.shift_y=.01
delta=world_to_camera_view(scene,cam,building_tops[0]).y
cam.data.shift_y=0
delta-=world_to_camera_view(scene,cam,building_tops[0]).y
cam.data.shift_y=.1288812756538391 if options.diverse else (.64-top)/(delta/.01)
cam['purpose']='Primary composition based on approved reference; no image projection'
cam['computed_vertical_shift']=cam.data.shift_y
camera('Inspection camera - confirms full 3D',(220,-130,180),(5,65,15),42)
camera('Waterfront detail camera',(50,-78,28),(20,28,8),52)
if options.diverse:
    plan=camera('Layout camera - plan check',(0,65,600),(0,65,0),42)
    plan.data.type='ORTHO'
    plan.data.ortho_scale=620

# Genuine camera translation, saved for later motion work; rendering approval uses frame 1 only.
cam.keyframe_insert(data_path='location',frame=1)
cam.location.x+=8
cam.keyframe_insert(data_path='location',frame=240)
scene.frame_set(1)
scene['stage']='in progress: actual modeled scene; 01 accepted as direction, refinements pending review'
if options.diverse:
    scene['stage']='in progress: 03 layout and building variety; 02 Cycles lighting accepted, 03 visual review pending'
if options.curated:
    scene['stage']='in progress: 04 neighbour-aware architectural composition and streaming asset source; visual review pending'
scene['reference']='../assets/city-still-01.png (visual reference only; never loaded as a scene texture)'
scene['building_count']=build_count
scene['tree_instances']=len(trees)
scene['render_devices']=', '.join(devices) or 'CPU'
# Depth-based atmospheric perspective, derived from rendered geometry (no backdrop image).
scene.view_layers[0].use_pass_z=True
scene.use_nodes=True
cn=scene.node_tree.nodes
cn.clear()
render=cn.new('CompositorNodeRLayers')
depth=cn.new('CompositorNodeMapRange')
depth.inputs['From Min'].default_value=460
depth.inputs['From Max'].default_value=900
depth.inputs['To Min'].default_value=0
depth.inputs['To Max'].default_value=1
depth.use_clamp=True
fog=cn.new('CompositorNodeMixRGB'); fog.blend_type='MIX'
fog.inputs[2].default_value=(3,2.955,2.88,1)
output=cn.new('CompositorNodeComposite')
scene.node_tree.links.new(render.outputs['Depth'],depth.inputs[0])
scene.node_tree.links.new(depth.outputs[0],fog.inputs[0])
scene.node_tree.links.new(render.outputs['Image'],fog.inputs[1])
scene.node_tree.links.new(fog.outputs[0],output.inputs[0])
scene.render.filepath=str(ROOT/'renders'/f'{options.name}{"-draft" if options.draft else ""}.png')
(ROOT/'renders').mkdir(exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/f'{options.name}.blend'))
manifest={'stage':'actual 3D scene, visual acceptance pending','buildings':build_count,'tree_instances':len(trees),
          'render_engine':'Cycles','device':devices or ['CPU'],'samples':scene.cycles.samples,
          'resolution':[scene.render.resolution_x,scene.render.resolution_y],
          'image_texture_nodes':sum(node.type=='TEX_IMAGE' for mat in bpy.data.materials if mat.use_nodes for node in mat.node_tree.nodes),'camera_shift_y':cam.data.shift_y,
          'object_count':len(scene.objects),'reference_asset_sha256':'A40E4BB3DAD43E3E6F0E57794C0F43F36AA70C26A96F078977AFF52B3C76C97E',
          'refinement_details':detail_report}
if layout:
    from collections import Counter
    manifest['building_forms']=dict(Counter(b['form'] for b in building_records))
    manifest['detail_levels']=dict(Counter(b['lod'] for b in building_records))
    manifest['relocated_buildings']=layout.moves
    manifest['buildings_layout']=building_records
    manifest['detail_policy']='Authored for the fixed hero camera; near/mid/far meshes, not runtime distance switching'
    if options.curated:
        manifest['composition_policy']='Neighbour-aware form selection with 110m repetition penalty; no whole-district copies'
manifest_name='scene-manifest.json' if options.name=='city-01' else f'{options.name}-manifest.json'
(ROOT/manifest_name).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('SCENE_SAVED',ROOT/f'{options.name}.blend',flush=True)
if not options.no_render:
    bpy.ops.render.render(write_still=True)
    print('RENDER_COMPLETE',scene.render.filepath,flush=True)
