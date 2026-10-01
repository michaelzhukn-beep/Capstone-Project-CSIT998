"""14 fixed-camera studio: satin whites, broad softboxes, concealed warm bounce."""
import bpy, json, hashlib, struct, math, sys
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

ROOT=Path(__file__).resolve().parent
source=ROOT/'city-13-smooth.blend'
source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
plan=json.loads((ROOT/'city-13-smooth-plan.json').read_text(encoding='utf-8'))
spec=json.loads((ROOT/'city-14-locked-camera.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(source));scene=bpy.context.scene

def fingerprint():
    result={}
    for ob in scene.objects:
        if ob.type!='MESH':continue
        h=hashlib.sha256()
        for row in ob.matrix_world:h.update(struct.pack('<4d',*row))
        for v in ob.data.vertices:h.update(struct.pack('<3f',*v.co))
        for p in ob.data.polygons:h.update(struct.pack('<'+'I'*len(p.vertices),*p.vertices))
        result[ob.name]=h.hexdigest()
    return result
before=fingerprint()
camera=bpy.data.objects['13 Selected composition'];scene.camera=camera
camera.location=spec['position']
camera.rotation_euler=(Vector(spec['target'])-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO';camera.data.clip_end=3000
camera.data.ortho_scale=spec['captured_frustum_width']/spec['zoom']
scene.render.resolution_x=1883;scene.render.resolution_y=1054;scene.render.resolution_percentage=100
bpy.context.view_layer.update()

# Linear reflectances: whites stay distinct instead of clipping all faces to one value.
settings={
 '13 White clay':((.914,.900,.870),.63,.32),
 '13 Roof and stone':((.945,.932,.903),.68,.28),
 '13 Recessed white panels':((.820,.840,.817),.44,.38),
 '13 Pavement':((.870,.874,.850),.75,.25),
 '13 Still water':((.790,.837,.821),.26,.42),
 '13 Tree crowns':((.925,.925,.898),.77,.24),
 '13 Branches':((.725,.736,.704),.78,.22),
}
for name,(color,rough,specular) in settings.items():
    m=bpy.data.materials[name];m.diffuse_color=(*color,1)
    p=m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value=(*color,1)
    p.inputs['Roughness'].default_value=rough
    p.inputs['Specular IOR Level'].default_value=specular
    p.inputs['Metallic'].default_value=0
    p.inputs['Transmission Weight'].default_value=0
    p.inputs['Coat Weight'].default_value=.035 if 'clay' in name else 0
    p.inputs['Coat Roughness'].default_value=.45

for ob in list(scene.objects):
    if ob.type=='LIGHT':bpy.data.objects.remove(ob,do_unlink=True)
lights=bpy.data.collections.new('09 Studio illumination');scene.collection.children.link(lights)
def area(name,location,target,power,size,color,depth=None,role='studio'):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.color=color
    data.shape='RECTANGLE';data.size=size;data.size_y=depth or size
    ob=bpy.data.objects.new(name,data);lights.objects.link(ob);ob.location=location
    ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
    ob['lighting_role']=role
    return ob
area('14 Overhead softbox',(-260,-90,390),(10,55,0),1900000,430,(.975,.989,1),380)
area('14 Front white bounce',(-180,-370,205),(20,50,35),200000,430,(1,.984,.951),300)
area('14 Gentle right rim',(290,180,460),(85,60,20),900000,370,(1,.985,.953),350)
world=scene.world;world.name='14 White studio environment';world.use_nodes=True
world.node_tree.nodes['Background'].inputs[0].default_value=(.965,.984,1,1)
world.node_tree.nodes['Background'].inputs[1].default_value=.55

# Each small emitter faces an existing recessed receiver; AREA lights have no
# camera-visible lamp polygon. Their light reflects from real facade geometry.
warm=(1,.66,.28);warm_sources=[]
def facade_light(b,axis,along,z,height,width,name,power_density=9):
    ob=next(o for o in scene.objects if o.get('id')==b['id'])
    if axis=='front':
        local=Vector((along,-b['d']/2-.28,z));target=local+Vector((0,1,0))
    else:
        local=Vector((-b['w']/2-.28,along,z));target=local+Vector((1,0,0))
    light=area(name,ob.matrix_world@local,ob.matrix_world@target,
        width*height*power_density,width,warm,height,'concealed warm receiver wash')
    warm_sources.append({'name':name,'building':b['id'],'kind':axis,'power':light.data.energy})

def visible(b):
    q=world_to_camera_view(scene,camera,Vector((b['x'],b['y'],b['z']+min(b['h']*.35,6))))
    return -.12<q.x<1.12 and -.15<q.y<.70
low=[b for b in plan['buildings'] if visible(b) and b['h']<23 and b['kind'] not in ('gable','sawtooth')]
# Separated clusters along the waterfront; do not light every building uniformly.
selected=[]
for b in sorted(low,key=lambda b:(b['y'], -b['w']*b['d'])):
    if all(math.hypot(b['x']-c['x'],b['y']-c['y'])>22 for c in selected):selected.append(b)
    if len(selected)==16:break
for b in selected:
    height=min(2.0,b['h']*.36);z=b['z']+height*.57+.3
    facade_light(b,'front',0,z,height,b['w']*.68,f"14 {b['id']} recessed lobby")
    if b['w']>15:
        facade_light(b,'left',0,z,height,b['d']*.42,f"14 {b['id']} side lobby",9)
towers=[b for b in plan['buildings'] if visible(b) and b['kind'].startswith('tower') and b['h']>37]
for b in sorted(towers,key=lambda b:-b['h'])[:6]:
    h=b['h']*.39
    facade_light(b,'front',-b['w']*.26,b['z']+5+h/2,h,.35,f"14 {b['id']} narrow vertical cove",14)
    facade_light(b,'front',0,b['z']+1.1,1.65,b['w']*.46,f"14 {b['id']} tower lobby",12)

# Only short concealed sections beneath the parapet, not a glowing bridge outline.
deck=next(o for o in scene.objects if o.type=='MESH' and ' deck' in o.name and len(o.data.vertices)>100)
verts=[deck.matrix_world@v.co for v in deck.data.vertices]
stations=max(1,len(verts)//4)
for i,fraction in enumerate((.30,.52,.73)):
    k=min(stations-2,int(stations*fraction))*4
    pos=(verts[k]+verts[k+1])/2;pos.z-=.8
    light=area(f'14 Bridge concealed accent {i}',pos,pos-Vector((0,0,1)),80,9,warm,.35,'concealed bridge accent')
    warm_sources.append({'name':light.name,'kind':'bridge','power':80})

scene.render.engine='CYCLES';scene.cycles.device='GPU'
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for d in prefs.devices:d.use=d.type=='OPTIX'
scene.cycles.samples=48 if '--draft' in sys.argv else 192
scene.cycles.use_denoising=True;scene.cycles.adaptive_threshold=.018
scene.cycles.max_bounces=10;scene.cycles.diffuse_bounces=6;scene.cycles.glossy_bounces=4
scene.view_settings.view_transform='AgX';scene.view_settings.look='AgX - Medium High Contrast';scene.view_settings.exposure=1.25
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA';scene.render.film_transparent=True
scene.use_nodes=True;nodes=scene.node_tree.nodes;nodes.clear()
rl=nodes.new('CompositorNodeRLayers');glare=nodes.new('CompositorNodeGlare');glare.glare_type='FOG_GLOW'
glare.quality='HIGH';glare.threshold=2.5;glare.mix=-.96;glare.size=7
out=nodes.new('CompositorNodeComposite');scene.node_tree.links.new(rl.outputs['Image'],glare.inputs['Image']);scene.node_tree.links.new(glare.outputs['Image'],out.inputs['Image'])
assert before==fingerprint(),'Studio setup moved or changed geometry'
assert not camera.animation_data
plan['composition_camera']=spec
plan['studio']={'exposure':1.25,'world_strength':.55,'diffuse_bounces':6,'warm_sources':warm_sources,
    'materials':settings,'background':'#f6f5f1','render_size':[1883,1054],
    'stage':'experimental lighting first pass; owner-locked camera; geometry unchanged from smooth shore',
    'source':source.name,'source_sha256':source_hash,'geometry_unchanged':True,
    'warm_source_visibility':'AREA lights; no directly visible source meshes',
    'render_note':'Cycles offline reference. Browser uses actual mesh with diffuse lighting transport; specular is approximate.'}
plan['camera_locked']=True
(ROOT/'city-14-studio-plan.json').write_text(json.dumps(plan,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
scene['stage']='14 locked-camera studio lighting';scene.render.filepath=str(ROOT/'renders/city-14-studio.png')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-14-studio.blend'))
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
print('STUDIO_READY',len(warm_sources),'warm accents',flush=True)
if '--no-render' not in sys.argv:bpy.ops.render.render(write_still=True)
