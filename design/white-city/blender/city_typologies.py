"""Distinct building masses; authored near/mid/far detail for the approved hero camera."""
import math


def model_form(ctx,stone,glass,metal,x,y,z,w,d,h,form,lod):
    near=lod=='near'
    far=lod=='far'
    floors=max(2,round(h/3.2))

    def block(cx,cy,base,ww,dd,hh,bands=True):
        stone.box((cx,cy,base+hh/2),(ww,dd,hh))
        stone.box((cx,cy,base+hh+.14),(ww+.22,dd+.22,.28))
        if far:
            return
        levels=max(2,round(hh/3.2))
        for level in range(levels):
            zz=base+(level+.5)*hh/levels
            if bands:
                # Thin glass strip sits in front of the solid core, with real solid frames.
                for side in [-1,1]:
                    glass.box((cx,cy+side*(dd/2+.025),zz),(ww-.65,.035,hh/levels*.38))
                if near:
                    for side in [-1,1]:
                        glass.box((cx+side*(ww/2+.025),cy,zz),(.035,dd-.65,hh/levels*.38))
                stone.box((cx,cy,base+level*hh/levels+.10),(ww+.35,dd+.35,.20))
        if near:
            for side in [-1,1]:
                for i in range(max(2,round(ww/2.6))+1):
                    px=cx-ww/2+i*ww/max(2,round(ww/2.6))
                    stone.box((px,cy+side*(dd/2+.08),base+hh/2),(.17,.20,hh))

    if form in ('gallery','colonnade','court_pavilion'):
        # Real glazed rooms, open circulation and distinct rooflines for the warm waterfront.
        stone.box((x,y,z+.18),(w+.8,d+.8,.36))
        roof=5.1
        if form=='gallery':
            # Three shallow folded roofs with clerestory slots; no opaque full-room box.
            for i in range(3):
                a=x-w/2+i*w/3;b=a+w/3
                verts=[(a,y-d/2-1,z+roof),(b,y-d/2-1,z+roof+.75),
                       (b,y+d/2+1,z+roof+.75),(a,y+d/2+1,z+roof)]
                stone.add(verts,[(0,1,2,3)])
                stone.box((b,y,z+roof+.25),(.18,d+2,.75))
                glass.box((b-.08,y,z+roof+.3),(.035,d-.4,.65))
        elif form=='colonnade':
            stone.box((x,y,z+roof),(w+1.8,d+1.8,.28))
            stone.box((x-w*.18,y+d*.12,z+roof+.8),(w*.5,d*.45,1.2))
        else:
            # L-shaped roof and open front court; two lit wings, not a duplicate pavilion slab.
            stone.box((x-w*.33,y,z+roof),(w*.34,d+1,.32))
            stone.box((x+w*.17,y+d*.32,z+roof),(w*.66,d*.36,.32))
        for side in [-1,1]:
            for i in range(max(4,round(w/3))+1):
                px=x-w/2+i*w/max(4,round(w/3))
                stone.box((px,y+side*d/2,z+roof/2),(.24,.28,roof))
            if form!='court_pavilion':
                glass.box((x,y+side*(d/2-.18),z+2.45),(w-.45,.045,4.7))
        if form=='court_pavilion':
            glass.box((x-w*.17,y,z+2.45),(.045,d-.4,4.7))
            glass.box((x+w*.16,y+d*.14,z+2.45),(w*.66,.045,4.7))
        else:
            for side in [-1,1]:
                glass.box((x+side*(w/2-.18),y,z+2.45),(.045,d-.4,4.7))
        for i in range(3):
            stone.box((x-w*.3+i*w*.24,y+d*.15,z+.6),(w*.12,.85,1.2))
        if form=='colonnade':
            for i in range(7):
                px=x-w*.45+i*w*.9/6
                stone.box((px,y-d/2-.85,z+roof/2),(.25,.25,roof))
    elif form=='blade':
        # Slender paired volumes with different crowns and a recessed connecting spine.
        block(x-w*.26,y,z,w*.44,d,h,bands=False)
        block(x+w*.26,y+d*.1,z,w*.44,d*.8,h*.81,bands=False)
        block(x,y+d*.2,z,w*.16,d*.45,h*.62,bands=False)
        if not far:
            for side in [-1,1]:
                for i in range(9 if near else 4):
                    px=x-w*.46+i*w*.92/(8 if near else 3)
                    hh=h if px<x else h*.81
                    metal.box((px,y-side*d*.5,z+hh/2),(.12,.16,hh))
    elif form=='corner':
        block(x-w*.32,y,z,w*.36,d,h)
        block(x+w*.18,y+d*.30,z,w*.64,d*.4,h*.78)
        if near:
            for level in range(1,floors):
                stone.box((x+w*.17,y+d*.08,z+level*h/floors),(w*.66,.8,.18))
    elif form=='cascading':
        for i in range(3):
            ww=w*(1-i*.2);dd=d*(1-i*.2)
            block(x-i*w*.075,y+i*d*.075,z+i*h/3,ww,dd,h/3)
            if near:
                for side in [-1,1]:
                    metal.box((x-i*w*.075,y+i*d*.075+side*dd/2,z+(i+1)*h/3+.7),(ww,.06,.07))
    elif form=='sawtooth':
        block(x,y,z,w,d,h*.72)
        for i in range(3):
            a=x-w/2+i*w/3;b=a+w/3
            verts=[(a,y-d/2,z+h*.72),(b,y-d/2,z+h),(b,y+d/2,z+h),(a,y+d/2,z+h*.72)]
            stone.add(verts,[(0,1,2,3)])
            stone.box((b,y,z+h*.86),(.14,d,h*.28))
    elif form=='rounded':
        # Elliptical ceramic residential tower, with projecting curved floor plates.
        sides=36 if near else 24 if not far else 16
        def ellipse(mesh,base,height,rx,ry):
            verts=[]
            for zz in (base,base+height):
                verts += [(x+rx*math.cos(i*math.tau/sides),y+ry*math.sin(i*math.tau/sides),zz)
                          for i in range(sides)]
            faces=[tuple(reversed(range(sides))),tuple(range(sides,2*sides))]
            faces += [(i,(i+1)%sides,(i+1)%sides+sides,i+sides) for i in range(sides)]
            mesh.add(verts,faces)
        ellipse(stone,z,h,w*.47,d*.47)
        ellipse(stone,z+h,.45,w*.49,d*.49)
        if not far:
            # Narrow curved glazing patches retain predominantly white ceramic faces.
            bays=20 if near else 12
            for floor in range(floors):
                bottom=z+(floor+.18)*h/floors;top=z+(floor+.84)*h/floors
                for bay in range(bays):
                    angle=bay*math.tau/bays
                    verts=[(x+w*.473*math.cos(angle+offset),y+d*.473*math.sin(angle+offset),zz)
                           for zz in (bottom,top) for offset in (-.065,0,.065)]
                    glass.add(verts,[(0,1,4,3),(1,2,5,4)])
            for floor in range(0,floors+1,1 if near else 3):
                ellipse(stone,z+floor*h/floors,.20 if near else .3,w*.51,d*.51)
            for i in range(20 if near else 12):
                a=i*math.tau/(20 if near else 12)
                px,py=x+w*.478*math.cos(a),y+d*.478*math.sin(a)
                stone.cylinder((px,py,z),(px,py,z+h),.15,6)
        ellipse(stone,z+h+.4,1.1,w*.30,d*.30)
    elif form=='stepped':
        # An asymmetric skyline tower: three vertical masses, not another tiered box crown.
        for width,depth,offset,base,height in [
            (w,d,0,z,h*.40),
            (w*.79,d*.83,-w*.085,z+h*.40,h*.32),
            (w*.57,d*.66,-w*.14,z+h*.72,h*.28)]:
            block(x+offset,y,base,width,depth,height,bands=False)
            if not far:
                count=max(3,round(width/(1.5 if near else 3.5)))
                for side in [-1,1]:
                    for i in range(count+1):
                        px=x+offset-width/2+i*width/count
                        stone.box((px,y+side*(depth/2+.08),base+height/2),(.15,.22,height))
                for side in [-1,1]:
                    for i in range(count):
                        px=x+offset-width/2+(i+.5)*width/count
                        glass.box((px,y+side*(depth/2+.025),base+height/2),(.42,.035,height*.88))
    elif form=='courtyard':
        # U-shaped housing around an open, ground-level courtyard.
        wing=w*.25
        block(x-w/2+wing/2,y,z,wing,d,h)
        block(x+w/2-wing/2,y,z,wing,d,h*.88)
        block(x,y+d*.34,z,w-wing*2,d*.32,h*.72)
        stone.box((x,y-d*.08,z+.06),(w*.46,d*.7,.12))
        if near:
            for side in [-1,1]:
                stone.box((x+side*w*.16,y-d*.08,z+.27),(.7,d*.4,.42))
            # Canopy over the rear connection; central courtyard remains open.
            for i in range(7):
                metal.box((x-w*.20+i*w*.4/6,y+d*.09,z+h*.72+.4),(.12,d*.28,.16))
    elif form=='gabled':
        # A row of individually pitched roofs reads as houses, not a small office tower.
        count=max(2,round(w/7))
        unit=w/count
        wall_h=min(h*.68,7.5)
        for i in range(count):
            cx=x-w/2+(i+.5)*unit
            ww=unit*.90
            stone.box((cx,y,z+wall_h/2),(ww,d,wall_h))
            base=z+wall_h;peak=z+h
            verts=[(cx-ww/2,y-d/2,base),(cx+ww/2,y-d/2,base),(cx,y-d/2,peak),
                   (cx-ww/2,y+d/2,base),(cx+ww/2,y+d/2,base),(cx,y+d/2,peak)]
            stone.add(verts,[(0,2,1),(3,4,5),(0,1,4,3),(0,3,5,2),(1,2,5,4)])
            if not far:
                for side in [-1,1]:
                    for px in [cx-ww*.23,cx+ww*.23]:
                        glass.box((px,y+side*(d/2+.025),z+wall_h*.6),(ww*.22,.035,wall_h*.43))
                stone.box((cx,y-d/2-.7,z+2.4),(ww*.55,1.45,.14))
                glass.box((cx,y-d/2-.025,z+1.1),(.8,.035,2.15))
    elif form=='slab':
        # Broad low office block with a recessed top storey and strong horizontal cornices.
        block(x,y,z,w,d,h*.77)
        block(x+w*.10,y+d*.05,z+h*.77,w*.73,d*.78,h*.23)
        if near:
            for i in range(1,floors):
                stone.box((x,y-d/2-.4,z+i*h/floors),(w+.65,.95,.18))
            for side in [-1,1]:
                metal.box((x+side*w*.3,y-d/2-.7,z+1.5),(.12,.12,3))
            stone.box((x,y-d/2-.6,z+3),(w*.68,1.5,.19))
    elif form=='terrace':
        tiers=3 if h>12 else 2
        for i in range(tiers):
            block(x,y+i*d*.035,z+i*h/tiers,w*(1-i*.12),d*(1-i*.12),h/tiers)
    elif form=='tower':
        block(x,y,z,w,d,h,bands=False)
        stone.box((x,y,z+h+.75),(w*.76,d*.75,1.2))
        if not far:
            for side in [-1,1]:
                for i in range(6):
                    px=x-w*.44+i*w*.88/5
                    stone.box((px,y+side*(d/2+.12),z+h/2),(.2,.3,h))
    else:
        block(x,y,z,w,d,h,bands=False)

    if near and form not in ('gabled','courtyard'):
        # Ground-level entrance scale only where it can be seen from the hero cameras.
        stone.box((x,y-d/2-1.0,z+3.1),(min(6,w*.4),2,.20))
        glass.box((x,y-d/2-.08,z+1.4),(min(2.8,w*.25),.045,2.8))
