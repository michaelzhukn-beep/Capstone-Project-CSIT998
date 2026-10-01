"""v26 立面实验:把低层楼的「方格窗」在内存里改成「通高竖鳍片 + 连续凹槽」。不保存源工程。

由 render_v24_pathtrace.py 的 --fins 调用。依据 inspect_v26_facades.py 与盒子清单实测:
每栋楼是一组轴对齐盒子 —— 每段体量一个「凹窗面板」盒(外皮内缩约 0.36 m),外面套
0.17 × 0.33 m 的竖梃(间距约 2.5 m)和每层一道 0.2 m 高的整圈横带(层高约 2.9 m)。
横带把凹槽切成一格一格,楼底打上来的光在第一层就断掉;参考图是通高鳍片、槽内连续。

做法(每栋、每段体量):
- 删掉体量中间的横带(保留体量底、顶两道,作为勒脚和檐口)
- 删掉原竖梃,按目标间距重新排鳍片:宽 fin_w,外伸到面板外 fin_out
"""
import bmesh, math
from mathutils import Vector


def _components(bm):
    seen, out = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        while stack:
            g = stack.pop()
            if g.index in seen:
                continue
            seen.add(g.index)
            comp.append(g)
            for e in g.edges:
                stack.extend(h for h in e.link_faces if h.index not in seen)
        vs = {v for g in comp for v in g.verts}
        lo = Vector((min(v.co.x for v in vs), min(v.co.y for v in vs), min(v.co.z for v in vs)))
        hi = Vector((max(v.co.x for v in vs), max(v.co.y for v in vs), max(v.co.z for v in vs)))
        out.append({'faces': comp, 'mat': comp[0].material_index, 'lo': lo, 'hi': hi})
    return out


def _box(bm, lo, hi, mat):
    xs, ys, zs = (lo.x, hi.x), (lo.y, hi.y), (lo.z, hi.z)
    v = [bm.verts.new((xs[i & 1], ys[(i >> 1) & 1], zs[(i >> 2) & 1])) for i in range(8)]
    for q in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
        bm.faces.new([v[i] for i in q]).material_index = mat


def apply(obj, spacing=1.25, fin_w=.14, fin_out=.75, max_h=26):
    """返回 (删横带数, 新鳍片数);不是这种盒子结构的楼原样跳过。"""
    names = [s.material.name if s.material else '' for s in obj.material_slots]
    try:
        panel_i, clay_i = names.index('13 Recessed white panels'), names.index('13 White clay')
    except ValueError:
        return 0, 0
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    comps = _components(bm)
    panels = [c for c in comps if c['mat'] == panel_i]
    if not panels or max(p['hi'].z for p in panels) - min(p['lo'].z for p in panels) > max_h:
        bm.free()
        return 0, 0
    kill, bands, fins = set(), 0, 0
    for c in comps:
        if c['mat'] != clay_i:
            continue
        d = c['hi'] - c['lo']
        for p in panels:
            inside_xy = c['lo'].x > p['lo'].x - 1 and c['hi'].x < p['hi'].x + 1 and c['lo'].y > p['lo'].y - 1 and c['hi'].y < p['hi'].y + 1
            if not inside_xy:
                continue
            if d.z < .3 and p['lo'].z + .3 < c['lo'].z and c['hi'].z < p['hi'].z - .3:
                kill.add(id(c)); bands += 1
            elif d.z > 1 and min(d.x, d.y) < .5 and abs(c['lo'].z - p['lo'].z) < .05 and abs(c['hi'].z - p['hi'].z) < .05:
                kill.add(id(c))
            break
    bmesh.ops.delete(bm, geom=list({f for c in comps if id(c) in kill for f in c['faces']}), context='FACES')
    for p in panels:
        lo, hi = p['lo'], p['hi']
        z0, z1 = lo.z, hi.z
        for axis in (0, 1):                     # 鳍片沿 x 排(贴 ±y 面)或沿 y 排(贴 ±x 面)
            a0, a1 = (lo.x, hi.x) if axis == 0 else (lo.y, hi.y)
            n = max(2, round((a1 - a0) / spacing) + 1)
            for side in (-1, 1):
                face = (lo.y if side < 0 else hi.y) if axis == 0 else (lo.x if side < 0 else hi.x)
                for k in range(n):
                    t = a0 + (a1 - a0) * k / (n - 1)
                    t = min(max(t, a0 + fin_w / 2), a1 - fin_w / 2)
                    o0, o1 = (face - fin_out, face + .02) if side < 0 else (face - .02, face + fin_out)
                    if axis == 0:
                        _box(bm, Vector((t - fin_w / 2, o0, z0)), Vector((t + fin_w / 2, o1, z1)), clay_i)
                    else:
                        _box(bm, Vector((o0, t - fin_w / 2, z0)), Vector((o1, t + fin_w / 2, z1)), clay_i)
                    fins += 1
    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return bands, fins
