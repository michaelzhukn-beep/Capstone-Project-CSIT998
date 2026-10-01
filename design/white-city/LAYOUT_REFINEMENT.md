# 城市布局修正版 13

**experimental / 保留的布局检查基准。** 本文记录 `v20-layout.html` 的完整三维
模型、地形、道路与体块。当前工作已进入 `v21-studio.html` 固定机位灯光校准：
最终机位来自确认后的浏览器当前视角；13-smooth 平滑岸边后派生 14 灯光工程，
其余几何保持不变。新文件、复现、已验证与待验证边界见 [LAYOUT_STUDIO.md](LAYOUT_STUDIO.md)。未接主站。

## 当前前景收边与选定机位

`v20-layout.html?view=camera` 当前使用 `city-13-shore.blend` / `city-13-shore.glb`。
从湖面扩展工程局部派生：旧前景裁切线外增加封闭连续地形，接缝标高沿用原地形，
向外平滑降低至 0.65，并延伸至镜头后方（前方范围到 y=-1200）。原竖直底座被地形
包住，湖面保留在真实坡面之间；删除南岸在旧裁切边缘形成的细长岸墙末端。
建筑、桥梁、植被、原地形、水面、材质、灯光及全部相机保持原样。

重建：`py design/white-city/blender/plan_layout_shore.py`（NumPy / SciPy / Shapely），
Blender `-b --python design/white-city/blender/build_layout_shore.py`，再运行
Blender `-b --python design/white-city/blender/audit_city_layout.py -- --shore`。
导出指纹确认 1,568 个既有非岸墙网格及变换未变、所有机位未变；新坡面封闭。
`city-13-shore-audit.json` PASS：180 个独立网格无开口，建筑侵水/占路/重叠均为零。
浏览器已核对固定构图及桥梁俯视：原前景台座切面被覆盖、白色长尖刺已移除。
原布局及湖面扩展工程保留。坡面视觉仍待验收，未进入最终材质灯光。
当前源工程 SHA256：`ea11bfbcfb2fbfa9b81bf8f744204ea697ac0c48944f0686aa70def9d6cc95cb`。

### 保留的湖面扩展基准

前一轮基准为 `city-13-lake.blend` / `city-13-lake.glb`。
由原 13 工程局部派生：只向镜头前方延伸实体水面，水位仍为 0；原陆地、岸线、桥梁、
建筑与植被不变。`city-13-lake-plan.json` 保存从自由检查选定的正交机位、目标、缩放和
取景宽度；网页固定机位与 Blender 中 `13 Selected composition` 使用相同构图。

重建：依次运行 `py design/white-city/blender/plan_layout_lake.py`、Blender
`-b --python design/white-city/blender/build_layout_lake.py`，再运行 Blender
`-b --python design/white-city/blender/audit_city_layout.py -- --lake`。
原 13 `.blend` / `.glb` 保留。导出核对 1,568 个非水面网格及变换未改动；
`city-13-lake-audit.json` 实际源工程审计 PASS，未发现开口、建筑侵水或占路。
浏览器已核对选定构图、前景露底覆盖，灯光与材质未调整。湖面外延用于这个取景，
不是完整湖岸的测绘还原；远离该机位的完整水域边界尚未作为最终场景验收。
源工程 SHA256：`6c398e994acbf1bd84805bd2ed48572f65e6c1d811369d139469c9e9a3311403`。
下方为保留的 13 布局基准及其原检查结果。

## 对照与修改

依据原始四视图、八幅补充视角和桥梁局部（`assets/city-*-reference.png`），统一为
一套世界坐标模型。不同参考的透视和比例并不完全一致，不将图中比例尺当作实测尺寸。

- **主桥与河湾**：上一版桥只保留左侧弧段；现在西南起桥、向北回弯，再完整延伸到
  东南方向接入右岸。桥后保持连续水带，桥前展开较大水湾；两岸分别描线，取消等宽河道。
  桥面、护栏、桥墩和两侧桥头为实体，桥墩接至河床以下。
- **地形与道路**：取消矩形底板上叠放独立圆山的形态。西北丘陵、西南坡地、东侧
  抬升共用连续地形；山麓道、中央道、滨水道与横向连接路随地形和河岸弯曲。
- **建筑高低**：164 栋建筑、21 个重点建筑。西侧低层街坊、中央地标及周围中层、
  东侧高层和次高层形成过渡；最高建筑集中在东部。两座主塔保留竖向主体和小型顶部退台。
- **地块与植被**：临街建筑混合窄面住宅与横向低层展馆，朝向跟随道路；不再沿全局
  等间距网格排布。1,394 棵树以滨水林带、街坊空隙和山脚树群填充，避开建筑、道路和桥。

## 文件与重建

| 文件 | 用途 |
|---|---|
| `blender/plan_city_layout.py` | 总平面、曲线、街区布置与独立占地校验 |
| `blender/layout_terrain.py` | 规划和 Blender 共用的连续地形高度计算 |
| `blender/city-13-layout-plan.json` | 布局、轮廓、标高、参考记录、规划检查与相机 |
| `blender/build_city_layout.py` | 建立封闭实体、导出 GLB 和六张中性 Cycles 检查图 |
| `blender/city-13-layout.blend` | 逐栋可编辑源工程，含九个固定检查相机 |
| `blender/city-13-layout.glb` | 网页同一模型；9,624,468 字节、12 材质子网格、1,992,528 三角形 |
| `blender/audit_city_layout.py` | 重新打开保存的工程，检查实际网格与占地 |
| `blender/city-13-audit.json`、`city-13-export.json` | 检查结果与源工程 SHA256 |
| `blender/renders/city-13-*.png` | 上/前/左/右/总览/桥梁的真实模型检查图，1600×1100、透明背景 |
| `v20-layout.html`、`city-layout.mjs` | 四视图、手动旋转、九个检查方向、图层及三份原图参考 |

在仓库根目录依次运行（规划依赖 Python + NumPy + Shapely 2.1）：

```powershell
$env:PYTHONIOENCODING='utf-8'
py -X faulthandler design/white-city/blender/plan_city_layout.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/build_city_layout.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/audit_city_layout.py
```

建模步骤将相机回写计划文件，三步完成后再刷新浏览器；`-- --no-render` 只跳过检查图。
规划使用固定随机种子。源工程保留逐栋对象，导出时仅合并内存副本。检查图使用本机 OptiX；
换机器需调整设备配置。此前 01–12 模型和 v19 入口保留，未覆盖。

## 已验证与边界

- 实际保存工程审计 PASS：179 个独立网格未发现开口边、游离边、多面共享的非流形边、
  非有限顶点或建筑高度不一致；未发现建筑侵水、占路、相互重叠，桥头平面检查均在岸上。
  地形边缘的微小三角形缺口已补面并重新审计。
- 21 个重点建筑均已放置。源工程 SHA256 与导出记录一致：
  `f1308e7ee0d8755ecd71d4ce661b08b2ec2804d82c35ad13d4c632129b4c4133`。
- 0 图像贴图、0 发光材质、0 相机动画。页面中的参考图片仅用于对照，不覆盖三维模型。
- 浏览器四视图加载正确，未出现横向溢出；静止时帧计数保持不变。自由检查的手动旋转、
  桥梁与后左预设、三份参考切换通过；控制台无警告或错误。Python / JS 语法检查通过。
- 相似度仍待目视确认：建筑轮廓较方正、东侧中层较密，桥的右侧接岸长度仍可继续比较。
  本轮没有证明逐栋精确复刻。中性检查光不是最终暖光；移动端和低端 GPU 未验收。

共享文档按 `AGENTS.md` 的集中更新节奏，待下一次「更新」同步 PROJECT_STATE/TODO
当前 v20 与模型待验收状态；ARCHITECTURE/DECISIONS 的真实完整模型、先几何后灯光约束
仍待集中同步。当前接手入口以本目录 README 和实际 13 工程为准。
