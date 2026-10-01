"""Geometry/light-source verification independent of the visual preview."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'city-08-source.blend'))
manifest=json.loads((ROOT/'city-04-manifest.json').read_text(encoding='utf-8'))
issues=[];solid_components=0;hidden=0;roof_hits=0;lamp_samples=0
for b in manifest['buildings_layout']:
    if b['lod']!='near':continue
    objects=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.startswith(b['tag']+' ')]
    solids=[o for o in objects if all(m and ('ceramic' in m.name or 'limestone' in m.name or 'mullions' in m.name) for m in o.data.materials)]
    for obj in solids:
        bm=bmesh.new();bm.from_mesh(obj.data);seen=set()
        for v in bm.verts:
            if v in seen:continue
            todo=[v];seen.add(v);verts=[]
            while todo:
                q=todo.pop();verts.append(q)
                for e in q.link_edges:
                    other=e.other_vert(q)
                    if other not in seen:seen.add(other);todo.append(other)
            faces={f for v in verts for f in v.link_faces};edges={e for v in verts for e in v.link_edges}
            if not faces:continue
            solid_components+=1
            if any(not e.is_manifold for e in edges):issues.append(dict(asset=b['tag'],mesh=obj.name,error='open solid component'))
            volume=0
            for f in faces:
                coords=[v.co for v in f.verts]
                for i in range(1,len(coords)-1):volume+=coords[0].dot(coords[i].cross(coords[i+1]))/6
            if volume<-.01:issues.append(dict(asset=b['tag'],mesh=obj.name,error='inward component',volume=volume))
        bm.free()
    for emitter in [o for o in objects if any(m and 'real emission' in m.name for m in o.data.materials)]:
        hidden+=1
        assert not emitter.visible_camera and not emitter.visible_glossy,emitter.name
        # Every sampled point of the emitter must have a solid overhead cover.
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
        vertices=[];polygons=[]
        for o in solids:
            k=len(vertices);vertices.extend(tuple(o.matrix_world@v.co) for v in o.data.vertices)
            polygons.extend(tuple(k+i for i in p.vertices) for p in o.data.polygons)
        bvh=BVHTree.FromPolygons(vertices,polygons)
        for face in emitter.data.polygons:
            points=[emitter.matrix_world@emitter.data.vertices[i].co for i in face.vertices]
            center=sum(points,Vector())/len(points)
            for p in [center,*[center.lerp(p,.9) for p in points]]:
                lamp_samples+=1;hit=bvh.ray_cast(p+Vector((0,0,.005)),Vector((0,0,1)),2)
                if hit[0] is not None:roof_hits+=1
                else:issues.append(dict(asset=b['tag'],error='uncovered emitter',point=list(p)))
report=dict(solid_components=solid_components,hidden_light_assets=hidden,overhead_cover_samples=lamp_samples,
            overhead_cover_hits=roof_hits,issues=issues)
(ROOT/'city-08-enclosure-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('ENCLOSURE_AUDIT',json.dumps(report),flush=True)
assert not issues, 'Architecture enclosure or source cover failed; see city-08-enclosure-audit.json'
