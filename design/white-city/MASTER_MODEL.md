# 四视图完整城市白模 12

**experimental / 模型待验收。** 当前入口 `v19-master.html`。本阶段只确认几何、
布局和高低关系；模型确认后才继续最终材质、灯光和主页构图。未接入主站。

## 当前模型

- 原始依据：`assets/city-four-view-reference.png`，保留完整原图。
- 单一世界坐标场景，124 栋建筑，其中 14 个重点建筑；10 类轮廓，920 棵实体树。
- 平面包含连续河湾、两岸滨水道、中央大道、山麓大道、6 条连接路、桥头接岸路；
  一座曲线主桥、一座上游步行桥。桥面、栏杆、桥墩都有实体，桥墩延至河床以下。
- 左侧低层、中央地标、右侧高层及坡地组团；前后 3 处层叠山体。
  山体为封闭网格，等高台阶不是贴图。南岸街坊和非正面立面也已建立。
- 建筑含基座、四面立面、屋顶和端面；庭院保留有意设计的室外空间，围墙和楼翼封口。
- 页面提供同一个模型的上/前/左/右四视图、手动旋转缩放、图层隐藏、线框和原图对照。
  无自动巡游、无按机位生成不同布局；只有操作或尺寸变化时重绘。

## 文件与重建

| 文件 | 用途 |
|---|---|
| `blender/plan_city_model.py` | 世界坐标总平面、地块避让、道路并集、树木布置；固定种子 |
| `blender/city-12-master-plan.json` | 可追溯的布局、参考哈希、轮廓、标高、检查结果与相机 |
| `blender/build_city_model.py` | 从总平面建立完整 Blender 模型、四向检查图和 GLB |
| `blender/city-12-master.blend` | 逐栋可编辑工程；地形、河道、道路、建筑、桥梁、山体、植被分组 |
| `blender/city-12-master.glb` | 网页优化导出，6,794,948 字节；7 个分组、13 个材质子网格、1,420,780 三角形 |
| `blender/renders/city-12-*.png` | 同一真实模型的 5 张中性 Cycles 检查图，1600×1100，含透明背景 |
| `blender/audit_city_model.py` | 重新打开保存的工程，独立检查实际网格和占地 |
| `blender/city-12-audit.json` | 实际工程检查结果及 SHA256 |
| `blender/city-12-export.json` | 导出大小、相机与源工程 SHA256 |
| `city-master.mjs`、`v19-master.html` | 一个 WebGL 场景、四个固定检查相机及自由检查相机 |

在仓库根目录运行，规划脚本依赖 Python + NumPy + Shapely 2.1；建模依赖 Blender 4.5：

```powershell
$env:PYTHONIOENCODING='utf-8'
py design/white-city/blender/plan_city_model.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/build_city_model.py
& 'D:/tools/blender/blender-4.5.13-windows-x64/blender.exe' -b --python design/white-city/blender/audit_city_model.py
```

三步按顺序完成后再刷新页面。第二步将相机回写总平面；`-- --no-render` 只跳过检查图。
Blender 使用本机 OptiX GPU 做中性检查图；更换机器时需调整设备配置。导出在内存副本合并
网格，保存的源工程仍保留逐栋建筑与链接树木。旧 01–11 模型、v18 页面保持原样。

## 已验证与边界

- 实际 `.blend` 审计 PASS：142 个独立网格未发现开放边/游离边、非有限顶点、
  建筑高度缺失、建筑侵水、建筑占路或建筑互相重叠；桥头平面检查均落在岸上。
- 源工程 SHA256 与导出记录一致；0 图像贴图、0 发光材质、0 相机动画。
- 浏览器加载、四视图、手动旋转、俯视/侧视预设、建筑/植被隐藏、线框、原始参考
  已检查；控制台无警告或错误。静止状态不持续重绘。JS/Python 语法检查通过。
- 参考四幅图带有透视且没有可靠的逐栋尺寸；当前为统一几何解释，未见背面作了合理补全，
  不是测绘模型，也没有证明逐栋精确复刻。页面左/右视图是真正东西侧的检查方向，
  与参考图中带斜向透视的示意机位不完全相同。
- 布局相似度、建筑比例仍待所有者目视确认。中性检查光不代表最终暖光质量；
  手机、低端 GPU 性能及主站接入未验收。本阶段到模型确认为止。

共享文档按 `AGENTS.md` 集中更新节奏：待下一次「更新」同步 PROJECT_STATE/TODO 的
v19 当前阶段与待验收项，以及 ARCHITECTURE/DECISIONS 中先完整建模再深化渲染的约束。
