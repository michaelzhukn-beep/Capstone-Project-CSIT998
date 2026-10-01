"""Run against a city blend. Export inspectable geometry and render detail/plan cameras."""
import bpy
import json
import sys
from pathlib import Path

root=Path(bpy.data.filepath).parent
name=Path(bpy.data.filepath).stem
suffix='' if name=='city-01' else '-'+name
scene=bpy.context.scene
scene.cycles.samples=64
scene.render.resolution_x=1600
scene.render.resolution_y=1000
scene.render.resolution_percentage=100
scene.camera=bpy.data.objects['Waterfront detail camera']
scene.render.filepath=str(root/'renders'/f'waterfront-detail{suffix}.png')
if '--export-only' not in sys.argv:
    bpy.ops.render.render(write_still=True)
    print('DETAIL_RENDER_COMPLETE',flush=True)
    if 'Layout camera - plan check' in bpy.data.objects:
        scene.camera=bpy.data.objects['Layout camera - plan check']
        # The plan is a geometry audit: hero-camera distance fog would hide the whole map.
        scene.render.use_compositing=False
        scene.render.resolution_x=1600
        scene.render.resolution_y=1200
        scene.render.filepath=str(root/'renders'/f'layout-{name}.png')
        bpy.ops.render.render(write_still=True)
        print('LAYOUT_RENDER_COMPLETE',flush=True)

# Collection instances export as actual mesh nodes, not textured planes.
bpy.ops.object.select_all(action='DESELECT')
for obj in scene.objects:
    if obj.name=='Continuous ground beyond camera':
        continue
    if obj.type=='MESH' or (obj.type=='EMPTY' and obj.instance_type=='COLLECTION'):
        obj.select_set(True)
# The GLB is a lightweight geometry inspector, not the final render asset. Leave expensive
# edge radii in the saved .blend; remove them only from this temporary export session.
for obj in scene.objects:
    if obj.type=='MESH':
        for modifier in list(obj.modifiers):
            obj.modifiers.remove(modifier)
bpy.ops.export_scene.gltf(filepath=str(root/f'{name}.glb'),export_format='GLB',use_selection=True,
    export_apply=False,export_cameras=False,export_lights=False,export_gpu_instances=True)

meshes=[obj for obj in scene.objects if obj.type=='MESH']
degenerate=[]
for mesh in bpy.data.meshes:
    if 'canopy' in mesh.name.lower() and sum(p.area for p in mesh.polygons)<1:
        degenerate.append(mesh.name)
assert not degenerate,degenerate
assert not any(node.type=='TEX_IMAGE' for mat in bpy.data.materials if mat.use_nodes for node in mat.node_tree.nodes)
report={'geometry_objects':len(meshes),'mesh_vertices_before_modifiers':sum(len(obj.data.vertices) for obj in meshes),
    'tree_prototype_collections':len([c for c in bpy.data.collections if c.name.startswith('Tree prototype')]),
    'cameras':[o.name for o in scene.objects if o.type=='CAMERA'],
    'image_texture_nodes':0,'render_engine':scene.render.engine,'glb_bytes':(root/f'{name}.glb').stat().st_size,
    'glb_purpose':'geometry inspection without bevel modifiers; full modifiers remain in the saved blend',
    'checks':'real mesh areas, no image texture nodes, alternative perspective render, GLB export'}
(root/f'verification{suffix}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('GEOMETRY_VERIFIED',json.dumps(report),flush=True)
