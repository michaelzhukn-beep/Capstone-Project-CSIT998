# 07 白底融合与局部光照

此为保留的 07 阶段记录；最新封口与灯源修复见 `ENCLOSURE.md`，入口 `v15-enclosed.html`。

**experimental；未接入主站。** 当前入口 `v14-studio.html`，上一版 `v13-districts.html` 保留。
布局、参考相机、河道与巡游算法沿用 06；本轮只处理渲染，仍是可移动的真实三维网格。

## 当前实现

- 页面与主站底色统一为 `#F5F4F0`。移除 WebGL 整场景深度混白及 Cycles compositor
  深度雾。楼体不随距离变淡；只有地面边缘收至白底。WebGL 用地面顶点系数及 AgX
  逆变换匹配页面色；Cycles 用仅作用于相机射线的地面透明边缘，保留地面的 GI 贡献。
- 35 个建筑资产有 Cycles 自身遮蔽，其中 **7 个有发光构件的资产**额外烘焙局部漫反射光。
  每栋单独计算，世界照明关闭、其他资产隐藏，不含邻楼阴影。64 samples、4 次 diffuse
  bounce，整库生成约 31 秒（当前机器）。
- `city-07-assets.glb` 为 8,068,352 字节，38 个资产：35 建筑、3 树木。只细分大表面，
  原点与完整包围盒和 04 一致，继续用原位置清单。没有背景图片替代模型。
- `COLOR_0` RGB 编码线性局部 diffuse 辐射数据 / 16，alpha 编码自身 AO。加载后改名
  `localLight`，**不作顶点底色或透明度**。shader 只对环境漫反射施加自身遮蔽，再加入
  局部光。直射光阴影、GTAO、河面反射继续实时计算。
- 实时显示改为 AgX、曝光乘数 2，加强侧向主光并减轻屏幕 AO。Bloom 只提取暖色 HDR
  高光，白色地面不参与。6 盏弱面光补未烘焙地面，强度由 2.1 降为 .25。
- 「局部烘焙」单独对照；「室内暖光」同时控制发光材质、烘焙暖光与面光。
  离线样张禁用实时灯光开关，避免误以为静帧随开关改变。

## 源文件与复现

| 文件 | 用途 |
|---|---|
| `city-lighting-07.mjs` | 实时光照、白底、选择性辉光；保留 06 的 resize 深度附件修复 |
| `city-local-light.mjs` | 局部光 shader、地面收边和 AgX 白色匹配 |
| `city-districts.mjs` | `studio:true` 选择新资产；默认 false 保持 v13 行为 |
| `blender/bake_city_local_light.py` | 从未改动的 `city-04.blend` 独立烘焙并导出资产 |
| `blender/render_studio.py` | 从未改动的 `city-06-districts.blend` 生成 07 工程及 Cycles 全景 |
| `blender/verify_local_light.py` | GLB 重新导入，核对占地范围、颜色数据、源文件哈希 |
| `blender/city-07-studio.blend` | 可编辑的同布局离线光照参考工程 |

在仓库根目录执行：

```powershell
$blender='D:/tools/blender/blender-4.5.13-windows-x64/blender.exe'
& $blender -b design/white-city/blender/city-04.blend --python design/white-city/blender/bake_city_local_light.py
& $blender -b --python design/white-city/blender/render_studio.py
& $blender -b --python design/white-city/blender/verify_local_light.py
node tests/test_city_districts.mjs
node tests/test_city_view.mjs
node tests/test_city_stream.mjs
```

## 验证与边界

- GLB 导入 PASS：38 资产齐全，35 建筑有数据，7 个暖光资产有效。包围盒最大误差 0；
  483,012 个彩色角点数值有限且在范围内，无截断；04 源哈希未变。证据见
  `blender/city-07-assets-bake.json`、`city-07-assets-review.json`。
- 6,549 个街区建筑占地、2,858 个旧巡游占地及 11 个机位锚点回归通过。
  07 没有修改布局生成器、04 资产清单或 `city-view.json`。
- 内嵌浏览器 1280×720 与 2560×800 检查；正常 9 / 宽屏 13 区块，反射水面数同步。
  0/3/12 公里抽查无加载或 shader 错误；4× 实际推进到 333.414 米，跨越 216 米重定位
  边界，暂停后距离保持。回到起点几何数恢复 144；宽屏远程段为 160，没有随跳转持续增长。
- Cycles 全景 2560×1415、192 samples、10 total / 5 diffuse bounces。它仅作对照，
  巡游不播放该静帧。工程无整场景雾，源布局与相机不变。
- **仍不是完整场景 GI。** 跨建筑反弹光、复杂玻璃光路、离线柔影与原模型倒角仍有差异。
  WebGL AgX 不含 Blender Medium High Contrast look，不能宣称显示变换完全一致。
  小尺度光影受顶点密度限制，近景最终观感待验收。
- 独立浏览器 GPU 帧率及低端设备未测，本轮不宣称性能已达上线标准。

下一步按实时画面的视觉反馈调整光照比例。资产或发光强度改变后须重新烘焙，不能只改
离线工程。共享四份状态文档按 AGENTS 的延迟政策待下一次明确「更新」同步。
