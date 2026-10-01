# 城市柔光 v23:实时 PBR 白模

**experimental。** 入口 `v23-studio.html`,渲染模块 `city-light-v23.mjs`,样式沿用 `layout-studio-v22.css`。
v21、v22 的页面、脚本、样式,以及所有 Blender 工程、GLB、烘焙数据均未改动(v21 哈希核对一致)。
v23 不再使用烘焙顶点色,改为实时 PBR:材质、主光、环境光、阴影直接建立白模质感。

## 修复前的工程记录

| 项 | 实际情况 |
|---|---|
| 渲染技术栈 / 版本 | Three.js 0.170.0(CDN importmap),GLTFLoader + DRACOLoader,EffectComposer |
| 图形接口 | WebGL 2;另有 Blender 4.5 Cycles 离线渲染用于烘焙与对照图 |
| 城市模型入口 | v21/v22 灯光:`blender/city-14-studio-baked.glb`(顶点色存光照);v21 白模对照与 v23:`blender/city-13-smooth.glb` |
| 相机配置 | `blender/city-14-studio-plan.json` 的 `composition_camera`(正交,zoom 2.778,锁定) |
| 坐标轴 / 包围盒 | 设计坐标 Z 向上,网页换成 Y 向上 `(x, z, -y)`,相机在 +Z 一侧。整个模型包围盒 x −1000…900、z −275…1200(地形前景延伸到镜头后);164 栋建筑包围盒 x −391…401、y −7.5…128、z −301…167 |
| v21 灯光 | 灯光模式无实时灯,光照全靠烘焙顶点色;白模对照为 Hemisphere 1.3 + Directional 2.5(4096 阴影) + 填光 0.55 |
| v21 材质 | 灯光模式 `MeshBasicMaterial` × 顶点色 × 16;GLB 原材质底色偏灰偏绿:凹窗面板 (0.60, 0.64, 0.63)、路面 0.66、水面偏青 |
| 环境照明 | 无 `scene.environment`,环境光只存在于烘焙数据里 |
| 阴影 | 灯光模式无实时阴影(烘焙);白模对照 PCFSoft 4096 |
| 后处理 | RenderPass → UnrealBloom(自定义加法混合) → OutputPass |
| 曝光 / 色调映射 | AgX,曝光 2^1.25;v22 改为 Neutral + 着色器内抬暗部 |
| 显示色彩空间 | sRGB,由 OutputPass 一次转换 |
| CSS 滤镜 | 画布及容器上没有 filter / opacity / 混合模式 |
| 发现的问题 | 顶点色在细三角形上被 MSAA 外推出负值(彩色噪点);顶点密度决定光照精度;原材质底色偏灰绿;暖光是着色器涂上去的,不是灯 |

## 实际采用的方案与最终参数

全部参数集中在 `city-light-v23.mjs` 顶部的 `PARAMS`,URL 参数可临时覆盖。

| 组 | 参数 |
|---|---|
| 色彩输出 | 场景线性 HDR(HalfFloat,4×MSAA)→ 选择性 Bloom 合成 → `OutputPass`(唯一一次色调映射 + sRGB)。色调映射固定 `NeutralToneMapping`,曝光 1.0 |
| 材质 | `MeshStandardMaterial`,metalness 0,无透明、无自发光。建筑 #F2F2F0 / 0.70;屋顶 #F4F4F1 / 0.74;凹窗面板 #ECECE9 / 0.66;地形 #F5F5F2 / 0.88;路面 #F0F0EC / 0.90;水面 #EDEFEE / 0.55;树冠 #F3F3F0 / 0.85;枝干 #E4E4DF / 0.85 |
| 主光 | DirectionalLight #FFFFFF,强度 2.5,位置 = 城市中心 + (0.35, 0.75, 0.45)·W(W = 791),照向城市中心 |
| 填光 | DirectionalLight #FFFFFF,强度 0.9,城市中心 + (−0.5, 0.35, 0.3)·W,放在主光对侧 |
| 环境 | `RoomEnvironment` 经 `PMREMGenerator` 生成一次,接入 `scene.environment`,`environmentIntensity` 0.9;`scene.background` 为空,背景交给页面 |
| 阴影 | 主光投影,PCFSoft,4096,阴影相机紧贴 164 栋建筑包围盒(912 × 762,约 0.22 单位/像素);bias −0.0004,normalBias 0.04 |
| AO | `GTAOPass`,混合强度 0.45,半径 2.2 |
| 暖光 A:灯片 | 8 栋靠前低层建筑一层,朝镜头立面。射线实测凹窗面板深度(0.49–1.1 m),薄灯片放在面板前 4 cm,颜色 #FFF0DC × 1.4;外框与竖梃自然遮挡 |
| 暖光 B:承光 | 3 盏 SpotLight #FFE7C8,1500 cd,距离 11,锥角 0.95,半影 0.85;檐下 2.3 m 向下照门前地面,不照上层墙面 |
| 暖光 C:辉光 | 独立 composer 只渲染灯片(其余网格临时换黑色以保留遮挡),UnrealBloom 强度 0.12、半径 0.08;只合成模糊层本身 |

### 与提示词起点不同的两处,及原因

- **主光方向改为 (0.35, 0.75, 0.45)。** 起点 (−0.35, 0.75, 0.45) 在本机位下同时正对镜头看到的两组立面,两面受光相同:小样实测顶面 250、正面 248,曝光 0.8 / 1.0 / 1.2 都只差约 4 级,不是曝光问题。换到右上前方后,朝左立面进入柔和背光,体积立住(对比图 `renders-v23/keydir-grid.png`)。
- **填光 0.9、环境 0.9,高于起点 0.35 / 0.5。** 起点下背光立面 179、桥墩 134,落到灰黑;按主光 → 环境 → 填光顺序逐项调整后,最暗 5% 为 211。

## 截图(同机位、同曝光、同画幅,1948 × 1050,见 `renders-v23/`)

| 文件 | 内容 |
|---|---|
| `01_before_v21.png` / `01_before_v22.png` | 修复前实际效果 |
| `02_neutral.png` | 中性白模,无暖光、无 Bloom |
| `03_warm_no_bloom.png` | 加灯片与承光,仍无 Bloom |
| `04_final.png` | 加轻微 Bloom |
| `closeup_02_neutral.png` / `closeup_03_warm_no_bloom.png` / `closeup_04_final.png` | 同一组建筑的近景(调试相机 `?view=sample`,只改相机) |
| `closeup-neutral-vs-final.png`、`stages-grid.png` | 对比拼图 |
| `exposure-0.8.png` / `1.0` / `1.2` | 曝光对比,其余设置一致 |
| `keydir-grid.png` | 四个主光方向对比 |

## 实测验收

- 城市局部灰度(非背景像素,5/25/50/75/95 分位):中性、暖光、最终三阶段完全一致,均为 207 / 234 / 247 / 249 / 251。受光面在 235–248 附近,背光面 207 起,无大片灰黑,最亮 251 不到 255。
- 关掉暖光:仅 1.32% 像素变化超过 5 级;暖色像素占画面 0.41%。关掉 Bloom:仅 0.96% 像素变化超过 5 级。
- 小样 AO:开 / 关 AO 时低于 150 灰度的像素均为 0,楼底没有黑圈。
- 近景:暖光只在一层窗格内,竖梃边缘清晰;门前地面局部略暖;上层墙面无光斑。
- 执行过的检查:`node --check city-light-v23.mjs`;本机 Chrome 无界面模式(GPU,ANGLE/D3D11)实际加载四个阶段与调试视图并截图;无控制台错误;v21 文件哈希核对。

## 测试环境与性能

Windows 11,RTX 5080(16 GB),Chrome 153 无界面模式,1948 × 1050,像素比 1。
模型 2,034,992 个三角形,4096 阴影贴图。页面按需渲染(静态机位,没有动画循环),静止时不持续占用 GPU。
单帧 GPU 耗时未能可靠测得(`gl.finish` 在 ANGLE 下不阻塞,读数 1 ms 不可信);JS 侧首帧约 55–77 ms。
低端 GPU、移动端、正常有界面浏览器下的观感与帧率**未验收**。

## 尚未解决

- 暖光只做了一层底部;提示词允许的高楼竖缝、桥梁边缘暖光未加(v22 的外挂灯管方案已被否定)。
- 建筑外边缘没有做极轻倒角(需要修改几何,本次未动模型)。
- 上方水纹未在本页实现;主站首页的集成未做。
- 本机内存不稳定(见 `eval/audit/BUGS.md` BUG-16),本次静态服务器与无界面浏览器各中途退出过一次,重启后结果一致。
- 用户视觉验收待确认。

## 如何只撤回本次修改

删除以下新增文件即可,其他文件未被修改:

```
design/white-city/v23-studio.html
design/white-city/city-light-v23.mjs
design/white-city/LIGHTING_V23.md
design/white-city/renders-v23/
```
