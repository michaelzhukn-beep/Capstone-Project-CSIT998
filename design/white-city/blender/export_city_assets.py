"""Export reusable local-space architecture/trees from city-04; source blend stays untouched."""
import json
import re
from pathlib import Path
import bpy
from mathutils import Matrix, Vector

root=Path(bpy.data.filepath).parent
name=Path(bpy.data.filepath).stem
assert name=='city-04', 'Export from the curated scene, never overwrite a baseline'
manifest=json.loads((root/f'{name}-manifest.json').read_text(encoding='utf-8'))
group=bpy.data.collections.new('Streaming asset library - local coordinates')
bpy.context.scene.collection.children.link(group)
original=list(bpy.context.scene.objects)
assets=[]

def copy_asset(key,objects,origin,info):
    parent=bpy.data.objects.new(key,None);group.objects.link(parent)
    vertices=[]
    for obj in objects:
        copy=obj.copy();copy.data=obj.data.copy();copy.animation_data_clear()
        for modifier in list(copy.modifiers):copy.modifiers.remove(modifier)
        # Mesh coordinates in this builder already carry world positions.
        transform=Matrix.Translation(-Vector(origin)) @ obj.matrix_world
        copy.data.transform(transform)
        copy.matrix_world=Matrix.Identity(4);copy.parent=parent
        copy.name=key+' '+obj.name;group.objects.link(copy)
        vertices.extend(v.co.copy() for v in copy.data.vertices)
    lo=[min(v[i] for v in vertices) for i in range(3)]
    hi=[max(v[i] for v in vertices) for i in range(3)]
    assets.append(dict(id=key,**info,bounds_min=lo,bounds_max=hi,
                       width=hi[0]-lo[0],depth=hi[1]-lo[1],height=hi[2]-lo[2]))

for b in manifest['buildings_layout']:
    if b['lod']!='near':continue
    objects=[o for o in original if o.type=='MESH' and o.name.startswith(b['tag']+' ')]
    floor=min((o.matrix_world @ Vector(v)).z for o in objects for v in o.bound_box)
    copy_asset('building_'+b['tag'][:3],objects,(b['x'],b['y'],floor),
               dict(kind='building',form=b['form'],source_tag=b['tag'],lod='near'))
for idx,collection in enumerate(['Tree prototype 00','Tree prototype 03','Distant Tree prototype 0']):
    copy_asset(f'tree_{idx}',list(bpy.data.collections[collection].objects),(0,0,0),
               dict(kind='tree',form='tree',lod='far' if idx==2 else 'near'))

bpy.ops.object.select_all(action='DESELECT')
for obj in group.objects:obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(root/'city-04-assets.glb'),export_format='GLB',
    use_selection=True,export_apply=False,export_cameras=False,export_lights=False,export_animations=False)
(root/'city-04-assets.json').write_text(json.dumps(dict(source='city-04.blend',
    coordinate_system='bounds in Blender Z-up; GLB is Y-up',assets=assets),indent=2),encoding='utf-8')
print('ASSETS_EXPORTED',len(assets),(root/'city-04-assets.glb').stat().st_size,flush=True)
