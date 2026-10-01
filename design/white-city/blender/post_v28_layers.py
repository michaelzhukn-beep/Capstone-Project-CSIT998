"""v28 烘焙后处理(纯 Python):贴图边缘填补 + 桌面影子层合成。

    python design/white-city/blender/post_v28_layers.py

1. 贴图填补(沿用 v26 fill 的做法,修黑洞 / 黑边):
   - smart 贴图:亮度 < 100 的贴图像素视为嵌进相邻盒子的无效像素,换成最近有效像素(白城真实光照最暗约 120)。
   - screen 贴图:透明像素(对象外)用最近的不透明像素颜色外扩,避免网页双线性过滤在边缘混进黑色;alpha 置 255。
   原图备份在 bake-v28/raw/,总是从 raw 读取,可重复运行。
2. 桌面影子层 floor-shadow-city.png / floor-shadow-house.png:Cycles 影子(× .45)+ 接触阴影
   (模型轮廓下方窄深 + 宽淡两层,只加在模型下方 60 px 内),输出黑色 + alpha,网页按宽幅机位投影到桌面。
   分两组是因为网页城市视角会把户型样板整组隐藏,它们投在桌面上的影子必须跟着隐藏(见 render_v28_shadows.py)。
"""
import json, shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

BAKE = Path(__file__).resolve().parent.parent / 'bake-v28'
RAW = BAKE / 'raw'; RAW.mkdir(exist_ok=True)
manifest = json.loads((BAKE / 'manifest.json').read_text(encoding='utf-8'))

# 修细线:screen 贴图里「该像素最前面也是 screen 对象」的地方,一律换成完整画面颜色(见 render_v28_ids.py)
beauty = np.array(Image.open(BAKE / 'layer-beauty.png').convert('RGBA'))
idimg = np.array(Image.open(BAKE / 'layer-ids.png').convert('RGBA'))
ids = json.loads((BAKE / 'ids.json').read_text(encoding='utf-8'))
screen_names = {v['object'] for v in manifest.values() if v['mode'] == 'screen'}
code = idimg[..., 0].astype(np.int32) * 256 + idimg[..., 1]
screen_codes = np.array([int(k.split(',')[0]) * 256 + int(k.split(',')[1]) for k, n in ids.items() if n in screen_names])
front_is_screen = np.isin(code, screen_codes) & (idimg[..., 3] > 200)
BH, BW = code.shape

for key, info in manifest.items():
    png = BAKE / f'{key}.png'
    raw = RAW / png.name
    if not raw.exists() or png.stat().st_mtime > raw.stat().st_mtime + 1:
        shutil.copy2(png, raw)
    a = np.array(Image.open(raw).convert('RGBA'))
    if info['mode'] == 'smart':
        invalid = (a[..., :3].astype(float) @ [.2126, .7152, .0722]) < 100
    else:
        invalid = a[..., 3] < 128
        x0, y0, x1, y1 = info['box']                      # 画框比例,左下原点
        c0, c1 = int(round(x0 * BW)), int(round(x1 * BW)); r0, r1 = int(round((1 - y1) * BH)), int(round((1 - y0) * BH))
        th, tw = a.shape[:2]
        fb = np.array(Image.fromarray(beauty[r0:r1, c0:c1]).resize((tw, th), Image.NEAREST))
        fm = np.array(Image.fromarray(front_is_screen[r0:r1, c0:c1].astype(np.uint8) * 255).resize((tw, th), Image.NEAREST)) > 128
        use = fm & (fb[..., 3] > 200)
        a[use, :3] = fb[use, :3]
        invalid = invalid & ~use
    n = int(invalid.sum())
    if n and n < invalid.size:
        _, (iy, ix) = ndimage.distance_transform_edt(invalid, return_indices=True)
        a[..., :3] = a[iy, ix, :3]
    a[..., 3] = 255
    Image.fromarray(a).save(png)
    st = raw.stat(); import os; os.utime(png, (st.st_atime, st.st_mtime))
print('V28_FILL_DONE', len(manifest))

# 桌面影子:城市 / 户型分开(网页城市视角会整组隐藏户型,影子要跟着走),各自叠上接触阴影
for group in ('city', 'house'):
    m = np.array(Image.open(BAKE / f'layer-alpha-{group}.png').convert('RGBA'))[..., 3].astype(float)
    sh = np.array(Image.open(BAKE / f'layer-shadow-{group}.png').convert('RGBA'))[..., 3].astype(float) / 255
    H, W = m.shape
    k_ = W / 8192 * 2.2                      # 预览合成按 2560 px / 720 m 调的参数,换算到宽幅贴图的像素密度
    mask = Image.fromarray(m.astype(np.uint8))

    def contact(shift, radius, strength):
        img = Image.new('L', mask.size, 0); img.paste(mask, (0, int(shift * k_)))
        return np.array(img.filter(ImageFilter.GaussianBlur(radius * k_))).astype(float) / 255 * strength

    occ = np.clip(contact(3, 4, .38) + contact(10, 26, .16), 0, .6)
    solid = m > 128
    last = np.full(W, -10 ** 6); below = np.zeros((H, W))
    for r in range(H):
        last = np.where(solid[r], r, last); below[r] = r - last
    occ = occ * np.clip(1 - below / (60 * k_), 0, 1) * (below > 0)
    alpha = 1 - (1 - sh * .45) * (1 - occ)
    out = np.zeros((H, W, 4), np.uint8); out[..., 3] = (alpha.clip(0, 1) * 255).astype(np.uint8)
    Image.fromarray(out).save(BAKE / f'floor-shadow-{group}.png')
    print('V28_SHADOW_DONE', group, W, H)
