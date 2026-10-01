"""Cycles scene from the same parcel/terrain export as the live 06 district viewer."""
import bpy,json,math,hashlib
from pathlib import Path
from mathutils import Matrix,Vector
ROOT=Path(__file__).resolve().parent
source=ROOT/'city-05.blend'
source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source))
scene=bpy.context.scene
plan=json.loads((ROOT/'city-06-plan.json').read_text(encoding='utf-8'))
original=json.loads((ROOT/'city-04-manifest.json').read_text(encoding='utf-8'))['buildings_layout']
objects=list(scene.objects)
library={}
for a in plan['assets']:
    if a['kind']=='tree':
        name=['Tree prototype 00','Tree prototype 03','Distant Tree prototype 0'][int(a['id'][-1])]
        library[a['id']]=bpy.data.collections[name]
        continue
    b=next(b for b in original if b['tag']==a['source_tag'])
    selected=[o for o in objects if o.type=='MESH' and o.name.startswith(b['tag']+' ')]
    floor=min((o.matrix_world @ Vector(c)).z for o in selected for c in o.bound_box)
    collection=bpy.data.collections.new('District asset '+a['id']);library[a['id']]=collection
    for o in selected:
        copy=o.copy();copy.data=o.data.copy();copy.animation_data_clear()
        copy.data.transform(Matrix.Translation(Vector((-b['x'],-b['y'],-floor))) @ o.matrix_world)
        copy.matrix_world=Matrix.Identity(4);collection.objects.link(copy)
for o in objects:
    if o.type in {'MESH','EMPTY'}:bpy.data.objects.remove(o,do_unlink=True)
for o in list(scene.objects):
    if o.type=='LIGHT' and 'recessed interior' in o.name:bpy.data.objects.remove(o,do_unlink=True)
district=bpy.data.collections.new('06 continuous district snapshot');scene.collection.children.link(district)
mats={
 'earth':bpy.data.materials['Seamless warm-white ground'],
 'stone':bpy.data.materials['Fine pale limestone'],
 'ceramic':bpy.data.materials['Ivory white architectural ceramic'],
 'water':bpy.data.materials['Pale river - physical reflection'],
 'foliage':bpy.data.materials['Matte white model foliage'],
}
def mat(name,color):
    m=bpy.data.materials.new(name);m.use_nodes=True
    p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=.85
    return m
mats['road']=mat('Pale stone streets',(.58,.60,.56));mats['garden']=mat('Recessed garden beds',(.65,.67,.60))
def mesh(name,vertices,faces,material):
    data=bpy.data.meshes.new(name);data.from_pydata(vertices,[],faces);data.update()
    obj=bpy.data.objects.new(name,data);district.objects.link(obj);data.materials.append(material);return obj
for surface in plan['surfaces']:
    mesh('District '+surface['material'],surface['vertices'],surface['faces'],mats[surface['material']])
cube_vertices=[(x,y,z) for z in [-.5,.5] for y in [-.5,.5] for x in [-.5,.5]]
cube_faces=[(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)]
cube_data=bpy.data.meshes.new('Shared district box');cube_data.from_pydata(cube_vertices,[],cube_faces);cube_data.materials.append(mats['ceramic'])
def box(name,p,size):
    o=bpy.data.objects.new(name,cube_data);district.objects.link(o);o.location=p;o.scale=size;return o
def instance(key,p,scale,yaw=0):
    o=bpy.data.objects.new('District '+key,None);o.instance_type='COLLECTION';o.instance_collection=library[key];district.objects.link(o);o.location=p;o.scale=scale;o.rotation_euler.z=-yaw;return o
for c in plan['chunks']:
    for b in c['buildings']:
        if b['lod']=='far':
            h=min(23,b['height']);box('Distant mass',(b['x'],b['y'],b['z']+h/2),(b['w'],b['d'],h))
            box('Distant crown',(b['x']-b['w']*.09,b['y']+b['d']*.08,b['z']+h+.45),(b['w']*.74,b['d']*.73,.9))
        else:
            instance(b['asset'],(b['modelX'],b['modelY'],b['z']),(b['sx'],b['sz'],b['sy']),b['yaw'])
            box('Building foundation',(b['x'],b['y'],b['z']-.3),(b['w'],b['d'],.6))
            if b['tall']:box('Tower podium',(b['x'],b['y'],b['z']+1.4),(b['w']*.98,b['d']*.98,2.8))
    for t in c['trees']:instance(t['asset'],(t['x'],t['y'],t['z']),(t['scale'],)*3)
    # Low planting is actual mesh, using a compact leaf cluster rather than billboard cards.
    for p in c['shrubs']:
        o=instance('tree_2',(p['x'],p['y'],p['z']-.1),(.35*p['scale'],.35*p['scale'],.09*p['scale']))
    for p in c['benches']:
        box('Riverside seat',(p['x'],p['y'],p['z']+.5),(2.4,.65,.12))
        for dx in [-.8,.8]:box('Seat leg',(p['x']+dx,p['y'],p['z']+.23),(.16,.5,.46))
        box('Seat back',(p['x'],p['y']+.28,p['z']+.8),(2.4,.1,.12))
    for x,y,z in c.get('bridgeRail',[]):box('Bridge rail post',(x,y,z+.45),(.08,.08,.9))

key=bpy.data.lights['Large soft daylight key'];key.energy=500000;key.size=90
key_object=next(o for o in scene.objects if o.type=='LIGHT' and o.data==key)
key_object.location=(-220,80,190)
key_object.rotation_euler=(Vector((0,55,8))-key_object.location).to_track_quat('-Z','Y').to_euler()
bpy.data.lights['Cool broad fill'].energy=18000
bpy.data.lights['Soft daylight direction'].energy=.4
for n in scene.world.node_tree.nodes:
    if n.type=='BACKGROUND' and n.inputs['Strength'].default_value<1:n.inputs['Strength'].default_value=.22
warm=bpy.data.materials['Recessed warm ceiling - real emission'].node_tree.nodes.get('Principled BSDF')
warm.inputs['Emission Color'].default_value=(1,.56,.27,1);warm.inputs['Emission Strength'].default_value=3.2
scene.camera.animation_data_clear()
scene['stage']='06 experimental continuous districts at distance zero; visual acceptance pending'
scene['source']='city-06-plan.json; same parcel positions as v13. Small shrub mesh differs from realtime.'
scene.render.resolution_x=2560;scene.render.resolution_y=1415;scene.render.resolution_percentage=100;scene.cycles.samples=128
scene.render.filepath=str(ROOT/'renders'/'city-06-districts.png')
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for d in prefs.devices:d.use=d.type=='OPTIX'
scene.cycles.device='GPU';scene.cycles.use_denoising=True
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-06-districts.blend'))
bpy.ops.render.render(write_still=True)
report={'source_sha256':source_hash,'plan_sha256':hashlib.sha256((ROOT/'city-06-plan.json').read_bytes()).hexdigest(),
 'buildings':sum(len(c['buildings']) for c in plan['chunks']),'trees':sum(len(c['trees']) for c in plan['chunks']),
 'camera':plan['view'],'samples':128,'resolution':[2560,1415],'stage':'experimental, not integrated',
 'differences':'Cycles uses original beveled assets and a different low-shrub cluster, while WebGL uses lighter exported assets; same building placements, trees and surface coordinates.'}
(ROOT/'city-06-cycles-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('DISTRICT_CYCLES_COMPLETE',report['buildings'],report['trees'],flush=True)
