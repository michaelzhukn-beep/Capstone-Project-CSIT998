"""Replace only the foreground apron with an eased, contour-conforming shore.

The old apron sampled the *old river bank* beyond the clipped site. That creates
a narrow ridge and makes a coarse triangle grid visible against level water.
Here each point inherits the height of the nearest original site boundary and
eases monotonically onto the low foreground plane. The z=0 contour is explicit.
"""
import json
from collections import Counter
from pathlib import Path
import numpy as np
from scipy.spatial import Delaunay
from shapely import constrained_delaunay_triangles, polygons, intersection
from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union
from layout_terrain import Terrain

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / 'city-13-shore-plan.json').read_text(encoding='utf-8'))
site = unary_union([Polygon(p['outer'], p.get('holes', [])) for p in plan['site']])
apron = box(-1000, -1200, 900, -65).difference(site)
ground = Terrain(plan['water_contour'])
boundary = np.asarray(site.exterior.coords[:-1], dtype=float)
next_boundary = np.roll(boundary, -1, axis=0)
edge_vec = next_boundary - boundary
edge_len2 = np.maximum(np.sum(edge_vec * edge_vec, axis=1), 1e-12)
boundary_z = np.array([ground(x, y) for x, y in boundary])
next_z = np.roll(boundary_z, -1)

samples = [tuple(p) for p in apron.exterior.coords]
# Local contour bands, rather than tessellating the huge hidden foreground.
for distance in [0.6, 1.5, 3, 5, 8, 12, 17, 22, 26, 29, 31, 33, 36, 40, 46, 52, 65, 85]:
    ring = site.buffer(distance, quad_segs=8).exterior
    step = 1.4 if distance <= 52 else 4
    for s in np.arange(0, ring.length, step):
        p = ring.interpolate(s)
        if apron.covers(p): samples.append((p.x, p.y))
samples += [(x, y) for x in np.arange(-1000, 901, 100)
            for y in np.arange(-1200, -64, 100) if apron.covers(Point(x, y))]
xy = np.unique(np.asarray(samples), axis=0)
cells = intersection(polygons(xy[Delaunay(xy).simplices]), apron)
points, ids, raw_faces = [], {}, []
def vertex(p):
    key = tuple(round(float(v), 7) for v in p)
    if key not in ids: ids[key] = len(points); points.append(key)
    return ids[key]
for cell in cells:
    if cell.is_empty or cell.area < 1e-10: continue
    for tri in constrained_delaunay_triangles(cell).geoms:
        f = tuple(vertex(p) for p in tri.exterior.coords[:3])
        if len(set(f)) == 3: raw_faces.append(f)

def height(x, y):
    delta = np.array([x, y]) - boundary
    t = np.clip(np.sum(delta * edge_vec, axis=1) / edge_len2, 0, 1)
    distance2 = np.sum((delta - t[:, None] * edge_vec)**2, axis=1)
    i = int(np.argmin(distance2))
    distance = float(np.sqrt(distance2[i]))
    edge_z = boundary_z[i] * (1 - t[i]) + next_z[i] * t[i]
    u = min(1, distance / 52)
    # Quintic Hermite interpolation: horizontal tangent and curvature at ends.
    blend = u**3 * (10 - 15*u + 6*u*u)
    return float(edge_z * (1 - blend) + .65 * blend)

vertices = [[x, y, height(x, y)] for x, y in points]
crossings = {}
def crossing(a, b):
    key = tuple(sorted((a, b)))
    if key not in crossings:
        va, vb = np.asarray(vertices[a]), np.asarray(vertices[b])
        t = -va[2] / (vb[2] - va[2]); v = va + t * (vb - va); v[2] = 0
        crossings[key] = len(vertices); vertices.append(v.tolist())
    return crossings[key]

faces = []
for f in raw_faces:
    z = [vertices[i][2] for i in f]
    if min(z) < 0 < max(z):
        # Split both sides at the same shared vertices: no T-junctions, and no
        # arbitrary water-plane intersection through a large triangle face.
        for sign in (-1, 1):
            poly = []
            for a, b in zip(f, f[1:] + f[:1]):
                za, zb = vertices[a][2], vertices[b][2]
                if sign * za >= 0: poly.append(a)
                if za * zb < 0: poly.append(crossing(a, b))
            for j in range(1, len(poly) - 1): faces.append((poly[0], poly[j], poly[j+1]))
    else: faces.append(f)
counts = Counter(tuple(sorted((a, b))) for f in faces for a, b in zip(f, f[1:] + f[:1]))
assert all(count <= 2 for count in counts.values())
boundary_edges = [list(e) for e, count in counts.items() if count == 1]
plan['foreground_apron'] = dict(vertices=vertices, triangles=faces, boundary=boundary_edges,
    bounds=list(apron.bounds), flat_height=.65, transition_width=52, camera_preserved=True)
plan['shore_smoothing'] = dict(source='city-13-shore.blend',
    method='Nearest original edge height, quintic descent/rise, explicit level-water contour',
    triangles=len(faces), vertices=len(vertices), waterline_vertices=len(crossings),
    transition_width=52, hidden_foreground_height=.65,
    position_quantization=20, unchanged=['city geometry', 'quays including removed spike', 'water', 'cameras', 'materials', 'lights'])
(ROOT/'city-13-smooth-plan.json').write_text(json.dumps(plan, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('SMOOTH_PLAN', json.dumps(plan['shore_smoothing']), flush=True)
