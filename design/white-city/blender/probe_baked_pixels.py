"""Locate the exact model faces behind remaining black exported pixels."""
from pathlib import Path
import bpy,json,hashlib
from mathutils import Vector
ROOT=Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'city-14-studio.blend'))
scene=bpy.context.scene
for ob in list(scene.objects):
    if ob.type!='CAMERA':bpy.data.objects.remove(ob,do_unlink=True)
bpy.ops.import_scene.gltf(filepath=str(ROOT/'city-14-studio-baked.glb'))
bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
cam=scene.camera;aspect=1883/1054;direction=cam.matrix_world.to_quaternion()@Vector((0,0,-1))
points=[(1053,507),(1576,608),(1614,612),(1623,613),(1642,615),(1328,688),(1548,705),(1543,706),(940,749),(941,749),(1260,768),(740,847),(1219,871),(1232,871),(297,914),(300,914),(300,915),(301,915),(302,915),(300,916),(301,916),(302,916),(303,916),(9,923),(88,1022),(46,1024)]
rows=[]
for x,y in points:
    origin=cam.matrix_world@Vector((((x+.5)/1883-.5)*cam.data.ortho_scale,(.5-(y+.5)/1054)*cam.data.ortho_scale/aspect,0))
    hit,point,normal,index,ob,matrix=scene.ray_cast(dg,origin,direction,distance=3000)
    if not hit:continue
    face=ob.data.polygons[index];color=ob.data.color_attributes[0]
    vals=[list(color.data[i if color.domain=='CORNER' else ob.data.loops[i].vertex_index].color) for i in face.loop_indices]
    row=dict(pixel=[x,y],object=ob.name,face=index,normal=list(normal),facing=normal.dot(-direction),point=list(point),colors=vals)
    rows.append(row);print('PIXEL_FACE',json.dumps(row),flush=True)
(ROOT/'probe-baked-pixels.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
