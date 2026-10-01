# ARCHITECTURE

> 这份文件描述**系统现在实际是怎么工作的**。不写理想架构;真要写规划,标 `planned`。
> 只在架构真的变了才更新(判据见 `AGENTS.md` §4)。

最后更新:2026-10-01

---

## 分层

```
浏览器 (app/web)  ──HTTP/SSE──>  FastAPI (app/api/server.py)
                                      │
                                      ├── LangGraph 编排 (app/orchestration/graph.py)
                                      │        │
                                      │        ├── 检索   app/search/search.py      → Postgres + pgvector
                                      │        ├── 估值   app/analytics/valuation.py → models/*.ubj
                                      │        ├── 指标   app/analytics/formulas.py + assumptions.py
                                      │        └── 环境   app/amenities/*            → data/ 快照
                                      │
                                      └── 标签翻译 app/i18n.py
```

外部依赖只有两个:**Postgres + pgvector**(Docker,15432)和一个 **OpenAI 兼容的 LLM
端点**(当前 DeepSeek)。地图瓦片要联网,其余功能全部离线可跑。

## 目录职责

| 路径 | 职责 |
|---|---|
| `app/api/server.py` | HTTP 层。SSE 事件流、静态托管、参数闸门。**不含业务逻辑。** |
| `app/orchestration/graph.py` | 七节点的图、全部提示词、排序与筛选口径。系统的中枢。 |
| `app/orchestration/refinement.py` | 多轮修改:把模型给出的本轮变更(changes)确定性地应用到上一轮条件;相对目标的基准与步幅;取舍属性(安静↔热闹)的门槛让步规则 |
| `app/search/search.py` | 语义检索 + SQL 硬条件。嵌入模型在进程内。 |
| `app/analytics/` | `valuation`(XGB 推理)、`train_valuation`(训练)、`formulas`(投资公式)、`assumptions`(可调假设 + 边界) |
| `app/amenities/` | `registry`(数据源与属性的唯一注册表)、`context`(证据 → 分数)、`nearby`(设施/地名/距离)、`planning`、`zones`、`suburb_stats` |
| `app/i18n.py` | **服务端标签**的英文版 + `check()` 完整性自检 |
| `app/web/` | 单页前端:`index.html` / `app.js` / `app.css` / `i18n.js`。无构建步骤。 |
| `app/web/showroom/` | 首屏白模沙盘:`showroom.mjs`(唯一的代码文件)+ 烘焙好的 GLB、贴图、相机 JSON。资产约 19MB,**目前未入库** |
| `pipeline/` | 一次性数据抓取与基准构建脚本 |
| `eval/` | 幻觉率评估与词汇覆盖评估 |
| `tests/` | 纯脚本测试,`python tests/test_x.py` |
| `_ui-lab/` | **experimental** — 另一套备用前端,自带 8080 服务并把 `/api/*` 反代到主站。**不碰 `app/`**,未集成 |
| `design/`、`qisuo-redesign/` | 设计稿,非线上代码 |
| `design/white-city/` | 首屏沙盘的**制作端**:`blender/*.py` 是建模/烘焙/后期/导出脚本(源码),`*.md` 是实验记录与复盘。其余是渲染产物、`.blend` 与历史实验页(v3–v24 实时光照路线,已不是主路径)。**整个目录 2.2GB,不要整目录入库** |
| `_rhine_analysis/` | **与本项目无关**,见 PROJECT_STATE 的 Known Issues |

## 请求流(一次提问)

1. 浏览器 `POST /api/chat {thread_id, message, lang}`
2. `server._run()` 在工作线程里跑图(图是同步的,含 LLM 调用,不能占事件循环),
   事件经队列回到异步端,以 SSE 逐个下发
3. 图依次跑:
   - `parse_intent` — LLM 把自然语言转成结构化参数(唯一一次解析用的 LLM 调用)
   - `search` — pgvector 语义检索 + SQL 硬条件，初始候选上限5,000；ROI多取1条哨兵判截断，保存本请求假设快照
   - `analyze` — 批量估值 + `formulas.investment_metrics()` 算全套投资指标
   - `enrich` — 对候选算周边证据、抽象属性分数、分项强度、全库排位、规划/学区
   - `rank` — 筛选 + 排序，留前20套给"换一批"；ROI未能认证前20或筛空时在节点内翻倍重跑search/analyze/enrich，单轮上限40,000，给准确范围说明
   - `present` — 只给最终 5 套补展示用的设施名、学区、分区、罪案率
   - `explain` — LLM 写说明,**逐字流式**下发
4. SSE 事件顺序:`node` → `params` → `ranking` → `more` → `results` → `token`* →
   `answer` → `done`。前端靠这个顺序做渐进呈现。

## API 表面

| 端点 | 作用 | 是否调 LLM |
|---|---|---|
| `GET /api/meta?lang=` | 全部中文名与口径。`lang=en` 走 `app/i18n.py` 翻译,**结构完全一致** | 否 |
| `POST /api/chat` | 一轮完整提问 | 是(解析 + 说明) |
| `POST /api/refine` | 条件卡改动后从 `search` 续跑,跳过解析 | 是(仅说明) |
| `POST /api/rebatch` | 换一批:只重跑 `explain` | 是(仅说明) |
| `POST /api/measure` | 解析地名 + 两点直线距离 | 否 |
| `POST /api/recalc` | 按给定假设重算一套房的投资指标 | 否 |
| `POST /api/assumptions` | 改**进程级**假设 | 否 |
| `GET /` + `/static/*` | 单页前端,带 `Cache-Control: no-cache` | 否 |

## 多轮修改(「再便宜点」「再安静一点」)

`parse_intent` 判为 `refine` 时,模型**只输出本轮变更** `changes`(set / remove / relative /
prioritize,每项必须带用户本轮原话里逐字出现的 `source`),**不重填整份条件**。
`refinement.apply_changes` 把它应用到上一轮条件上:任一项不合法就整轮拒绝、转 `clarify`,
不会半改半留;没提到的条件原样保留。

- **相对调整**(relative):基准 = 上一轮**实际展示的**房源在该字段的中位数,记进
  `relative_preferences`。`rank` 里由 `refinement.relative_rank` 按候选分布算步幅:属性分数
  「一点 / 更 / 明显」至少挪 10 / 15 / 25 分;价格、收益、距离只要求方向正确。
- **取舍属性**(`registry.CONFLICTS`,目前只有安静↔热闹):调整一方时,另一方的词条保留;
  它的门槛若是系统推断的(`value_source=inferred` 且非 `required`),原门槛内凑不够 5 套时
  自动让 10 分(最低 50)并在排序说明最前面写明;用户明确给的分数或「必须」永不自动让。
  同一句里对反向属性的 prioritize(「稍微安静点,但还是要热闹」)视为重申保留,不改排序。
- **找不到兼容结果**:`rank` 返回 `refinement_base`(修改前的整轮快照),恢复上一轮条件与房源,
  `turn_notice` 给出确定性说明,`present` / `explain` 看到 `turn_notice` 就不再过 LLM。
  结果只是变少(1–4 套)时**不**用 `turn_notice`,说明写进排序说明,房源照常展示和讲解。
- **出错回滚**:`server._run` 在跑图前深拷贝会话状态,任何异常都整轮写回(含对话历史)。
- 条件卡改动走 `/api/refine`:`prepare_refinement` 以卡片条件为准,删除的属性同时清掉
  对应排序与相对目标,并从保留下来的结构化条件重建英文检索描述。

`refine` / `rebatch` 都走 `GRAPH.update_state(..., as_node=...)`,把新状态当作某个节点的
输出写进会话,再从它后面继续 —— 这是"不重跑整张图"的机制。

## 数据流与真实性分层

三类数字在代码里就是分开的,前端也按三类上不同标记:

- **实测/法定** — 数据库字段、维州法定印花税(`formulas.stamp_duty_vic`)
- **基于假设** — NOI / Cap Rate / ROI,依赖 `assumptions`(运营支出比例、过户杂费)
- **模型预测** — `valuation.predict_values()`,带按房型的典型误差

车位字段的数据契约：新导入把原始Car缺失存为NULL、记录0保留；新表car_spaces可空，旧库数据/模型不改，映射/迁移/回填取消。网页详情与收藏详情省略全部车位数；explain新建不含car_spaces的facts副本，analyze特征、会话metrics、API和收藏快照保留。graph用有限规则区分明确房源车位、歧义与公共设施/专名；明确要求不进入车位筛选，语义清理保护公共短语，歧义保留原文并条件式说明。refine通过程序标志保留上一轮未取消的unsupported记录，结构化取消抑制重新添加；新搜索无继承，快照支持无结果回滚。英文条件卡使用i18n.UNSUPPORTED_KEY_EN的房源车位映射，规划Parking独立保留。真实LLM遵守情况仍未验证。价格SQL预选将price<=0排后，最终价格rank排除非正值。

`formulas.investment_metrics()` 是**唯一**一处把这些串起来的实现,`analyze` 节点和
`/api/recalc` 共用它 —— 前端不自己算公式。

ROI候选使用formulas.roi_order_sql（由同一税档表生成的不取整式）预排序，最终指标/排序用investment_metrics。roi_pool记录截断cutoff、opex_rate、other_costs和limit；roi_certified_prefix仅认证无法被池外超过的前缀。费用太小或不能认证时扩容，超过40,000仍不能保证全局结果；循环只在rank节点内部，不向SSE推送中间半成品。

search首次取得assumption_snap（opex_rate、other_costs、display），扩容/analyze/每套指标及解释沿用此快照；refinement.snapshot同时保存roi_pool/assumption_snap，回滚恢复旧指标和元数据，上限说明通过turn_notice交代。server done优先描述有效assumption_snap.display，旧状态退回第一条metrics.assumptions，均缺失时兼容使用一次捕获的当前全局快照；中文通过assumptions.describe(snap)公共纯格式入口。按ID详情的旧全局分次读取及解释ABA原子性仍未证明，不表示整个API已原子一致。真实扩容模型/几何成本未测；协调PG的一次候选SQL执行246.070ms只作局部证据。

## 抽象属性(安静/热闹/…)

`app/amenities/registry.py` 是**唯一**的注册表:数据源、证据项、属性权重、
不支持项清单全在这里。提示词片段、`/api/meta`、评分、英文标签都从它生成。
加一个数据源只改这一个文件;`tests/test_registry.py` 会挡住"加了源却忘了配别处"。

打分:原始证据 → 用 `data/context_baseline.json` 的分位表转成 0~1 → 按权重合成
0~100。合成分**本身不是分位数**,所以另存了 `score_quantiles`,`context.score_rank()`
把分数翻译成"高于全库百分之几"。

## 首屏白模沙盘

**离线烘焙,网页不算光。** 这是它与普通 three.js 场景最大的区别,也是相机被锁死的原因。

```
Blender 4.5 + Cycles/OptiX                          浏览器 (app/web/showroom/showroom.mjs)
design/white-city/blender/
  render_v27_plinth.py   台座与城市场景
  build_v28_houses.py    四套户型样板 + 售房牌     ┐
  bake_v28_showroom.py   把光烘成贴图              ├─> city-v26-baked.glb   ─> MeshBasicMaterial
  render_v28_ids.py      beauty + 对象 ID 层       │   trees-v26.glb        ─> InstancedMesh
  render_v28_shadows.py  桌面影子(城市/户型两张)   │   layer-trees.webp     ─> 投影查表着色器
  post_v28_layers.py     补洞、去隐藏面细线        │   floor-shadow-*.webp  ─> 两块投影平面
  export_v26_web.py      导出 GLB(Draco + WEBP)  ┘   cam-*.json           ─> 正交相机画框
```

- **相机是锁死的正交相机。** 只能在烘焙时那个宽幅画框内平移/缩放(平移对正交相机是纯
  二维位移,烘好的光仍然成立),**不能旋转** —— 一旋转烘焙的明暗就错了。
- **两个画面**:城市沙盘 ↔ 四套户型样板,靠画框平移过渡(`pan` 0→1)。
- **城市视角把整组户型隐藏**:两组模型在 `.blend` 里只隔十几米,不隐藏就会在首屏
  露出一角;它们投在桌面上的影子也是单独一张,跟着一起淡入淡出。
- **取景自适应**:`cityFrame()` 按模型在相机平面上的包围盒 + 输入框的实测位置算画框,
  保证整座模型(含桌面影子)完整露出、底部留空隙、最高的塔落在输入框右侧。
- **售房牌是 DOM**,不是贴图:把三维四角投影到屏幕,用 CSS `matrix3d` 贴上去,
  所以文字清晰、可点击、可翻译。词条池在 `i18n.js`(`showroomSigns` + `showroomSignVariants`,
  每栋 10 条、共 40 条,中英各一套,标题全局唯一);每块牌洗牌后依次轮完再重洗,
  并避开其他牌正在显示的标题。
- **河面调色**:烘焙贴图里的水几乎无色,网页按效果图在运行时调色 —— `gradeWater` 只作用于
  台座、河道两个对象里遮罩内的像素(遮罩 `water-mask-*.png` 由
  `design/white-city/blender/make_water_masks.py` 从烘焙贴图生成,与贴图同一套 UV)。
  `?debug=water` 把水面涂成品红,供截图取样验证。外层禁用 transform 过渡并裁剪溢出;内层只做透明度动画,
  不改变板面坐标。`i18n.js` 的 `showroomSigns` + `showroomSignVariants` 提供每牌 3 条示例,
  点击读取当前索引,语言切换保持索引。每牌独立随机计时,悬停/聚焦暂停,离开可见首屏停止。
  WAAPI 淡入/淡出均为 200ms,定时器负责取消临时动画,保持可见底色,不依赖动画结束事件。
- **草坪覆盖贴图**:`lawn-{cottage,villa,terrace,apartment}.png` 是原始独立渲染层的逐字节副本,
  在加载时替换旧 GLB 内的四张草坪 map(`flipY=false`,沿用 glTF UV,alphaTest 0.5)。
  旧 `post_v28_layers.py` 的 beauty/ID 合成会把白色遮挡边缘混入草坪;覆盖层绕开该步骤,
  不改 GLB 或 `.blend`。重建: `node design/white-city/blender/copy_showroom_lawns.mjs`,
  来源 `design/white-city/bake-v28/raw/v28_*_lawn.png`,复制后逐个校验 SHA-256。

牌面浏览器回归:先 `python serve.py --no-open --port=8520`,再
`node tests/test_showroom_browser.mjs`,打开 `http://127.0.0.1:8521/`。
可用 `?width=900&height=720` 在固定大小 iframe 里测试;测试独立代理不修改主站,
量实际 CSS 矩阵与当前投影目标的逐帧差,检查轮换、聚焦、双语点击及城市视角清理。

与 `app.js` 的**边界:两边互不引用**,只通过三个自定义事件通信:

| 事件 | 方向 | 作用 |
|---|---|---|
| `nw:query` | showroom → app | 点售房牌,等同于在输入框里提问并发送 |
| `nw:lang` | app → showroom | 语言切换,重渲染牌面文案 |
| `nw:showroom` | showroom → app | 沙盘就绪,`app.js` 停掉 SVG 城市的漂移动画 |

## 国际化

| 类别 | 位置 | 切换方式 |
|---|---|---|
| 界面文案(按钮、段标题、整句) | `app/web/i18n.js` | 换 `T` 表后重渲染 |
| 服务端标签(属性名、设施名、排序口径、规划分区) | `app/i18n.py` | 重取 `/api/meta?lang=` |
| LLM 生成的说明、rank 的口径 | `graph.py`(`_t()` + 提示词追加段) | 重跑一次 `refine` |

原则:**一个字符串只有一个出处**。注册表在后端,它的英文也在后端。

## 前端结构

单页,无构建。`app.js` 一个 IIFE,内部按区块组织:状态 → 工具 → 对话 → 条件卡 →
结果卡 → 地图 → 详情窗 → 首屏 SVG 城市与立面词条 → 语言切换 → 启动。

首屏背景有两套,互为回退:宽屏(≥900px)且资产加载成功时用 `showroom.mjs` 的白模沙盘,
否则用 `app.js` 里 `drawCity()` 生成的 SVG 城市。切换由 `<div id="app">` 上的
`data-showroom="ready"` 驱动,CSS 决定谁可见。

注意:Leaflet 的全局是 `L`,所以文案表叫 `T`,不要再引入名为 `L` 的局部变量。
