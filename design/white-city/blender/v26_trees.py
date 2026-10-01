"""v26 树木实验:把 4 个树原型换成「小球团簇」的蓬松树冠 + 深色主干分枝。只改内存,不保存源工程。

由 render_v24_pathtrace.py 的 --trees 调用。实测:1,394 棵树是 4 个原型网格的实例
(`13 Tree prototype 0..3`,各 414 面,高约 4.5 m、冠宽约 3.6 m,再乘 0.9–1.78 的实例缩放)。
替换原型网格即全部树同步更新,树的位置、数量、缩放都不动。
"""
import bmesh, math, random
from mathutils import Vector, Matrix


def _cyl(bm, a, b, r, mat, seg=6):
    d = b - a
    rot = d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    m = Matrix.Translation(a) @ rot
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r * .7, depth=d.length,
                                matrix=m @ Matrix.Translation((0, 0, d.length / 2)))
    for f in {f for v in res['verts'] for f in v.link_faces}:
        f.material_index = mat


def _blob(bm, c, r, mat, subdiv):
    res = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=r, matrix=Matrix.Translation(c))
    for f in {f for v in res['verts'] for f in v.link_faces}:
        f.material_index = mat
        f.smooth = True


def build(mesh, crown_mat, branch_mat, seed, width=1.0, blobs=48, subdiv=2):
    rng = random.Random(seed)
    bm = bmesh.new()
    # 主干 + 三到四根斜向上的分枝,伸进树冠
    top = Vector((rng.uniform(-.1, .1), rng.uniform(-.1, .1), 2.4))
    _cyl(bm, Vector((0, 0, 0)), top, .13, branch_mat)
    for k in range(rng.choice((3, 4))):
        ang = k * 2 * math.pi / 4 + rng.uniform(-.4, .4)
        tip = top + Vector((math.cos(ang) * 1.1 * width, math.sin(ang) * 1.1 * width, rng.uniform(.7, 1.1)))
        _cyl(bm, top - Vector((0, 0, .3)), tip, .07, branch_mat, seg=5)
    # 树冠:椭球外壳上的小球团 + 少量内部大球填实,整体略扁、底部开口露出枝干
    c = Vector((0, 0, 3.55)); rx, rz = 2.05 * width, 1.45
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(blobs):
        y = 1 - 2 * (i + .5) / blobs
        if y < -.55:                                 # 冠底留空
            continue
        rr = math.sqrt(1 - y * y); th = golden * i + rng.uniform(-.25, .25)
        p = c + Vector((math.cos(th) * rr * rx, math.sin(th) * rr * rx, y * rz)) * rng.uniform(.82, 1.0)
        _blob(bm, p, rng.uniform(.5, .82) * (1 if y > -.2 else .8), crown_mat, subdiv)
    for i in range(6):
        p = c + Vector((rng.uniform(-.6, .6) * rx, rng.uniform(-.6, .6) * rx, rng.uniform(-.2, .5) * rz))
        _blob(bm, p, rng.uniform(.9, 1.2), crown_mat, 1)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(mesh.polygons)


def apply(bpy, width=1.0, blobs=48, subdiv=2):
    total = 0
    for i in range(4):
        me = bpy.data.meshes.get(f'13 Tree prototype {i}')
        if not me:
            continue
        names = [m.name if m else '' for m in me.materials]
        total += build(me, names.index('13 Tree crowns'), names.index('13 Branches'), seed=100 + i, width=width, blobs=blobs, subdiv=subdiv)
    return total
