"""Extend only the foreground water of layout 13; preserve the authored land."""
import json
from pathlib import Path
from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent
plan = json.loads((ROOT / 'city-13-layout-plan.json').read_text(encoding='utf-8'))
def polygons(items):
    return unary_union([Polygon(p['outer'], p.get('holes', [])) for p in items])
site = polygons(plan['site'])
old_water = polygons(plan['surfaces']['water']['polygons'])
dry_land = site.difference(old_water)
# Extend toward the selected south-west camera. Subtract existing land so the
# peninsula, quays, bridge landings and building plots stay completely dry.
water = unary_union([old_water, box(-1000, -1200, 900, -40).difference(dry_land)])
assert water.is_valid and water.geom_type == 'Polygon'
assert water.intersection(dry_land).area < 1e-6
assert water.intersection(site).symmetric_difference(old_water).area < 1e-6
plan['surfaces']['water'] = {
    'polygons': [{'outer': list(water.exterior.coords)[:-1],
                  'holes': [list(r.coords)[:-1] for r in water.interiors]}],
    'triangles': [[list(p) for p in t.exterior.coords][:3]
                  for t in constrained_delaunay_triangles(water).geoms],
}
# Exact position/target/zoom read from the owner's orbit view. The orbit started
# at the 400-unit bridge preset, with its 1600:1100 reference framing unchanged.
plan['composition_camera'] = {
    'type': 'orthographic',
    'position': [-168.54179198257603, -414.23142990879165, 110.77892750392161],
    'target': [37.64678466314971, -0.5595456880126443, 85.58283522675842],
    'up': [0, 0, 1], 'scale': 400, 'zoom': 1.2774168864397786,
    'reference_aspect': 1600 / 1100,
}
plan['lake_extension'] = {
    'source': 'city-13-layout.blend', 'water_level': 0,
    'bounds': list(water.bounds), 'added_area_design_units': water.area - old_water.area,
    'dry_land_overlap': water.intersection(dry_land).area,
    'original_water_change': water.intersection(site).symmetric_difference(old_water).area,
}
(ROOT / 'city-13-lake-plan.json').write_text(json.dumps(plan, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(json.dumps(plan['lake_extension'], ensure_ascii=True))
