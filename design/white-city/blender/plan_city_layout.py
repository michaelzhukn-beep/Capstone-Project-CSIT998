"""13: trace shore/bridge topology, then compose coherent building districts.

Original four-view plan anchors determine topology. Supplemental elevations
constrain the massing and hillside. Design units, not survey measurements.
"""
import json,math,random,hashlib
from pathlib import Path
import numpy as np
from shapely import constrained_delaunay_triangles,delaunay_triangles
from shapely.geometry import Point,LineString,Polygon,MultiPoint,box
from shapely.ops import unary_union
from shapely.affinity import rotate,scale
from layout_terrain import Terrain,smooth

ROOT=Path(__file__).resolve().parent;rng=random.Random(130917)
def uv(px,py):return [(px-368)*.9,(340-py)*1.15]
def curve(points,steps=12):
    p=np.asarray(points,float);out=[]
    for i in range(len(p)-1):
        a,b,c,d=p[max(0,i-1)],p[i],p[i+1],p[min(len(p)-1,i+2)]
        for j in range(steps):
            t=j/steps;out.append(.5*(2*b+(-a+c)*t+(2*a-5*b+4*c-d)*t*t+(-a+3*b-3*c+d)*t**3))
    return np.asarray(out+[p[-1]])
def trace(points):return curve([uv(*p) for p in points])
def serial(poly):
    if poly.is_empty:return []
    parts=[poly] if poly.geom_type=='Polygon' else list(poly.geoms)
    return [dict(outer=list(p.exterior.coords)[:-1],holes=[list(r.coords)[:-1] for r in p.interiors]) for p in parts if p.geom_type=='Polygon' and p.area>.01]
def triangles(poly):return [[list(p) for p in t.exterior.coords][:3] for t in constrained_delaunay_triangles(poly).geoms]

outline=[(-26,224),(45,185),(149,136),(209,131),(283,166),(381,169),(469,139),(517,108),(565,132),(633,102),(713,111),(750,160),(754,267),(731,344),(690,410),(620,454),(537,479),(437,480),(337,462),(281,483),(179,480),(78,468),(12,437),(-21,397),(-30,323),(-26,224)]
site=Polygon(trace(outline)).buffer(0)
# Independent banks open into the broad southern basin visible below the bridge.
north_pixels=[(-52,286),(32,282),(91,288),(150,307),(197,322),(244,318),(286,308),(329,310),(379,323),(425,343),(476,377),(522,407),(548,412),(586,394),(641,361),(697,325),(782,276)]
south_pixels=[(-52,323),(29,317),(87,323),(133,346),(175,365),(214,376),(238,397),(233,430),(259,447),(314,453),(416,476),(513,494),(605,474),(694,429),(782,365)]
nb=trace(north_pixels);sb=trace(south_pixels)
water=Polygon(list(nb)+list(sb[::-1])).buffer(0).intersection(site)
assert water.geom_type=='Polygon' and water.is_valid
ground=Terrain(list(water.exterior.coords)[:-1])
banks=water.buffer(1.2,quad_segs=3).difference(water).intersection(site)
roads=[]
def road(name,pts,width,category='street',curved=True):
    line=LineString(curve(pts) if curved else pts)
    roads.append(dict(name=name,path=list(line.coords),width=width,category=category,shape=line.buffer(width/2,quad_segs=3)))
def traced_road(name,pixels,width,category='street'):road(name,[uv(*p) for p in pixels],width,category)
traced_road('山麓曲线大道',[(-35,220),(104,229),(227,228),(312,211),(422,205),(520,184),(618,144),(754,137)],6.4)
traced_road('中央生活街',[(-35,267),(104,270),(199,275),(279,261),(355,250),(451,258),(532,247),(619,222),(754,187)],6.4)
road('北岸滨水大道',list(LineString(nb).offset_curve(7.3,quad_segs=5).coords),5.5,'quay',False)
traced_road('西南河湾公园路',[(-35,348),(58,351),(115,342),(153,363),(194,383),(213,401),(214,428)],4.2,'park')
for name,pixels in [
 ('西侧巷道',[(68,287),(93,263),(86,227)]),
 ('居住区斜街',[(204,323),(228,282),(220,254),(218,226)]),
 ('中央广场街',[(348,325),(359,294),(365,267),(353,243),(373,207)]),
 ('中东坡道',[(453,368),(464,328),(465,286),(480,236),(481,194)]),
 ('东部生活街',[(550,411),(558,373),(550,340),(562,299),(560,270),(578,217),(594,159)]),
 ('高层组团街',[(651,354),(632,317),(614,278),(632,242),(650,203),(676,137)])]:
    pts=[uv(*p) for p in pixels]
    # Clip no streets over water: the long bridge is the crossing, not an
    # accidentally flooded street. Project local endpoints onto the quays.
    quay=LineString(roads[2]['path']);p=quay.interpolate(quay.project(Point(pts[0])));pts[0]=list(p.coords)[0]
    road(name,pts,4.3)

bridges=[]
def bridge(name,pixels,width,rise):
    path=LineString(trace(pixels));pp=list(path.coords)
    bridges.append(dict(name=name,path=pp,width=width,rise=rise,shape=path.buffer(width/2+1.2),pier_spacing=22))
    for endpoint in (pp[0],pp[-1]):
        quay=min(roads[:4],key=lambda r:LineString(r['path']).distance(Point(endpoint)))
        q=LineString(quay['path']).interpolate(LineString(quay['path']).project(Point(endpoint)))
        if q.distance(Point(endpoint))>.15:road(name+' 接岸',[endpoint,list(q.coords)[0]],width,'approach',False)
bridge('河湾长弧主桥',[(226,403),(242,374),(264,347),(297,331),(330,328),(368,336),(407,352),(451,376),(495,401),(533,416),(581,388)],7.0,5.2)
bridge('上游小桥',[(78,337),(87,314),(99,277)],3.7,2.0)
road_area=unary_union([r['shape'] for r in roads]).difference(water.buffer(.8)).intersection(site)
walks=unary_union([r['shape'].buffer(1.45) for r in roads]).difference(road_area).difference(water.buffer(.4)).intersection(site)
park_shapes=[scale(Point(-194,196).buffer(1,quad_segs=32),82,53),scale(Point(-277,-79).buffer(1,quad_segs=32),79,47),scale(Point(269,247).buffer(1,quad_segs=32),56,31)]
protected_road=road_area.buffer(1.5);protected_water=water.buffer(3.1);protected_bridge=unary_union([b['shape'] for b in bridges]).buffer(.9)
reserved=unary_union([protected_road,protected_water,protected_bridge]+park_shapes)
buildings=[];feet=[];unplaced=[]
def add(label,x,y,w,d,h,kind,angle=0,landmark=False):
    foot=rotate(box(x-w/2-.65,y-d/2-.65,x+w/2+.65,y+d/2+.65),angle,origin=(x,y))
    if not site.buffer(-3).contains(foot) or reserved.intersects(foot) or any(foot.distance(p)<1.8 for p in feet):return False
    samples=list(foot.exterior.coords)+[(x,y)]
    zs=[ground(*p) for p in samples]
    buildings.append(dict(id=f'B{len(buildings):03}',label=label,x=x,y=y,w=w,d=d,h=h,angle=angle,kind=kind,landmark=landmark,z=max(zs)+.15,base=min(zs)-.30,footprint=list(foot.exterior.coords)[:-1]))
    feet.append(foot);return True

# Heights form three groups, with middle-height shoulders rather than lonely towers.
anchors=[
 ('西部滨水塔',120,251,12,15,31,'tower_fins',-6),('西部小塔',165,243,11,14,25,'tower_frame',0),('西部次塔',51,248,10,13,19,'tower_fins',0),
 ('中央主塔 A',390,270,15,19,53,'tower_fins',0),('中央主塔 B',426,269,13,17,59,'tower_crown',0),('中央次塔',432,306,15,16,35,'tower_frame',-7),
 ('中央街角楼',370,298,19,18,26,'office',-5),('中央中层楼',398,235,18,16,24,'terrace',4),
 ('东部最高塔',642,193,16,20,83,'tower_crown',14),('东部高塔 B',674,210,15,18,67,'tower_fins',17),('东部高塔 C',608,228,16,19,58,'tower_fins',14),
 ('东部高塔 D',635,250,15,18,52,'tower_crown',17),('东部组团北塔',699,180,13,16,49,'tower_frame',16),
 ('东部中高层 A',584,250,19,21,38,'office',16),('东部中高层 B',671,265,18,19,42,'tower_fins',18),('东部中高层 C',693,292,18,19,32,'terrace',25),
 ('东部过渡街坊',585,298,23,18,27,'office',-15),('东部坡地街坊',650,313,22,22,26,'terrace',22),
 ('滨水文化馆',397,309,24,16,13,'pavilion',-12),('河湾转角展馆',506,353,28,22,17,'gallery',-27),('东侧滨水馆',596,360,28,23,18,'courtyard',31)]
for label,px,py,w,d,h,kind,angle in anchors:
    x,y=uv(px,py);placed=False
    for dx,dy in [(0,0),(0,5),(5,0),(-5,0),(0,-5),(6,7),(-7,7),(0,11),(11,0),(-11,0),(0,-11),(11,11),(-11,-11),(17,0),(-17,0),(0,17),(0,-17)]:
        if add(label,x+dx,y+dy,w,d,h,kind,angle,True):placed=True;break
    if not placed:unplaced.append(label)

def building_style(x,y,width):
    shore=water.distance(Point(x,y));east=smooth(-130,245,x)
    if x< -95:
        kind=rng.choices(['gable','office','courtyard','gallery','terrace'],[.22,.30,.12,.18,.18])[0];h=rng.uniform(6,12.5)
    else:
        kind=rng.choices(['office','terrace','courtyard','gallery','pavilion'],[.42,.26,.12,.12,.08])[0]
        h=rng.uniform(8,16)+east*rng.uniform(1,6)
        cluster_distance=min(math.hypot(x-b['x'],y-b['y']) for b in buildings if b['landmark'] and b['h']>=45)
        if cluster_distance<43:h+=rng.uniform(3,8)
    if shore<29:h=min(h,rng.uniform(10,19))
    if kind in ('gallery','pavilion'):h=min(h,15)
    return kind,h

# Variable-width frontages follow road tangents and form recognizable blocks.
# No fixed four rows and no global alternating roof-type sequence.
for ridx,sides in [(0,[-1,1]),(1,[-1,1]),(2,[1]),(3,[-1,1])]:
    line=LineString(roads[ridx]['path'])
    for side in sides:
        distance=12+rng.uniform(0,8)
        while distance<line.length-10:
            small=rng.random()<.34
            w=rng.uniform(11,15) if small else rng.uniform(18,27);d=rng.uniform(10,13) if small else rng.uniform(12,18)
            row=line.offset_curve(side*(roads[ridx]['width']/2+3+d/2),quad_segs=5)
            q=row.interpolate(min(distance,row.length));a=row.interpolate(max(0,distance-1));b=row.interpolate(min(row.length,distance+1))
            angle=math.degrees(math.atan2(b.y-a.y,b.x-a.x));kind,h=building_style(q.x,q.y,w)
            if ridx==3:kind='gable' if rng.random()<.25 else 'gallery';h=rng.uniform(6,10)
            for shift in [0,3,-3]:
                t=math.radians(angle)
                if add('沿街街坊',q.x+shift*math.cos(t),q.y+shift*math.sin(t),w,d,h,kind,angle):break
            distance+=w+rng.uniform(3,8)

# Fill residual courtyards in the developed envelope, not the entire display base.
nb_line=LineString(nb);back=LineString(roads[0]['path'])
developed=Polygon(list(roads[0]['path'])+list(nb[::-1])).buffer(0)
for i in range(3500):
    x=rng.uniform(-335,331);y=rng.uniform(-92,235)
    if not developed.contains(Point(x,y)):continue
    w=rng.uniform(7,14);d=rng.uniform(7,13);kind,h=building_style(x,y,w)
    nearest=min(roads[:3],key=lambda r:LineString(r['path']).distance(Point(x,y)))
    line=LineString(nearest['path']);t=line.project(Point(x,y));a=line.interpolate(max(0,t-1));b=line.interpolate(min(line.length,t+1))
    angle=math.degrees(math.atan2(b.y-a.y,b.x-a.x))
    add('内街院落',x,y,w,d,h,kind,angle)
    if len(buildings)>=192:break

trees=[];tree_points=[]
def plant(x,y,s):
    p=Point(x,y)
    if not site.buffer(-2).contains(p) or water.buffer(.8).contains(p) or road_area.buffer(.65).contains(p) or protected_bridge.contains(p):return
    if any(p.distance(f)<1.5*s for f in feet) or any((x-a)**2+(y-b)**2<(2.1*s)**2 for a,b in tree_points):return
    trees.append([x,y,ground(x,y),s,len(trees)%4]);tree_points.append((x,y))
# Riverbank groves alternate with open overlooks, never perfectly spaced rows.
for shore in [LineString(nb),LineString(sb)]:
    for side in [1,-1]:
        path=shore.offset_curve(side*4.4)
        for t in np.arange(0,path.length,4.5):
            q=path.interpolate(t+rng.uniform(-1.8,1.8));plant(q.x+rng.uniform(-1,1),q.y+rng.uniform(-1,1),rng.uniform(.9,1.8))
for _ in range(8000):
    x=rng.uniform(-348,340);y=rng.uniform(-166,272)
    if not site.contains(Point(x,y)):continue
    near=water.distance(Point(x,y));h=ground(x,y)
    # Denser groves on the river peninsulas and hill toes, sparse at hill summits.
    if near>35 and not developed.buffer(21).contains(Point(x,y)) and rng.random()>.20:continue
    if x< -120 and y>160 and h>20 and rng.random()>.12:continue
    plant(x,y,rng.uniform(.9,1.75))
    if len(trees)>=1400:break

surfaces={}
for name,poly in [('water',water),('banks',banks),('roads',road_area),('sidewalks',walks)]:surfaces[name]=dict(polygons=serial(poly),triangles=triangles(poly))
minx,miny,maxx,maxy=site.bounds
pts=[p for p in site.exterior.coords]+[(x,y) for x in np.arange(minx,maxx,3.2) for y in np.arange(miny,maxy,3.2) if site.contains(Point(x,y))]
terrain_triangles=[[list(p) for p in t.exterior.coords][:3] for t in delaunay_triangles(MultiPoint(pts)).geoms if site.covers(t)]
height_hist={label:sum(lo<=b['h']<hi for b in buildings) for label,lo,hi in [('below15',0,15),('15to30',15,30),('30to50',30,50),('50plus',50,200)]}
validation=dict(buildings=len(buildings),landmarks=sum(b['landmark'] for b in buildings),trees=len(trees),height_histogram=height_hist,
 building_water_conflicts=sum(protected_water.intersects(p) for p in feet),building_road_conflicts=sum(protected_road.intersects(p) for p in feet),building_pairs=sum(a.intersects(b) for i,a in enumerate(feet) for b in feet[i+1:]),
 bridge_landings_in_water=[b['name'] for b in bridges if any(water.contains(Point(p)) for p in [b['path'][0],b['path'][-1]])],main_bridge_length=LineString(bridges[0]['path']).length)
report=dict(stage='13',status='layout revision / visual acceptance pending',reference='assets/city-four-view-reference.png',additional_reference='assets/city-additional-views-reference.png',
 reference_sha256=hashlib.sha256((ROOT.parent/'assets/city-four-view-reference.png').read_bytes()).hexdigest(),extent=list(site.bounds),terrain_z_max=80,coordinate_system='X east, Y north, Z up; inferred design units',
 site=serial(site),terrain_triangles=terrain_triangles,water_contour=list(water.exterior.coords)[:-1],north_bank=nb.tolist(),south_bank=sb.tolist(),water_z=0,
 roads=[{k:v for k,v in r.items() if k!='shape'} for r in roads],bridges=[{k:v for k,v in r.items() if k!='shape'} for r in bridges],surfaces=surfaces,buildings=buildings,trees=trees,landforms=[],unplaced_landmarks=unplaced,validation=validation,
 limits=['reference panels have differing perspective and cannot uniquely specify hidden geometry','complete single city geometry, not a pixel-perfect reconstruction','model layout only, final lighting deferred'])
(ROOT/'city-13-layout-plan.json').write_text(json.dumps(report,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print(json.dumps(validation,ensure_ascii=False));print('UNPLACED',unplaced)
if unplaced or any(validation[k] for k in ['building_water_conflicts','building_road_conflicts','building_pairs','bridge_landings_in_water']):raise SystemExit('Layout needs geometric correction')
