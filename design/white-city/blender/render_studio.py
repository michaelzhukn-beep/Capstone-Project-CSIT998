"""07 same-layout Cycles reference. Only light/display/ground treatment changes."""
import bpy,json,math,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
source=ROOT/'city-06-districts.blend';before=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source))
scene=bpy.context.scene
camera_before=list(scene.camera.matrix_world)
scene.view_settings.view_transform='AgX';scene.view_settings.look='AgX - Medium High Contrast'
scene.view_settings.exposure=1.0
scene.render.film_transparent=True
scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA'
# Baseline compositor had its own depth-to-white mix: remove it as well as WebGL fog.
scene.use_nodes=True;scene.node_tree.nodes.clear()
layers=scene.node_tree.nodes.new('CompositorNodeRLayers')
output=scene.node_tree.nodes.new('CompositorNodeComposite')
scene.node_tree.links.new(layers.outputs['Image'],output.inputs['Image'])
# Camera-only transparency at unoccupied ground margins leaves its contribution to
# global illumination intact. The white page supplies the backdrop, not a fog volume.
ground=bpy.data.materials['Seamless warm-white ground']
nodes=ground.node_tree.nodes;links=ground.node_tree.links
out=next(n for n in nodes if n.type=='OUTPUT_MATERIAL')
surface=out.inputs['Surface'].links[0].from_socket
attribute=nodes.new('ShaderNodeAttribute');attribute.attribute_name='studio_ground_fade'
path=nodes.new('ShaderNodeLightPath');multiply=nodes.new('ShaderNodeMath');multiply.operation='MULTIPLY'
links.new(attribute.outputs['Fac'],multiply.inputs[0]);links.new(path.outputs['Is Camera Ray'],multiply.inputs[1])
transparent=nodes.new('ShaderNodeBsdfTransparent');mix=nodes.new('ShaderNodeMixShader')
links.new(multiply.outputs[0],mix.inputs[0]);links.new(surface,mix.inputs[1]);links.new(transparent.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],out.inputs['Surface'])
def smooth(x,a,b):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)
for obj in scene.objects:
    if obj.type!='MESH' or ground not in list(obj.data.materials):continue
    attr=obj.data.attributes.new('studio_ground_fade','FLOAT','POINT')
    for i,v in enumerate(obj.data.vertices):
        p=obj.matrix_world@v.co
        offset=p.y-26*math.sin(p.x/330)-13*math.sin(p.x/151)
        attr.data[i].value=max(smooth(-offset,180,240),smooth(offset,360,580))
scene.cycles.samples=192;scene.cycles.max_bounces=10;scene.cycles.diffuse_bounces=5
scene.cycles.use_denoising=True
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for d in prefs.devices:d.use=d.type=='OPTIX'
scene.cycles.device='GPU'
scene['stage']='07 experimental white integration and asset-local bake reference; not production'
scene['lighting_note']='Cycles reference computes full GI. Runtime uses local diffuse vertex bake plus realtime lights/shadows. Layout unchanged from 06.'
scene.render.filepath=str(ROOT/'renders'/'city-07-studio.png')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-07-studio.blend'))
bpy.ops.render.render(write_still=True)
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
assert list(scene.camera.matrix_world)==camera_before
report=dict(source=source.name,source_sha256=before,plan_sha256=hashlib.sha256((ROOT/'city-06-plan.json').read_bytes()).hexdigest(),
    layout='06 unchanged',camera='city-view.json unchanged',samples=192,engine='Cycles / OptiX',
    bounces=10,diffuse_bounces=5,display='AgX / Medium High Contrast / +1 EV',
    background='transparent camera rays and ground-only margin, composited over page #F5F4F0',
    differences='WebGL AgX has no Blender Medium High Contrast look; asset-local diffuse bake is not full scene GI. Original Cycles modifiers retained.',
    status='experimental; visual acceptance pending')
(ROOT/'city-07-cycles-review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('STUDIO_CYCLES_COMPLETE',flush=True)
