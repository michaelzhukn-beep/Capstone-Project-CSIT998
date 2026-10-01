"""Inspect actual saved scene meshes for river/bridge intrusion; compare 02 and 03."""
import collections
import json
import math
import re
import struct
import sys
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d

ROOT=Path(__file__).resolve().parent


def inside(point,poly):
    # Independent ray-casting check; does not call the placement module's SAT predicate.
    x,y=point;hit=False
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            hit=not hit
    return hit


def overlap(a,b):
    if max(p[0] for p in a)<min(p[0] for p in b) or max(p[0] for p in b)<min(p[0] for p in a):
        return False
    if max(p[1] for p in a)<min(p[1] for p in b) or max(p[1] for p in b)<min(p[1] for p in a):
        return False
    if any(inside(p,b) for p in a) or any(inside(p,a) for p in b):
        return True
    return any(intersect_line_line_2d(Vector(p),Vector(q),Vector(r),Vector(s)) is not None
               for p,q in zip(a,a[1:]+a[:1]) for r,s in zip(b,b[1:]+b[:1]))


def scene_report(name):
    bpy.ops.wm.open_mainfile(filepath=str(ROOT/f'{name}.blend'))
    scene=bpy.context.scene
    scene.frame_set(1)
    def numbers(values):return [round(float(v),6) for v in values]
    daylight={o.name:[numbers(v for row in o.matrix_world for v in row),o.data.energy,numbers(o.data.color)]
              for o in scene.objects if o.type=='LIGHT' and o.name in ('Large soft daylight key','Cool broad fill','Soft daylight direction')}
    interiors=sorted([o.data.energy,numbers(o.data.color),o.data.size,o.data.size_y]
                     for o in scene.objects if o.type=='LIGHT' and 'recessed interior' in o.name)
    hero=bpy.data.objects['Hero camera - editable real perspective']
    hero_settings=[numbers(v for row in hero.matrix_world for v in row),hero.data.lens,hero.data.shift_y]
    water=bpy.data.objects['River surface - reflective geometry']
    water_polys=[[(water.matrix_world@water.data.vertices[i].co).xy[:] for i in p.vertices] for p in water.data.polygons]
    bridge=bpy.data.objects['Slender arched bridge - deck rails and piers']
    a=(bridge.data.vertices[0].co+bridge.data.vertices[1].co)/2
    b=(bridge.data.vertices[192].co+bridge.data.vertices[193].co)/2
    n=(b-a).xy.normalized();t=Vector((-n.y,n.x));center=(a.xy+b.xy)/2
    half=(b.xy-a.xy).length/2+14
    corridor=[tuple(center+n*u+t*v) for u,v in [(-half,-5),(half,-5),(half,5),(-half,5)]]
    groups=collections.defaultdict(list)
    geometry=collections.defaultdict(lambda:dict(buildings=0,vertices=0,triangles=0))
    levels={}
    for obj in scene.objects:
        if obj.type!='MESH' or not re.match(r'^\d{3} ',obj.name):
            continue
        key=obj.name[:3]
        groups[key].append(obj)
        if obj.name.endswith('ceramic structure'):
            levels[key]=obj.get('detail_level','near')
    rivers=[];bridges=[];rects={}
    for key,objects in groups.items():
        corners=[obj.matrix_world@Vector(c) for obj in objects for c in obj.bound_box]
        x0,x1=min(p.x for p in corners),max(p.x for p in corners)
        y0,y1=min(p.y for p in corners),max(p.y for p in corners)
        rect=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
        rects[key]=rect
        if any(overlap(rect,poly) for poly in water_polys):rivers.append(key)
        if overlap(rect,corridor):bridges.append(key)
        level=levels[key];geometry[level]['buildings']+=1
        for obj in objects:
            geometry[level]['vertices']+=len(obj.data.vertices)
            geometry[level]['triangles']+=sum(len(p.vertices)-2 for p in obj.data.polygons)
    pairs=[]
    for i,key in enumerate(rects):
        for other in list(rects)[i+1:]:
            if overlap(rects[key],rects[other]):pairs.append([key,other])
    return dict(buildings=len(groups),river_intrusions=rivers,bridge_corridor_intrusions=bridges,
                building_overlaps=pairs,geometry_by_level=dict(geometry),
                image_texture_nodes=sum(n.type=='TEX_IMAGE' for mat in bpy.data.materials if mat.use_nodes for n in mat.node_tree.nodes),
                daylight=daylight,interior_light_settings=interiors,hero_camera=hero_settings,
                exposure=scene.view_settings.exposure,look=scene.view_settings.look)


baseline=scene_report('city-02')
target=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'city-03'
current=scene_report(target)
assert baseline['river_intrusions'], 'Regression check must detect the actual 02 water bug'
assert baseline['bridge_corridor_intrusions'], 'Regression check must detect the actual 02 bridge bug'
assert not current['river_intrusions'],current['river_intrusions']
assert not current['bridge_corridor_intrusions'],current['bridge_corridor_intrusions']
assert not current['building_overlaps'],current['building_overlaps']
assert current['image_texture_nodes']==0
for field in ('daylight','interior_light_settings','hero_camera','exposure','look'):
    assert baseline[field]==current[field],field
assert current['buildings']>baseline['buildings']
near=current['geometry_by_level']['near'];far=current['geometry_by_level']['far']
assert far['vertices']/far['buildings']<near['vertices']/near['buildings']*.2
report=dict(result='PASS',baseline=baseline,current=current,
            visual_acceptance=f'02 detail and Cycles panorama accepted; {target} current visual review pending')
report_name='layout-verification.json' if target=='city-03' else f'layout-verification-{target}.json'
(ROOT/report_name).write_text(json.dumps(report,indent=2),encoding='utf-8')
print('LAYOUT_VERIFIED',json.dumps(report),flush=True)
