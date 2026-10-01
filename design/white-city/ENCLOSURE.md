# 08 模型封口与隐藏灯源

**experimental，尚未接入主站；视觉最终验收待定。** 当前入口 `v15-enclosed.html`。
沿用 06 街区、参考机位和 07 局部烘焙机制；`v14-studio.html` 保留原版对照。

## 已修改

- 展馆折板屋顶、锯齿屋顶补实体厚度、底面与端封板；修正封闭构件的朝内法线。
- L 形展馆补外墙与翼部玻璃端面，删除露天庭院中没有顶棚承接的孤立立柱。
  保留有意设计的露天庭院，不把整个院子加盖成封闭盒子。
- 原灯板在地面上方 2.8m，且不区分屋顶形状，会直接伸进露天庭院。08 改为屋顶下
  4.69m 的窄灯带，配顶盖和 0.42m 高的灯槽挡边；庭院型各放在有顶棚的两个翼部。
  灯槽靠窗侧向下照明，暖光落在窗边墙地面上。
- Cycles 灯源禁用 camera/glossy ray 可见性；实时发光网格不进入主画面和河面反射。
  保留灯光贡献，不再靠直接显示发光灯板制造亮度。7 个发光资产均重新烘焙。
- 普通展馆的整屋实心玻璃盒改成四面薄玻璃，保留原建筑占地。
- 材质调为较亮的中性暖白；Cycles 主面光 620000、宽度 115，世界补光 .27，
  AgX Medium High Contrast / +1.8 EV。实时 AgX 曝光 2.65，维持转角和窗洞的层次。
- 新增「检查封口」：在当前真实巡游场景中暂停并解锁观察，可拖动、缩放；
  「参考机位」恢复原机位。页面默认仍暂停并锁定参考视角。

## 文件与复现

`blender/city_enclosure.py` 是共享几何修复与材质函数，分别用于原始建筑源文件和
离线街区中的局部资产集合，避免实时/离线两套几何各改一份。

```powershell
$blender='D:/tools/blender/blender-4.5.13-windows-x64/blender.exe'
& $blender -b --python design/white-city/blender/build_enclosed_source.py
& $blender -b --python design/white-city/blender/verify_enclosure.py
& $blender -b design/white-city/blender/city-08-source.blend --python design/white-city/blender/bake_city_local_light.py -- --stage=08
& $blender -b --python design/white-city/blender/render_enclosed.py
& $blender -b --python design/white-city/blender/verify_local_light.py -- --stage=08
py design/white-city/blender/analyze_enclosed_render.py
```

- `city-08-source.blend`：修复后的建筑源库，由只读 04 派生。
- `city-08-assets.glb`：实时资产，8,221,476 字节；局部光 RGB 编码为 radiance / 64，
  alpha 为自身遮蔽，加载后使用专用属性，不作为模型透明度。默认 07 路径仍用 /16。
- `city-08-enclosed.blend`：可编辑的完整 08 街区；从只读 07 派生、保留原机位和位置。
- `renders/city-08-enclosed.png`：192 samples、2560×1415 的实际 Cycles 全景，只作对照。
- `city-lighting-08.mjs`：隐藏灯源与实时调光；原 07 灯光模块保留。

## 验证

- `city-08-enclosure-audit.json`：3,101 个实体构件无开边或负体积；7 个发光资产隐藏
  camera/glossy 可见性，50/50 灯源采样点向上均命中实体顶盖。
- `city-08-assets-review.json`：GLB 导入 38 资产通过；35 建筑、7 个暖光资产，
  原点/完整包围盒与 04 最大误差 0，无编码截断；源文件哈希检查通过。
- 街区 6,549 个占地、旧巡游 2,858 个占地和 11 个相机锚点回归通过。
- 浏览器检查正常屏/2560×800 宽屏、3km 跳转、封口检查缩放/恢复参考、暖光开关。
  宽屏 13 区块、13 个水面，可见灯源 0；未见加载或 shader 错误。
- `city-08-tonal-review.json`：相同相机的共同不透明像素，排除顶端 20%；
  亮度中位数由 190 提至约 220，90 分位由 212 提至约 235（8-bit），纯白截断 0%。
  该统计只验证提亮，没有把它当作效果图匹配或人眼验收。

## 边界

仍采用建筑局部光照烘焙和实时阴影，未实现完整场景实时 GI。源网格的封口检查不代表
任意未来新增建筑也会正确，新增类型仍需跑审计。白模、暖光比例和独立浏览器性能待验收。
共享四份文档按 AGENTS 的约定待下一次明确「更新」集中同步。
