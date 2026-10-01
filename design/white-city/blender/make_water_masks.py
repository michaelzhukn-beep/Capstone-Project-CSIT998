"""从烘焙贴图里提取水面遮罩,供网页给水面单独调色(不改 GLB、不重烘)。

    python design/white-city/blender/make_water_masks.py

为什么不重烘:河面颜色是所有者按效果图定的「青绿」,只是调色问题。烘焙贴图里水面与地面在
亮度上差别很小,但水面带一点青(蓝、绿都比红高 3~14),而台座与河道这两张贴图里除了水
没有别的偏青像素(遮罩检查见 LIGHTING_V24_EXPERIMENTS.md 实验 18)。所以按颜色取遮罩,
再平滑去掉抖动噪点,存成与原贴图同尺寸的灰度 PNG,网页用同一套 UV 采样。
输出:app/web/showroom/water-mask-plinth.png、water-mask-river.png
"""
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[3]
GLB = ROOT / 'app/web/showroom/city-v26-baked.glb'
OUT = ROOT / 'app/web/showroom'
OBJECTS = {'plinth': 'v26 baked v27_plinth', 'river': 'v26 baked 13_Continuous_river'}


def glb_textures(path):
    b = path.read_bytes()
    n = struct.unpack('<I', b[12:16])[0]
    doc = json.loads(b[20:20 + n])
    off = 20 + n
    blob = b[off + 8:off + 8 + struct.unpack('<I', b[off:off + 4])[0]]

    def image(material):
        m = next(x for x in doc['materials'] if x['name'] == material)
        slot = m.get('pbrMetallicRoughness', {}).get('baseColorTexture') or m['emissiveTexture']
        tex = doc['textures'][slot['index']]
        src = tex.get('source', tex.get('extensions', {}).get('EXT_texture_webp', {}).get('source'))
        view = doc['bufferViews'][doc['images'][src]['bufferView']]
        start = view.get('byteOffset', 0)
        return Image.open(io.BytesIO(blob[start:start + view['byteLength']])).convert('RGB')
    return image


def section_band(a):
    """台座前方的水体截面(树脂):灰偏绿、红蓝接近,按颜色挑不进上面的"偏青"范围。
    它是一整条连续的带,所以取颜色相符像素里最大的连通块,零散的灰色阴影不会进来。"""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lum = a.mean(-1)
    cand = (lum >= 125) & (lum <= 172) & (g - r >= -3) & (g - r <= 8) & (b - r >= -12) & (b <= g + 2)
    cand = ndimage.binary_closing(cand, iterations=2)
    labels, n = ndimage.label(cand)
    if not n:
        return np.zeros(cand.shape, bool)
    sizes = ndimage.sum(cand, labels, range(1, n + 1))
    return labels == (int(np.argmax(sizes)) + 1)


def water_mask(rgb, with_section=False):
    a = np.asarray(rgb).astype(np.float32)
    cool = np.minimum(a[..., 1], a[..., 2]) - a[..., 0]
    raw = (cool >= 3) & (cool <= 14)                       # 水面偏青的范围;全黑的遮挡区 cool=0,不会进来
    if with_section:
        raw |= section_band(a)
    solid = ndimage.uniform_filter(raw.astype(np.float32), 9) > .5   # 贴图有抖动噪点,按邻域多数决
    solid = ndimage.binary_opening(solid, iterations=2)    # 去掉孤立小点
    # 水里有建筑灯光的倒影(偏暖,不在"偏青"范围内),截面带中间也有一条接缝:不补会成为白洞/暗线
    solid = ndimage.binary_closing(solid, iterations=8)
    solid = ndimage.binary_fill_holes(solid)
    soft = ndimage.gaussian_filter(solid.astype(np.float32), 1.2)    # 边缘羽化,避免调色出锯齿
    return Image.fromarray((np.clip(soft, 0, 1) * 255).astype(np.uint8), 'L')


if __name__ == '__main__':
    image = glb_textures(GLB)
    for key, material in OBJECTS.items():
        mask = water_mask(image(material), with_section=key == 'plinth')
        dst = OUT / f'water-mask-{key}.png'
        mask.save(dst, optimize=True)
        cover = (np.asarray(mask) > 127).mean() * 100
        print(f'{dst.name}: {mask.size[0]}x{mask.size[1]}, water {cover:.1f}%, {dst.stat().st_size // 1024} KB')
