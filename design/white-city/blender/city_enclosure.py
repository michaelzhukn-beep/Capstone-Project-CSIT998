"""08: close architectural shells and place downlights inside physical roof coves.

Coordinates are Blender Z-up. Works on original world-space meshes and on the
local-space collections used by the district scene. Courtyards stay open-air.
"""
import bpy,bmesh,math
from mathutils import Vector

class Parts:
    def __init__(self):self.vertices=[];self.faces=[]
    def add(self,vertices,faces):
        offset=len(self.vertices);self.vertices.extend(vertices)
        self.faces.extend(tuple(offset+i for i in face) for face in faces)
    def box(self,c,s):
        x,y,z=c;a,b,d=[v/2 for v in s]
        self.add([(x-a,y-b,z-d),(x+a,y-b,z-d),(x+a,y+b,z-d),(x-a,y+b,z-d),
                  (x-a,y-b,z+d),(x+a,y-b,z+d),(x+a,y+b,z+d),(x-a,y+b,z+d)],
                 [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    def finish(self,name,material,collection):
        data=bpy.data.meshes.new(name);data.from_pydata(self.vertices,[],self.faces);data.materials.append(material);data.update()
        if 'real emission' not in material.name:
            bm=bmesh.new();bm.from_mesh(data);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(data);bm.free();data.update()
        obj=bpy.data.objects.new(name,data);collection.objects.link(obj);return obj

def palette():
    changes={
      'Ivory white architectural ceramic':((.88,.875,.85),.36),
      'Fine pale limestone':((.86,.855,.83),.56),
      'Seamless warm-white ground':((.90,.895,.87),.66),
      'White satin metal mullions':((.83,.845,.83),.35),
      'Matte white model foliage':((.86,.865,.84),.68),
      'Recessed neutral low-iron glazing':((.89,.905,.89),.16),
      'Pale stone streets':((.81,.815,.79),.82),
      'Recessed garden beds':((.80,.815,.77),.86),
    }
    for name,(color,roughness) in changes.items():
        m=bpy.data.materials.get(name)
        if not m:continue
        p=m.node_tree.nodes.get('Principled BSDF')
        p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=roughness
        m.diffuse_color=(*color,1)
        if name=='Recessed neutral low-iron glazing':p.inputs['Transmission Weight'].default_value=.82
    m=bpy.data.materials['Recessed warm ceiling - real emission'];p=m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Emission Color'].default_value=(1,.70,.39,1);p.inputs['Emission Strength'].default_value=45

def repair(collection,objects,b,x,y,z):
    w,d,h,form=[b[k] for k in ('w','d','h','form')]
    ceramic=bpy.data.materials['Ivory white architectural ceramic'];glass=bpy.data.materials['Recessed neutral low-iron glazing']
    tag=b['tag'];extra=Parts();sheets=0
    # Roof quads in gallery/sawtooth were isolated single-sided faces. Give each a
    # closed underside and rim. Other solid architectural components stay unchanged.
    for obj in objects:
        if obj.type!='MESH' or not any(m==ceramic for m in obj.data.materials):continue
        bm=bmesh.new();bm.from_mesh(obj.data)
        closed=[f for f in bm.faces if all(not e.is_boundary for e in f.edges)]
        if closed:bmesh.ops.recalc_face_normals(bm,faces=closed)
        open_faces=[f for f in bm.faces if all(e.is_boundary for e in f.edges)]
        for face in open_faces:
            if face.normal.z<.2:continue
            verts=[tuple(v.co) for v in face.verts];n=len(verts)
            extra.add(verts+[(a,c,k-.18) for a,c,k in verts],
                      [tuple(range(n)),tuple(reversed(range(n,2*n)))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)])
            bmesh.ops.delete(bm,geom=[face],context='FACES');sheets+=1
        bm.to_mesh(obj.data);bm.free();obj.data.update()
    if form=='sawtooth':
        # Close the triangular roof ends down to the existing solid building body.
        for i in range(3):
            a=x-w/2+i*w/3;bb=a+w/3;base=z+h*.72;top=z+h-.18
            for side in [-1,1]:
                yy=y+side*(d/2-.06)
                extra.add([(a,yy-.06,base),(bb,yy-.06,base),(bb,yy-.06,top),
                           (a,yy+.06,base),(bb,yy+.06,base),(bb,yy+.06,top)],
                          [(0,2,1),(3,4,5),(0,1,4,3),(1,2,5,4),(2,0,3,5)])
    if form=='gallery':
        for i in range(3):
            a=x-w/2+i*w/3;bb=a+w/3
            for side in [-1,1]:
                yy=y+side*(d/2-.1)
                extra.add([(a,yy-.08,z+4.75),(bb,yy-.08,z+4.75),(bb,yy-.08,z+5.67),(a,yy-.08,z+4.92),
                           (a,yy+.08,z+4.75),(bb,yy+.08,z+4.75),(bb,yy+.08,z+5.67),(a,yy+.08,z+4.92)],
                          [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    glazing=Parts()
    if form=='pavilion':
        # The old "glass room" was one solid glass box occupying the whole interior.
        # Replace it with four thin closed panes so room light can reach the viewer.
        for obj in list(objects):
            if obj.type=='MESH' and obj.name.startswith(tag+' recessed glass'):
                objects.remove(obj);bpy.data.objects.remove(obj,do_unlink=True)
        for side in [-1,1]:
            glazing.box((x,y+side*(d/2-.25),z+2.55),(w-.5,.035,4.6))
            glazing.box((x+side*(w/2-.25),y,z+2.55),(.035,d-.5,4.6))
    if form=='court_pavilion':
        # The two existing courtyard-facing glass walls remain. Close outer sides
        # and exposed wing ends, without putting a roof over the intended court.
        extra.box((x-w/2+.12,y,z+2.5),(.24,d,5))
        extra.box((x,y+d/2-.12,z+2.5),(w,.24,5))
        for cx,cy,ww,dd in [(x-w*.33,y-d/2+.12,w*.34,.045),(x+w/2-.12,y+d*.32,.045,d*.36)]:
            glazing.box((cx,cy,z+2.45),(ww,dd,4.7))
        # Remove orphan posts around the open front court. Keep posts beneath roofs.
        for obj in objects:
            if obj.type!='MESH' or 'ceramic structure' not in obj.name:continue
            bm=bmesh.new();bm.from_mesh(obj.data);seen=set();remove=[]
            for v in bm.verts:
                if v in seen:continue
                stack=[v];component=[];seen.add(v)
                while stack:
                    q=stack.pop();component.append(q)
                    for edge in q.link_edges:
                        other=edge.other_vert(q)
                        if other not in seen:seen.add(other);stack.append(other)
                lo=Vector([min(q.co[j] for q in component) for j in range(3)]);hi=Vector([max(q.co[j] for q in component) for j in range(3)])
                c=(lo+hi)/2;size=hi-lo
                if size.x<.3 and size.y<.35 and size.z>4.8 and c.x>x-w*.16 and c.y<y:remove.extend(component)
            if remove:bmesh.ops.delete(bm,geom=remove,context='VERTS')
            bm.to_mesh(obj.data);bm.free();obj.data.update()
    # Replace the floating all-sided light board with recessed emitting strips inside
    # covered wings. A solid shelf and lip shield each strip from external views.
    emitters=[o for o in objects if o.type=='MESH' and any(m and m.name=='Recessed warm ceiling - real emission' for m in o.data.materials)]
    lamps=Parts();lamp_centers=[]
    if emitters:
        if form=='court_pavilion':
            strips=[(x-w*.24,y-d*.05,.42,d*.7),(x+w*.15,y+d*.225,w*.54,.42)]
        else:strips=[(x,y-d*.33,w*.76,.42)]
        for cx,cy,ww,dd in strips:
            # Wide cove footprint, narrow upward light strip, with continuous front fascia.
            extra.box((cx,cy,z+4.83),(ww+.20,dd+.24,.12))
            for side in [-1,1]:extra.box((cx,cy+side*(dd/2+.10),z+4.55),(ww+.24,.12,.42))
            for side in [-1,1]:extra.box((cx+side*(ww/2+.06),cy,z+4.55),(.12,dd+.24,.42))
            # Facing down through the cove opening; the solid roof and .42m lip
            # block views from above and low external angles. Floor bounce stays visible.
            lamps.add([(cx-ww/2,cy-dd/2,z+4.69),(cx+ww/2,cy-dd/2,z+4.69),
                       (cx+ww/2,cy+dd/2,z+4.69),(cx-ww/2,cy+dd/2,z+4.69)],[(3,2,1,0)])
            lamp_centers.append([cx,cy,z+4.69])
        for obj in emitters:bpy.data.objects.remove(obj,do_unlink=True)
        light=lamps.finish(tag+' concealed cove downlight',bpy.data.materials['Recessed warm ceiling - real emission'],collection)
        light.visible_camera=False;light.visible_glossy=False
    if glazing.vertices:glazing.finish(tag+' wing end glazing',glass,collection)
    if extra.vertices:extra.finish(tag+' closed roof edges and cove baffles',ceramic,collection)
    return dict(tag=tag,form=form,closed_roof_sheets=sheets,concealed_emitters=len(lamp_centers),lamp_centers=lamp_centers)
