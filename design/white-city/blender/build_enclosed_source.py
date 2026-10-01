import bpy,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from city_enclosure import repair,palette
source=ROOT/'city-04.blend';source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(source));palette()
manifest=json.loads((ROOT/'city-04-manifest.json').read_text(encoding='utf-8'));report=[]
for b in manifest['buildings_layout']:
    if b['lod']!='near':continue
    objects=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.startswith(b['tag']+' ')]
    report.append(repair(objects[0].users_collection[0],objects,b,b['x'],b['y'],b['z']))
bpy.context.scene['stage']='08 sealed roofs and concealed cove lights; source library for realtime bake'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'city-08-source.blend'))
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
(ROOT/'city-08-enclosure.json').write_text(json.dumps(dict(source_sha256=source_hash,assets=report),indent=2),encoding='utf-8')
print('ENCLOSURE_SOURCE_READY',flush=True)
