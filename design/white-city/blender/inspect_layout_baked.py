"""Render actual exported vertex radiance to isolate bake defects from WebGL."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
source=ROOT/'city-14-studio.blend'
before=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source))
scene=bpy.context.scene
for ob in list(scene.objects):
    if ob.type!='CAMERA':bpy.data.objects.remove(ob,do_unlink=True)
bpy.ops.import_scene.gltf(filepath=str(ROOT/'city-14-studio-baked.glb'))
report=json.loads((ROOT/'city-14-studio-bake.json').read_text())
mat=bpy.data.materials.new('14 Baked radiance only');mat.use_nodes=True
nodes=mat.node_tree.nodes;nodes.clear();links=mat.node_tree.links
attr=nodes.new('ShaderNodeVertexColor')
scale=nodes.new('ShaderNodeVectorMath');scale.operation='SCALE';scale.inputs['Scale'].default_value=report['radiance_scale']
emit=nodes.new('ShaderNodeEmission');output=nodes.new('ShaderNodeOutputMaterial')
links.new(attr.outputs['Color'],scale.inputs[0]);links.new(scale.outputs[0],emit.inputs['Color']);links.new(emit.outputs[0],output.inputs[0])
for ob in scene.objects:
    if ob.type!='MESH':continue
    assert len(ob.data.color_attributes),ob.name
    print('IMPORTED_COLOR',ob.name,[c.name for c in ob.data.color_attributes],flush=True)
    ob.data.color_attributes.active_color=ob.data.color_attributes[0]
    ob.data.materials.clear();ob.data.materials.append(mat)
    for face in ob.data.polygons:face.material_index=0
scene.render.engine='CYCLES';scene.cycles.samples=1;scene.cycles.use_denoising=False
scene.use_nodes=False;scene.render.filepath=str(ROOT/'renders/city-14-baked-diagnostic.png')
scene.render.resolution_x=1883;scene.render.resolution_y=1054
bpy.ops.render.render(write_still=True)
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
print('BAKED_DIAGNOSTIC_PASS',flush=True)
