# Cycles 间接光烘焙 → 顶点色。不走 UV2/图集:Cycles 支持 target='VERTEX_COLORS' 直接写顶点色,
# 而本模型立面本身有 177 个四边面/朝向,顶点密度足够承载这种低频光照。
# 只烘 DIFFUSE 的 indirect 通道(关掉 direct 与 color) —— 要的就是"每栋楼接收到邻居反弹光各不相同"。
# 源工程只读打开,不保存;只导出到本目录。
# 用法:blender -b --python bake_gi.py -- <src.blend> <out.glb> <samples> <device>
import bpy, sys

argv = sys.argv[sys.argv.index('--') + 1:]
src, out = argv[0], argv[1]
SAMPLES = int(argv[2]) if len(argv) > 2 else 48
DEVICE = argv[3] if len(argv) > 3 else 'GPU'

bpy.ops.wm.open_mainfile(filepath=src)
scene = bpy.context.scene

# ---- 世界:中性棚拍天光(上亮下暖),与网页端的 studioEnvironment 同一套关系 ----
world = scene.world or bpy.data.worlds.new('W')
scene.world = world
world.use_nodes = True
nt = world.node_tree
nt.nodes.clear()
out_node = nt.nodes.new('ShaderNodeOutputWorld')
bg = nt.nodes.new('ShaderNodeBackground')
ramp = nt.nodes.new('ShaderNodeValToRGB')
sep = nt.nodes.new('ShaderNodeSeparateXYZ')
tex = nt.nodes.new('ShaderNodeTexCoord')
bg.inputs['Strength'].default_value = 1.0
# 生成坐标的 Z 即仰角方向:顶部亮、地平线中、底部带暖
ramp.color_ramp.elements[0].position = 0.0
ramp.color_ramp.elements[0].color = (1.00, 0.92, 0.80, 1)   # 地面暖反射
ramp.color_ramp.elements[1].position = 1.0
ramp.color_ramp.elements[1].color = (1.55, 1.55, 1.55, 1)   # 天顶
mid = ramp.color_ramp.elements.new(0.5)
mid.color = (1.00, 0.99, 0.97, 1)                            # 地平线
nt.links.new(tex.outputs['Generated'], sep.inputs['Vector'])
nt.links.new(sep.outputs['Z'], ramp.inputs['Fac'])
nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
nt.links.new(bg.outputs['Background'], out_node.inputs['Surface'])

# ---- Cycles 设置 ----
scene.render.engine = 'CYCLES'
try:
    scene.cycles.device = DEVICE
except Exception as e:
    print(f'device={DEVICE} 设置失败: {e}')
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 6
scene.cycles.diffuse_bounces = 6
scene.cycles.glossy_bounces = 2
scene.cycles.bake_type = 'DIFFUSE'
bk = scene.render.bake
bk.use_pass_direct = False
bk.use_pass_indirect = True
bk.use_pass_color = False
bk.target = 'VERTEX_COLORS'
bk.margin = 0
bk.use_clear = True

buildings = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('B')]
print(f'GI bake: buildings={len(buildings)} samples={SAMPLES} device={DEVICE}')

bpy.ops.object.select_all(action='DESELECT')
kept = []
for o in buildings:
    me = o.data
    ca = me.color_attributes.get('BakedGI')
    if ca is None or ca.domain != 'CORNER':
        ca = me.color_attributes.new(name='BakedGI', type='BYTE_COLOR', domain='CORNER')
    try:
        me.color_attributes.active_color_index = list(me.color_attributes).index(ca)
    except Exception:
        pass
    o.select_set(True)
    kept.append(o)

bpy.context.view_layer.objects.active = kept[0]
try:
    bpy.ops.object.bake(type='DIFFUSE', use_selected_to_active=False)
    print('BAKE ok')
except Exception as e:
    print(f'BAKE FAILED: {e}')
    raise

# 统计写入结果
mn, mx, sm, n = 9.0, -9.0, 0.0, 0
for o in kept:
    ca = o.data.color_attributes.get('BakedGI')
    if not ca:
        continue
    for d in ca.data:
        v = d.color[0]
        mn = min(mn, v); mx = max(mx, v); sm += v; n += 1
print(f'GI values: min={mn:.3f} max={mx:.3f} mean={(sm/max(1,n)):.3f} n={n}')

kw = dict(filepath=out, export_format='GLB', export_apply=True, export_yup=True)
DRACO = dict(export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
             export_draco_position_quantization=14, export_draco_normal_quantization=10,
             export_draco_color_quantization=10)
for vc_kw in ({'export_vertex_color': 'ACTIVE', 'export_all_vertex_colors': True}, {'export_all_vertex_colors': True}, {}):
    try:
        bpy.ops.export_scene.gltf(**kw, **DRACO, **vc_kw)
        print(f'EXPORTED {out}  vc_kw={vc_kw}')
        break
    except TypeError as e:
        print(f'  vc_kw={vc_kw} 不支持: {e}')
