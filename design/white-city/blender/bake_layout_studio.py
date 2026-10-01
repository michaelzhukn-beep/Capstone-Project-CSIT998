"""Bake city-14 studio diffuse transport into its real, layered geometry.

Run only after build/render has saved city-14-studio.blend and its plan JSON.
The source scene is never saved by this script. Hidden emitter meshes remain GI
contributors, but are never exported. Transport is DIFFUSE, not COMBINED; the
visibility repair is specific to the approved locked camera and must be rebaked
if that camera or the scene changes.
"""
import hashlib
import json
import math
import time
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parent
STEM = 'city-14-studio'
SOURCE = ROOT / f'{STEM}.blend'
PLAN_FILE = ROOT / f'{STEM}-plan.json'
LAYERS = ['01 Terrain', '02 Water and banks', '03 Streets and sidewalks',
          '04 Buildings', '05 Bridges', '06 Civic landscape', '07 Vegetation']
source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
plan_hash = hashlib.sha256(PLAN_FILE.read_bytes()).hexdigest()
plan = json.loads(PLAN_FILE.read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
scene = bpy.context.scene
assert scene.camera is not None, 'Studio source must contain the approved camera'
camera_matrix = [list(row) for row in scene.camera.matrix_world]
scene.render.engine = 'CYCLES'
scene.cycles.samples = 128
scene.cycles.use_denoising = False
scene.cycles.use_adaptive_sampling = False
assert scene.cycles.diffuse_bounces >= 6, 'Source requires at least six diffuse bounces'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'
prefs.get_devices()
assert any(device.type == 'OPTIX' for device in prefs.devices), 'OptiX device unavailable'
for device in prefs.devices:
    device.use = device.type == 'OPTIX'
scene.cycles.device = 'GPU'
scene.render.bake.target = 'VERTEX_COLORS'
scene.render.bake.use_clear = True
scene.render.bake.use_selected_to_active = False
scene.render.bake.view_from = 'ABOVE_SURFACE'

# Keep the original shader graph and GI occluders, apart from an explicitly
# disclosed diffuse approximation for transmitting display surfaces.
approximated = []
for material in bpy.data.materials:
    if not material.use_nodes:
        continue
    for node in material.node_tree.nodes:
        if node.type != 'BSDF_PRINCIPLED':
            continue
        transmission = node.inputs.get('Transmission Weight')
        if transmission and not transmission.is_linked and transmission.default_value > 0:
            approximated.append(material.name)
            transmission.default_value = 0

emitter_names = [ob.name for ob in scene.objects if ob.type == 'MESH' and ob.get('emitter')]
exportable = [ob for ob in scene.objects if ob.type == 'MESH' and not ob.get('emitter')
              and not ob.hide_render]
grouped = {}
for name in LAYERS:
    collection = bpy.data.collections.get(name)
    grouped[name] = [ob for ob in collection.all_objects if ob in exportable] if collection else []
assigned = [ob.name for parts in grouped.values() for ob in parts]
assert len(assigned) == len(set(assigned)), 'Export object belongs to more than one layer'
assert set(assigned) == {ob.name for ob in exportable}, 'Unassigned visible meshes would be lost'

# A local city bounding box prevents million-unit foreground continuations from
# consuming sample subdivisions. No global edge-length tessellation is performed.
site_points = [point for polygon in plan['site'] for point in polygon['outer']]
xs, ys = zip(*site_points)
city_bounds = (min(xs)-30, max(xs)+30, min(ys)-30, max(ys)+30)
projection = scene.camera.calc_matrix_camera(
    bpy.context.evaluated_depsgraph_get(),
    x=scene.render.resolution_x, y=scene.render.resolution_y)
vp = projection @ scene.camera.matrix_world.inverted()
exterior_bvh = None
exterior_materials = None
exterior_material_names = None


def scene_exterior():
    """All actual scene solids, including bridge over terrain and lake over banks."""
    global exterior_bvh, exterior_materials, exterior_material_names
    if exterior_bvh is not None:
        return exterior_bvh
    points, faces, material_ids = [], [], []
    names = sorted({m.name for o in scene.objects if o.type == 'MESH' for m in o.data.materials if m})
    names_index = {name: i for i, name in enumerate(names)}
    offset = 0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for ob in scene.objects:
        if ob.type != 'MESH' or ob.hide_render or ob.get('emitter') or ob.name.startswith('14 Temporary') or ob.name.startswith('14 Independent'):
            continue
        evaluated = ob.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        co = np.empty(len(mesh.vertices)*3,np.float32)
        mesh.vertices.foreach_get('co',co);co=co.reshape(-1,3)
        matrix=np.asarray(ob.matrix_world,dtype=np.float32)
        world=co@matrix[:3,:3].T+matrix[:3,3]
        points.extend(world.tolist())
        for face in mesh.polygons:
            faces.append(tuple(index+offset for index in face.vertices))
            material_ids.append(names_index[mesh.materials[face.material_index].name])
        offset+=len(mesh.vertices)
        evaluated.to_mesh_clear()
    exterior_bvh=BVHTree.FromPolygons(points,faces,all_triangles=False)
    exterior_materials=np.asarray(material_ids,dtype=np.int32)
    exterior_material_names=names
    print('SCENE_EXTERIOR_READY',len(points),len(faces),flush=True)
    return exterior_bvh


def camera_region(point):
    q = vp @ Vector((*point, 1))
    return q.w > 0 and abs(q.x/q.w) < 1.10 and abs(q.y/q.w) < 1.10


def subdivide_visible(target, layer):
    """Sample only broad, visible city faces; leave far apron/tree detail alone."""
    if layer == '07 Vegetation':
        return 0
    bm = bmesh.new()
    bm.from_mesh(target.data)
    faces = []
    for face in bm.faces:
        center = face.calc_center_median()
        if not (city_bounds[0] <= center.x <= city_bounds[1]
                and city_bounds[2] <= center.y <= city_bounds[3]
                and camera_region(center)):
            continue
        area = face.calc_area()
        lengths = [edge.calc_length() for edge in face.edges]
        if area <= 3 or area > 400 or min(lengths) <= 1.1 or max(lengths) > 35:
            continue
        if layer == '01 Terrain' and face.normal.z <= .1:
            continue
        faces.append(face)
    edges = list({edge for face in faces for edge in face.edges})
    if edges:
        bmesh.ops.subdivide_edges(bm, edges=edges,
                                 cuts=1 if layer in ('01 Terrain', '02 Water and banks') else 3,
                                 use_grid_fill=True)
    bm.to_mesh(target.data)
    bm.free()
    target.data.update()
    return len(faces)


def has_emission(material):
    if not material or not material.use_nodes:
        return False
    for node in material.node_tree.nodes:
        if node.type == 'EMISSION':
            return node.inputs['Strength'].is_linked or node.inputs['Strength'].default_value > 0
        if node.type == 'BSDF_PRINCIPLED':
            strength = node.inputs.get('Emission Strength')
            color = node.inputs.get('Emission Color')
            if strength and color and (strength.is_linked or strength.default_value > 0):
                if color.is_linked or max(color.default_value[:3]) > 0:
                    return True
    return False


def bake_layer(target, inset_limit=.45, inset_distance=.42, normal_offset=.04, preserve_normals=True, repair_visibility=True):
    """Inset corners stay out of intersecting window bars/slabs; no radiance clamp."""
    me = target.data
    nv, nl, nf = len(me.vertices), len(me.loops), len(me.polygons)
    co = np.empty(nv*3, np.float32)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    vi = np.empty(nl, np.int32)
    me.loops.foreach_get('vertex_index', vi)
    starts, counts, mi = [np.empty(nf, np.int32) for _ in range(3)]
    for attr, values in [('loop_start', starts), ('loop_total', counts), ('material_index', mi)]:
        me.polygons.foreach_get(attr, values)
    normals = np.empty(nf*3, np.float32)
    me.polygons.foreach_get('normal', normals)
    normals = normals.reshape(-1, 3)
    corners = co[vi]
    centers = np.add.reduceat(corners, starts, axis=0) / counts[:, None]
    delta = np.repeat(centers, counts, axis=0) - corners
    distance = np.linalg.norm(delta, axis=1)
    inset = np.minimum(inset_limit, inset_distance/np.maximum(distance, .0001))
    sample = corners + delta*inset[:, None] + np.repeat(normals, counts, axis=0)*normal_offset
    proxy_mesh = bpy.data.meshes.new('14 Temporary inset irradiance sampler')
    proxy_mesh.vertices.add(nl)
    proxy_mesh.vertices.foreach_set('co', sample.ravel())
    proxy_mesh.loops.add(nl)
    proxy_mesh.loops.foreach_set('vertex_index', np.arange(nl, dtype=np.int32))
    proxy_mesh.polygons.add(nf)
    for attr, values in [('loop_start', starts), ('loop_total', counts), ('material_index', mi)]:
        proxy_mesh.polygons.foreach_set(attr, values)
    for material in me.materials:
        proxy_mesh.materials.append(material)
    proxy_mesh.update()
    # Preserve smooth tree/terrain shading rather than flattening each sample face.
    smooth = np.empty(nf, np.bool_)
    me.polygons.foreach_get('use_smooth', smooth)
    if preserve_normals:
        proxy_mesh.polygons.foreach_set('use_smooth', smooth)
        split_normals = np.empty(nl*3, np.float32)
        me.corner_normals.foreach_get('vector', split_normals)
        proxy_mesh.normals_split_custom_set(split_normals.reshape(-1, 3))
    proxy = bpy.data.objects.new('14 Temporary inset irradiance sampler', proxy_mesh)
    scene.collection.objects.link(proxy)
    proxy.matrix_world = target.matrix_world
    for ray in ['camera', 'diffuse', 'glossy', 'shadow', 'transmission']:
        setattr(proxy, 'visible_'+ray, False)
    colors = proxy_mesh.color_attributes.new(name='StudioSamples', type='FLOAT_COLOR', domain='CORNER')
    proxy_mesh.color_attributes.active_color = colors
    bpy.ops.object.select_all(action='DESELECT')
    proxy.select_set(True)
    bpy.context.view_layer.objects.active = proxy
    print('STUDIO_BAKE_START', target.name, nl, flush=True)
    bpy.ops.object.bake(type='DIFFUSE', pass_filter={'DIRECT', 'INDIRECT', 'COLOR'})
    values = np.empty(nl*4, np.float32)
    colors.data.foreach_get('color', values)
    rgb = values.reshape(-1, 4)[:, :3].copy()
    raw_luminance = rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)
    retries = 0
    recovered = 0
    # Floor plates are largely buried inside full-height cores: only a tiny outer
    # ledge is visible. Their dark buried corners cannot be repaired by a small
    # normal offset. For the explicitly locked camera, sample the actual visible
    # exterior along that corner's viewing ray. Each sample is an independent tiny
    # triangle so no distorted/non-planar proxy polygon can rotate its normals.
    direction = np.asarray(scene.camera.matrix_world.to_quaternion() @ Vector((0, 0, 1)), dtype=np.float32)
    front = (normals @ direction) > -.015
    retry_mask = np.repeat(front, counts) & (raw_luminance < .02) & repair_visibility
    retries = int(retry_mask.sum())
    exterior_hits = 0
    if retries:
        bvh = scene_exterior()
        material_lookup={m.name:i for i,m in enumerate(me.materials) if m}
        for name in exterior_material_names:
            if name not in material_lookup:
                material_lookup[name]=len(me.materials)
                me.materials.append(bpy.data.materials[name])
        global_to_local=np.asarray([material_lookup[name] for name in exterior_material_names],dtype=np.int32)
        indices = np.flatnonzero(retry_mask)
        retry_sample = sample[indices].copy()
        sample_normals = np.repeat(normals, counts, axis=0)[indices].copy()
        sample_materials = np.repeat(mi, counts)[indices].copy()
        view_direction = Vector(direction)
        for k, index in enumerate(indices):
            # Keep the point close to the corresponding visible edge instead of
            # moving a floor ledge sample into its completely buried face center.
            point = corners[index] + delta[index]*min(.06,.035/max(distance[index],.0001))
            origin = Vector(point) + view_direction*2500
            hit, hit_normal, face_index, _ = bvh.ray_cast(origin, -view_direction, 5000)
            if hit is not None:
                # Offset along the known unobstructed ray. A downward bevel normal
                # can point into an overlapping floor although the hit is visible.
                retry_sample[k] = hit + view_direction*.06
                sample_normals[k] = hit_normal
                sample_materials[k] = global_to_local[exterior_materials[face_index]]
                exterior_hits += 1
        retry_mesh = bpy.data.meshes.new('14 Independent visible exterior samples')
        axis = np.zeros_like(sample_normals)
        axis[:,2] = 1
        axis[np.abs(sample_normals[:,2])>.9] = [0,1,0]
        tangent = np.cross(axis,sample_normals)
        tangent /= np.maximum(np.linalg.norm(tangent,axis=1)[:,None],1e-8)
        bitangent = np.cross(sample_normals,tangent)
        epsilon = np.maximum(.0005,np.abs(retry_sample).max(axis=1)*1e-6)[:,None]
        points = np.stack([retry_sample,
                           retry_sample+tangent*epsilon,
                           retry_sample+bitangent*epsilon],axis=1).reshape(-1,3)
        retry_mesh.vertices.add(retries*3);retry_mesh.vertices.foreach_set('co',points.ravel())
        retry_mesh.loops.add(retries*3);retry_mesh.loops.foreach_set('vertex_index',np.arange(retries*3,dtype=np.int32))
        retry_mesh.polygons.add(retries)
        retry_mesh.polygons.foreach_set('loop_start',np.arange(retries,dtype=np.int32)*3)
        retry_mesh.polygons.foreach_set('loop_total',np.full(retries,3,dtype=np.int32))
        retry_mesh.polygons.foreach_set('material_index',sample_materials)
        for material in me.materials:retry_mesh.materials.append(material)
        retry_mesh.update()
        retry_mesh.normals_split_custom_set(np.repeat(sample_normals,3,axis=0))
        retry_ob=bpy.data.objects.new('14 Independent visible exterior samples',retry_mesh)
        scene.collection.objects.link(retry_ob)
        for ray in ['camera','diffuse','glossy','shadow','transmission']:
            setattr(retry_ob,'visible_'+ray,False)
        retry_colors=retry_mesh.color_attributes.new(name='ExteriorSamples',type='FLOAT_COLOR',domain='CORNER')
        retry_mesh.color_attributes.active_color=retry_colors
        bpy.ops.object.select_all(action='DESELECT');retry_ob.select_set(True)
        bpy.context.view_layer.objects.active=retry_ob
        bpy.context.view_layer.update()
        bpy.ops.object.bake(type='DIFFUSE', pass_filter={'DIRECT', 'INDIRECT', 'COLOR'})
        retry_values=np.empty(retries*3*4,dtype=np.float32)
        retry_colors.data.foreach_get('color',retry_values)
        measured=retry_values.reshape(retries,3,4)[:,:,:3].mean(axis=1)
        assert np.isfinite(measured).all(), 'Non-finite exterior samples'
        rgb[retry_mask] = measured
        recovered = int((measured @ np.array([.2126, .7152, .0722], dtype=np.float32) >= .02).sum())
        bpy.data.objects.remove(retry_ob,do_unlink=True);bpy.data.meshes.remove(retry_mesh)
        bpy.ops.object.select_all(action='DESELECT');proxy.select_set(True)
        bpy.context.view_layer.objects.active=proxy
    emit = any(has_emission(me.materials[index]) for index in set(mi))
    if emit:
        # Emission does not belong to DIFFUSE: add only the receiver's own emission.
        # Hidden emitters already contribute through Cycles direct/indirect transport.
        bpy.ops.object.bake(type='EMIT')
        colors.data.foreach_get('color', values)
        rgb += values.reshape(-1, 4)[:, :3]
    bpy.data.objects.remove(proxy, do_unlink=True)
    bpy.data.meshes.remove(proxy_mesh)
    assert np.isfinite(rgb).all(), f'{target.name}: non-finite bake samples'
    negative_channels = int((rgb < 0).sum())
    rgb = np.maximum(rgb, 0)
    luminance = rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)
    lo = np.minimum.reduceat(luminance, starts)
    hi = np.maximum.reduceat(luminance, starts)
    visible_faces = np.array([camera_region(center) for center in centers], dtype=np.bool_)
    view_direction = np.asarray(scene.camera.matrix_world.to_quaternion() @ Vector((0, 0, 1)), dtype=np.float32)
    facing = (normals @ view_direction) > .1
    candidate = visible_faces & facing
    # These identify candidates for visual review, not a claim that every dark
    # sample is a defect. Interior undersides legitimately receive little light.
    dark_wedges = candidate & (lo < .02) & (hi > .30)
    report = dict(name=target.name, vertices=nv, corners=nl,
                  max_radiance=float(rgb.max()), negative_channels=negative_channels, nonfinite_channels=0,
                  dark_corner_count=int((luminance < .02).sum()),
                  raw_dark_corner_count=int((raw_luminance < .02).sum()),
                  exterior_retry_samples=retries, exterior_retry_recovered=recovered,
                  exterior_geometry_hits=exterior_hits,
                  raw_radiance_percentiles=[float(value) for value in np.percentile(raw_luminance, [0, 1, 10, 50, 90, 99, 100])],
                  radiance_percentiles=[float(value) for value in np.percentile(luminance, [0, 1, 10, 50, 90, 99, 100])],
                  visible_facing_faces=int(candidate.sum()),
                  visible_dark_wedge_candidates=int(dark_wedges.sum()),
                  dark_wedge_centers=centers[dark_wedges][:16].tolist(),
                  receiver_emission_baked=emit)
    return rgb, report


start = time.time()
outputs, results, reports = [], [], []
for layer, parts in grouped.items():
    if not parts:
        continue
    bpy.ops.object.select_all(action='DESELECT')
    for ob in parts:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.convert(target='MESH')
    bpy.ops.object.join()
    target = bpy.context.object
    target.name = layer
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    subdivided = subdivide_visible(target, layer)
    rgb, report = bake_layer(target)
    report['subdivided_faces'] = subdivided
    outputs.append(target)
    results.append(rgb)
    reports.append(report)

maximum = max(float(rgb.max()) for rgb in results)
# Usually 16 or 32. Raise only if actual measurements require it, never silently
# clip warmth/highlights or assume the source's exposure is part of bake encoding.
scale = max(16, 2**math.ceil(math.log2(max(maximum*1.001, 1))))
for target, rgb, report in zip(outputs, results, reports):
    me = target.data
    for attr in list(me.color_attributes):
        me.color_attributes.remove(attr)
    colors = me.color_attributes.new(name='StudioRadiance', type='FLOAT_COLOR', domain='CORNER')
    me.color_attributes.active_color = colors
    encoded = np.ones((len(rgb), 4), np.float32)
    encoded[:, :3] = rgb / scale
    assert encoded[:, :3].max() < 1
    colors.data.foreach_set('color', encoded.ravel())
    me.update()
    report['clipped_channels'] = 0

bpy.ops.object.select_all(action='DESELECT')
for target in outputs:
    target.select_set(True)
bpy.context.view_layer.objects.active = outputs[0]
output = ROOT / f'{STEM}-baked.glb'
bpy.ops.export_scene.gltf(
    filepath=str(output), export_format='GLB', use_selection=True, export_apply=False,
    export_cameras=False, export_lights=False, export_animations=False,
    export_vertex_color='ACTIVE', export_all_vertex_colors=False,
    export_active_vertex_color_when_no_material=True,
    export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
    export_draco_position_quantization=24, export_draco_normal_quantization=12,
    export_draco_color_quantization=16)
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
assert hashlib.sha256(PLAN_FILE.read_bytes()).hexdigest() == plan_hash
assert [list(row) for row in scene.camera.matrix_world] == camera_matrix
report = dict(
    source=SOURCE.name, source_sha256=source_hash, plan_sha256=plan_hash,
    source_preserved=True, camera_unchanged=True, layers_preserved=True,
    radiance_scale=scale,
    encoding=f'COLOR_0 linear diffuse radiance with albedo + receiver emission / {scale}; A=1',
    engine='Cycles OptiX DIFFUSE direct + indirect + color; EMIT only on emitting receivers',
    samples=128, view_from='ABOVE_SURFACE', diffuse_bounces=scene.cycles.diffuse_bounces,
    hidden_emitters_retained_for_gi=len(emitter_names), hidden_emitters_exported=0,
    transmission_materials_approximated=sorted(set(approximated)),
    display_exposure=scene.view_settings.exposure, display_transform=scene.view_settings.view_transform,
    display_look=scene.view_settings.look,
    limitations='Diffuse vertex transport is not per-pixel Cycles glossy/transmission. Dark camera-facing corners use independent sampler triangles on the BVH-visible exterior along the LOCKED camera rays. This visibility-aware diffuse cache is view-specific and must be rebuilt if the approved camera or geometry changes. No denoising or low-value brightness clamping.',
    draco_position_quantization=24, objects=reports,
    bytes=output.stat().st_size, output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
    elapsed_seconds=round(time.time()-start, 2))
(ROOT / f'{STEM}-bake.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('STUDIO_BAKE_PASS', json.dumps({key: report[key] for key in ['radiance_scale', 'bytes', 'elapsed_seconds']}), flush=True)
