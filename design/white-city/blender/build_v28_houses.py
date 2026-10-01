"""v28 户型样板:4 栋高精度白模 + 方形草坪 + 澳洲式地插销售牌。

    blender -b --python design/white-city/blender/build_v28_houses.py -- [--preview] [--samples 128]

四栋都对应数据库里真实存在的房型(house / townhouse / apartment,见 app/orchestration/graph.py):
  1 单层独立屋(house)  2 双层小别墅(house)  3 联排别墅(townhouse,三户)  4 小公寓楼(apartment,四层)
按真实尺寸(米)建模,再整体放大 SCALE 倍 —— 与城市沙盘相比是「更大比例的户型模型」。
--preview:新建空场景单独渲染 4 栋近景,检查模型精度(renders-v28/houses-preview.png);
不带 --preview 时只提供 build(scene, origin_list, ...) 给沙盘场景脚本调用。
"""
import bpy, bmesh, math, sys
from pathlib import Path
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'renders-v28'
SCALE = 5.0                                          # 户型模型比例放大到 5 倍:与 40 m 厚的沙盘台身并置时读得出细节


def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in c]


def material(name, hexc, rough, **kw):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = (*srgb(hexc), 1)
    p.inputs['Roughness'].default_value = rough
    for k, v in kw.items():
        p.inputs[k].default_value = v
    return m


def materials():
    M = {
        'wall': material('v28 white clay', '#F3F2EE', .6),
        'trim': material('v28 trim', '#FAF9F6', .45),
        'roof': material('v28 roof', '#E9E7E1', .7),
        'glass': material('v28 glass', '#C4CED1', .12, **{'Specular IOR Level': .8}),
        'dark': material('v28 recess', '#D6D4CE', .8),
        'water': material('v28 pool', '#9FC3C4', .04, **{'Specular IOR Level': .9}),
        'sign': material('v28 sign board', '#FBFBF9', .5),
        'band': material('v28 sign band', '#DAD8D2', .6),
        'post': material('v28 sign post', '#E4E1DA', .6),
    }
    # 草:青绿色,细噪声色差 + 细凹凸,像建筑模型的植绒草皮
    g = material('v28 grass', '#4E9C7C', .95)                # 青绿,与白色城市形成对比
    nt = g.node_tree; N = nt.nodes; L = nt.links; p = N['Principled BSDF']
    tc = N.new('ShaderNodeTexCoord'); nz = N.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 3.5; nz.inputs['Detail'].default_value = 8
    L.new(tc.outputs['Object'], nz.inputs['Vector'])
    ramp = N.new('ShaderNodeValToRGB'); L.new(nz.outputs['Fac'], ramp.inputs['Fac'])
    ramp.color_ramp.elements[0].position = .35; ramp.color_ramp.elements[0].color = (*srgb('#3F8C6F'), 1)
    ramp.color_ramp.elements[1].position = .7; ramp.color_ramp.elements[1].color = (*srgb('#62AC8C'), 1)
    L.new(ramp.outputs['Color'], p.inputs['Base Color'])
    fine = N.new('ShaderNodeTexNoise'); fine.inputs['Scale'].default_value = 60; fine.inputs['Detail'].default_value = 4
    L.new(tc.outputs['Object'], fine.inputs['Vector'])
    bump = N.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = .35
    L.new(fine.outputs['Fac'], bump.inputs['Height']); L.new(bump.outputs['Normal'], p.inputs['Normal'])
    p.inputs['Sheen Weight'].default_value = .4
    M['grass'] = g
    M['soil'] = material('v28 lawn base', '#EDEBE5', .8)
    M['path'] = material('v28 path', '#E3E0D8', .85)
    return M


class Kit:
    """在一个 bmesh 里累积盒子 / 棱柱,最后生成一个对象。坐标为本地米制(z 向上,+y 为房子正面朝向)。"""

    def __init__(self, M):
        self.bm = bmesh.new(); self.M = M; self.slots = []

    def mi(self, key):
        m = self.M[key]
        if m not in self.slots:
            self.slots.append(m)
        return self.slots.index(m)

    def box(self, c, s, key='wall', smooth=False):
        (cx, cy, cz), (sx, sy, sz) = c, s
        v = [self.bm.verts.new((cx + dx * sx / 2, cy + dy * sy / 2, cz + dz * sz / 2))
             for dz in (-1, 1) for dy in (-1, 1) for dx in (-1, 1)]
        idx = self.mi(key)
        for q in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
            f = self.bm.faces.new([v[i] for i in q]); f.material_index = idx

    def poly_prism(self, pts, z0, z1, key='wall'):
        """xy 平面多边形(逆时针)拉伸成棱柱。"""
        idx = self.mi(key)
        lo = [self.bm.verts.new((x, y, z0)) for x, y in pts]
        hi = [self.bm.verts.new((x, y, z1)) for x, y in pts]
        self.bm.faces.new(lo[::-1]).material_index = idx
        self.bm.faces.new(hi).material_index = idx
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            self.bm.faces.new([lo[i], lo[j], hi[j], hi[i]]).material_index = idx

    def gable_roof(self, cx, cy, z, length, depth, pitch, thick=.22, over=.55, key='roof', axis='x'):
        """双坡屋顶:屋脊沿 axis;两片有厚度的屋面 + 山墙三角封板(墙色)。"""
        rise = depth / 2 * math.tan(math.radians(pitch))
        L = length + 2 * over; hd = depth / 2 + over; drop = over * math.tan(math.radians(pitch))
        for side in (-1, 1):
            # 屋面板:从檐口(外伸 over、下降 drop)到屋脊
            a = (-L / 2, side * hd, z - drop); b = (L / 2, side * hd, z - drop)
            c = (L / 2, 0, z + rise); d = (-L / 2, 0, z + rise)
            quad = [a, b, c, d]
            idx = self.mi(key)
            vs_lo = [self.bm.verts.new(self._ax(cx, cy, p, axis)) for p in quad]
            vs_hi = [self.bm.verts.new(self._ax(cx, cy, (p[0], p[1], p[2] + thick), axis)) for p in quad]
            for f in (vs_lo[::-1], vs_hi):
                self.bm.faces.new(f).material_index = idx
            for i in range(4):
                j = (i + 1) % 4
                self.bm.faces.new([vs_lo[i], vs_lo[j], vs_hi[j], vs_hi[i]]).material_index = idx
        # 山墙三角
        for end in (-1, 1):
            tri = [(end * length / 2, -depth / 2, z), (end * length / 2, depth / 2, z), (end * length / 2, 0, z + rise)]
            vs = [self.bm.verts.new(self._ax(cx, cy, p, axis)) for p in tri]
            flip = (end > 0) == (axis == 'x')                  # axis='y' 时 x/y 互换是镜像,绕序要反过来(否则山墙朝内,网页被背面剔除)
            self.bm.faces.new(vs if flip else vs[::-1]).material_index = self.mi('wall')
        return rise

    @staticmethod
    def _ax(cx, cy, p, axis):
        x, y, z = p
        return (cx + x, cy + y, z) if axis == 'x' else (cx + y, cy + x, z)

    def window(self, cx, y_face, zc, w, h, facing=1, mullions=1, sill=True):
        """正面(±y)上的窗:凹进的玻璃 + 外框 + 竖梃 + 窗台。"""
        d = .12 * facing
        self.box((cx, y_face - d, zc), (w, .04, h), 'glass')
        fr = .09
        for sx in (-1, 1):
            self.box((cx + sx * (w / 2 + fr / 2), y_face + .02 * facing, zc), (fr, .16, h + 2 * fr), 'trim')
        for sz in (-1, 1):
            self.box((cx, y_face + .02 * facing, zc + sz * (h / 2 + fr / 2)), (w + 2 * fr, .16, fr), 'trim')
        for k in range(1, mullions + 1):
            self.box((cx - w / 2 + w * k / (mullions + 1), y_face - .02 * facing, zc), (.05, .08, h), 'trim')
        if sill:
            self.box((cx, y_face + .1 * facing, zc - h / 2 - fr - .04), (w + .4, .26, .08), 'trim')

    def window_side(self, x_face, cy, zc, w, h, facing=1):
        d = .12 * facing
        self.box((x_face - d, cy, zc), (.04, w, h), 'glass')
        fr = .09
        for sy in (-1, 1):
            self.box((x_face + .02 * facing, cy + sy * (w / 2 + fr / 2), zc), (.16, fr, h + 2 * fr), 'trim')
        for sz in (-1, 1):
            self.box((x_face + .02 * facing, cy, zc + sz * (h / 2 + fr / 2)), (.16, w + 2 * fr, fr), 'trim')

    def door(self, cx, y_face, w=1.0, h=2.2, facing=1):
        self.box((cx, y_face - .1 * facing, h / 2), (w, .05, h), 'dark')
        for sx in (-1, 1):
            self.box((cx + sx * (w / 2 + .06), y_face + .02 * facing, h / 2 + .03), (.12, .16, h + .06), 'trim')
        self.box((cx, y_face + .02 * facing, h + .06), (w + .24, .16, .12), 'trim')
        for k in range(3):
            self.box((cx, y_face - .07 * facing, .45 + k * .62), (w * .7, .02, .42), 'trim')

    def rail(self, x0, x1, y, z, h=1.0, spacing=.14, key='trim'):
        self.box(((x0 + x1) / 2, y, z + h), (x1 - x0, .08, .06), key)
        self.box(((x0 + x1) / 2, y, z + .08), (x1 - x0, .06, .05), key)
        n = int((x1 - x0) / spacing)
        for k in range(n + 1):
            self.box((x0 + (x1 - x0) * k / n, y, z + h / 2), (.03, .03, h), key)

    def hedge(self, cx, cy, sx, sy, h=.9):
        self.box((cx, cy, h / 2), (sx, sy, h), 'wall')
        self.box((cx, cy, h + .03), (sx - .06, sy - .06, .06), 'trim')

    def to_object(self, name, loc, rot_z, scale):
        me = bpy.data.meshes.new(name)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        self.bm.to_mesh(me); self.bm.free()
        for m in self.slots:
            me.materials.append(m)
        ob = bpy.data.objects.new(name, me)
        ob.location = loc; ob.rotation_euler = (0, 0, rot_z); ob.scale = (scale, scale, scale)
        return ob


# ------------------------------------------------------------------ 四栋房子(本地坐标:地面 z=0,正面朝 +y)

def house_cottage(k):
    """1 单层独立屋:双坡屋顶、前廊、烟囱。"""
    W, D, H = 13.0, 9.0, 3.3
    k.box((0, 0, H / 2), (W, D, H))
    k.box((0, 0, .15), (W + .3, D + .3, .3), 'trim')                        # 勒脚
    k.gable_roof(0, 0, H, W, D, 28)
    k.box((3.6, -1.8, H + 3.0), (.9, .9, 3.4))                               # 烟囱
    k.box((3.6, -1.8, H + 4.75), (1.1, 1.1, .15), 'trim')
    # 前廊:平台 + 柱 + 廊顶 + 栏杆
    k.box((0, D / 2 + 1.25, .2), (W - 1.0, 2.5, .4), 'trim')
    for x in (-5.5, -2.75, 0, 2.75, 5.5):
        k.box((x, D / 2 + 2.25, .4 + 1.45), (.22, .22, 2.9), 'trim')
    k.box((0, D / 2 + 1.35, 3.35), (W - .6, 2.9, .18), 'roof')
    k.box((0, D / 2 + 2.5, 3.2), (W - .6, .14, .28), 'trim')
    k.rail(-5.5, -.8, D / 2 + 2.25, .4, h=.8)
    k.rail(.8, 5.5, D / 2 + 2.25, .4, h=.8)
    k.box((0, D / 2 + 2.9, .1), (1.6, .8, .2), 'trim')                      # 台阶
    k.door(0, D / 2, facing=1)
    for x in (-3.8, 3.8):
        k.window(x, D / 2, 1.75, 1.6, 1.5, mullions=1)
    for y in (-2.0, 2.0):
        k.window_side(W / 2, y, 1.75, 1.3, 1.4, facing=1)
        k.window_side(-W / 2, y, 1.75, 1.3, 1.4, facing=-1)
    for x in (-3.5, 3.5):
        k.window(x, -D / 2, 1.75, 1.3, 1.3, facing=-1)
    k.hedge(-5.2, D / 2 + 4.2, 3.0, .8); k.hedge(5.2, D / 2 + 4.2, 3.0, .8)
    k.box((0, D / 2 + 4.6, .1), (1.4, 3.2, .2), 'path')


def house_villa(k):
    """2 双层小别墅:上层悬挑、平屋顶、落地窗格栅、阳台、棚架、泳池。"""
    k.box((-1.0, 0, 1.65), (11.0, 9.0, 3.3))                                  # 首层
    k.box((.8, .8, 3.3 + 1.55), (11.5, 9.4, 3.1))                             # 二层悬挑
    k.box((.8, .8, 6.55), (11.9, 9.8, .3), 'trim')                            # 屋顶板
    k.box((.8, .8, 6.85), (11.9, 9.8, .3), 'wall'); k.box((.8, .8, 6.92), (11.3, 9.2, .3), 'roof')   # 女儿墙 + 内凹屋面
    k.box((-1.0, 0, 3.35), (11.4, 9.4, .12), 'trim')
    # 首层落地玻璃 + 竖向格栅
    k.box((-2.5, 4.42, 1.5), (6.0, .05, 2.6), 'glass')
    for i in range(13):
        k.box((-5.4 + i * .48, 4.62, 1.5), (.08, .3, 2.7), 'trim')
    k.door(3.2, 4.5)
    # 二层:带形窗 + 阳台(板 + 栏杆)
    k.box((.8, 5.47, 4.8), (9.5, .05, 1.8), 'glass')
    for i in range(6):
        k.box((-3.9 + i * 1.9, 5.55, 4.8), (.1, .14, 1.9), 'trim')
    k.box((.8, 6.6, 3.45), (8.0, 2.2, .22), 'trim')
    k.rail(-3.2, 4.8, 7.62, 3.55, h=1.05, spacing=.12)
    for x in (-5.6, 7.1):
        k.window_side(x, .8, 4.8, 3.0, 1.6, facing=1 if x > 0 else -1)
    # 棚架(侧面)
    for i in range(9):
        k.box((-8.3, -3.5 + i * .9, 3.2), (3.0, .12, .2), 'trim')
    for y in (-3.6, 3.6):
        k.box((-9.6, y, 1.6), (.2, .2, 3.2), 'trim')
    k.box((-8.3, 0, 3.02), (3.1, 7.6, .14), 'trim')
    # 泳池 + 池边平台
    k.box((6.0, -8.0, .12), (9.0, 5.0, .24), 'trim')
    k.box((6.0, -8.0, .2), (7.0, 3.0, .12), 'water')
    k.box((0, 7.5, .1), (1.4, 5.0, .2), 'path')


def house_terrace(k):
    """3 联排别墅:三户相连、各自山墙、车库门、二层小阳台、前院。"""
    UW, D = 6.2, 11.0
    for u in range(3):
        cx = (u - 1) * UW
        k.box((cx, 0, 3.1), (UW - .08, D, 6.2))
        k.gable_roof(cx, 0, 6.2, D, UW, 38, axis='y', over=.35)              # 屋脊前后向 → 正面是山墙
        k.box((cx - UW / 2 + .02, 0, 3.3), (.18, D + .3, 6.9), 'trim')        # 分户墙外凸
        k.box((cx + 1.3, D / 2 + .02, 1.25), (2.6, .08, 2.5), 'dark')         # 车库门
        for r in range(5):
            k.box((cx + 1.3, D / 2 + .08, .35 + r * .48), (2.5, .04, .06), 'trim')
        k.box((cx + 1.3, D / 2 + .1, 2.6), (2.9, .2, .14), 'trim')
        k.door(cx - 1.6, D / 2, w=.95)
        k.box((cx - 1.6, D / 2 + .9, 2.45), (1.6, 1.8, .12), 'roof')         # 门斗雨棚
        k.window(cx, D / 2, 4.6, 3.2, 1.8, mullions=2, sill=False)
        k.box((cx, D / 2 + .6, 3.55), (3.6, 1.2, .14), 'trim')                # 小阳台
        k.rail(cx - 1.8, cx + 1.8, D / 2 + 1.18, 3.62, h=.95, spacing=.13)
        k.window(cx, D / 2, 6.95, .9, .9, sill=False)                         # 山墙小窗
        for y in (-3.0, 1.0):
            pass
        k.hedge(cx - 1.6, D / 2 + 3.2, 2.6, .6, h=.7)
        k.box((cx + 1.3, D / 2 + 2.6, .1), (2.8, 5.0, .2), 'path')
    for x in (-3 * UW / 2, 3 * UW / 2):
        f = 1 if x > 0 else -1
        for y in (-2.5, 2.5):
            k.window_side(x, y, 1.7, 1.2, 1.4, facing=f)
            k.window_side(x, y, 4.6, 1.2, 1.4, facing=f)


def house_apartment(k):
    """4 小公寓楼:四层、每层阳台、竖向格栅、入口雨棚、屋顶设备间。"""
    W, D, FH, N = 16.0, 12.0, 3.1, 4
    k.box((0, 0, FH * N / 2), (W, D, FH * N))
    k.box((0, 0, FH * N + .45), (W + .3, D + .3, .9), 'wall')                # 女儿墙
    k.box((0, 0, FH * N + .55), (W - .4, D - .4, .9), 'roof')
    k.box((3.0, -1.5, FH * N + 2.0), (4.5, 3.5, 2.2), 'wall')                 # 设备间
    k.box((3.0, -1.5, FH * N + 3.15), (4.9, 3.9, .15), 'trim')
    for f in range(N):
        z0 = f * FH
        k.box((0, D / 2 + .01, z0 + .05), (W + .2, .3, .14), 'trim')          # 楼板线
        if f == 0:
            k.box((0, D / 2 - .6, 1.55), (5.5, .05, 2.9), 'glass')            # 大堂玻璃
            k.box((0, D / 2 + 1.1, 3.0), (7.5, 2.6, .22), 'trim')             # 入口雨棚
            for x in (-3.4, 3.4):
                k.box((x, D / 2 + 2.2, 1.5), (.2, .2, 3.0), 'trim')
            for x in (-6.0, 6.0):
                k.window(x, D / 2, 1.6, 2.4, 1.6, mullions=1)
            continue
        for ux in (-4.0, 4.0):
            k.box((ux, D / 2 + .04, z0 + 1.55), (6.0, .05, 2.5), 'glass')      # 落地窗
            for i in range(7):
                k.box((ux - 3.0 + i * 1.0, D / 2 + .12, z0 + 1.55), (.07, .16, 2.6), 'trim')
            k.box((ux, D / 2 + .85, z0 + .12), (6.4, 1.7, .2), 'trim')        # 阳台板
            k.rail(ux - 3.2, ux + 3.2, D / 2 + 1.66, z0 + .22, h=1.05, spacing=.12)
        for x in (-8.0, 0, 8.0):
            k.box((x, D / 2 + .5, z0 + 1.55), (.28, 1.0, FH), 'wall')          # 竖向隔板
        for y in (-3.5, 0, 3.5):
            k.window_side(W / 2, y, z0 + 1.6, 1.4, 1.6, facing=1)
            k.window_side(-W / 2, y, z0 + 1.6, 1.4, 1.6, facing=-1)
    k.box((0, D / 2 + 4.0, .1), (3.0, 4.0, .2), 'path')
    k.hedge(-5.5, D / 2 + 3.0, 5.0, .8); k.hedge(5.5, D / 2 + 3.0, 5.0, .8)


HOUSES = [('cottage', house_cottage, 22.0), ('villa', house_villa, 26.0), ('terrace', house_terrace, 26.0), ('apartment', house_apartment, 26.0)]


def lawn(k, size):
    """方形草坪台的白色底座;草面是单独对象(真实草丛,见 grass_object)。"""
    k.box((0, 0, -.6), (size, size, 1.2), 'soil')


def grass_material():
    """草叶:青绿,按随机值在深浅两色间取色,根部略暗。"""
    m = bpy.data.materials.get('v28 grass blades') or bpy.data.materials.new('v28 grass blades')
    m.use_nodes = True; nt = m.node_tree; N = nt.nodes; L = nt.links; p = N['Principled BSDF']
    info = N.new('ShaderNodeHairInfo')
    ramp = N.new('ShaderNodeValToRGB'); L.new(info.outputs['Random'], ramp.inputs['Fac'])
    ramp.color_ramp.elements[0].color = (*srgb('#3D6634'), 1); ramp.color_ramp.elements[1].color = (*srgb('#6C9550'), 1)   # 所有者选「精緻庭園草坪」:深而不艷
    root = N.new('ShaderNodeMix'); root.data_type = 'RGBA'
    L.new(info.outputs['Intercept'], root.inputs[0])
    root.inputs[6].default_value = (*srgb('#2A4424'), 1); L.new(ramp.outputs['Color'], root.inputs[7])
    L.new(root.outputs[2], p.inputs['Base Color'])
    p.inputs['Roughness'].default_value = .6
    p.inputs['Sheen Weight'].default_value = .5
    return m


def grass_object(name, size, mw, density=6.0):
    """草坪面 + 发丝粒子草丛(每平方米本地单位 density 根主叶 × 子叶)。"""
    me = bpy.data.meshes.new(f'{name} lawn')
    bm = bmesh.new(); h = size / 2 - .01
    h -= .25                                              # 草丛内缩,不越出底座边缘
    bm.faces.new([bm.verts.new(v) for v in [(-h, -h, .02), (h, -h, .02), (h, h, .02), (-h, h, .02)]])
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=6, use_grid_fill=True)
    bm.to_mesh(me); bm.free()
    me.materials.append(material('v28 grass base', '#35532D', .95))
    me.materials.append(grass_material())
    ob = bpy.data.objects.new(f'{name} lawn', me)
    ob.matrix_world = mw
    mod = ob.modifiers.new('grass', 'PARTICLE_SYSTEM'); ps = mod.particle_system.settings
    ps.type = 'HAIR'; ps.count = int(size * size * density * 2.6); ps.hair_length = .12                                # 修剪过的草坪:矮而密
    ps.use_advanced_hair = True; ps.emit_from = 'FACE'; ps.distribution = 'RAND'
    ps.use_rotations = True; ps.rotation_mode = 'NOR'; ps.phase_factor_random = 2.0
    ps.factor_random = .06; ps.normal_factor = 1.0; ps.brownian_factor = .02
    ps.child_type = 'INTERPOLATED'; ps.child_percent = ps.rendered_child_count = 12; ps.child_length = .9; ps.child_length_threshold = .3
    ps.roughness_1 = .09; ps.roughness_endpoint = .12; ps.clump_factor = .35; ps.roughness_2 = .05
    ps.material_slot = 'v28 grass blades'
    ps.root_radius = .9; ps.tip_radius = 0; ps.radius_scale = .012
    ps.display_step = ps.render_step = 3
    return ob


def sign(k, bw=9.0, bh=14.0):
    """侧挂信息牌(所有者选「方案 C」):立在草坪右侧桌面上的竖向白板 + 左侧细立杆。
    本地原点在牌子底部中心、桌面高度;正面朝 +y。返回牌面(中心 x, y, z, 宽, 高)。"""
    k.box((0, 0, bh / 2), (bw, .45, bh), 'sign')
    k.box((0, 0, .15), (bw + .4, 1.4, .3), 'trim')                          # 底座
    k.box((-bw / 2 - .35, 0, (bh + 1.6) / 2), (.22, .22, bh + 1.6), 'post')  # 细立杆,略高于牌
    return (0, .24, bh / 2 + .6, bw - 1.2, bh - 1.6)


SIGN_GAP = 2.0          # 牌子与草坪右边缘的间距(本地单位)


def build(scene, placements, sign_rot=None, tree_meshes=None, collection_name='v28 houses'):
    """placements: [(世界坐标 (x, y, z), 朝向角 rad)] × 4。
    sign_rot:销售牌朝向(默认同房子);tree_meshes:草坪上点缀的树原型网格。返回 [(房子名, 牌面世界四角)]。"""
    import random
    rng = random.Random(28)
    M = materials()
    col = bpy.data.collections.get(collection_name) or bpy.data.collections.new(collection_name)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    out = []
    for (name, fn, size), (loc, rot) in zip(HOUSES, placements):
        k = Kit(M); fn(k); lawn(k, size)
        ob = k.to_object(f'v28 {name}', loc, rot, SCALE); col.objects.link(ob)
        house_mw = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot, 4, 'Z') @ Matrix.Diagonal((SCALE, SCALE, SCALE, 1))
        col.objects.link(grass_object(f'v28 {name}', size, house_mw))
        # 销售牌:草坪前角,单独对象,正对镜头
        corner_local = Vector((-(size / 2 + SIGN_GAP + 4.5), 0, -1.2))    # 草坪在画面右侧:房子正面朝镜头时本地 −x 是画面右方
        sk = Kit(M); sx, sy, sz, bw, bh = sign(sk)
        s_loc = house_mw @ corner_local
        s_rot = rot if sign_rot is None else sign_rot
        sob = sk.to_object(f'v28 {name} sign', s_loc, s_rot, SCALE); col.objects.link(sob)
        s_mw = Matrix.Translation(s_loc) @ Matrix.Rotation(s_rot, 4, 'Z') @ Matrix.Diagonal((SCALE, SCALE, SCALE, 1))
        corners = [s_mw @ Vector((sx + dx * bw / 2, sy + .01, sz + dz * bh / 2)) for dx, dz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        out.append((f'v28 {name}', corners))
        # 草坪后角点缀两三棵蓬松白树(与城市同款树型)
        if tree_meshes:
            for tx, ty in ((-size / 2 + 3.5, -size / 2 + 3.5), (size / 2 - 3.5, -size / 2 + 4.5), (size / 2 - 3.0, 0.0))[:3 if size > 24 else 2]:
                t = bpy.data.objects.new(f'v28 {name} tree', rng.choice(tree_meshes)); col.objects.link(t)
                t.location = house_mw @ Vector((tx, ty, 0)); t.rotation_euler = (0, 0, rng.uniform(0, math.tau))
                t.scale = (SCALE * .75,) * 3
    return out


if __name__ == '__main__' and '--preview' in sys.argv:
    argv = sys.argv[sys.argv.index('--') + 1:]
    samples = int(argv[argv.index('--samples') + 1]) if '--samples' in argv else 128
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    placements = [((-60 + i * 110, 0, 0), math.radians(205)) for i in range(4)]   # 正面(本地 +y)朝向镜头
    res = build(sc, placements)
    bpy.context.view_layer.update()
    # 地面阴影接收 + 太阳 + 白色世界
    fme = bpy.data.meshes.new('floor'); fbm = bmesh.new()
    fbm.faces.new([fbm.verts.new(v) for v in [(-2000, -2000, -3.85), (2000, -2000, -3.85), (2000, 2000, -3.85), (-2000, 2000, -3.85)]])
    fbm.to_mesh(fme); fbm.free(); fl = bpy.data.objects.new('floor', fme); sc.collection.objects.link(fl); fl.is_shadow_catcher = True
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sc.collection.objects.link(sun)
    sun.data.energy = 3.8; sun.data.angle = math.radians(2.5); sun.rotation_euler = (math.radians(45), 0, math.radians(-35))
    world = bpy.data.worlds.new('w'); sc.world = world; world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (1, .88, .74, 1); world.node_tree.nodes['Background'].inputs[1].default_value = .35
    cam_d = bpy.data.cameras.new('cam'); cam_d.type = 'ORTHO'; cam_d.ortho_scale = 470; cam_d.clip_end = 10000
    cam = bpy.data.objects.new('cam', cam_d); sc.collection.objects.link(cam); sc.camera = cam
    fwd = Vector((.431 * math.cos(math.radians(20)), .897 * math.cos(math.radians(20)), -math.sin(math.radians(20)))).normalized()
    fwd = Vector((0, 1, 0)); fwd = Vector((math.sin(math.radians(-25)) * math.cos(math.radians(22)), math.cos(math.radians(-25)) * math.cos(math.radians(22)), -math.sin(math.radians(22))))
    tgt = Vector((105, 0, 20)); cam.location = tgt - fwd * 3000; cam.rotation_euler = fwd.to_track_quat('-Z', 'Y').to_euler()
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'
    prefs = bpy.context.preferences.addons['cycles'].preferences; prefs.compute_device_type = 'OPTIX'; prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == 'OPTIX'
    sc.cycles.samples = samples; sc.cycles.use_denoising = True
    sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - High Contrast'; sc.view_settings.exposure = 1.1
    sc.render.resolution_x, sc.render.resolution_y = 2560, 1100
    sc.render.film_transparent = True
    OUT.mkdir(exist_ok=True)
    sc.render.filepath = str(OUT / 'houses-preview.png')
    bpy.ops.render.render(write_still=True)
    # 近景:检查细节精度
    sc.render.resolution_x, sc.render.resolution_y = 1600, 1200
    for i in (0, 1, 2, 3):
        cam_d.ortho_scale = 120
        t = Vector((-60 + i * 110, 0, 18)); cam.location = t - fwd * 3000
        sc.render.filepath = str(OUT / f'house-{i}.png')
        bpy.ops.render.render(write_still=True)
    print('V28_PREVIEW_DONE', [n for n, _ in res], flush=True)
