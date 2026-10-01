"""Pure geometry placement constraints; independent of Blender and render visibility."""
import math


def rectangle(x,y,hw,hd):
    return [(x-hw,y-hd),(x+hw,y-hd),(x+hw,y+hd),(x-hw,y+hd)]


def bounds(poly):
    return min(p[0] for p in poly),min(p[1] for p in poly),max(p[0] for p in poly),max(p[1] for p in poly)


def intersects(a,b):
    """Convex polygon SAT, including edge crossing and containment (not just corners)."""
    ax,ay,bx,by=bounds(a);cx,cy,dx,dy=bounds(b)
    if bx<cx or dx<ax or by<cy or dy<ay:
        return False
    for poly in (a,b):
        for p,q in zip(poly,poly[1:]+poly[:1]):
            nx,ny=p[1]-q[1],q[0]-p[0]
            pa=[x*nx+y*ny for x,y in a];pb=[x*nx+y*ny for x,y in b]
            if max(pa)<min(pb)-1e-8 or max(pb)<min(pa)-1e-8:
                return False
    return True


def river_strip(points,normals,half_width):
    left=[(p[0]+n[0]*half_width,p[1]+n[1]*half_width) for p,n in zip(points,normals)]
    right=[(p[0]-n[0]*half_width,p[1]-n[1]*half_width) for p,n in zip(points,normals)]
    return [[left[i],right[i],right[i+1],left[i+1]] for i in range(len(points)-1)]


class Layout:
    def __init__(self,river,normals,bridge_index=77):
        self.water=river_strip(river,normals,19.5)
        self.protected=river_strip(river,normals,25.5)
        p,n=river[bridge_index],normals[bridge_index]
        t=(-n[1],n[0])
        self.bridge=[(p[0]+n[0]*u+t[0]*v,p[1]+n[1]*u+t[1]*v)
                     for u,v in [(-40,-5),(40,-5),(40,5),(-40,5)]]
        self.occupied=[]
        self.moves=[]

    def valid(self,x,y,w,d,margin=3.5):
        footprint=rectangle(x,y,w/2+margin,d/2+margin)
        if any(intersects(footprint,p) for p in self.protected):
            return False
        if intersects(footprint,self.bridge):
            return False
        return not any(intersects(footprint,p) for p in self.occupied)

    def place(self,x,y,w,d,relocate=False):
        origin=(x,y)
        candidates=[origin]
        if relocate:
            # Nearest valid land parcel, with deterministic ordering and no random retries.
            for radius in range(4,85,4):
                for i in range(24):
                    angle=i*math.tau/24
                    candidates.append((x+math.cos(angle)*radius,y+math.sin(angle)*radius))
        for px,py in candidates:
            if self.valid(px,py,w,d):
                self.occupied.append(rectangle(px,py,w/2+3.5,d/2+3.5))
                if math.dist(origin,(px,py))>.1:
                    self.moves.append(dict(before=list(origin),after=[px,py],distance=math.dist(origin,(px,py))))
                return px,py
        if relocate:
            raise ValueError(f'No safe land parcel for building at {origin}')
        return None

    def bridge_clear(self,x,y,radius=2):
        return not intersects(rectangle(x,y,radius,radius),self.bridge)
