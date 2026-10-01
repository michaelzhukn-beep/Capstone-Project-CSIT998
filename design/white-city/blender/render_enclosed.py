"""08 sealed architecture and brighter Cycles white-model reference, same camera/layout."""
import bpy,json,hashlib,sys,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from city_enclosure import repair,palette
source=ROOT/'city-07-studio.blend';before=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source));scene=bpy.context.scene;palette()
original=json.loads((ROOT/'city-04-manifest.json').read_text(encoding='utf-8'))['buildings_layout']
assets=json.loads((ROOT/'city-04-assets.json').read_text(encoding='utf-8'))['assets']
changes=[]
for a in assets:
    if a['kind']!='building':continue
    b=next(b for b in original if b['tag']==a['source_tag'])
    collection=bpy.data.collections['District asset '+a['id']];objects=list(collection.objects)
    emit=[o for o in objects if any(m and m.name=='Recessed warm ceiling - real emission' for m in o.data.materials)]
    base=0
    if emit:base=sum(v.co.z for v in emit[0].data.vertices)/len(emit[0].data.vertices)-2.8
    elif b['form'] in ('gallery','sawtooth'):
        structure=next(o for o in objects if 'ceramic structure' in o.name)
        # The disconnected roof sheets are the only isolated ceramic quads.
        import bmesh
        bm=bmesh.new();bm.from_mesh(structure.data)
        faces=[f for f in bm.faces if all(e.is_boundary for e in f.edges) and f.normal.z>.2]
        base=min(v.co.z for f in faces for v in f.verts)-(5.1 if b['form']=='gallery' else b['h']*.72);bm.free()
    changes.append(repair(collection,objects,b,0,0,base))
key=bpy.data.lights['Large soft daylight key'];key.energy=620000;key.size=115
bpy.data.lights['Cool broad fill'].energy=24000
bpy.data.lights['Soft daylight direction'].energy=.32
bpy.data.lights['Soft daylight direction'].angle=math.radians(22)
for n in scene.world.node_tree.nodes:
    if n.type=='BACKGROUND' and n.inputs['Strength'].default_value<1:n.inputs['Strength'].default_value=.27
scene.view_settings.exposure=1.8;scene.cycles.samples=192
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for device in prefs.devices:device.use=device.type=='OPTIX'
scene.cycles.device='GPU'
scene['stage']='08 closed roof edges / concealed downlights / bright white palette; experimental'
scene.render.filepath=str(ROOT/'renders'/'city-08-enclosed.png')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-08-enclosed.blend'))
bpy.ops.render.render(write_still=True)
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
(ROOT/'city-08-cycles-review.json').write_text(json.dumps(dict(source_sha256=before,
    geometry_repairs=changes,camera='unchanged city-view.json',layout='unchanged city-06-plan.json',
    display='AgX / Medium High Contrast / +1.8 EV',emission='45; recessed cove sources hidden from camera and glossy rays',
    resolution=[2560,1415],samples=192,source_preserved=True),indent=2),encoding='utf-8')
print('ENCLOSED_CYCLES_READY',flush=True)
