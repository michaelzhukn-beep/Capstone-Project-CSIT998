# 真实城市模型

**当前入口 `../v20-layout.html`，13 布局修正版待验收。** 补充视图驱动的连续坡地、非等宽河湾、完整长弧桥及混合街坊；164 栋建筑、21 个重点建筑、1,394 棵树。`city-13-layout.blend` 逐栋可编辑，GLB 供四向/自由检查；实际网格审计 PASS。当前只确认几何，后续材质和灯光待模型确认。重建、验证与相似度边界见 `../LAYOUT_REFINEMENT.md`。

**12 保留入口 `../v19-master.html`。** 四视图完整白模的上一版，124 栋建筑、2 座桥；工程 `city-12-master.blend`、GLB 与检查图未改动，记录见 `../MASTER_MODEL.md`。09–11 固定机位实验保留，入口见上级 README。

**08 保留入口 `../v15-enclosed.html`。** 08 补屋顶厚度和端封板、修正法线、用带挡边的隐藏灯槽替代悬空灯板，并提亮 Cycles 全景。`city-08-source.blend`、`city-08-assets.glb` 与 `city-08-enclosed.blend` 分别为修复源库、实时资产和完整街区。原布局与机位不变；复现和审计见 `../ENCLOSURE.md`，尚未接入主站。

**07 对照入口 `../v14-studio.html`。** 07 保留 06 布局与相机，增加独立资产 Cycles 局部光照烘焙、35 建筑自身遮蔽与地面白底收边；WebGL 和 Cycles 均移除旧深度雾。`city-07-assets.glb` 为实时光照资产，`city-07-studio.blend` 为可编辑离线参考，仍是 experimental。复现、参数与验证见 `../STUDIO.md`。

**06 对照入口为 `../v13-districts.html`。** `city-06-districts.blend` 从 05 工程中的真实建筑资产生成，使用网页导出的相同街区布局、地形和参考机位，含 636 栋建筑、1,175 棵树，2560×1415 / 128 samples Cycles 全景。`export_district_plan.mjs` → `city-06-plan.json` → `render_districts.py` 可重建；源 05 哈希保持不变。新布局、侧向光照、验证和网页/离线差异见 `../DISTRICTS.md`。06 为待视觉验收的原型。

**05 对照入口为 `../v12-lighting.html`。** 05 保留 04 的全部几何，派生柔化面光、室内暖光与按参考图拟合的机位；工程 `city-05.blend`、同机位 Cycles 远近景保留。完整机位约束、命令、验证与画质边界见 `../LIGHTING.md`。下方 04 是保留的建筑资产与布局基准。

**in progress：03 保留为继续深化的基准；04 减少近景重复，新增真实建筑资产导出和连续街区巡游。04 视觉待验收，尚未接入主站。**

## 保留版本 04

入口：`http://127.0.0.1:8765/v11-continuous.html`。切换 03 / 04 对比真实模型或同主机位 Cycles 远近景。「持续巡游」基于 04 资产另行生成连续河岸，机制和边界见 `../STREAMING.md`。

- `build_city.py --curated` 调用 `city_composition.py`，对附近 110m 内的相同类型施加选择惩罚；保持 03 的有效地块、河岸/桥头排除与主相机。近景相距 65m 内的同型建筑从 03 的 3 对降至 0 对。
- 15 类建筑轮廓：在原 8 类基础上增加柱廊、折顶展厅、开敞庭院展馆、双体塔楼、转角楼、单侧退台和锯齿屋顶。仍为 150 栋、近/中/远 35/54/61；不是靠增加每栋面数来掩盖重复。
- `city-04.blend`、`city-04.glb`（6,910,656 字节，301 个网格定义，0 图片）和全景/近景/俯视渲染已生成；主日光、相机、曝光和室内灯参数与 02 检查一致。局部遮挡/反射会随新几何改变，不能把画面像素说成完全不变。
- `export_city_assets.py` 生成 `city-04-assets.glb`（3,407,528 字节）及 JSON：35 栋近景建筑和 3 个树木原型，局部坐标、真实包围盒、同材质子网格供实例复用。导出不修改保存的 Blender 工程。
- `layout-verification-city-04.json` PASS：无建筑侵水、无桥头占用、无建筑互相重叠；Python/JS 语法、GLB 结构与巡游布局脚本检查通过。04 视觉验收、实时巡游的 Cycles 级光照及主站集成未完成。

重建 04（在项目根目录）：

```powershell
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/build_city.py -- --name city-04 --refine --diverse --curated
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b design/white-city/blender/city-04.blend --python design/white-city/blender/inspect_and_export.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b design/white-city/blender/city-04.blend --python design/white-city/blender/export_city_assets.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/verify_city_layout.py -- city-04
node tests/test_city_stream.mjs
```

`--curated` 禁止覆盖 01/02/03。静态主相机的旧 8 米关键帧仍仅供草稿使用；持续巡游由网页街区系统实现，不能把该短镜头动画误当作无尽城市。

## 保留的基准 03

入口：`http://127.0.0.1:8765/v10-diversity.html`。默认加载可旋转的真实 `city-03.glb`；02 / 03 切换保留视角。提供全景、河岸、俯视机位，以及 Cycles 全景/近景对照。01、02 的工程、GLB 和渲染均保留。

- **完整占地校验**：`city_layout.py` 对建筑主体及外伸构件预留 3.5m，避开河道、沿岸步道、桥头通道和其他地块。前景建筑迁移至最近有效地块，背景候选位置不合法则跳过。桥面两端按实际岸高接地，树木与矮植被避开桥头。
- **真实建筑类型**：`city_typologies.py` 增加圆形住宅塔楼、不对称退台塔楼、U 形庭院、横向板楼和成组坡顶住宅，保留原塔楼、台阶式建筑与暖光展馆。狭长玻璃窗、白色实体和楼板保持白模基调。
- **按主机位分配细节**：150 栋中近景 35、中景 54、远景 61。近景保留入口、栏杆、倒角等细节；中景保留主要立面节奏；远景以简单体块和轮廓填充。远处树木也使用简化实例。这里是制作时分级，**不是随旋转镜头动态切换的 LOD**；自由放大远景会看到简化模型。
- **保持认可的光照方向**：主机位、镜头、投影偏移、日光、曝光和色彩管理沿用 02。展馆迁移时室内灯跟随移动，功率、色温与面积不变。没有引入参考图片作为模型纹理。
- `city-03.blend`：可编辑完整场景；`city-03.glb`：8,247,876 字节，334 个网格定义、0 个图片资产（实例复用后页面中有更多网格对象）。02 GLB 为 24,601,276 字节。仅建筑网格三角形从 410,112 降至 103,564，约减少 75%；这不是整场景含树木/地形的三角形统计。
- `renders/city-03.png`：2560×1440、128 samples；`renders/waterfront-detail-city-03.png`：1600×1000、64 samples。`renders/layout-city-03.png`：1600×1200 俯视检查图，仅此检查图关闭主机位距离雾，避免俯视高度使场景被雾遮住；不修改工程中的全景合成设置。
- `city-03-manifest.json` 保存每栋建筑的布局、类型、细节级别和迁移；`verification-city-03.json` 保存导出统计。

### 验证与继续工作

`verify_city_layout.py` 读取实际模型包围范围与河流网格，用独立的线段相交/包含判断验证，不调用布置算法的 SAT。`layout-verification.json` 为 PASS：02 检出 8 组侵水、1 组占桥头、2 对建筑重叠；03 三项均为 0。主机位、日光变换/能量/颜色、室内灯功率/颜色/尺寸和曝光对比通过；无图片纹理节点。

Python/JS 语法、GLB 结构与 Git 空白检查通过。桌面浏览器确认 02 / 03 加载、俯视机位及 Cycles 样张。自检通过不等于视觉验收。03 已保留为 04 的对照基准，当前验收与剩余工作见顶部 04 段落；继续动画/网页渲染集成；Cycles 光照仍未烘焙进 WebGL 模型，实时页目前用于几何检查。

构建、渲染与检查 03：

```powershell
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/build_city.py -- --name city-03 --refine --diverse
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b design/white-city/blender/city-03.blend --python design/white-city/blender/inspect_and_export.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/verify_city_layout.py
```

`--diverse` 必须同时提供 `--refine`，并禁止命名为 `city-01` / `city-02`，以免覆盖基准。`--draft` 可低采样迭代；省略则完整渲染。

## 保留的细节基准 02

入口：`http://127.0.0.1:8765/v9-refined.html`。切换 01 / 02 保持机位，比较同机位 Cycles 近景和全景。02 的精细度和光照已认可，历史侵水/桥头问题保留用于与 03 做回归对照。

- `city-02.blend` / `city-02.glb`：73 栋建筑布局保留；新增阳台细栏杆、部分塔楼立面节奏和入口雨棚、20 处屋顶廊架、8 处展馆天窗开口与室内陈设、22 处入口台阶、18 组沿河座椅、451 组低矮植被。原有 711 棵树位置保留，树冠略收拢、加厚。
- `city_details.py`：独立细化模块，由 `build_city.py --name city-02 --refine` 调用。仅真实网格与实例，不添加或调亮灯具；天窗在屋面实体中留洞。
- `renders/city-02.png`：2560×1440、128 samples 全景；`renders/waterfront-detail-city-02.png`：1600×1000、64 samples 近景。
- `verify_refinement.py` / `refinement-verification.json`：核对两版相机位置/镜头、全部灯光参数、环境光、原有材质、曝光、建筑边界和树木位置一致。GLB 约 24.6MB，344 个网格定义、0 个图片资产。
- 实时检查页修正斜视时的阴影条纹；WebGL 仍是几何检查，Cycles 光照尚未烘焙进网页模型。动画、移动端性能与主站接入不在本轮完成范围内。
- 验证：Blender 对比检查 PASS，Python/JS 语法与 Git 空白检查通过；桌面浏览器验证 01/02 网格切换、机位、线框、远近景渲染加载，未出现控制台错误。此轮旧检查只验证保留基线与细化一致，未覆盖河道占用；03 已补上独立布局回归检查。

构建、渲染与检查 02：

```powershell
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/build_city.py -- --name city-02 --refine
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b design/white-city/blender/city-02.blend --python design/white-city/blender/inspect_and_export.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/verify_refinement.py
```

加 `--draft` 可低采样迭代；默认完整渲染。细化模式禁止以 `city-01` 命名，避免覆盖已认可的基准。

## 参考边界

已认可的 `../assets/city-still-01.png` 只用于指导构图、材质与灯光。
最终制作必须以真实模型和渲染为基础，不能用该图片的位移/缩放代替。

## 基准 01 文件

- `city-01.blend`：可编辑 Blender 场景，保留建筑倒角、玻璃、树木实例、实际灯光和三台相机。
- `build_city.py`：确定性建模脚本，生成建筑/地形/河道/桥梁/植物，不加载参考图片作为纹理。
- `renders/city-01.png`：2560×1440、128 samples 的 Cycles 实际渲染；非 AI 生成结果。
- `renders/waterfront-detail.png`：同一模型的另一台相机，1600×1000、64 samples，检查近景几何。
- `city-01.glb`：约 22MB 的真实几何检查文件；仅导出时省去倒角修改器，完整倒角仍在 `.blend`。
- `inspect_and_export.py`：近景渲染、GLB 导出与几何检查。
- `scene-manifest.json` / `verification.json`：实际构建参数与核验结果。

查看 `http://127.0.0.1:8765/v8-model.html`。默认加载可旋转模型，按钮可切换实际渲染、近景和目标参考。
WebGL 视图用于几何检查，未烘焙 Cycles 光照，不能视为最终网页渲染质量。

## 重建

本机使用便携版 Blender 4.5.13 LTS，路径：
`D:/tools/blender/blender-4.5.13-windows-x64/blender.exe`。
从 Blender 官方下载目录取得，ZIP SHA256 已与官方清单核对：
`b5fdf800ce65fa2f209e8f68d02667e4d720fa1c42f247c72d1882ab04decba6`。

在项目根目录运行：

```powershell
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/build_city.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b design/white-city/blender/city-01.blend --python design/white-city/blender/inspect_and_export.py
```

其他机器替换 Blender 可执行路径。`-- --draft` 生成低采样草稿；`-- --no-render` 仅建模；`-- --cpu` 不启用 OptiX。
当前在 RTX 5080 上使用 OptiX 渲染。主相机保存了 1–240 帧的实际位置关键帧，但未制作最终动画序列。

## 验证与剩余工作

- 已验证：场景保存、Cycles GPU 渲染、另一台相机渲染、有效树冠面片、无图片纹理节点、GLB 导出。
- 模型检查页已验证加载、拖动旋转、线框切换、远景/近景/参考切换，浏览器无错误；GLB 头部与长度有效，包含 184 个网格定义、0 个图片资产。原图并未变成模型中的平面、环境贴图或投影纹理。
- 未完成：04 视觉验收、巡游最终光照与主站集成；此前版本的认可不代表这些工作已完成。
- v7 图片微动路线已否决，不能继续作为实际建模/渲染任务的替代交付。
