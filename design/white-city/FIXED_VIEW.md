# 固定机位复刻验证 09

**experimental / in progress。** `v16-fixed.html` 是固定构图的独立验证页，尚未逐栋复刻目标，
未达到「完美复刻」，未接入主站。`v15-enclosed.html` 和全部历史模型保留。

## 验证结论

固定机位使一次性的精确布置、可见面细化和整场景烘焙可行，避免继续为无限巡游调整
重复率、区块接缝和远景覆盖。但暂停或删除巡游本身不会改变光照算法，也不会恢复参考图
未知的模型、材质与灯光。单张图只能约束可见投影，不能唯一确定三维源场景。

参考图为 `assets/fixed-reference.png`（所有者提供的原文件，未经编辑）。只在「目标参考」
中展示，**没有贴到模型、没有生成图片背景、没有深度卡片**。页面默认展示真实 GLB。
Cycles 按钮是明确标注的同一模型离线对照，不冒充网页渲染。

## 已实现的验证

- 固定正交机位，俯角 14°；按参考的可见投影布置 16 个重点建筑位置，
  其余以受天际线限制的确定性组团填充。位置记录在 `city-09-fixed-plan.json`。
  这些点是**人工读取的构图约束**，投影误差接近零只证明相机计算正确，不是相似度评分。
- 左下弧形公共建筑、中央弯曲河道和拱桥、右侧逐级上升的塔楼组；封闭建筑外壳、
  细竖向构件和薄玻璃。展馆 H14 为避免侵水向岸内调整，未宣称与原图位置完全相同。
- 完整 Blender 场景、2560×1441 / 192 samples Cycles 以及真实 GLB 均生成。
- 整个固定场景参与 48 samples / 5 次 diffuse bounce 烘焙，包括环境、主辅光、邻楼、
  树木、河岸与隐藏暖光源。RGB 为线性 diffuse radiance（含 albedo）/32。
- 直接在共享顶点烘焙会在相交窗框/楼板边界形成黑斑；改为面内偏移的采样代理，
  原始几何仍参与遮挡和 GI，采样后删除代理并导出未改形的几何。
- 网页采用烘焙颜色与 AgX 显示；Blender 的 Medium High Contrast look 与 Three.js 的
  标准 AgX 也不是同一套完整显示曲线。玻璃、水面暂按漫反射近似，**没有烘焙反射/透射**。
  不把 diffuse 全场景烘焙说成完整的 Cycles 画质。
- Draco 使用 position/color 16-bit、normal 12-bit。没有巡游、分块回收、鼠标视差、
  OrbitControls 或常驻动画帧循环；只在加载、尺寸改变和切换检查方式时渲染。
  当前 139 栋建筑、436 棵树；压缩 GLB 为 24,920,588 字节，仍需后续设备性能验收。

## 为什么颜色与精致感仍不同

| 项目 | 查证结果 | 固定机位是否自动解决 |
|---|---|---|
| 构图与密度 | 旧巡游是连续街区；目标是底部留白与右高左低的定制构图 | 否，09 重新布置 |
| 建筑设计 | 目标各建筑的楼体比例、层次、立面节奏不同；09 仍含复用类型 | 否，仍需逐栋匹配 |
| 细节尺度 | 树冠、栏杆和窗框在画面中的像素尺度影响精密感；只加面数无效 | 否 |
| 材质 | 原白模灰色窗面占比过高；09 减少大片灰带，增加细白竖线与倒角 | 否 |
| 光线传递 | 旧版只做资产局部暖光；09 计算固定全场景 diffuse 反弹 | 有帮助，但反射/透射仍有差距 |
| 色调与高光 | 曝光会整体提亮；目标还需要更暖的局部亮部和更宽的明暗分布 | 否 |

## 已做检查

`city-09-fixed-audit.json`：139 栋建筑实际底座对河道网格的 SAT 检查，侵水 0、建筑交叠 0；
90 个光源对象均对 camera/glossy/transmission 隐藏；相机动画为 false；图片纹理节点 0。

浏览器：9 个渲染网格、1,565,548 三角形、缺失顶点颜色 0；Draco 加载与着色器无控制台
错误。两次间隔观察中相机矩阵相同、渲染计数保持 2；线框和 Cycles 切换通过。
这是本机静态画面验证，不是移动端/独立浏览器帧率验收。

`city-09-reference-tones.json` 比较相同归一化城市区域 `[.03,.78,.97,.91]`：

| 8-bit 图像指标 | 目标参考 | 09 Cycles |
|---|---:|---:|
| 亮度 P10 | 205.987 | 211.924 |
| 亮度中位数 | 231.209 | 233.783 |
| 亮度 P90 | 249.201 | 241.996 |
| 平均 R−B（粗略暖色指标） | 10.036 | 4.491 |

亮度中位数已接近，但目标高光更亮、暖色更丰富。**这些统计既不证明布局一致，也不证明
网页与 Cycles 一致。** 自检结论是方向可行，当前验证版还没有完美复刻。

## 后续重点与边界

1. 用目标图逐栋校准近景建筑和河湾，而非继续随机增加楼数。
2. 重点建筑改用高分辨率 UV lightmap，验证反射与玻璃的固定视角处理；顶点采样不能
   承载所有细小光照变化。当前网页暗部比 Cycles 更硬，暖光不足。
3. 树群、坡地及目标顶部水纹光尚未逐项还原；字体/标题目前只用于对照构图。
4. 手机和不同长宽比暂按原图比例留白展示，没有把相机扩大来补满屏；主站集成未做。

## 重建

```powershell
$blender='D:/tools/blender/blender-4.5.13-windows-x64/blender.exe'
& $blender -b --python design/white-city/blender/build_fixed_hero.py
& $blender -b --python design/white-city/blender/bake_fixed_hero.py
& $blender -b --python design/white-city/blender/verify_fixed_hero.py
py design/white-city/blender/analyze_fixed_reference.py
```

完整场景 `blender/city-09-fixed.blend`；网页光照网格 `blender/city-09-fixed-baked.glb`。
`--draft` 仅用于低采样迭代；最终对照使用完整渲染。共享状态按 AGENTS 的集中更新节奏维护，
新发现的网页画质限制即时放入 Known Issues，其余变更待下一次「更新」。

技术依据：[Blender 烘焙说明](https://docs.blender.org/manual/en/latest/render/cycles/baking.html)、
[固定观察位置与烘焙](https://developer.blender.org/docs/release_notes/3.4/cycles/)、
[AgX 色彩管理](https://developer.blender.org/docs/release_notes/4.0/color_management/)。
