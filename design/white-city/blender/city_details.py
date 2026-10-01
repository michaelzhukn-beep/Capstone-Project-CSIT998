"""Model 02: geometric architectural and landscape detail, preserving the 01 light rig."""
import math
import random
import bpy
from mathutils import Vector


def add_details(ctx):
    Mesh = ctx['Mesh']
    group = ctx['collection']('06 Crafted architectural and riverfront details')
    garden = ctx['collection']('07 Understory - linked geometric instances')
    ceramic, metal = ctx['porcelain'], ctx['frame_mat']
    stone, leaf = ctx['limestone'], ctx['leaf_mat']
    glass = ctx['glass']
    ground = ctx['ground_z']
    rng = random.Random(602)
    report = dict(balcony_buildings=0, roof_pergolas=0, pavilion_interiors=0,
                  entrance_stairs=0, river_benches=0, planting_groups=0)

    # Reuse a few detailed shrub prototypes. They are 3D leaf clusters, never billboards.
    prototypes = []
    for variant in range(3):
        local = random.Random(960 + variant)
        proto = bpy.data.collections.new(f'Understory prototype {variant}')
        mesh = Mesh()
        for cluster in range(11):
            angle = cluster * 2.399
            r = math.sqrt(cluster / 11) * .54
            center = Vector((math.cos(angle)*r, math.sin(angle)*r, .35 + local.uniform(-.09,.17)))
            radius = local.uniform(.25,.4)
            vertices = [tuple(center + Vector((a*radius,b*radius,c*radius*.85)))
                        for a,b,c in ctx['ico_data']]
            mesh.add(vertices,ctx['ico_faces'])
        mesh.finish(f'Understory canopy {variant}',leaf,proto,smooth=True)
        prototypes.append(proto)

    def shrub(x,y,z,scale=1):
        obj = bpy.data.objects.new(f'Understory {report["planting_groups"]:04d}',None)
        obj.instance_type = 'COLLECTION'
        obj.instance_collection = prototypes[rng.randrange(3)]
        obj.location = (x,y,z)
        obj.rotation_euler.z = rng.uniform(0,math.tau)
        obj.scale = (scale,scale,scale*rng.uniform(.75,1.05))
        garden.objects.link(obj)
        report['planting_groups'] += 1

    def planter(mesh,x,y,z,w,d):
        # Real open rim, with a recessed bed and low foliage, not a solid raised box.
        for side in [-1,1]:
            mesh.box((x,y+side*d/2,z+.25),(w+.16,.16,.5))
            mesh.box((x+side*w/2,y,z+.25),(.16,d,.5))
        for j in range(max(2,round(w/1.3))):
            shrub(x-w*.35+j*w*.7/max(1,round(w/1.3)-1),y,z+.1,.66)

    for b in ctx['building_records']:
        if b.get('lod','near')!='near' or b.get('form',b['kind'])!=b['kind']:
            continue
        x,y,z,w,d,h,kind,seed = [b[k] for k in ('x','y','z','w','d','h','kind','seed')]
        solid, rail, glazing = Mesh(), Mesh(), Mesh()
        if kind == 'terrace':
            floors = max(2,round(h/3.1))
            for level in range(1,floors):
                setback = max(0,level-floors//2)*.68
                ww,dd = w-setback*2,d-setback*1.6
                zz = z+level*h/floors+.40
                # Alternate open rails and solid balcony ends; fine scale casts real shadows.
                front = y-dd/2-1.0
                rail.box((x,front,zz+.84),(ww,.065,.065))
                for j in range(round(ww/.85)+1):
                    px = x-ww/2+j*ww/round(ww/.85)
                    rail.box((px,front,zz+.42),(.045,.045,.84))
                for side in [-1,1]:
                    solid.box((x+side*ww/2,front+.35,zz+.4),(.14,.75,.8))
                if level==1 and seed%2==0:
                    planter(solid,x+ww*.23,front+.42,zz,ww*.25,.45)
            report['balcony_buildings'] += 1
            # A roof garden on selected low buildings changes their silhouette without towers
            # getting taller. The original stepped roof and service blocks remain editable.
            if seed%3==0 or seed in (5,7,9,25):
                step=max(0,floors-1-floors//2)*.68
                rw,rd=w-step*2,d-step*1.6
                px,py,pz=x-rw*.18,y-rd*.17,z+h+.42
                aw,ad=rw*.42,rd*.44
                for sx in [-1,1]:
                    for sy in [-1,1]:
                        rail.box((px+sx*aw/2,py+sy*ad/2,pz+1.25),(.12,.12,2.5))
                for side in [-1,1]:
                    rail.box((px,py+side*ad/2,pz+2.40),(aw+.25,.18,.22))
                for j in range(max(3,round(aw/.55))+1):
                    qx=px-aw/2+j*aw/max(3,round(aw/.55))
                    rail.box((qx,py,pz+2.5),(.14,ad+.3,.2))
                planter(solid,x+rw*.28,y-rd*.27,pz,rw*.26,.85)
                report['roof_pergolas'] += 1
        elif kind == 'tower':
            # Distinguish quieter paired-fins towers with fine horizontal crown screens.
            if seed%3==0:
                for level in range(4):
                    zz=z+h+.6+level*.48
                    for side in [-1,1]:
                        rail.box((x,y+side*d*.42,zz),(w*.86,.12,.10))
                        rail.box((x+side*w*.42,y,zz),(.12,d*.86,.10))
            # Small entrance canopy gives each tall volume a believable ground-floor scale.
            solid.box((x,y-d/2-1.1,z+3.25),(w*.42,2.3,.19))
            for side in [-1,1]:
                rail.box((x+side*w*.18,y-d/2-2,z+1.55),(.10,.10,3.1))
        else:
            # Glazed rooflight, thin drip edge, double entry frame and interior gallery furniture.
            # No emitters are added or brightened: retain the accepted warm light distribution.
            for side in [-1,1]:
                solid.box((x-w*.18,y+d*.12+side*d*.175,z+h+.05),(w*.33+.18,.18,.18))
                solid.box((x-w*.18+side*w*.165,y+d*.12,z+h+.05),(.18,d*.35,.18))
            glazing.box((x-w*.18,y+d*.12,z+h+.08),(w*.33,d*.35,.06))
            for side in [-1,1]:
                rail.box((x+side*1.3,y-d/2-.12,z+1.5),(.08,.13,3))
                rail.box((x+side*.08,y-d/2-.22,z+1.45),(.035,.055,.7))
            rail.box((x,y-d/2-.12,z+3),(2.7,.13,.08))
            for j in range(3):
                px=x-w*.30+j*w*.30
                solid.box((px,y-d*.15,z+.70),(w*.14,d*.18,.16))
                solid.box((px,y-d*.15,z+.34),(.25,.5,.60))
                solid.box((px,y+d*.12,z+.35),(w*.12,.65,.55))
            report['pavilion_interiors'] += 1

        if y<95:
            # Entrance steps meet the actual terrain. Heights come from model elevations.
            front=y-d/2-.7
            bottom=ground(x,front-1.6)+.04
            rise=z+.20-bottom
            steps=max(1,math.ceil(rise/.17))
            if 0<rise<1.5:
                for j in range(steps):
                    top=bottom+rise*(j+1)/steps
                    solid.box((x,front-steps*.29+j*.29,(top+bottom)/2),
                              (min(4,w*.35),.32,max(.03,top-bottom)))
                report['entrance_stairs'] += 1
        solid.finish(b['tag']+' refined stone details',ceramic,group,bevel=.025)
        rail.finish(b['tag']+' precise satin rails and screens',metal,group,bevel=.012)
        glazing.finish(b['tag']+' rooflight',glass,group,bevel=.01)

    # Riverfront furniture is aligned to the curved bank, not to the world grid.
    paving, benches, frames = Mesh(),Mesh(),Mesh()
    def oriented_box(mesh,center,tangent,normal,size):
        local=Mesh();local.box((0,0,0),size)
        origin=Vector(center)
        verts=[tuple(origin+Vector((tangent.x*a+normal.x*b,tangent.y*a+normal.y*b,c)))
               for a,b,c in local.vertices]
        mesh.add(verts,local.faces)

    for i in range(8,len(ctx['river'])-10,4):
        p,n=ctx['river'][i],ctx['normals'][i]
        tangent=Vector((-n.y,n.x))
        for side in [-1,1]:
            # Hairline paving seams remain sparse enough not to turn the banks grey.
            center=p+n*(side*22)
            a=p+n*(side*20.2); bb=p+n*(side*23.7)
            verts=[]
            for q in (a-tangent*.015,a+tangent*.015,bb+tangent*.015,bb-tangent*.015):
                verts.append((q.x,q.y,ground(q.x,q.y)+.065))
            paving.add(verts,[(0,1,2,3)])
            if i%12!=8 or 67<i<88:
                continue
            q=p+n*(side*23.35)
            z=ground(q.x,q.y)+.08
            oriented_box(benches,(q.x,q.y,z+.46),tangent,n,(2.4,.62,.14))
            for offset in [-.87,.87]:
                foot=q+tangent*offset
                oriented_box(frames,(foot.x,foot.y,z+.20),tangent,n,(.12,.4,.4))
            report['river_benches'] += 1

    paving.finish('Sparse river promenade paving joints',stone,group)
    benches.finish('Riverside stone benches',ceramic,group,bevel=.035)
    frames.finish('Riverside bench supports',metal,group,bevel=.015)

    # Add a lower foliage layer in small clusters; leave the pedestrian path and entrances open.
    for i in range(10,len(ctx['river'])-8,7):
        p,n=ctx['river'][i],ctx['normals'][i]
        tangent=Vector((-n.y,n.x))
        for side in [-1,1]:
            center=p+n*(side*32.5)
            for j in range(5):
                q=center+tangent*(j-2)*1.0+n*rng.uniform(-.6,.6)
                if ctx.get('layout') and not ctx['layout'].bridge_clear(q.x,q.y,2):
                    continue
                if any(abs(q.x-bx)<bw+1.1 and abs(q.y-by)<bd+1.1 for bx,by,bw,bd in ctx['footprints']):
                    continue
                if any((q.x-tx)**2+(q.y-ty)**2<1.0 for tx,ty in ctx['trees']):
                    continue
                shrub(q.x,q.y,ground(q.x,q.y),rng.uniform(.9,1.3))

    for i,(x,y) in enumerate(ctx['trees']):
        if i%5 or y>160:
            continue
        for j in range(2):
            qx,qy=x+1.9+j*.95,y+.6
            if ctx.get('layout') and not ctx['layout'].bridge_clear(qx,qy,2):
                continue
            if ctx['river_distance'](qx,qy)<26 or any(abs(qx-bx)<bw+1 and abs(qy-by)<bd+1 for bx,by,bw,bd in ctx['footprints']):
                continue
            shrub(qx,qy,ground(qx,qy),rng.uniform(.85,1.2))
    print('DETAILS_ADDED',report,flush=True)
    return report
