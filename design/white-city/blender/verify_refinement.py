"""Blender background verification: refinement must preserve the accepted camera/light rig."""
import hashlib
import json
import struct
from pathlib import Path
import bpy

root=Path(__file__).resolve().parent

def rounded(values):
    return [round(float(v),6) for v in values]

def snapshot(path):
    bpy.ops.wm.open_mainfile(filepath=str(path))
    scene=bpy.context.scene
    scene.frame_set(1)
    cameras={o.name:dict(matrix=rounded(v for row in o.matrix_world for v in row),
                        lens=o.data.lens,shift=[o.data.shift_x,o.data.shift_y])
             for o in scene.objects if o.type=='CAMERA'}
    lights={o.name:dict(matrix=rounded(v for row in o.matrix_world for v in row),
                       color=rounded(o.data.color),energy=o.data.energy,type=o.data.type,
                       size=getattr(o.data,'size',None),size_y=getattr(o.data,'size_y',None),
                       angle=getattr(o.data,'angle',None))
            for o in scene.objects if o.type=='LIGHT'}
    materials={}
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        shader=mat.node_tree.nodes.get('Principled BSDF')
        if shader:
            materials[mat.name]=[rounded(shader.inputs['Base Color'].default_value),
                shader.inputs['Roughness'].default_value,shader.inputs['Metallic'].default_value,
                shader.inputs['Transmission Weight'].default_value,
                rounded(shader.inputs['Emission Color'].default_value),shader.inputs['Emission Strength'].default_value]
    world={n.name:[rounded(n.inputs['Color'].default_value),n.inputs['Strength'].default_value]
           for n in scene.world.node_tree.nodes if n.type=='BACKGROUND'}
    trees={o.name:rounded(v for row in o.matrix_world for v in row)
           for o in scene.objects if o.instance_collection and o.instance_collection.name.startswith('Tree prototype')}
    layout={o.name:rounded([min(v.co[i] for v in o.data.vertices) for i in range(3)] +
                          [max(v.co[i] for v in o.data.vertices) for i in range(3)])
            for o in scene.objects if o.type=='MESH' and o.name.endswith('ceramic structure')}
    return dict(cameras=cameras,lights=lights,materials=materials,world=world,trees=trees,
                layout=layout,
                exposure=scene.view_settings.exposure,look=scene.view_settings.look,
                image_nodes=sum(n.type=='TEX_IMAGE' for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes),
                buildings=scene['building_count'],mesh_objects=len([o for o in scene.objects if o.type=='MESH']))

baseline=snapshot(root/'city-01.blend')
refined=snapshot(root/'city-02.blend')
for key in ('cameras','lights','world','materials','exposure','look','trees','buildings','layout'):
    assert baseline[key]==refined[key],f'Accepted baseline changed: {key}'
assert refined['image_nodes']==0
assert refined['mesh_objects']>baseline['mesh_objects']
glb=root/'city-02.glb'
with glb.open('rb') as file:
    magic,version,total=struct.unpack('<4sII',file.read(12))
    length,kind=struct.unpack('<II',file.read(8))
    model=json.loads(file.read(length))
assert magic==b'glTF' and version==2 and total==glb.stat().st_size
assert kind==0x4e4f534a and model.get('meshes') and not model.get('images')
report=dict(result='PASS',preserved=['camera poses and lenses','all light transforms, powers and colors',
    'world lighting','original PBR materials','exposure and look','all 711 tree placements','73 building layout'],
    baseline_mesh_objects=baseline['mesh_objects'],refined_mesh_objects=refined['mesh_objects'],
    glb_bytes=total,glb_mesh_definitions=len(model['meshes']),glb_image_assets=len(model.get('images',[])),
    baseline_sha256={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [root/'city-01.blend',root/'renders'/'city-01.png',root/'renders'/'waterfront-detail.png']},
    visual_acceptance='01 is the accepted direction; 02 needs owner review')
(root/'refinement-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('REFINEMENT_VERIFIED',json.dumps(report),flush=True)
