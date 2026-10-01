"""Shared camera-independent terrain for layout 13 (Python and Blender)."""
import math
import numpy as np

def smooth(a,b,x):
    t=max(0.,min(1.,(x-a)/(b-a)));return t*t*(3-2*t)

class Terrain:
    def __init__(self,water_ring):
        p=np.array(water_ring,dtype=float)
        self.a=p;self.b=np.roll(p,-1,axis=0);self.ab=self.b-self.a
        self.den=np.maximum((self.ab*self.ab).sum(axis=1),1e-12)
    def __call__(self,x,y):
        # Broad hillside carries the entire eastern district; it is not a flat
        # display board with isolated mountains placed on top.
        east=44*smooth(-150,325,x)*smooth(-94,175,y)
        hills=0
        for cx,cy,rx,ry,h in [(-194,196,84,58,27),(-277,-79,89,55,17),(269,247,65,37,15)]:
            dx=(x-cx)/rx;dy=(y-cy)/ry
            r=math.sqrt(dx*dx+dy*dy)*(1+.12*math.sin(math.atan2(dy,dx)*3))
            raw=h*math.exp(-2.1*r**4)
            step=1.15;level=raw/step
            hills+=step*(math.floor(level)+smooth(.73,1,level%1))
        land=3.4+east+hills
        p=np.array([x,y]);t=np.clip(((p-self.a)*self.ab).sum(axis=1)/self.den,0,1)
        distance=float(np.sqrt(((p-self.a-self.ab*t[:,None])**2).sum(axis=1)).min())
        ax,ay=self.a[:,0],self.a[:,1];bx,by=self.b[:,0],self.b[:,1]
        cross=((ay>y)!=(by>y)) & (x<(bx-ax)*(y-ay)/np.where(abs(by-ay)<1e-12,1e-12,by-ay)+ax)
        inside=bool(np.count_nonzero(cross)%2)
        # Continuous riverbed and banks; the river basin is a traced polygon,
        # not a uniform-width tube. Keep a low promenade along either shore.
        if inside:return -1.35
        return -1.35+(land+1.35)*smooth(0,7.5,distance)
