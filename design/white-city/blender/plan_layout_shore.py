"""Continue the cut foreground into a smooth ground apron; trim the quay sliver."""
import json
import numpy as np
from scipy.spatial import Delaunay
from pathlib import Path
from collections import Counter
from functools import lru_cache
from shapely import constrained_delaunay_triangles, polygons, intersection
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union
from layout_terrain import Terrain, smooth

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / 'city-13-lake-plan.json').read_text(encoding='utf-8'))
site = unary_union([Polygon(p['outer'], p.get('holes', [])) for p in plan['site']])
apron = box(-1000, -1200, 900, -65).difference(site)
ground = Terrain(plan['water_contour'])

points, ids = [], {}
def vertex(p):
    key = tuple(round(float(n), 7) for n in p)
    if key not in ids:
        ids[key] = len(points); points.append(key)
    return ids[key]

def edge(a, b): return tuple(sorted((a, b)))
# Dense near the original edge, sparse on the level continuation. Clip every
# triangulation cell to the exact join instead of dropping boundary slivers.
samples = [tuple(p) for p in apron.exterior.coords]
samples += [(x,y) for x in np.arange(-445,446,4) for y in np.arange(-250,-64,4)]
samples += [(x,y) for x in np.arange(-1000,901,100) for y in np.arange(-1200,-64,100)]
xy = np.unique(np.asarray(samples),axis=0)
cells = intersection(polygons(xy[Delaunay(xy).simplices]),apron)
faces = []
for cell in cells:
    if cell.is_empty or cell.area < 1e-10: continue
    for t in constrained_delaunay_triangles(cell).geoms:
        f = tuple(vertex(p) for p in t.exterior.coords[:3])
        if len(set(f)) == 3: faces.append(f)
print('APRON_TRIANGLES',len(faces),flush=True)

@lru_cache(maxsize=None)
def height(x, y):
    distance = site.distance(Point(x, y))
    # Same height as the original surface at the join. Horizontal tangent at the
    # far end gives a seamless white ground, rather than another model plinth.
    blend = smooth(0, 65, distance)
    return ground(x, y) * (1-blend) + .65 * blend

vertices = [[x, y, height(x, y)] for x, y in points]
counts = Counter(edge(a, b) for f in faces for a, b in zip(f, f[1:] + f[:1]))
boundary = [list(e) for e, count in counts.items() if count == 1]
assert all(count <= 2 for count in counts.values())
plan['foreground_apron'] = {'vertices': vertices, 'triangles': faces, 'boundary': boundary,
    'bounds': list(apron.bounds), 'flat_height': .65, 'transition_width': 65,
    'camera_preserved': True}

# The southern quay tapered to a paper-thin strip at the old site cut. Remove
# that terminal segment; retain the inhabited waterfront and both bridge heads.
banks = unary_union([Polygon(p['outer'], p.get('holes', [])) for p in plan['surfaces']['banks']['polygons']])
trim = box(-62, -210, 110, -120)
clean = banks.difference(trim)
polys = [clean] if clean.geom_type == 'Polygon' else list(clean.geoms)
plan['surfaces']['banks'] = {
    'polygons': [{'outer': list(p.exterior.coords)[:-1], 'holes': [list(r.coords)[:-1] for r in p.interiors]} for p in polys],
    'triangles': [list(t.exterior.coords)[:3] for t in constrained_delaunay_triangles(clean).geoms],
}
plan['shore_repair'] = {'source': 'city-13-lake.blend', 'removed_quay_area': banks.difference(clean).area,
    'removed_quay_bounds': list(banks.intersection(trim).bounds), 'apron_triangles': len(faces),
    'unchanged': ['composition_camera', 'buildings', 'bridges', 'trees', 'roads', 'materials', 'lights']}
(ROOT / 'city-13-shore-plan.json').write_text(json.dumps(plan, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('SHORE_PLAN', json.dumps(plan['shore_repair']))
