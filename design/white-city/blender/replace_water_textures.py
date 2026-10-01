"""把水面重烘结果接入现有 GLB,逐字节保留几何和其他贴图。

Blender 全量导出会重排部分 Draco 数据;本轮只换水材质,不发布那些无关变化。
先跑 water_material_v28 / bake_v28_showroom / render_v28_ids / post_v28_layers /
export_v26_web,再运行:
    python replace_water_textures.py --source <新导出.glb> --target <主站.glb>

只接受相同节点、访问器与水网格的两份模型;几何/UV 改动必须走完整导出流程。
"""
import argparse
import copy
import json
import struct
from pathlib import Path

WATER = {'v27_plinth', '13_Continuous_river'}


def read(path):
    data = path.read_bytes()
    magic, version, total = struct.unpack_from('<III', data)
    assert (magic, version, total) == (0x46546C67, 2, len(data)), 'Invalid GLB'
    size, kind = struct.unpack_from('<II', data, 12)
    assert kind == 0x4E4F534A
    doc = json.loads(data[20:20 + size])
    size_bin, kind = struct.unpack_from('<II', data, 20 + size)
    assert kind == 0x004E4942 and len(doc['buffers']) == 1
    return doc, data[28 + size:28 + size + size_bin]


def view(doc, binary, index):
    item = doc['bufferViews'][index]
    assert item.get('buffer', 0) == 0
    start = item.get('byteOffset', 0)
    return binary[start:start + item['byteLength']]


def replace(source, target):
    old, old_bin = read(target)
    new, new_bin = read(source)
    for key in ('nodes', 'scenes', 'accessors'):
        assert old[key] == new[key], f'{key} differs; full export required'
    for mesh, baked in zip(old['meshes'], new['meshes'], strict=True):
        if mesh['name'].replace(' ', '_') not in WATER:
            continue
        for a, b in zip(mesh['primitives'], baked['primitives'], strict=True):
            ext = 'KHR_draco_mesh_compression'
            assert view(old, old_bin, a['extensions'][ext]['bufferView']) == view(
                new, new_bin, b['extensions'][ext]['bufferView']), 'Water geometry/UV changed'
    old_images = {i['name']: i for i in old['images']}
    new_images = {i['name']: i for i in new['images']}
    patches = {}
    for name in WATER:
        a, b = old_images[name], new_images[name]
        assert a['mimeType'] == b['mimeType']
        patches[a['bufferView']] = view(new, new_bin, b['bufferView'])
    result = copy.deepcopy(old)
    binary = bytearray()
    for index, item in enumerate(result['bufferViews']):
        binary.extend(b'\0' * (-len(binary) % 4))
        payload = patches.get(index, view(old, old_bin, index))
        item['byteOffset'], item['byteLength'] = len(binary), len(payload)
        binary.extend(payload)
    result['buffers'][0]['byteLength'] = len(binary)
    binary.extend(b'\0' * (-len(binary) % 4))
    header = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    header += b' ' * (-len(header) % 4)
    output = (struct.pack('<III', 0x46546C67, 2, 28 + len(header) + len(binary))
              + struct.pack('<II', len(header), 0x4E4F534A) + header
              + struct.pack('<II', len(binary), 0x004E4942) + binary)
    temporary = target.with_suffix('.water.tmp')
    temporary.write_bytes(output)
    actual, actual_bin = read(temporary)
    for index in range(len(old['bufferViews'])):
        expected = patches.get(index, view(old, old_bin, index))
        assert view(actual, actual_bin, index) == expected, 'Writeback verification failed'
    temporary.replace(target)
    print('Replaced water textures:', ', '.join(sorted(WATER)))
    print('Preserved all geometry, transforms and other textures byte-for-byte.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    replace(args.source, args.target)
