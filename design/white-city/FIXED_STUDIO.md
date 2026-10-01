# 固定机位材质与灯光深化 10

**experimental / in progress。** 入口 `v17-fixed-studio.html`，环境核对可直接打开
`v17-fixed-studio.html?view=environment`。未接主站，布局与最终画质待验收。09/v16 保留。

## 本轮范围

- `blender/refine_fixed_hero.py` 从实际 `city-09-fixed.blend` 派生 10；仅修改材料、灯光与采样。
  相机矩阵与所有网格顶点/面/变换在修改前后逐项指纹检查一致；无相机动画。
  139 栋建筑、436 棵树、河道与桥的位置不变，方便把环境差异和照明差异分开判断。
- 墙体改为柔和缎面白、屋顶粉白，浅色窗洞与细金属边框独立控制粗糙度；薄玻璃与水面
  保留在 Cycles 原场景中。曝光仍为 1.75，侧向主光、背光、补光分别调整。
- 隐藏灯槽按展馆/塔楼分为 22/16 的发光强度（建模参数，不是实测灯具数据）。90 个
  发光对象继续对 camera/glossy/transmission 隐藏。源模型并未用可见发光条替代室内照明。
- 10 Cycles：2560×1441、256 samples、6 次 diffuse bounce；网页全场景 diffuse 顶点
  烘焙：128 samples、RGB 线性辐亮度 /64，以容纳局部更强的暖光。玻璃/水面在网页烘焙中
  仍为漫反射近似，不能称为完整 Cycles 输出。

## 环境对照

`fixed-review.mjs` / `fixed-review.css` 提供上下比较和可拖动分界。两幅图都只用 CSS 裁出
原图下方 44%，保持同一比例，不做重绘、局部拉伸、独立缩放或背景替换。
对照明确标注 Cycles 离线渲染；「返回真实模型」回到实际 GLB。相机不会因比较、缩放窗口
或滑块操作而移动。保留主站品牌，参考图仅作为核对资料。

当前环境差距：河湾较窄且桥/前景弧形建筑比例未对齐；近景建筑类型与裙房仍重复；
右侧坡地、左侧背景山体和连续树群缺失。这些没有因调光被标为完成。

## 验证与未采用实验

- `city-10-studio-audit.json`：139 个实际建筑基座检查，侵水 0、互相重叠 0；90 个光源
  隐藏标志通过；相机无动画；图片纹理节点 0。检查不等于逐栋复刻验收。
- `city-10-studio-plan.json` 保存几何指纹、相机不变结果及源文件 SHA-256；09 工程没有覆盖。
- 最终 GLB 24,454,260 字节，辐亮度截断通道 0；浏览器加载 9 个网格、1,565,548 个三角形，
  缺失颜色属性 0，无控制台错误/警告。间隔观察相机矩阵一致、渲染计数保持 2。
  环境上下对照、分界滑块（35%）、灯光前后与返回模型通过；v16 旧资产兼容加载通过。
  Python/JS 语法与 diff 格式检查通过；未运行与本次独立视觉原型无关的业务验收脚本。
- `--camera-bake` 的 ACTIVE_CAMERA / COMBINED 试验生成独立 `*-camera-baked.glb`，
  **未通过视觉检查，不被 v17 引用**：玻璃/窄构件仍出现黑条和错误插值。不能把该文件当作
  正式光照资产。当前入口引用 `city-10-studio-baked.glb` 的 diffuse 方案。
- 首轮试验亮度过高（城市 ROI 亮度中位数约 239），未交付该参数；降低主辅光后，最终
  统计如下。统计只衡量大范围明度与粗略暖色，不是相似度评分。

| 同一城市区域 `[.03,.78,.97,.91]` | 目标图 | 09 Cycles | 10 Cycles |
|---|---:|---:|---:|
| 亮度 P10 | 205.987 | 211.924 | 213.852 |
| 亮度中位数 | 231.209 | 233.783 | 232.209 |
| 亮度 P90 | 249.201 | 241.996 | 240.349 |
| 平均 R−B | 10.036 | 4.491 | 6.768 |

暖色和整体明度更接近，但高光上限、阴影层次与目标仍有差距。网页反射透射、移动端性能、
不同设备的色彩与主站集成均未验收。下一步需要先根据环境对照确定楼群、河湾与地形的修改，
不能仅靠曝光或继续增加建筑数量。

## 重建

```powershell
$blender='D:/tools/blender/blender-4.5.13-windows-x64/blender.exe'
& $blender -b --python design/white-city/blender/refine_fixed_hero.py
& $blender -b --python design/white-city/blender/bake_fixed_hero.py -- --studio
& $blender -b --python design/white-city/blender/verify_fixed_hero.py -- --studio
py design/white-city/blender/analyze_fixed_reference.py --studio
```

`bake_fixed_hero.py` / `verify_fixed_hero.py` / `analyze_fixed_reference.py` 无 `--studio` 时仍使用 09。
`city-fixed.mjs` 按页面声明读取资产及烘焙编码倍率；v16 默认 09，v17 使用 10。
共享四份文档按 AGENTS 集中更新节奏处理，已有画质差距仍有效。
