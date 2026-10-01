"""v26 网页资产导出:烘焙后的城市模型 + 树原型。只读打开 city-26-baked.blend,不保存。

    blender -b --python design/white-city/blender/export_v26_web.py -- [--img WEBP] [--quality 90]

输出 design/white-city/bake-v26/web/:
- city-v26-baked.glb:已烘焙对象(楼、地形、道路、河、岸墙、桥、地灯)。每个对象只留 lightmap 一套 UV,
  材质换成「底色 = 烘焙贴图」的单一材质;网页端统一替换为无光照材质直接显示贴图颜色。
- trees-v26.glb:1,394 棵树(4 个原型网格共享),网页端合并成 InstancedMesh,颜色取自锁定机位的树木渲染层。
"""
import bpy, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BAKE = ROOT.parent / 'bake-v26'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(k, d, cast=str):
    return cast(argv[argv.index(k) + 1]) if k in argv else d
BAKE = Path(arg('--bakedir', str(BAKE)))                   # v28 复用:--bakedir design/white-city/bake-v28
WEB = Path(arg('--out', str(BAKE / 'web')))
WEB.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=arg('--src', str(ROOT / 'city-26-baked.blend')))
scene = bpy.context.scene
manifest = json.loads(Path(arg('--manifest', str(BAKE / 'manifest.json'))).read_text(encoding='utf-8'))
by_obj = {v['object']: k for k, v in manifest.items()}

baked, trees, missing = [], [], []
for ob in scene.objects:
    if ob.type != 'MESH':
        continue
    col = ob.users_collection[0].name if ob.users_collection else ''
    if col == '07 Vegetation' or ob.data.name.startswith('13 Tree prototype'):     # v28 草坪点缀树也是树原型实例
        trees.append(ob)
    elif ob.name in by_obj:
        baked.append(ob)
    elif ob.get('v26_baked') is None and col != '07 Vegetation':
        missing.append(ob.name)
print('V26_EXPORT baked', len(baked), 'trees', len(trees), 'not baked (off-screen or pending)', len(missing), missing[:8], flush=True)

for ob in baked:
    key = by_obj[ob.name]
    me = ob.data
    for uvl in [u for u in me.uv_layers if u.name != 'lightmap']:
        me.uv_layers.remove(uvl)
    img = bpy.data.images.load(str(BAKE / f'{key}.png'), check_existing=True)
    img.colorspace_settings.name = 'sRGB'
    m = bpy.data.materials.new(f'v26 baked {key}')
    m.use_nodes = True
    nt = m.node_tree
    pb = nt.nodes['Principled BSDF']
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = img; tex.interpolation = 'Linear'
    uvn = nt.nodes.new('ShaderNodeUVMap'); uvn.uv_map = 'lightmap'
    nt.links.new(uvn.outputs[0], tex.inputs['Vector'])
    nt.links.new(tex.outputs['Color'], pb.inputs['Base Color'])
    pb.inputs['Roughness'].default_value = 1; pb.inputs['Metallic'].default_value = 0
    for slot in ob.material_slots:
        slot.link = 'OBJECT'; slot.material = m
    me.materials.clear(); me.materials.append(m)
    for slot in ob.material_slots:
        slot.link = 'DATA'
    ob['v26_key'] = key


def export(objs, path, **extra):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True, export_apply=True,
                              export_yup=True, export_extras=True, export_cameras=False, export_lights=False,
                              export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
                              export_draco_position_quantization=16, export_draco_texcoord_quantization=14,
                              export_normals=False, **extra)
    print('V26_EXPORTED', path, round(path.stat().st_size / 1e6, 2), 'MB', flush=True)


# 相机:原工程相机带镜头偏移(shift),烘焙与 Cycles 渲染都按它取景;网页相机必须用同一偏移才能对齐
cd = scene.camera.data
(WEB / 'camera.json').write_text(json.dumps({'matrix_world': [list(r) for r in scene.camera.matrix_world],
    'ortho_scale': cd.ortho_scale, 'shift_x': cd.shift_x, 'shift_y': cd.shift_y,
    'sensor_fit': cd.sensor_fit, 'resolution': [scene.render.resolution_x, scene.render.resolution_y]}, indent=1), encoding='utf-8')
fmt = arg('--img', 'WEBP')
export(baked, WEB / 'city-v26-baked.glb', export_image_format=fmt, export_image_quality=int(arg('--quality', 90)))
for ob in trees:
    ob.data.materials.clear()
    for s in ob.material_slots:
        s.link = 'DATA'
export(trees, WEB / 'trees-v26.glb', export_materials='NONE')
