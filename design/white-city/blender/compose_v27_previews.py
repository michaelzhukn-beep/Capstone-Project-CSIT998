"""v27 沙盘预览合成(纯 Python):页面底色 + 减淡落地影 + 可选移轴 + 主页排版示意。

    python design/white-city/blender/compose_v27_previews.py

输入 renders-v27/plinth-flat.png、plinth-layered.png(Cycles,透明背景,台底阴影接收面)。
输出 renders-v27/preview-1-flat.png、preview-2-layered.png、preview-3-layered-tiltshift.png、previews-all.png。
标题 / 输入框只是平面排版位置示意,不是设计稿。
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

D = Path(__file__).resolve().parent.parent / 'renders-v27'
BG = (246, 245, 242)


def on_page(path, shadow=.35):
    a = np.array(Image.open(path).convert('RGBA')).astype(float)
    rgb, al = a[..., :3], a[..., 3:] / 255
    lum = rgb @ [.2126, .7152, .0722]
    # 阴影接收面输出的是「黑色 + 透明度」:只把这类暗且半透明/落在台外的像素减淡,模型本身不动
    shadow_px = (lum < 60)[..., None]
    al = np.where(shadow_px, al * shadow, al)
    out = rgb * al + np.array(BG) * (1 - al)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def tilt_shift(im, focus=.60, band=.16, max_r=5.5):
    """按画面纵向距离对焦带做逐级模糊(正交机位下纵向≈景深方向)。"""
    W, H = im.size
    levels = [im] + [im.filter(ImageFilter.GaussianBlur(r)) for r in np.linspace(1, max_r, 6)]
    arrs = [np.array(x).astype(float) for x in levels]
    y = np.arange(H) / H
    t = np.clip((np.abs(y - focus) - band / 2) / (.45 - band / 2), 0, 1) ** 1.3 * (len(levels) - 1)
    lo = np.floor(t).astype(int); hi = np.minimum(lo + 1, len(levels) - 1); f = (t - lo)[:, None, None]
    out = np.empty_like(arrs[0])
    for r in range(H):
        out[r] = arrs[lo[r]][r] * (1 - f[r, 0, 0]) + arrs[hi[r]][r] * f[r, 0, 0]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def layout(im, label):
    im = im.copy(); d = ImageDraw.Draw(im); W, H = im.size
    serif = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 44)
    small = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 17)
    tiny = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 14)
    d.text((W / 2, 150), 'NESTWISE · 筑明AI', font=small, fill=(128, 133, 123), anchor='mm')
    d.text((W / 2, 212), '用一句话,找到想住的城市一角', font=serif, fill=(53, 59, 52), anchor='mm')
    d.rounded_rectangle([W / 2 - 330, 262, W / 2 + 330, 318], radius=28, outline=(205, 208, 200), width=2, fill=(252, 252, 250))
    d.text((W / 2 - 300, 290), '例如:通勤 30 分钟内、安静、预算 80 万的两居室', font=small, fill=(160, 164, 156), anchor='lm')
    d.text((28, H - 30), label, font=tiny, fill=(150, 154, 146), anchor='lm')
    return im


def fade_bottom(im, start=.80):
    """白底衔接演示:画面底部 start 以下逐渐淡进页面底色。"""
    a = np.array(im).astype(float); H = a.shape[0]
    t = np.clip((np.arange(H) / H - start) / (1 - start), 0, 1) ** 1.5
    a = a * (1 - t[:, None, None]) + np.array(BG) * t[:, None, None]
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


import sys, json


def perspective_coeffs(dst, src):
    """PIL PERSPECTIVE 系数:把输出图上的四边形 dst 映射回源图矩形 src。"""
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    return np.linalg.solve(np.array(A, float), np.array(B, float)).tolist()


SIGN_TEXT = {   # 示意:正式上线前逐条用解析器验证能解析出房型
    'v28 cottage': ('独立屋', '独栋住宅 · 3 房', '带私家庭院'),
    'v28 villa': ('别墅', '安静街区 · 4 房', '100万内'),
    'v28 terrace': ('联排别墅', '近车站 · 3 房', '80万内'),
    'v28 apartment': ('公寓', '墨大周边 · 2 房', '通勤方便'),
}


def print_signs(im, signs, scale=1.0):
    """侧挂信息牌:竖版牌面 —— 青绿短横 + 房型大字 + 青绿短横 + 两行条件 + 底部「查看房源 →」。
    文字始终为深色(所有者要求字不变色);可点击的暗示靠底部箭头行,悬停效果留给网页做轻微浮起。"""
    W, H = im.size
    base = np.array(im).astype(float)
    f1 = ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc', 150); f2 = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 74)
    f3 = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 66)
    green = (47, 150, 70); ink = (34, 38, 34); soft = (88, 92, 88)
    for name, quad in signs.items():
        l1, l2, l3 = SIGN_TEXT.get(name, ('', '', ''))
        cw, ch = 780, 1240                                       # 牌面 7.8 : 12.4
        card = Image.new('RGB', (cw, ch), (255, 255, 255)); d = ImageDraw.Draw(card)
        d.rectangle([70, 150, 150, 162], fill=green)
        d.text((66, 300), l1, font=f1 if len(l1) <= 3 else ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc', 118), fill=ink, anchor='lm')
        d.rectangle([70, 430, 150, 442], fill=green)
        d.text((70, 540), l2, font=f2, fill=soft, anchor='lm')
        d.text((70, 640), l3, font=f2, fill=soft, anchor='lm')
        d.text((70, 1100), '查看房源  →', font=f3, fill=ink, anchor='lm')
        d.line([(70, 1150), (420, 1150)], fill=(150, 154, 150), width=3)
        px = [(x * W, y * H) for x, y in quad]
        dst = [px[2], px[3], px[0], px[1]]
        src = [(0, 0), (cw, 0), (cw, ch), (0, ch)]
        warped = np.array(card.transform((W, H), Image.PERSPECTIVE, perspective_coeffs(dst, src), Image.BICUBIC, fillcolor=(255, 255, 255))).astype(float) / 255
        base = base * (warped * .92 + .08)
    return Image.fromarray(base.clip(0, 255).astype(np.uint8))


def screen_tiltshift(im, focus_y, band=.24, max_r=7.0):
    """移轴:画面纵向以 focus_y 为中心的一条清晰带,上下逐渐虚化(正交机位下深度差太小,按深度虚化无效)。"""
    W, H = im.size
    levels = [np.array(im).astype(float)] + [np.array(im.filter(ImageFilter.GaussianBlur(r))).astype(float) for r in np.linspace(1, max_r, 5)]
    y = np.arange(H) / H
    t = np.clip((np.abs(y - focus_y) - band / 2) / .3, 0, 1) ** 1.4 * (len(levels) - 1)
    lo = np.floor(t).astype(int); hi = np.minimum(lo + 1, len(levels) - 1); f = t - lo
    out = np.empty_like(levels[0])
    for r in range(H):
        out[r] = levels[lo[r]][r] * (1 - f[r]) + levels[hi[r]][r] * f[r]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def depth_tiltshift(im, depth_path, focus_pts, strength=9.0, band=.05):
    """移轴景深:按深度与焦平面(销售牌处)的距离逐级模糊。"""
    dep = np.array(Image.open(depth_path).convert('L')).astype(float) / 255
    W, H = im.size
    focus = float(np.median([dep[int(y * H), int(x * W)] for x, y in focus_pts if 0 <= x < 1 and 0 <= y < 1]))
    dist = np.clip((np.abs(dep - focus) - band) / (.35 - band), 0, 1)
    dist = np.where(dep <= 0.001, np.nan, dist)                 # 背景(无模型)沿用附近的值:按行插值
    rowm = np.nanmean(np.where(np.isnan(dist), np.nan, dist), axis=1)
    dist = np.where(np.isnan(dist), np.nan_to_num(rowm, nan=0)[:, None], dist)
    levels = [np.array(im).astype(float)] + [np.array(im.filter(ImageFilter.GaussianBlur(r))).astype(float) for r in np.linspace(1.2, strength, 5)]
    t = dist * (len(levels) - 1); lo = np.floor(t).astype(int); hi = np.minimum(lo + 1, len(levels) - 1); f = (t - lo)[..., None]
    stack = np.stack(levels)
    out = np.take_along_axis(stack, lo[None, ..., None].repeat(3, -1), 0)[0] * (1 - f) + np.take_along_axis(stack, hi[None, ..., None].repeat(3, -1), 0)[0] * f
    return Image.fromarray(out.clip(0, 255).astype(np.uint8)), focus


if '--showroom' in sys.argv:
    tag = sys.argv[sys.argv.index('--showroom') + 1]
    raw = Image.open(D / f'{tag}-raw.png').convert('RGB')
    signs = json.loads((D / f'plinth-layered-{tag}-signs.json').read_text(encoding='utf-8'))
    printed = print_signs(raw, signs, scale=raw.width / 2560)
    printed.save(D / f'{tag}-signs.png')
    centers = [(sum(p[0] for p in q) / 4, sum(p[1] for p in q) / 4) for q in signs.values()]
    focus = float(np.mean([c[1] for c in centers]))
    tilt = screen_tiltshift(printed, focus)
    tilt = fade_bottom(tilt, .90); tilt.save(D / f'{tag}-showroom.png')
    print('V28_SHOWROOM', tag, 'focus', round(focus, 3)); sys.exit()

if '--final' in sys.argv:
    # 正式版:模型层 + 单独影子层分层合成(不再用亮度阈值猜影子),底部 10% 淡入页面底色
    tag = sys.argv[sys.argv.index('--final') + 1]
    m = np.array(Image.open(D / f'plinth-layered-{tag}.png').convert('RGBA')).astype(float)
    sh = np.array(Image.open(D / f'plinth-layered-{tag}-shadow.png').convert('RGBA')).astype(float)
    Hh, Ww = m.shape[:2]; bgc = np.array(BG, float)
    base = np.ones((Hh, Ww, 3)) * bgc * (1 - sh[..., 3:] / 255 * .45)
    # 接触阴影:台子贴地一圈没有暗部会显得悬空。取模型轮廓往下错开几个像素后模糊,
    # 一层窄而深(贴地线)+ 一层宽而淡(柔光晕),只作用在模型外的地面上
    k_ = Ww / 2560
    mask = Image.fromarray(m[..., 3].astype(np.uint8))
    def contact(shift, radius, strength):
        sh_img = Image.new('L', mask.size, 0); sh_img.paste(mask, (0, int(shift * k_)))
        return np.array(sh_img.filter(ImageFilter.GaussianBlur(radius * k_))).astype(float) / 255 * strength
    occ = np.clip(contact(3, 4, .38) + contact(10, 26, .16), 0, .6)
    # 只加在模型下方:逐行记录每列「上方最近的模型像素」距离,距离 0–60 px 内才有接触阴影
    # (每列取最低模型像素的做法在斜边上逐列跳变,底边出现一排细锯齿;不限制则小山 / 塔楼上缘出现灰边)
    solid = m[..., 3] > 128
    last = np.full(Ww, -10 ** 6); below = np.zeros((Hh, Ww))
    for r in range(Hh):
        last = np.where(solid[r], r, last)
        below[r] = r - last
    reach = 60 * k_
    occ = occ * np.clip(1 - below / reach, 0, 1) * (below > 0)
    occ = np.array(Image.fromarray((occ * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5 * k_))).astype(float) / 255
    base = base * (1 - occ[..., None])
    al = m[..., 3:] / 255; out = m[..., :3] * al + base * (1 - al)
    Image.fromarray(out.clip(0, 255).astype(np.uint8)).save(D / f'{tag}-raw.png')
    faded = fade_bottom(Image.fromarray(out.clip(0, 255).astype(np.uint8)), .90)
    faded.save(D / f'{tag}-page-nolayout.png')
    k = Ww / 1920; im = faded.copy(); d = ImageDraw.Draw(im)
    serif = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', int(44 * k)); small = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', int(17 * k))
    d.text((Ww / 2, 150 * k), 'NESTWISE · 筑明AI', font=small, fill=(128, 133, 123), anchor='mm')
    d.text((Ww / 2, 212 * k), '用一句话,找到想住的城市一角', font=serif, fill=(53, 59, 52), anchor='mm')
    d.rounded_rectangle([Ww / 2 - 330 * k, 262 * k, Ww / 2 + 330 * k, 318 * k], radius=int(28 * k), outline=(205, 208, 200), width=2, fill=(252, 252, 250))
    d.text((Ww / 2 - 300 * k, 290 * k), '例如:通勤 30 分钟内、安静、预算 80 万的两居室', font=small, fill=(160, 164, 156), anchor='lm')
    im.save(D / f'{tag}-page.png')
    print('V27_FINAL_COMPOSED', tag); sys.exit()
import sys
if '--near' in sys.argv:
    specs = [('A', '近景 A · 俯角 10° · 画框宽 520 m', False), ('B', '近景 B · 俯角 15° · 画框宽 620 m', False),
             ('B', '近景 B + 台身下缘淡入白底', True), ('C', '近景 C · 俯角 20° · 画框宽 720 m', False)]
    outs = []
    for tag, label, fade in specs:
        im = on_page(D / f'plinth-layered-{tag}.png')
        if fade:
            im = fade_bottom(im)
        outs.append((f'near-{tag}{"-fade" if fade else ""}.png', layout(im, label)))
    for name, im in outs:
        im.save(D / name)
    W, H = outs[0][1].size
    sheet = Image.new('RGB', (W, H * len(outs) + 10 * len(outs)), (255, 255, 255))
    for k, (_, im) in enumerate(outs):
        sheet.paste(im, (0, k * (H + 10)))
    sheet.resize((W // 2, sheet.height // 2), Image.LANCZOS).save(D / 'near-all.png')
    print('V27_NEAR', [n for n, _ in outs]); sys.exit()

flat = on_page(D / 'plinth-flat.png')
layered = on_page(D / 'plinth-layered.png')
tilt = tilt_shift(layered)
outs = [('preview-1-flat.png', layout(flat, '方案 1 · 薄台面 + 底座')),
        ('preview-2-layered.png', layout(layered, '方案 2 · 等高线层叠剖面 + 树脂水体')),
        ('preview-3-layered-tiltshift.png', layout(tilt, '方案 3 · 方案 2 + 移轴景深'))]
for name, im in outs:
    im.save(D / name)
W, H = outs[0][1].size
sheet = Image.new('RGB', (W, H * 3 + 20), (255, 255, 255))
for k, (_, im) in enumerate(outs):
    sheet.paste(im, (0, k * (H + 10)))
sheet.resize((W // 2, (H * 3 + 20) // 2), Image.LANCZOS).save(D / 'previews-all.png')
print('V27_COMPOSED', [n for n, _ in outs])
