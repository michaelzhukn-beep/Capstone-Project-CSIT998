"""07: asset-local Cycles diffuse bake + self visibility in vertex data; no scene images.

Run Blender city-04.blend --background --python this.py [-- --pilot].
RGB stores diffuse radiance/albedo / 16; alpha stores self AO. Each asset is isolated:
neighbour shadows, world daylight and moving district terrain are NOT baked.
"""
import bpy, bmesh, json, math, hashlib, sys, time
import numpy as np
from pathlib import Path
from mathutils import Matrix, Vector

root=Path(__file__).resolve().parent
stage='08' if '--stage=08' in sys.argv else '07'
source=root/('city-08-source.blend' if stage=='08' else 'city-04.blend')
scale=64 if stage=='08' else 16
assert Path(bpy.data.filepath)==source
source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
pilot='--pilot' in sys.argv
manifest=json.loads((root/'city-04-manifest.json').read_text(encoding='utf-8'))
metadata=json.loads((root/'city-04-assets.json').read_text(encoding='utf-8'))
scene=bpy.context.scene
original=list(scene.objects)
library=bpy.data.collections.new('07 local light assets');scene.collection.children.link(library)
scene.render.engine='CYCLES';scene.cycles.samples=64
scene.cycles.max_bounces=8;scene.cycles.diffuse_bounces=4
scene.cycles.use_denoising=False
prefs=bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type='OPTIX';prefs.get_devices()
for device in prefs.devices:device.use=device.type=='OPTIX'
scene.cycles.device='GPU'
scene.world.use_nodes=True
scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value=0
scene.render.bake.target='VERTEX_COLORS';scene.render.bake.use_clear=True
for material in bpy.data.materials:
    if material.name=='Recessed warm ceiling - real emission':
        bsdf=material.node_tree.nodes.get('Principled BSDF')
        if stage=='07':
            bsdf.inputs['Emission Color'].default_value=(1,.56,.27,1)
            bsdf.inputs['Emission Strength'].default_value=3.2
for obj in original:obj.hide_render=True
report=[];start=time.time()

def copy_part(obj,key,origin,refine):
    copy=obj.copy();copy.data=obj.data.copy();copy.animation_data_clear()
    copy.hide_render=False;copy.hide_viewport=False
    for modifier in list(copy.modifiers):copy.modifiers.remove(modifier)
    copy.data.transform(Matrix.Translation(-Vector(origin)) @ obj.matrix_world)
    copy.matrix_world=Matrix.Identity(4);copy.name=key+' '+obj.name;library.objects.link(copy)
    if refine:
        bm=bmesh.new();bm.from_mesh(copy.data)
        # Uniform per-part subdivision preserves the original silhouette and normals.
        broad=[f for f in bm.faces if f.calc_area()>4 and min(e.calc_length() for e in f.edges)>1]
        edges=list({e for f in broad for e in f.edges})
        maximum=max((e.calc_length() for e in edges),default=0)
        cuts=min(5,max(0,math.ceil(maximum/2.5)-1))
        if cuts:
            bmesh.ops.subdivide_edges(bm,edges=edges,cuts=cuts,use_grid_fill=True)
        bm.to_mesh(copy.data);bm.free();copy.data.update()
    return copy

def join(objects):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.object.join()
    return objects[0]

for b in manifest['buildings_layout']:
    if b['lod']!='near':continue
    key='building_'+b['tag'][:3]
    if pilot and key!='building_007':continue
    objects=[o for o in original if o.type=='MESH' and o.name.startswith(b['tag']+' ')]
    floor=min((o.matrix_world @ Vector(v)).z for o in objects for v in o.bound_box)
    opaque=[];others=[]
    for obj in objects:
        mats=[m.name for m in obj.data.materials if m]
        special=any('glazing' in m or 'real emission' in m for m in mats)
        copy=copy_part(obj,key,(b['x'],b['y'],floor),not special)
        (others if special else opaque).append(copy)
    target=join(opaque);target.name=key+' baked opaque surfaces'
    colors=target.data.color_attributes.new(name='LocalLight',type='FLOAT_COLOR',domain='CORNER')
    target.data.color_attributes.active_color=colors
    count=len(colors.data);rgba=np.empty(count*4,dtype=np.float32)
    has_emitter=any(any(m and 'real emission' in m.name for m in o.data.materials) for o in others)
    if has_emitter:
        bpy.ops.object.bake(type='DIFFUSE',pass_filter={'DIRECT','INDIRECT'})
        colors.data.foreach_get('color',rgba)
        radiance=np.maximum(0,rgba.reshape(-1,4)[:,:3].copy())
    else:radiance=np.zeros((count,3),dtype=np.float32)
    bpy.ops.object.bake(type='AO')
    colors.data.foreach_get('color',rgba)
    ao=np.clip(rgba.reshape(-1,4)[:,:3].mean(axis=1),0,1)
    packed=np.ones((count,4),dtype=np.float32);packed[:,:3]=np.clip(radiance/scale,0,1);packed[:,3]=ao
    colors.data.foreach_set('color',packed.ravel());target.data.update()
    parent=bpy.data.objects.new(key,None);library.objects.link(parent)
    for obj in [target,*others]:obj.parent=parent;obj.hide_render=True
    report.append(dict(id=key,form=b['form'],vertices=len(target.data.vertices),corners=count,
                       emitter=has_emitter,radiance_max=float(radiance.max()),radiance_mean=float(radiance.mean()),
                       ao_min=float(ao.min()),ao_mean=float(ao.mean()),clipped_channels=int((radiance>scale).sum())))
    print('BAKE_ASSET',json.dumps(report[-1]),flush=True)

if not pilot:
    for idx,name in enumerate(['Tree prototype 00','Tree prototype 03','Distant Tree prototype 0']):
        key=f'tree_{idx}';parent=bpy.data.objects.new(key,None);library.objects.link(parent)
        for obj in bpy.data.collections[name].objects:
            copy=copy_part(obj,key,(0,0,0),False);copy.parent=parent;copy.hide_render=True

bpy.ops.object.select_all(action='DESELECT')
for obj in library.objects:obj.hide_render=False;obj.select_set(True)
suffix='pilot' if pilot else 'assets'
output=root/f'city-{stage}-{suffix}.glb'
bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',use_selection=True,
    export_apply=False,export_cameras=False,export_lights=False,export_animations=False,
    export_vertex_color='ACTIVE',export_all_vertex_colors=False,export_active_vertex_color_when_no_material=True)
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
(root/f'city-{stage}-{suffix}-bake.json').write_text(json.dumps(dict(source=source.name,source_sha256=source_hash,
    engine='Cycles / OptiX',samples=64,diffuse_bounces=4,world_strength=0,
    encoding=f'COLOR_0 linear RGB = local diffuse bake (direct+indirect, no albedo) / {scale}; A = self AO',
    excludes='world daylight, neighbouring geometry, district terrain',assets=report,
    elapsed_seconds=round(time.time()-start,2),bytes=output.stat().st_size),indent=2),encoding='utf-8')
print('BAKE_FINISHED',output,time.time()-start,flush=True)
