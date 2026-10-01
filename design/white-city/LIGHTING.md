# 灯光深化 05（experimental）

06 的街区、侧向光照和同布局 Cycles 对照见 `DISTRICTS.md`；本文件仅描述保留的 05。

当前入口：`http://127.0.0.1:8765/v12-lighting.html`。默认是真实 GLB 模型，保留 04 的建筑、地块和树木；新旧灯光可同机位切换。Cycles 按钮展示同一实际模型的离线对照，不能称为实时画面。尚未接主站，05 视觉待验收。

## 固定参考机位

`city-view.json` 是本轮机位的共同来源，网页和 `blender/refine_lighting.py` 都读取它。构图是左侧近景塔楼较大、河岸斜向右侧展开、右侧高楼群，不是此前正面远景。Three.js Y-up 坐标：位置 `[-185.4913,51.0202,251.5698]`，目标 `[13.5907,12.3485,-69.7880]`，参考纵向 FOV 30.1523°，宽高比约 1.809。窄视口扩大纵向视场保持横向范围。

这是依据参考图建筑屋顶/基座位置拟合的近似机位，不是精确相机标定。`tests/test_city_view.mjs` 用 11 个参考地标独立投影核对，在 2048×1132 基准上 RMS 9.8px。改灯光时不得顺手换回 v11 的默认机位。默认锁定，解锁后可旋转；「参考机位」恢复；切换灯光不改变机位，巡游沿参考朝向，退出巡游恢复进入前的模型机位。

## 实际改动

- **Cycles**：从受保护的 `city-04.blend` 派生 `city-05.blend`，保留真实网格与实例。主面光尺寸 70→105，能量 500000→440000；柔化太阳方向光，增加克制的冷色补光，室内暖光改为偏奶油色。采用真实遮挡、多次反弹和反射。05 工程默认输出到自己的文件，不覆盖 04 对照。
- **实时**：`city-lighting.mjs` 为静态模型和巡游共用的灯光模块。4096 VSM 柔影、GTAO 接触层次、有限的环境补光与 HDR 高阈值微弱 Bloom。透光玻璃不再投下整片不透明墙的阴影。关闭接触层次仍刷新深度，远景融合不会失效。
- **局部暖光**：基于模型内已有的发光天花板位置配置向下面光，最多 6 个；距离和候选交替边界平滑降低强度。它是实时的局部补光近似，不是 Cycles GI 烘焙；面光不提供墙体遮挡，功率保持克制。
- **水面**：由当前三维场景生成一次平面反射，再由实际河面网格采样，带柔化与受控反射强度。所有巡游块共用一个 768×768 反射缓存。河面继承双面绘制，避免旧网格绕序使河水消失。没有图片背景或参考图投影。
- **资源**：巡游仍使用 04 的 35 栋真实建筑资产及树木模板，街区布局与回收规则未变。`city-stream.mjs` 仅为水面材质添加语义名称，供新灯光模块识别；旧 v11 保留。

## 文件与验证

- `blender/refine_lighting.py`：读取 04，生成 05 工程、两版同参考机位与同河岸近景的 Cycles 对照。运行：`blender -b --python design/white-city/blender/refine_lighting.py`。本机 Blender 路径见 `blender/README.md`。
- `blender/renders/reference-lighting-04.png` / `reference-lighting-05.png`：2560×1415，128 samples；`waterfront-lighting-04.png` / `waterfront-lighting-05.png`：1600×1000，128 samples。
- `blender/lighting-verification-city-05.json`：04 源文件哈希不变、几何指纹不变、无图片纹理节点、共享机位、灯光与采样参数。
- `tests/test_city_view.mjs` PASS：机位地标与 WebGL/Cycles 共用配置；`tests/test_city_stream.mjs` PASS：2,858 个建筑占地、河岸/桥头/邻居、重复类型间距、区块连续、时钟生命周期。
- 浏览器对比开关不移动相机；暖光关闭后局部面光数为 0；关 AO 仍有正常画面；巡游返回机位一致。巡游抽查 0→12.00km，9 个活跃块，36 个回收块，几何计数 424–430 波动，面光 6、反射缓存 1，没有随抽查距离增加。详见 `blender/city-05-review.json`。

## 尚未完成

实时画面仍是光栅化近似；精确 GI、玻璃多次折射、光照烘焙和 Cycles 级实时质量未完成。原型有大量模型绘制与反射/AO 开销，低端设备、独立浏览器连续帧率、移动端尚未验收。固定场景外围仍是有限的模型底板；无限巡游使用另一套连续河岸布局。不要把离线对照或资源回收抽查说成最终视觉/性能验收。

实现参考：[Three.js r170 GTAOPass](https://github.com/mrdoob/three.js/blob/r170/examples/jsm/postprocessing/GTAOPass.js)、[Reflector](https://github.com/mrdoob/three.js/blob/r170/examples/jsm/objects/Reflector.js)、[UnrealBloomPass](https://github.com/mrdoob/three.js/blob/r170/examples/jsm/postprocessing/UnrealBloomPass.js)。

共享 docs 按 AGENTS 集中更新节奏暂缓写入；下一次「更新」补录 05 灯光、共用参考机位、当前画质边界与待验收状态。
