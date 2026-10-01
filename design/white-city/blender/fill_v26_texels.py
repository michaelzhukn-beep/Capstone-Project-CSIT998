"""v26 烘焙贴图修补:把接近纯黑的无效像素换成最近的有效像素颜色(纯 Python,不需要 Blender)。

    python design/white-city/blender/fill_v26_texels.py [--threshold 60] [--threshold-building 100]

原因(实验 13):楼由相交的盒子组成,面嵌进别的盒子里的那一截烘焙是黑的;贴图分辨率有限,交界处 1–2 个
贴图像素的黑色会渗到可见部分,网页上鳍片根部出现黑条 / 黑洞。图块之间未烘焙的空白也是黑的,过滤时会被混进来。
白色城市在真实光照下不会出现接近纯黑的颜色(Cycles 画面最暗约 100 级以上),所以亮度低于阈值的像素一律视为无效。

首次运行把原始烘焙图备份到 bake-v26/raw/,之后从 raw/ 读取、写回 bake-v26/,可反复调阈值;
重烘覆盖过的图(比 raw 新)会先重新备份。
"""
import os, sys, shutil
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

BAKE = Path(__file__).resolve().parent.parent / 'bake-v26'
RAW = BAKE / 'raw'
RAW.mkdir(exist_ok=True)
thr = float(sys.argv[sys.argv.index('--threshold') + 1]) if '--threshold' in sys.argv else 60
skip = {'trees-2x.png'}
thr_b = float(sys.argv[sys.argv.index('--threshold-building') + 1]) if '--threshold-building' in sys.argv else 100

total = 0
for png in sorted(BAKE.glob('*.png')):
    if png.name in skip:
        continue
    raw = RAW / png.name
    if not raw.exists() or png.stat().st_mtime > raw.stat().st_mtime + 1:   # 新烘焙覆盖过的图重新备份
        shutil.copy2(png, raw)
    a = np.array(Image.open(raw).convert('RGBA'))
    lum = a[..., :3].astype(float) @ [.2126, .7152, .0722]
    # 楼 / 地灯(独立 UV)用更高阈值 thr_b:面嵌进相邻盒子的那一截常是 70–100 的深灰,不是纯黑;
    # 地形 / 道路等投影 UV 贴图保持 thr,避免误伤真实的楼间阴影
    invalid = lum < (thr_b if (png.name.startswith('B') or 'lamps' in png.name) else thr)
    n = int(invalid.sum())
    if n and n < invalid.size:
        _, (iy, ix) = ndimage.distance_transform_edt(invalid, return_indices=True)
        a[..., :3] = a[iy, ix, :3]
    Image.fromarray(a).save(png, optimize=False)
    st = raw.stat(); os.utime(png, (st.st_atime, st.st_mtime))          # 与 raw 同时间,避免下次被误当成新烘焙结果
    total += n
    print(f'{png.name:48s} invalid {n / invalid.size * 100:5.1f}%')
print('V26_FILL_DONE threshold', thr, 'building', thr_b, 'texels replaced', total)
