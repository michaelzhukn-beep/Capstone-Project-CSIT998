"""Read-only source diagnostic: compare facade bake proxy locations/normals."""
from pathlib import Path
script = Path(__file__).with_name('bake_layout_studio.py')
exec(compile(script.read_text(encoding='utf-8').split('start = time.time()')[0], str(script), 'exec'))
scene.cycles.samples = 32
choices = [ob for ob in grouped['04 Buildings'] if ob.get('kind') in ('office','tower_frame','tower_crown')]
chosen = sorted(choices, key=lambda ob: -ob.get('h',0))[:2]
print('PROBE_OBJECTS', [o.name for o in chosen], flush=True)
bpy.ops.object.select_all(action='DESELECT')
for ob in chosen: ob.select_set(True)
bpy.context.view_layer.objects.active=chosen[0]
bpy.ops.object.convert(target='MESH');bpy.ops.object.join()
target=bpy.context.object
bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
subdivide_visible(target,'04 Buildings')
reports=[]
for label,args in [('original',{'inset_limit':.26,'inset_distance':.16,'normal_offset':.012}),
                   ('flat_normals',{'inset_limit':.26,'inset_distance':.16,'normal_offset':.012,'preserve_normals':False}),
                   ('inset_large',{'inset_limit':.45,'inset_distance':.42,'normal_offset':.045}),
                   ('outward',{'inset_limit':.45,'inset_distance':.42,'normal_offset':.26})]:
    rgb,report=bake_layer(target,repair_visibility=False,**args)
    report['variant']=label
    reports.append(report)
    np.save(ROOT/f'probe-layout-{label}.npy',rgb)
    print('PROBE_RESULT',label,json.dumps(report),flush=True)
(ROOT/'probe-layout-bake.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==source_hash
print('PROBE_COMPLETE',flush=True)
