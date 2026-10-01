"""12: a single world-space city plan from the four-view reference.

Run with the repository Python (Shapely 2.1), then build_city_model.py in Blender.
Image landmarks are authored estimates. Scene units are design units, not surveyed m.
"""
import json, math, random, hashlib
from pathlib import Path
import numpy as np
from shapely import constrained_delaunay_triangles, delaunay_triangles
from shapely.geometry import Point, LineString, Polygon, MultiPoint, box
from shapely.ops import unary_union
from shapely.affinity import rotate, scale

ROOT=Path(__file__).resolve().parent
rng=random.Random(120916)
def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)
def uv(px,py):return [(px-368)*.90,(340-py)*.90]
def curve(points,steps=16):
    p=np.array(points,float);out=[]
    for i in range(len(p)-1):
        a,b,c,d=p[max(0,i-1)],p[i],p[i+1],p[min(len(p)-1,i+2)]
        for j in range(steps):
            t=j/steps;out.append(.5*(2*b+(-a+c)*t+(2*a-5*b+4*c-d)*t*t+(-a+3*b-3*c+d)*t**3))
    return np.array(out+[p[-1]])
def serial(poly):
    if poly.is_empty:return []
    parts=[poly] if poly.geom_type=='Polygon' else list(poly.geoms)
    return [dict(outer=list(p.exterior.coords)[:-1],holes=[list(r.coords)[:-1] for r in p.interiors]) for p in parts if p.geom_type=='Polygon' and p.area>.01]
def triangles(poly):
    return [[list(p) for p in tri.exterior.coords][:3] for tri in constrained_delaunay_triangles(poly).geoms]

site=box(-340,-139,340,200).buffer(16,quad_segs=8)
riverline=curve([uv(*p) for p in [(-35,307),(80,307),(155,316),(224,336),(296,348),(385,355),(473,388),(555,413),(644,400),(785,347)]],24)
for _ in range(45):riverline[1:-1]=.5*riverline[1:-1]+.25*(riverline[:-2]+riverline[2:])
river_path=LineString(riverline);water=river_path.buffer(9.5,quad_segs=4).intersection(site)
banks=water.buffer(2.1,quad_segs=3).difference(water).intersection(site)
river_rim=water.buffer(2.1)
roads=[]
def road(name,pts,width,category='street',smoothed=True):
    line=LineString(curve(pts) if smoothed else pts)
    roads.append(dict(name=name,width=width,category=category,path=list(line.coords),shape=line.buffer(width/2,quad_segs=4)))
road('北侧山麓大道',[uv(*p) for p in [(-28,230),(130,229),(280,223),(407,204),(520,190),(628,148),(752,174)]],7.2)
road('中央街区大道',[uv(*p) for p in [(-28,270),(126,270),(263,281),(365,274),(490,263),(601,229),(752,195)]],7.8)
for side in [1,-1]:
    offset=river_path.offset_curve(side*16.8,quad_segs=6)
    road('北岸滨水道' if side==1 else '南岸滨水道',list(offset.coords),4.8,'quay',False)

def point_at_x(path,x):
    for a,b in zip(path,path[1:]):
        if min(a[0],b[0])<=x<=max(a[0],b[0]):
            t=(x-a[0])/(b[0]-a[0]);return a[1]+(b[1]-a[1])*t
    return min(path,key=lambda p:abs(p[0]-x))[1]
for idx,x in enumerate([-290,-181,-72,63,166,281]):
    y0=point_at_x(roads[2]['path'],x);y1=point_at_x(roads[0]['path'],x)
    road(f'街区连接路 {idx+1}',[(x,y0),(x+4,(y0+y1)/2),(x-4,y1)],4.8)

bridges=[]
def bridge(name,pts,width,rise):
    line=LineString(curve(pts,18));points=list(line.coords)
    # Landings join the nearest quay, rather than terminating in an empty field.
    for endpoint in (points[0],points[-1]):
        quay=min(roads[2:4],key=lambda r:LineString(r['path']).distance(Point(endpoint)))
        q=LineString(quay['path']).interpolate(LineString(quay['path']).project(Point(endpoint)))
        if Point(endpoint).distance(q)>.25:road(name+' 接岸路',[endpoint,list(q.coords)[0]],width,'approach',False)
    bridges.append(dict(name=name,path=points,width=width,rise=rise,shape=line.buffer(width/2+1.0)))
bridge('河湾主拱桥',[uv(*p) for p in [(240,397),(253,365),(291,342),(323,332),(351,324)]],6.2,5.8)
x=-239;y=point_at_x(riverline,x)
bridge('上游步行桥',[(x-6,y-18),(x-2,y),(x+4,y+18)],3.4,2.5)

# A single union surface removes coplanar junctions and inside-turn overlaps.
road_area=unary_union([r['shape'] for r in roads]).difference(water.buffer(.8)).intersection(site)
walks=unary_union([r['shape'].buffer(1.45) for r in roads]).difference(road_area).difference(water.buffer(1)).intersection(site)
roads_protected=road_area.buffer(2.0)
water_protected=water.buffer(3.8)
bridge_protected=unary_union([b['shape'] for b in bridges])
civic=scale(Point(-269,-104).buffer(1,quad_segs=32),75,43)
parks=[scale(Point(-179,163).buffer(1,quad_segs=24),63,36),scale(Point(265,187).buffer(1,quad_segs=24),63,30),civic.buffer(4)]
reserved=unary_union([roads_protected,water_protected,bridge_protected]+parks)

def ground(x,y):
    # Shared by terrain, road meshes, foundations and planting. River stays level.
    rise=21*smooth(-5,290,x)*smooth(-67,165,y)
    hills=19*math.exp(-((x+179)/53)**2-((y-165)/30)**2)+13*math.exp(-((x-265)/56)**2-((y-188)/27)**2)
    level=3.2+rise+hills
    d=river_path.distance(Point(x,y))
    return -1.15+(level+1.15)*smooth(10.0,16.3,d)

buildings=[];footprints=[];rejected=[]
def add_building(label,x,y,w,d,h,kind,angle=0,landmark=False):
    # Include roof eaves and foundation ledges in collision tests, all four sides.
    foot=rotate(box(x-w/2-.65,y-d/2-.65,x+w/2+.65,y+d/2+.65),angle,origin=(x,y))
    if not site.contains(foot) or reserved.intersects(foot):return False
    if any(foot.distance(p)<2.2 for p in footprints):return False
    zs=[ground(*p) for p in foot.exterior.coords]
    buildings.append(dict(id=f'B{len(buildings):03}',label=label,x=x,y=y,w=w,d=d,h=h,angle=angle,kind=kind,landmark=landmark,z=max(zs)+.15,base=min(zs)-.30,footprint=list(foot.exterior.coords)[:-1]))
    footprints.append(foot);return True

# World-space landmarks from the top panel. Elevations constrain their height groups.
landmarks=[
 ('西侧细塔',-247,75,10,11,34,'tower_fins',-2),('西侧双塔 A',-208,80,10,10,39,'tower_setback',-3),
 ('西侧双塔 B',-231,51,9,10,28,'tower_frame',-3),('中轴地标',28,93,11,12,48,'tower_fins',3),
 ('中部双塔 A',80,94,12,14,57,'tower_setback',5),('中部双塔 B',111,104,10,12,49,'tower_frame',7),
 ('东部高层 A',210,135,12,13,67,'tower_fins',14),('东部最高塔',246,145,14,15,88,'tower_setback',17),
 ('东部高层 B',271,133,10,13,61,'tower_frame',17),('东部次高塔',226,95,12,12,48,'tower_setback',15),
 ('东部地标 C',302,123,10,11,43,'tower_fins',17),('河湾文化馆',17,0,29,17,8,'pavilion',-12),
 ('南岸展馆',115,-58,30,19,12,'terrace',-20),('右前方街角馆',225,-36,28,18,14,'courtyard',-14)]
for label,x,y,w,d,h,kind,angle in landmarks:
    placed=False
    for dx,dy in [(0,0),(0,8),(8,0),(-8,0),(0,-8),(8,9),(-9,10),(0,17),(-15,0),(15,0),(0,26),(0,32),(0,-16),(0,-24),(0,-34),(-20,12),(20,12)]:
        if add_building(label,x+dx,y+dy,w,d,h,kind,angle,True):placed=True;break
    if not placed:rejected.append(label)

# Fill actual street blocks from centreline samples, preserving courtyards and alleys.
# Deterministic frontage rows replace random free-floating towers.
styles=['terrace','courtyard','office','gallery','gable','pavilion','sawtooth']
for row in range(4):
    for col,x in enumerate(np.arange(-318,325,19.7)):
        rear=point_at_x(roads[0]['path'],x);mid=point_at_x(roads[1]['path'],x);quay=point_at_x(roads[2]['path'],x)
        low,high=(mid,rear) if row<2 else (quay,mid)
        if high-low<23:continue
        y=low+(high-low)*(.29 if row%2==0 else .73)
        spacing=min(16.5,(high-low)*.37)
        w=rng.uniform(11.5,16.5);d=min(spacing,rng.uniform(11.5,16.0))
        kind=styles[(col+row*3)%len(styles)]
        h=rng.uniform(7,14)+(7*smooth(40,300,x) if row<2 else 0)
        if kind in ('pavilion','gallery','gable','sawtooth'):h=min(h,8)
        a=math.degrees(math.atan2(point_at_x(roads[1]['path'],x+2)-point_at_x(roads[1]['path'],x-2),4))
        for dx,dy in [(0,0),(0,3),(0,-3),(-3,0),(3,0)]:
            if add_building(f'街坊 {row+1}-{col+1}',float(x+dx),y+dy,w,d,h,kind,a):break

# South-bank ribbon, including the low-rise group visible under the main bridge.
for i,x in enumerate(np.arange(-314,330,23)):
    y=point_at_x(roads[3]['path'],x)-15
    kind=['gable','gallery','terrace','pavilion','office'][i%5]
    if x<-170 and y<-62:continue
    for dx,dy in [(0,0),(0,-4),(0,-8),(4,0)]:
        if add_building(f'南岸街坊 {i+1}',float(x+dx),y+dy,16,12,7+(i%3)*2,kind,-12):break

# Secondary infill uses block-specific height limits, always subject to full geometry.
for i in range(500):
    x=rng.uniform(-326,324);q=point_at_x(roads[2]['path'],x);rear=point_at_x(roads[0]['path'],x)
    y=rng.uniform(q+8,rear-8);w=rng.uniform(7,11);d=rng.uniform(7,11)
    kind=['office','terrace','gable','courtyard'][i%4]
    h=rng.uniform(6,12)+5*smooth(60,300,x)
    add_building('街坊补全',x,y,w,d,h,kind,8*smooth(0,300,x))
    if len(buildings)>=172:break

trees=[];tree_points=[]
def plant(x,y,s):
    p=Point(x,y)
    if not site.buffer(-4).contains(p) or water.buffer(2.8).contains(p) or road_area.buffer(.8).contains(p) or bridge_protected.buffer(1).contains(p) or any(park.buffer(2).contains(p) for park in parks):return
    if any(p.distance(f)<2.0*s for f in footprints):return
    if any((x-a)**2+(y-b)**2<(2.2*s)**2 for a,b in tree_points):return
    trees.append([x,y,ground(x,y),s,len(trees)%4]);tree_points.append((x,y))
for path in [roads[0]['path'],roads[1]['path'],roads[2]['path'],roads[3]['path']]:
    line=LineString(path)
    for side in [-1,1]:
        row=line.offset_curve(side*7.0)
        for d in np.arange(4,row.length,6.2):
            p=row.interpolate(d);plant(p.x,p.y,rng.uniform(.85,1.3))
for _ in range(2700):
    x=rng.uniform(-337,335);q=point_at_x(roads[3]['path'],x);rear=point_at_x(roads[0]['path'],x)
    y=rng.uniform(q-24,min(204,rear+27))
    plant(x,y,rng.uniform(.7,1.5))
    if len(trees)>=920:break

surfaces={}
for name,poly in [('water',water),('banks',banks),('roads',road_area),('sidewalks',walks)]:
    surfaces[name]=dict(polygons=serial(poly),triangles=triangles(poly))
terrain_points=[p for p in site.exterior.coords]+[(x,y) for x in np.arange(-354,357,4.5) for y in np.arange(-153,216,4.5) if site.contains(Point(x,y))]
terrain_triangles=[[list(p) for p in t.exterior.coords][:3] for t in delaunay_triangles(MultiPoint(terrain_points)).geoms if site.covers(t)]
report=dict(stage='12',status='geometry study / model approval pending',coordinate_system='X east, Y north, Z up; design units, not surveyed dimensions',
    reference='assets/city-four-view-reference.png',reference_sha256=hashlib.sha256((ROOT.parent/'assets/city-four-view-reference.png').read_bytes()).hexdigest(),
    extent=[-356,-155,356,216],river_centerline=riverline.tolist(),river_halfwidth=9.5,water_z=0,
    site=serial(site),terrain_triangles=terrain_triangles,roads=[{k:v for k,v in r.items() if k!='shape'} for r in roads],
    bridges=[{k:v for k,v in b.items() if k!='shape'} for b in bridges],surfaces=surfaces,buildings=buildings,trees=trees,
    landforms=[dict(name='西南层叠坡地',x=-269,y=-104,rx=75,ry=43,h=11.0),dict(name='西北山体等高台地',x=-179,y=163,rx=63,ry=36,h=8.0),dict(name='东北山麓台地',x=265,y=187,rx=56,ry=26,h=6.0)],unplaced_landmarks=rejected,
    validation=dict(buildings=len(buildings),landmarks=sum(b['landmark'] for b in buildings),trees=len(trees),
        building_water_conflicts=sum(water_protected.intersects(p) for p in footprints),building_road_conflicts=sum(roads_protected.intersects(p) for p in footprints),
        building_pairs=sum(a.intersects(b) for i,a in enumerate(footprints) for b in footprints[i+1:]),
        bridge_landings_in_water=[b['name'] for b in bridges if any(water.contains(Point(p)) for p in (b['path'][0],b['path'][-1]))]),
    limits=['four reference views contain perspective and are not dimensioned orthographic plans','unseen geometry is completed coherently, not recovered exactly','model only; final materials and lighting deferred'])
(ROOT/'city-12-master-plan.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print(json.dumps(report['validation'],ensure_ascii=False));print('unplaced',rejected)
if rejected or any(report['validation'][k] for k in ['building_water_conflicts','building_road_conflicts','building_pairs','bridge_landings_in_water']):raise SystemExit('Plan failed geometry constraints')
