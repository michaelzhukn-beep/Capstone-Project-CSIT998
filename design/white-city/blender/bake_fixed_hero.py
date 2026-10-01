"""Whole fixed-scene Cycles diffuse vertex bake, including neighbouring geometry.

The result remains actual geometry, not a screenshot/depth-card. The combined bake
trial was rejected because thin intersections produced black wedges. The final diffuse
bake uses inward face samples and explicitly approximates glass/water as diffuse.
"""
import bpy,bmesh,json,hashlib,time,math,sys
import numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ALIGNED='--aligned' in sys.argv
STUDIO='--studio' in sys.argv or ALIGNED;CAMERA_BAKE='--camera-bake' in sys.argv
stem='city-11-aligned' if ALIGNED else ('city-10-studio' if STUDIO else 'city-09-fixed')
suffix='-camera' if CAMERA_BAKE else ''
SCALE=128 if ALIGNED else (64 if STUDIO or CAMERA_BAKE else 32)
source=ROOT/(stem+'.blend')
before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source))
scene=bpy.context.scene;scene.cycles.samples=128 if STUDIO else 48;scene.cycles.use_denoising=False
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for d in prefs.devices:d.use=d.type=='OPTIX'
scene.cycles.device='GPU';scene.render.bake.target='VERTEX_COLORS';scene.render.bake.use_clear=True
scene.render.bake.view_from='ACTIVE_CAMERA' if CAMERA_BAKE else 'ABOVE_SURFACE'
# Vertex COMBINED/active-camera sampling produced black patches at thin glazing and
# overlapping facade corners in the browser trial. Use robust diffuse transport;
# frosted glazing/water are explicitly approximated, not called pixel-identical GI.
for m in bpy.data.materials:
    if not CAMERA_BAKE and m.name in ('09 Low iron thin glass','09 Pearlescent reflective water'):
        m.node_tree.nodes.get('Principled BSDF').inputs['Transmission Weight'].default_value=0
all_mesh=[o for o in scene.objects if o.type=='MESH' and not o.get('emitter')]
ground=next(o for o in all_mesh if o.name.endswith('Continuous studio landscape'))
# Ground opacity is a display seam treatment, not something to bake into irradiance.
mat=ground.data.materials[0];nodes=mat.node_tree.nodes;links=mat.node_tree.links
links.new(nodes.get('Principled BSDF').outputs[0],nodes.get('Material Output').inputs[0])
start=time.time();reports=[];outputs=[]
bpy.ops.object.select_all(action='DESELECT')
for ob in all_mesh:ob.select_set(True)
bpy.context.view_layer.objects.active=all_mesh[0]
bpy.ops.object.convert(target='MESH')
all_mesh=[o for o in scene.objects if o.type=='MESH' and not o.get('emitter')]
ground=next(o for o in all_mesh if o.name.endswith('Continuous studio landscape'))
# Keep the ground separate so only its far margin fades into the page.
for name,parts in [('Fixed architecture and vegetation',[o for o in all_mesh if o!=ground]),('Fixed studio ground',[ground])]:
    bpy.ops.object.select_all(action='DESELECT')
    for ob in parts:ob.select_set(True)
    bpy.context.view_layer.objects.active=parts[0];bpy.ops.object.join();target=parts[0];target.name=name
    if ALIGNED:
        # Apply the joined object's transform, rather than applying individual
        # linked tree meshes. Face insets and normal offsets then use world units.
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    # Add samples to broad faces, while leaving tiny facade details alone.
    bm=bmesh.new();bm.from_mesh(target.data)
    faces=[f for f in bm.faces if f.calc_area()>3 and min(e.calc_length() for e in f.edges)>1.1]
    if ALIGNED and target==ground:
        # The oblique scene includes a large off-screen landscape. Spend extra
        # irradiance samples only on visible foreground, not the distant backdrop.
        projection=scene.camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),x=1672,y=941)
        vp=projection@scene.camera.matrix_world.inverted()
        detailed=[]
        for f in faces:
            center=target.matrix_world@f.calc_center_median();q=vp@center.to_4d()
            if q.w>0 and abs(q.x/q.w)<1.10 and -1.15<q.y/q.w<-.50 and (center-scene.camera.location).length<400:detailed.append(f)
        faces=detailed
    edges=list({e for f in faces for e in f.edges})
    if edges:bmesh.ops.subdivide_edges(bm,edges=edges,cuts=3,use_grid_fill=True)
    bm.to_mesh(target.data);bm.free();target.data.update()
    colors=target.data.color_attributes.new(name='FixedRadiance',type='FLOAT_COLOR',domain='CORNER')
    target.data.color_attributes.active_color=colors
    print('BAKE_FIXED_START',name,len(target.data.loops),flush=True)
    # Sample just inside each face, analogous to texel-centre sampling in a lightmap.
    # Exact shared corners frequently lie inside a crossing mullion or floor slab;
    # baking those intersection points and interpolating creates false black wedges.
    # The unchanged original mesh remains the shadow/GI occluder. The sampling proxy
    # is invisible to transport and is discarded; exported geometry is unchanged.
    me=target.data;nv=len(me.vertices);nl=len(me.loops);nf=len(me.polygons)
    co=np.empty(nv*3,np.float32);me.vertices.foreach_get('co',co);co=co.reshape(-1,3)
    vi=np.empty(nl,np.int32);me.loops.foreach_get('vertex_index',vi)
    starts=np.empty(nf,np.int32);counts=np.empty(nf,np.int32);mi=np.empty(nf,np.int32)
    me.polygons.foreach_get('loop_start',starts);me.polygons.foreach_get('loop_total',counts);me.polygons.foreach_get('material_index',mi)
    normals=np.empty(nf*3,np.float32);me.polygons.foreach_get('normal',normals);normals=normals.reshape(-1,3)
    lc=co[vi];centers=np.add.reduceat(lc,starts,axis=0)/counts[:,None]
    delta=np.repeat(centers,counts,axis=0)-lc;dist=np.linalg.norm(delta,axis=1)
    inset=np.minimum(.26,.16/np.maximum(dist,.0001))
    sample=lc+delta*inset[:,None]+np.repeat(normals,counts,axis=0)*(.02 if ALIGNED else .009)
    proxyme=bpy.data.meshes.new('Temporary inset lighting samples');proxyme.vertices.add(nl);proxyme.vertices.foreach_set('co',sample.ravel())
    proxyme.loops.add(nl);proxyme.loops.foreach_set('vertex_index',np.arange(nl,dtype=np.int32))
    proxyme.polygons.add(nf);proxyme.polygons.foreach_set('loop_start',starts);proxyme.polygons.foreach_set('loop_total',counts);proxyme.polygons.foreach_set('material_index',mi)
    for material in me.materials:proxyme.materials.append(material)
    proxyme.update()
    proxy=bpy.data.objects.new('Temporary inset lighting samples',proxyme);scene.collection.objects.link(proxy);proxy.matrix_world=target.matrix_world
    proxy.visible_camera=False;proxy.visible_diffuse=False;proxy.visible_glossy=False;proxy.visible_shadow=False;proxy.visible_transmission=False
    pc=proxyme.color_attributes.new(name='Samples',type='FLOAT_COLOR',domain='CORNER');proxyme.color_attributes.active_color=pc
    bpy.ops.object.select_all(action='DESELECT');proxy.select_set(True);bpy.context.view_layer.objects.active=proxy
    if CAMERA_BAKE:
        bpy.ops.object.bake(type='COMBINED',pass_filter={'DIRECT','INDIRECT','DIFFUSE','GLOSSY','TRANSMISSION','EMIT'})
    else:
        bpy.ops.object.bake(type='DIFFUSE',pass_filter={'DIRECT','INDIRECT','COLOR'})
    values=np.empty(len(colors.data)*4,dtype=np.float32);pc.data.foreach_get('color',values)
    bpy.data.objects.remove(proxy,do_unlink=True);bpy.data.meshes.remove(proxyme)
    values=values.reshape(-1,4);rgb=np.maximum(0,values[:,:3].copy());values[:,:3]=np.clip(rgb/SCALE,0,1);values[:,3]=1
    if target==ground:
        axis=scene.get('ground_fade_axis',[0,1,0]);fade0,fade1=scene.get('ground_fade_range',[42,170])
        for i,loop in enumerate(target.data.loops):
            p=target.matrix_world@target.data.vertices[loop.vertex_index].co
            depth=sum(p[j]*axis[j] for j in range(3))
            values[i,3]=1-min(1,max(0,(depth-fade0)/(fade1-fade0)))
    colors.data.foreach_set('color',values.ravel());target.data.update();outputs.append(target)
    reports.append(dict(name=name,vertices=len(target.data.vertices),corners=len(values),max_radiance=float(rgb.max()),clipped_channels=int((rgb>SCALE).sum())))
bpy.ops.object.select_all(action='DESELECT')
for ob in outputs:ob.select_set(True)
bpy.context.view_layer.objects.active=outputs[0]
output=ROOT/(stem+suffix+'-baked.glb')
bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',use_selection=True,export_apply=False,export_cameras=False,export_lights=False,export_animations=False,export_vertex_color='ACTIVE',export_all_vertex_colors=False,export_active_vertex_color_when_no_material=True,
    export_draco_mesh_compression_enable=True,export_draco_mesh_compression_level=6,
    export_draco_position_quantization=16,export_draco_normal_quantization=12,export_draco_color_quantization=16)
assert hashlib.sha256(source.read_bytes()).hexdigest()==before
report=dict(source=source.name,source_sha256=before,source_preserved=True,radiance_scale=SCALE,encoding=f'COLOR_0 linear radiance with albedo / {SCALE}; A = ground perimeter opacity',
    engine='Cycles OptiX '+('COMBINED active-camera experiment' if CAMERA_BAKE else 'DIFFUSE direct + indirect + color'),samples=scene.cycles.samples,view_from=scene.render.bake.view_from,diffuse_bounces=scene.cycles.diffuse_bounces,
    includes='Whole authored static scene: environment, key/fill, neighbouring buildings, plants, river and warm sources',
    limitations=('View-dependent vertex samples; interpolation cannot reproduce per-pixel reflections; visual review required' if CAMERA_BAKE else 'Frosted glass and water use opaque diffuse approximation; glossy/transmission are not captured; no pixel-identical Cycles claim'),
    objects=reports,elapsed_seconds=round(time.time()-start,2),bytes=output.stat().st_size)
(ROOT/(stem+suffix+'-bake.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print('FIXED_BAKE_DONE',report['elapsed_seconds'],report['bytes'],flush=True)
