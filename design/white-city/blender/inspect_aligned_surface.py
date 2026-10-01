"""Read-only ray probes for the fixed camera's shore artefacts."""
import bpy,json
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(root/'city-11-aligned.blend'))
scene=bpy.context.scene;cam=scene.camera;frame=cam.data.view_frame(scene=scene)
x0=min(v.x for v in frame);x1=max(v.x for v in frame);y0=min(v.y for v in frame);y1=max(v.y for v in frame)
for u,v in [(798/1672,888/941),(.48,.944),(.44,.94),(.35,.888),(.373503,.876398),(.404986,.911295)]:
    d=(cam.rotation_euler.to_matrix()@Vector((x0+(x1-x0)*u,y1-(y1-y0)*v,frame[0].z))).normalized()
    hit,loc,norm,face,ob,mat=scene.ray_cast(bpy.context.evaluated_depsgraph_get(),cam.location,d)
    print('SHORE_PROBE',json.dumps(dict(uv=[u,v],hit=hit,object=ob.name if ob else None,location=list(loc),normal=list(norm),face=face)),flush=True)
