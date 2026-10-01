"""v27 沙盘预览:把城市裁成矩形台面上的精致模型。只读打开 city-26-v26.blend,全部在内存里改,不保存。

    blender -b --python design/white-city/blender/render_v27_plinth.py -- --variant flat|layered [--samples 64]

- 台面矩形(设计坐标,Z 向上):x −345…335,y −150…210(680 × 360 m)。依据 renders-v27/topmap-grid.png 与高度采样:
  西、南两个朝镜头的侧面切过河道 / 河湾与西南小山,东北角本身是 47–60 m 的高坡。
- 地面类对象按四个平面 bisect 裁掉外侧;跨边界的楼、树删除;地灯删掉台外顶点。
- 台身:在矩形内按 2 m 网格对地面做射线采样,生成比真实地面低 0.25 m 的填充面(补北侧地形缺口),
  四周侧面按 0.5 m 采样贴合地形剖面一直落到台底。
- flat:剖面纯白实心,底下再垫一块略大的薄底座。
- layered:台身加厚到 40 m,剖面为 4 m 一层的等高线切片(每层一道浅槽、相邻层色阶交替),
  河道剖面是透明树脂块并夸张加深到 −22 m;无底座。
- 相机:正交,沿用 v26 的水平朝向,俯角 32°,模型约占画面宽 62%,中心在画面 37% 高度处(页面中下方)。
- 台底放阴影接收面(shadow catcher),背景透明,之后合成到页面底色上。
输出 renders-v27/plinth-<variant>.png(RGBA)。
"""
import bpy, bmesh, math, sys
import numpy as np
from pathlib import Path
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'renders-v27'
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(k, d, cast=str):
    return cast(argv[argv.index(k) + 1]) if k in argv else d
VARIANT = arg('--variant', 'flat')
X0, X1, Y0, Y1 = -345.0, 335.0, -150.0, 210.0
BASE = -6.0 if VARIANT == 'flat' else -40.0          # 层叠版台身加厚,剖面才读得出来(实际比例 14 m 在画面上只剩一条细边)
RESIN_BOTTOM = -22.0                                  # 层叠版树脂水体剖面夸张加深到 −22 m
PITCH = math.radians(float(arg('--pitch', 32)))

bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'city-26-v26.blend'))
sc = bpy.context.scene
col = lambda o: o.users_collection[0].name if o.users_collection else ''
GROUND = {'01 Terrain', '02 Water and banks', '03 Streets and sidewalks'}
river = sc.objects['13 Continuous river']

# ---------- 1. 射线采样地面高度(只让地面类对象参与) ----------
hidden = []
for o in sc.objects:
    if o.type == 'MESH' and col(o) not in GROUND:
        o.hide_viewport = True; hidden.append(o)
dg = bpy.context.evaluated_depsgraph_get()

def surface(x, y):
    """返回 (最上层地面高度含水面, 去掉水面后的河床/地面高度);没有地面返回 None。"""
    hit, loc, _, _, ob, _ = sc.ray_cast(dg, Vector((x, y, 500)), Vector((0, 0, -1)))
    if not hit:
        return None
    top = loc.z
    while hit and ob == river:
        hit, loc, _, _, ob, _ = sc.ray_cast(dg, loc - Vector((0, 0, .01)), Vector((0, 0, -1)))
    return top, (loc.z if hit else top - 3)

# 所有者要求:东南角那块平地不留,湖面一直延伸到台角
LAKE = lambda x, y: x > 120 and y < -15
STEP = 2.0
gx = np.arange(X0, X1 + .01, STEP); gy = np.arange(Y0, Y1 + .01, STEP)
H = np.full((len(gy), len(gx)), np.nan)          # 河床 / 地面高度(不含水面),给侧面剖面用
T = np.full((len(gy), len(gx)), np.nan)          # 最上层地表(含水面),给填充面用
for j, y in enumerate(gy):
    for i, x in enumerate(gx):
        s = surface(x, y)
        if s:
            H[j, i] = s[1]; T[j, i] = s[0]
HIT = ~np.isnan(T)                                # 该格上方有没有真实地面 / 水面
LAKE_MASK = np.array([[LAKE(x, y) for x in gx] for y in gy]) & (np.nan_to_num(T, nan=0) < 1.2)
# 缺口外推:反复用有效邻居的均值填补
def _fill(A):
    while np.isnan(A).any():
        P = np.pad(A, 1, constant_values=np.nan)
        nb = np.stack([P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]])
        cnt = (~np.isnan(nb)).sum(0); avg = np.nansum(nb, 0) / np.maximum(cnt, 1)
        A = np.where(np.isnan(A) & (cnt > 0), avg, A)
    return A
H = _fill(H); T = _fill(T)
T = np.where(LAKE_MASK, 0.0, T); H = np.where(LAKE_MASK, np.minimum(H, -1.5), H); HIT = HIT & ~LAKE_MASK

# 东岸陡坡一带(x > 260 m)的填充高度做平滑:2 m 网格在陡坡上采成台阶,渲染出一排暗三角
def _blur(A, r):
    k = np.exp(-np.arange(-r, r + 1) ** 2 / (2 * (r / 2) ** 2)); k /= k.sum()
    P_ = np.pad(A, r, mode='edge')
    P_ = np.apply_along_axis(lambda v: np.convolve(v, k, 'valid'), 1, P_)
    return np.apply_along_axis(lambda v: np.convolve(v, k, 'valid'), 0, P_)
Hs = _blur(H, 4)
wx = np.clip((gx - 260) / 20, 0, 1)[None, :] * np.clip((gy + 30) / 20, 0, 1)[:, None]   # 只在河道以北的坡地(y > −30 m)
H = H * (1 - wx) + Hs * wx
T = T * (1 - wx) + _blur(T, 4) * wx

def grid_t(x, y):
    i = min(max(int(round((x - X0) / STEP)), 0), len(gx) - 1); j = min(max(int(round((y - Y0) / STEP)), 0), len(gy) - 1)
    return T[j, i]

def grid_h(x, y):
    i = min(max(int(round((x - X0) / STEP)), 0), len(gx) - 1); j = min(max(int(round((y - Y0) / STEP)), 0), len(gy) - 1)
    return H[j, i]

for o in hidden:
    o.hide_viewport = False

# ---------- 2. 裁切 ----------
planes = [((X0, 0, 0), (-1, 0, 0)), ((X1, 0, 0), (1, 0, 0)), ((0, Y0, 0), (0, -1, 0)), ((0, Y1, 0), (0, 1, 0))]
for o in [o for o in sc.objects if o.type == 'MESH' and col(o) in GROUND | {'05 Bridges'}]:
    if o.data.users > 1:
        o.data = o.data.copy()
    inv = o.matrix_world.inverted(); n3 = o.matrix_world.to_3x3().transposed()
    bm = bmesh.new(); bm.from_mesh(o.data)
    for co, no in planes:
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=inv @ Vector(co), plane_no=(n3 @ Vector(no)).normalized(), clear_outer=True)
    bm.to_mesh(o.data); bm.free()

inside = lambda p, m=0: X0 + m <= p.x <= X1 - m and Y0 + m <= p.y <= Y1 - m
removed = 0
for o in [o for o in sc.objects if o.type == 'MESH' and col(o) in {'04 Buildings', '07 Vegetation'}]:
    bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
    ok = all(inside(p, 1) for p in bb) if col(o) == '04 Buildings' else inside(sum(bb, Vector()) / 8, 3)
    if not ok:
        bpy.data.objects.remove(o, do_unlink=True); removed += 1
lamps = sc.objects.get('v26 lamps')
if lamps:
    bm = bmesh.new(); bm.from_mesh(lamps.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not inside(lamps.matrix_world @ v.co, 1)], context='VERTS')
    bm.to_mesh(lamps.data); bm.free()
print('V27_CUT removed', removed, flush=True)

# ---------- 3. 材质 ----------
def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in c]

def principled(name, hexc, rough, **kw):
    m = bpy.data.materials.new(name); m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*srgb(hexc), 1); p.inputs['Roughness'].default_value = rough
    for k, v in kw.items():
        p.inputs[k].default_value = v
    return m

m_fill = principled('v27 plinth top', '#F4F4F1', .9)
m_bevel = principled('v27 bevel', '#F8F7F3', .55)          # 台边 45° 倒角:朝上受光形成细亮边
BEV = 1.4                                                   # 倒角宽 1.4 m(约 5 px @2560);0.7 m 时只有 2 px 读不出来
m_base = principled('v27 pedestal', '#ECEBE6', .75)
if VARIANT == 'layered':
    m_sec = principled('v27 section layers', '#EFEDE8', .85)
    nt = m_sec.node_tree; N = nt.nodes; L = nt.links; p = N['Principled BSDF']
    geo = N.new('ShaderNodeNewGeometry'); sep = N.new('ShaderNodeSeparateXYZ'); L.new(geo.outputs['Position'], sep.inputs[0])
    div = N.new('ShaderNodeMath'); div.operation = 'DIVIDE'; div.inputs[1].default_value = 4.0; L.new(sep.outputs['Z'], div.inputs[0])
    fr = N.new('ShaderNodeMath'); fr.operation = 'FRACT'; L.new(div.outputs[0], fr.inputs[0])
    groove = N.new('ShaderNodeMath'); groove.operation = 'LESS_THAN'; groove.inputs[1].default_value = .045; L.new(fr.outputs[0], groove.inputs[0])
    fl = N.new('ShaderNodeMath'); fl.operation = 'FLOOR'; L.new(div.outputs[0], fl.inputs[0])
    md = N.new('ShaderNodeMath'); md.operation = 'MODULO'; md.inputs[1].default_value = 2; L.new(fl.outputs[0], md.inputs[0])
    tone = N.new('ShaderNodeMix'); tone.data_type = 'RGBA'
    tone.inputs[6].default_value = (*srgb('#F3F1EC'), 1); tone.inputs[7].default_value = (*srgb('#DEDAD1'), 1)
    L.new(md.outputs[0], tone.inputs[0])
    mix = N.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.inputs[7].default_value = (*srgb('#A9A49A'), 1)
    L.new(tone.outputs[2], mix.inputs[6]); L.new(groove.outputs[0], mix.inputs[0]); L.new(mix.outputs[2], p.inputs['Base Color'])
    # 树脂水体:不透明、竖向渐变的淡青白(透明材质会透出伸进剖面的岸墙 / 河床,也无法烘焙进网页贴图)
    m_resin = principled('v27 resin', '#E6EEEE', .08, **{'Specular IOR Level': .7, 'Coat Weight': .6, 'Coat Roughness': .03})
    rn = m_resin.node_tree; RN = rn.nodes; rp = RN['Principled BSDF']
    rg = RN.new('ShaderNodeNewGeometry'); rs = RN.new('ShaderNodeSeparateXYZ'); rn.links.new(rg.outputs['Position'], rs.inputs[0])
    mr = RN.new('ShaderNodeMapRange'); mr.inputs['From Min'].default_value = RESIN_BOTTOM; mr.inputs['From Max'].default_value = 0
    rn.links.new(rs.outputs['Z'], mr.inputs['Value'])
    ramp = RN.new('ShaderNodeValToRGB'); rn.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
    ramp.color_ramp.elements[0].color = (*srgb('#8AA3A8'), 1); ramp.color_ramp.elements[1].color = (*srgb('#DCE7E8'), 1)
    mid_ = ramp.color_ramp.elements.new(.55); mid_.color = (*srgb('#BCCDCF'), 1)
    top_line = ramp.color_ramp.elements.new(.965); top_line.color = (*srgb('#D6E3E3'), 1)
    rn.links.new(ramp.outputs['Color'], rp.inputs['Base Color'])
else:
    m_sec = principled('v27 section', '#F2F1EC', .8)
    m_resin = None

# 东侧陡坡由细长面片组成,平滑着色后仍有尖锐暗三角:东岸 x > 285 m 的地形整片换成下方按 2 m 网格生成的
# 平顺填充面;其余地形平滑着色。台边 2 m 内的岸墙残片删除(台角碎片)
steep = 0
for o in [o for o in sc.objects if o.type == 'MESH' and col(o) == '01 Terrain']:
    n3 = o.matrix_world.to_3x3()
    bm_ = bmesh.new(); bm_.from_mesh(o.data)
    # 只处理东岸陡坡:x > 285 m 的地形面整片删掉(全局删陡面会误伤路堤,局部删陡面坡顶留锯齿)
    mw_ = o.matrix_world
    kill = [f for f in bm_.faces if (lambda c: c.x > 285 and c.y > -10)(mw_ @ f.calc_center_median())]
    steep += len(kill)
    bmesh.ops.delete(bm_, geom=kill, context='FACES')
    for f in bm_.faces:
        f.smooth = True
    bm_.to_mesh(o.data); bm_.free()
lake_removed = 0
for o in [o for o in sc.objects if o.type == 'MESH' and col(o) in {'01 Terrain', '02 Water and banks', '03 Streets and sidewalks'} and o.name != '13 Continuous river']:
    bm_ = bmesh.new(); bm_.from_mesh(o.data); mw_ = o.matrix_world
    kill = [f for f in bm_.faces if (lambda c: LAKE(c.x, c.y) and c.z < 1.2)(mw_ @ f.calc_center_median())]
    lake_removed += len(kill)
    bmesh.ops.delete(bm_, geom=kill, context='FACES'); bm_.to_mesh(o.data); bm_.free()
print('V27_LAKE_REMOVED', lake_removed, flush=True)
quay = sc.objects.get('13 Closed quay walls')
if quay:
    bm_ = bmesh.new(); bm_.from_mesh(quay.data); mw_ = quay.matrix_world
    def near_edge(p):
        return min(abs(p.x - X0), abs(p.x - X1), abs(p.y - Y0), abs(p.y - Y1)) < 2
    shard = [f for f in bm_.faces if near_edge(mw_ @ f.calc_center_median())]
    bmesh.ops.delete(bm_, geom=shard, context='FACES'); bm_.to_mesh(quay.data); bm_.free()
    print('V27_QUAY_SHARDS', len(shard), flush=True)
print('V27_STEEP_REMOVED', steep, flush=True)

# 河面:白底上几乎看不出水,改为略冷、光滑的树脂水面,能映出楼的倒影
rm = river.material_slots[0].material if river.material_slots else None
for slot in river.material_slots:
    # 只改水面材质:每个物体都挂着全部 7 个材质槽,遍历全部会把白墙 / 屋顶 / 路面 / 树冠一起染成青灰(final2–4 发蓝的原因)
    if slot.material and slot.material.name == '13 Still water' and slot.material.use_nodes and 'Principled BSDF' in slot.material.node_tree.nodes:
        pw = slot.material.node_tree.nodes['Principled BSDF']
        pw.inputs['Base Color'].default_value = (*srgb('#AEC0C3'), 1); pw.inputs['Roughness'].default_value = .02   # 光滑:映出岸边楼群与楼脚暖光
        pw.inputs['Specular IOR Level'].default_value = 1.0
        # 细微波纹:让水面接住高光和倒影,读得出是水
        wn = slot.material.node_tree; tc = wn.nodes.new('ShaderNodeTexCoord'); nz = wn.nodes.new('ShaderNodeTexNoise')
        nz.inputs['Scale'].default_value = .08; nz.inputs['Detail'].default_value = 3
        mp = wn.nodes.new('ShaderNodeMapping'); mp.inputs['Scale'].default_value = (1, 4, 1)
        wn.links.new(tc.outputs['Object'], mp.inputs['Vector']); wn.links.new(mp.outputs['Vector'], nz.inputs['Vector'])
        bump = wn.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = .025
        wn.links.new(nz.outputs['Fac'], bump.inputs['Height']); wn.links.new(bump.outputs['Normal'], pw.inputs['Normal'])

# ---------- 4. 台身 ----------
bm = bmesh.new()
mats = [m_fill, m_sec, m_base, m_resin or m_sec, next((sl.material for sl in river.material_slots if sl.material and sl.material.name == '13 Still water'), m_fill), m_bevel]
def quad(vs, mi):
    f = bm.faces.new([bm.verts.new(v) for v in vs]); f.material_index = mi; return f

# 填充顶面(比真实地面低 0.25 m)
vid = {}
for j, y in enumerate(gy):
    for i, x in enumerate(gx):
        # 有真实地面覆盖:藏在其下 0.25 m;没有覆盖(原本地形外的台角):与四周齐平,只低 0.02 m
        vid[j, i] = bm.verts.new((x, y, T[j, i] - (.25 if HIT[j, i] else .02)))
for j in range(len(gy) - 1):
    for i in range(len(gx) - 1):
        f = bm.faces.new([vid[j, i], vid[j, i + 1], vid[j + 1, i + 1], vid[j + 1, i]]); f.smooth = True
        # 河道模型在台边前就结束的台角:填充格用水面材质,让河面延伸到台边
        # 与水面同高的格一律用水面材质(被河面盖住的看不见;交界格若按是否有地面区分,会露出一排白色锯齿)
        f.material_index = 4 if max(T[j, i], T[j, i + 1], T[j + 1, i], T[j + 1, i + 1]) < .3 else 0

# 侧面(正式版重写):沿四条边每 0.25 m 一列,整条剖面共用顶点;干 / 湿交界在两样本中点插入竖直边。
# 预览版逐段独立生成,干湿交界处出现白色尖角和断口(所有者截图)。
# 侧面采样只打在地面类对象上(裁切后重新求值)
for o in sc.objects:
    if o.type == 'MESH' and col(o) not in GROUND:
        o.hide_viewport = True
dg = bpy.context.evaluated_depsgraph_get()
edges = [((X0, Y0), (X1, Y0), (0, -1)), ((X1, Y0), (X1, Y1), (1, 0)), ((X1, Y1), (X0, Y1), (0, 1)), ((X0, Y1), (X0, Y0), (-1, 0))]
resin_runs = 0
SAMPLE = .25
for (ax, ay), (bx, by), (nx, ny) in edges:
    L_ = math.hypot(bx - ax, by - ay); n = int(L_ / SAMPLE)
    prof = []
    for k in range(n + 1):
        t = k / n; x = ax + (bx - ax) * t; y = ay + (by - ay) * t
        s_ = surface(x - nx * .05, y - ny * .05)
        top, bed = s_ if s_ else (grid_t(x, y) - .02, grid_t(x, y) - .02)     # 无地面处跟随齐平的填充面
        if x > 285 and y > -10 and top - bed <= .15:                        # 东岸地形已换成平滑填充面,侧面顶边跟随它
            top = bed = grid_t(x, y) - .25
        if LAKE(x - nx * .05, y - ny * .05) and grid_t(x, y) < .3:
            top, bed = 0.0, -1.5
        wet = bool(m_resin) and top - bed > .15
        prof.append((t, top, wet))
    # 两段水带之间不足 4 m 的干段(河口处的一小段岸)并入水带,避免水带中间出现白色竖条
    gap_max = int(4 / SAMPLE)
    k = 0
    while k < len(prof):
        if prof[k][2]:
            k += 1; continue
        j = k
        while j < len(prof) and not prof[j][2]:
            j += 1
        if k > 0 and j < len(prof) and j - k <= gap_max:
            tops = [prof[k - 1][1], prof[j][1]]
            for m in range(k, j):
                prof[m] = (prof[m][0], min(tops), True)
        k = j
    # 列:(参数 t, 实心剖面顶高, 是否湿);交界处在中点放两列(干顶 / 湿顶),形成竖直边
    cols = []
    for k, (t, top, wet) in enumerate(prof):
        if k and wet != prof[k - 1][2]:
            tm = (t + prof[k - 1][0]) / 2
            dry_top = prof[k - 1][1] if not prof[k - 1][2] else top
            first, second = (dry_top, RESIN_BOTTOM) if not prof[k - 1][2] else (RESIN_BOTTOM, dry_top)
            cols.append((tm, first, prof[k - 1][2], prof[k - 1][1])); cols.append((tm, second, wet, top))
        cols.append((t, RESIN_BOTTOM if wet else top, wet, top))
    P = lambda t, z: (ax + (bx - ax) * t, ay + (by - ay) * t, z)
    bottom = [bm.verts.new(P(c[0], BASE)) for c in cols]
    upper = [bm.verts.new(P(c[0], c[1] if c[2] else c[1] - BEV)) for c in cols]
    for k in range(len(cols) - 1):
        if cols[k + 1][0] - cols[k][0] < 1e-6:
            continue
        f = bm.faces.new([bottom[k], bottom[k + 1], upper[k + 1], upper[k]]); f.material_index = 1
        if not cols[k][2] and not cols[k + 1][2]:
            # 倒角:从剖面顶边(地表 − BEV)斜向内上到地表 + 0.02 m
            a_, b_ = cols[k], cols[k + 1]
            inner = lambda c: bm.verts.new((P(c[0], 0)[0] - nx * BEV, P(c[0], 0)[1] - ny * BEV, c[1] + .02))
            f = bm.faces.new([upper[k], upper[k + 1], inner(b_), inner(a_)]); f.material_index = 5
    # 树脂水体:连续湿列组成一个闭合棱柱(正面 / 背面 / 顶 / 底 / 两端),深 0.7 m
    k = 0
    while k < len(cols):
        if not cols[k][2]:
            k += 1; continue
        j = k
        while j + 1 < len(cols) and cols[j + 1][2]:
            j += 1
        run = cols[k:j + 1]
        if len(run) >= 2:
            # 树脂水体:顶边做成半径 BEV 的四分之一圆角(所有者要求水的边缘圆角),深度 = BEV
            D = BEV; ix, iy = -nx * D, -ny * D
            SEG = 8
            fb = [bm.verts.new(P(c[0], RESIN_BOTTOM)) for c in run]
            bb_ = [bm.verts.new((v.co.x + ix, v.co.y + iy, v.co.z)) for v in fb]
            # 每列一条圆弧:圆心在(边线内缩 R,水面 − R),θ 从 0(正面)到 90°(顶面)
            arcs = []
            for c in run:
                px_, py_, _ = P(c[0], 0); top_ = c[3] - .01
                ring = []
                for q in range(SEG + 1):
                    th = math.pi / 2 * q / SEG
                    ring.append(bm.verts.new((px_ - nx * BEV + nx * BEV * math.cos(th), py_ - ny * BEV + ny * BEV * math.cos(th),
                                              top_ - BEV + BEV * math.sin(th))))
                arcs.append(ring)
            for i in range(len(run) - 1):
                if run[i + 1][0] - run[i][0] < 1e-6:
                    continue
                bm.faces.new([fb[i], fb[i + 1], arcs[i + 1][0], arcs[i][0]]).material_index = 3          # 正面
                for q in range(SEG):
                    f = bm.faces.new([arcs[i][q], arcs[i + 1][q], arcs[i + 1][q + 1], arcs[i][q + 1]]); f.material_index = 3; f.smooth = True
                bm.faces.new([bb_[i + 1], bb_[i], arcs[i][SEG], arcs[i + 1][SEG]]).material_index = 3    # 背面
                bm.faces.new([fb[i + 1], fb[i], bb_[i], bb_[i + 1]]).material_index = 3                   # 底面
            bm.faces.new([fb[0]] + arcs[0] + [bb_[0]]).material_index = 3
            bm.faces.new([bb_[-1]] + arcs[-1][::-1] + [fb[-1]]).material_index = 3
            resin_runs += 1
        k = j + 1
for o in sc.objects:
    o.hide_viewport = False
# 台底
quad([(X0, Y1, BASE), (X1, Y1, BASE), (X1, Y0, BASE), (X0, Y0, BASE)], 1)
# flat 版底座:四周外扩 10 m、厚 4 m 的薄板
if VARIANT == 'flat':
    m_ = 10; z0, z1 = BASE - 4, BASE
    c = [(X0 - m_, Y0 - m_), (X1 + m_, Y0 - m_), (X1 + m_, Y1 + m_), (X0 - m_, Y1 + m_)]
    for k in range(4):
        (xa, ya), (xb, yb) = c[k], c[(k + 1) % 4]
        quad([(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)], 2)
    quad([(x, y, z1) for x, y in c], 2); quad([(x, y, z0) for x, y in c[::-1]], 2)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=.001)
bm.normal_update()
me = bpy.data.meshes.new('v27 plinth'); bm.to_mesh(me); bm.free()
for m in mats:
    me.materials.append(m)
plinth = bpy.data.objects.new('v27 plinth', me); sc.collection.objects.link(plinth)

print('V27_PLINTH faces', len(me.polygons), 'resin segments', resin_runs, flush=True)

# ---------- 湖面船只与码头(所有者选的创意 2)----------
if '--noboats' not in argv:
    import random
    rng_b = random.Random(27)
    m_boat = principled('v27 boat', '#F6F5F1', .5)
    WATER = T < .3
    ER = WATER.copy()
    for _ in range(6):                                   # 离岸至少约 12 m
        ER[1:-1, 1:-1] = ER[1:-1, 1:-1] & ER[:-2, 1:-1] & ER[2:, 1:-1] & ER[1:-1, :-2] & ER[1:-1, 2:]
    cand = [(gx[i], gy[j]) for j, i in zip(*np.nonzero(ER))]
    rng_b.shuffle(cand)
    bbm = bmesh.new(); boats = []
    def box(cx, cy, z0, L, Wd, Hh, ang, bow=False):
        ca, sa = math.cos(ang), math.sin(ang)
        pts = []
        for dz in (z0, z0 + Hh):
            for lx, ly in ((-L / 2, -Wd / 2), (L / 2, -Wd / 2), (L / 2, Wd / 2), (-L / 2, Wd / 2)):
                if bow and lx > 0:
                    ly *= .15 if dz > z0 else .05
                pts.append(bbm.verts.new((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca, dz)))
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            bbm.faces.new([pts[i] for i in q])
    for x, y in cand:
        if len(boats) >= 5:
            break
        if not (-300 < x < 320 and -140 < y < 0) or any(math.hypot(x - bx, y - by) < 45 for bx, by in boats):
            continue
        L = rng_b.uniform(9, 14); ang = rng_b.uniform(0, math.tau)
        box(x, y, -.35, L, L * .32, 1.05, ang, bow=True)                     # 船身(船头收尖)
        box(x - math.cos(ang) * L * .12, y - math.sin(ang) * L * .12, .7, L * .36, L * .22, .9, ang)   # 舱室
        boats.append((x, y))
    # 码头:从城市南岸伸入湖面的栈道 + 桩
    piers = 0
    for px_ in (230.0, 165.0):
        i = int(round((px_ - X0) / STEP)); shore = None
        for j in range(len(gy) - 1, -1, -1):
            if gy[j] < -5 and WATER[j, i] and j + 1 < len(gy) and not WATER[j + 1, i]:
                shore = gy[j]; break
        if shore is None:
            continue
        length = 26 if piers == 0 else 18
        for k_ in range(int(length / 2)):
            yk = shore + 1 - k_ * 2
            bbm_f = box(px_, yk - 1, .75, 2.9, 2.0, .25, math.pi / 2)
        for k_ in range(0, int(length / 5) + 1):
            for side in (-1.2, 1.2):
                box(px_ + side, shore + 1 - k_ * 5, -1.5, .35, .35, 2.4, 0)
        piers += 1
    bme = bpy.data.meshes.new('v27 boats'); bbm.to_mesh(bme); bbm.free(); bme.materials.append(m_boat)
    sc.collection.objects.link(bpy.data.objects.new('v27 boats', bme))
    print('V27_BOATS', len(boats), 'piers', piers, flush=True)

# 阴影接收面
floor_z = BASE - (4 if VARIANT == 'flat' else 0) - .01
fl_me = bpy.data.meshes.new('v27 floor'); fbm = bmesh.new()
fbm.faces.new([fbm.verts.new(v) for v in [(-3000, -3000, floor_z), (3000, -3000, floor_z), (3000, 3000, floor_z), (-3000, 3000, floor_z)]])
fbm.to_mesh(fl_me); fbm.free()
floor = bpy.data.objects.new('v27 floor', fl_me); sc.collection.objects.link(floor); floor.is_shadow_catcher = True

# ---------- 户型样板(v28):沙盘右侧同一张桌面上的 4 栋高精度白模 ----------
SIGNS = []
LAWN_CENTERS = []
if '--houses' in argv:
    sys.path.insert(0, str(ROOT))
    import build_v28_houses as v28
    fxy_ = (sc.camera.matrix_world.to_3x3() @ Vector((0, 0, -1))); fxy_.z = 0; fxy_.normalize()
    right_xy = Vector((fxy_.y, -fxy_.x, 0))                       # 画面右方向(水平)
    cxy = Vector(((X0 + X1) / 2, (Y0 + Y1) / 2, 0))
    half = max((Vector((x, y, 0)) - cxy).dot(right_xy) for x in (X0, X1) for y in (Y0, Y1))
    gap, spacing = float(arg('--hgap', 95)), float(arg('--hspacing', 118))
    toward_cam = math.atan2(-fxy_.y, -fxy_.x)
    rot = toward_cam - math.pi / 2 - math.radians(float(arg('--hyaw', 35)))     # 正面偏离正对镜头 35°,看到正面 + 侧面
    lawn_bottom = -1.2 * v28.SCALE
    placements = []
    # 2 × 2 错位排布:矮的两栋(独立屋、别墅)在前排,高的两栋(联排、公寓)在后排并向右错开半格,
    # 互不遮挡;整组紧凑,镜头拉近时 4 栋都在画面里、牌子都读得清
    back_xy = Vector((fxy_.x, fxy_.y, 0))
    grid = [(0, 0), (1, 0), (.5, 1), (1.5, 1)]                    # (右移格数, 后移排数)
    for i, (gxs, gys) in enumerate(grid):
        c = cxy + right_xy * (half + gap + gxs * spacing) + back_xy * (gys * float(arg('--hdepth', 150)) - 40)
        placements.append(((c.x, c.y, BASE - lawn_bottom), rot))
        LAWN_CENTERS.append(Vector((c.x, c.y, BASE + 15)) + right_xy * 25)   # 右侧信息牌也算进构图中心
    tree_meshes = [bpy.data.meshes[f'13 Tree prototype {i}'] for i in range(4) if f'13 Tree prototype {i}' in bpy.data.meshes]
    for name, corners in v28.build(sc, placements, sign_rot=toward_cam - math.pi / 2, tree_meshes=tree_meshes):
        SIGNS.append((name, corners))
    print('V28_HOUSES', [(n, tuple(round(v, 1) for v in placements[i][0])) for i, (n, _) in enumerate(SIGNS)], flush=True)

# ---------- 5. 相机 ----------
old = sc.camera
fxy = (old.matrix_world.to_3x3() @ Vector((0, 0, -1))); fxy.z = 0; fxy.normalize()
fwd = Vector((fxy.x * math.cos(PITCH), fxy.y * math.cos(PITCH), -math.sin(PITCH)))
target = Vector((float(arg('--tx', (X0 + X1) / 2)), float(arg('--ty', (Y0 + Y1) / 2)), 12))
if '--pan' in argv and LAWN_CENTERS:
    end_t = sum(LAWN_CENTERS, Vector()) / len(LAWN_CENTERS)        # 镜头右移后的终点:对准户型样板中心
    fr_ = float(arg('--panfrac', 1.0))                              # 0 = 城市机位,1 = 户型机位(预览中间帧用)
    target = target.lerp(end_t, fr_)
cam_d = bpy.data.cameras.new('v27 cam'); cam_d.type = 'ORTHO'; cam_d.clip_end = 10000
cam = bpy.data.objects.new('v27 cam', cam_d); sc.collection.objects.link(cam)
cam.location = target - fwd * 3000
cam.rotation_euler = fwd.to_track_quat('-Z', 'Y').to_euler()
sc.camera = cam
bpy.context.view_layer.update()
right = cam.matrix_world.to_3x3() @ Vector((1, 0, 0)); up = cam.matrix_world.to_3x3() @ Vector((0, 1, 0))
m_ = 10 if VARIANT == 'flat' else 0
corners = [Vector((x, y, z)) for x in (X0 - m_, X1 + m_) for y in (Y0 - m_, Y1 + m_) for z in (BASE - 4, 62)]
us = [(p - target).dot(right) for p in corners]; vs = [(p - target).dot(up) for p in corners]
RX, RY = int(arg('--rx', 1920)), int(arg('--ry', 1080))
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = RX, RY, 100
width = float(arg('--ortho', 0)) or (max(us) - min(us)) / float(arg('--fill', .62))   # --ortho 直接指定画框宽度(米)
cam_d.ortho_scale = width
frame_h = width * RY / RX
uc, vc = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
cam_d.shift_x = (uc if '--ortho' not in argv else 0) / width
cam_d.shift_y = (vc + (.5 - float(arg('--ycenter', .37))) * frame_h) / width
if '--topfrac' in argv and ('--pan' not in argv or float(arg('--panfrac', 1.0)) == 0):
    # 让楼群最高点落在画面高度 topfrac 处(从底部算),上方留给主页标题
    vtop = max((o.matrix_world @ Vector(c) - target).dot(up) for o in sc.objects if o.type == 'MESH' and col(o) == '04 Buildings' for c in o.bound_box)
    cam_d.shift_y = (vtop - (float(arg('--topfrac', .65)) - .5) * frame_h) / width
print('V27_CAMERA ortho', round(width, 1), 'shift', round(cam_d.shift_x, 4), round(cam_d.shift_y, 4), flush=True)

# ---------- 6. 渲染 ----------
sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == 'OPTIX'
sc.cycles.samples = int(arg('--samples', 64)); sc.cycles.use_denoising = True
sc.cycles.transmission_bounces = 8
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'
OUT.mkdir(exist_ok=True)
sc.render.filepath = str(OUT / f"plinth-{VARIANT}{arg('--tag', '')}.png")
if '--camjson' in argv:
    # 记录当前机位(世界矩阵、正交宽度、镜头偏移、分辨率),网页与宽幅烘焙机位用
    import json as _json
    cdd = sc.camera.data
    Path(arg('--camjson', 'cam.json')).write_text(_json.dumps({'matrix_world': [list(r) for r in sc.camera.matrix_world],
        'ortho_scale': cdd.ortho_scale, 'shift_x': cdd.shift_x, 'shift_y': cdd.shift_y,
        'resolution': [sc.render.resolution_x, sc.render.resolution_y]}, indent=1), encoding='utf-8')
    if SIGNS:
        Path(arg('--camjson', 'cam.json').replace('.json', '-signs3d.json')).write_text(_json.dumps({n: [list(c) for c in cs] for n, cs in SIGNS}, indent=1), encoding='utf-8')
if '--saveas' in argv:
    dst = ROOT / arg('--saveas', 'city-27-plinth.blend')
    assert dst.name not in ('city-13-smooth.blend', 'city-26-v26.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(dst), copy=True, compress=True)
    print('V27_SAVED', dst, flush=True)
if '--norender' not in argv:
    floor.hide_render = True                                    # 模型层:不含地面影子
    bpy.ops.render.render(write_still=True)
    if SIGNS:
        from bpy_extras.object_utils import world_to_camera_view
        import json as _json
        data = {n: [[round(q.x, 5), round(1 - q.y, 5)] for q in (world_to_camera_view(sc, sc.camera, c) for c in cs)] for n, cs in SIGNS}
        Path(sc.render.filepath.replace('.png', '-signs.json')).write_text(_json.dumps(data, indent=1), encoding='utf-8')
    if '--depthpass' in argv:
        # 深度层:视线方向距离编码成灰度(16 位),合成移轴景深用;关色调映射,不参与降噪
        vs_, look_, exp_ = sc.view_settings.view_transform, sc.view_settings.look, sc.view_settings.exposure
        sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'; sc.view_settings.exposure = 0
        dm = bpy.data.materials.new('v28 depth'); dm.use_nodes = True; dn = dm.node_tree.nodes; dl = dm.node_tree.links
        dn.remove(dn['Principled BSDF'])
        camd = dn.new('ShaderNodeCameraData'); mr = dn.new('ShaderNodeMapRange')
        mr.inputs['From Min'].default_value = float(arg('--dnear', 2500)); mr.inputs['From Max'].default_value = float(arg('--dfar', 3500))
        em = dn.new('ShaderNodeEmission'); dl.new(camd.outputs['View Z Depth'], mr.inputs['Value'])
        dl.new(mr.outputs['Result'], em.inputs['Color']); dl.new(em.outputs[0], dn['Material Output'].inputs['Surface'])
        vl = sc.view_layers[0]; vl.material_override = dm
        floor.hide_render = True
        smp, den = sc.cycles.samples, sc.cycles.use_denoising
        sc.cycles.samples = 4; sc.cycles.use_denoising = False
        sc.render.image_settings.color_depth = '16'
        main_path = sc.render.filepath
        sc.render.filepath = main_path.replace('.png', '-depth.png')
        bpy.ops.render.render(write_still=True)
        sc.render.filepath = main_path; vl.material_override = None
        sc.view_settings.view_transform, sc.view_settings.look, sc.view_settings.exposure = vs_, look_, exp_
        sc.cycles.samples, sc.cycles.use_denoising = smp, den
        sc.render.image_settings.color_depth = '8'
    if '--shadowpass' in argv:
        # 影子层:模型全部 holdout(仍投影),只留阴影接收面 → alpha 就是影子浓度;合成时分层叠加,不再用亮度阈值猜
        floor.hide_render = False
        for o in sc.objects:
            if o.type == 'MESH' and o is not floor:
                o.is_holdout = True
        sc.cycles.samples = int(arg('--shadowsamples', 64))
        main_path = sc.render.filepath
        sc.render.filepath = main_path.replace('.png', '-shadow.png')
        bpy.ops.render.render(write_still=True)
        sc.render.filepath = main_path
print('V27_DONE', sc.render.filepath, flush=True)
