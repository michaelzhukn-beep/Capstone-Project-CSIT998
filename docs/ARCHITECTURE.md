# ARCHITECTURE

> 这份文件描述**系统现在实际是怎么工作的**。不写理想架构;真要写规划,标 `planned`。
> 只在架构真的变了才更新(判据见 `AGENTS.md` §4)。

最后更新:2026-10-06

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
                                      ├── 账号与收藏 app/auth/*               → Postgres(users/sessions/favorites)
                                      └── 标签翻译 app/i18n.py
```

外部依赖只有两个:**Postgres + pgvector**(Docker,15432)和一个 **OpenAI 兼容的 LLM
端点**(当前 DeepSeek,换供应商只改 `.env`,见 `docs/en/CONFIGURATION.md`)。
地图底图与前端库(Leaflet、MapLibre GL、three.js)走 CDN / 在线瓦片,其余功能全部离线可跑。

**新环境建库**:`docker compose -f db/docker-compose.yml up -d` → `python db/setup_db.py`。
后者从 `db/seed/properties.dump`(pg_dump 自定义格式,只含 `properties` 表与向量,
不含任何账号/收藏)恢复 20,800 条房源,再跑 `db/schema.sql` 补其余表;可重复执行。
种子要和数据管线产物保持一致:重跑 `pipeline/load_properties.py` 后按 `db/setup_db.py`
文件头的命令重新导出。

## 目录职责

| 路径 | 职责 |
|---|---|
| `app/api/server.py` | HTTP 层。SSE 事件流、静态托管、参数闸门。**不含业务逻辑。** |
| `app/orchestration/graph.py` | 七节点的图、全部提示词、排序与筛选口径。系统的中枢。 |
| `app/orchestration/refinement.py` | 多轮修改:把模型给出的本轮变更(changes)确定性地应用到上一轮条件;相对目标的基准与步幅;取舍属性(安静↔热闹)的门槛让步规则 |
| `app/search/search.py` | 语义检索 + SQL 硬条件。嵌入模型在进程内。 |
| `app/analytics/` | `valuation`(XGB 推理)、`train_valuation`(训练)、`formulas`(投资公式)、`assumptions`(可调假设 + 边界) |
| `app/amenities/` | `registry`(数据源与属性的唯一注册表)、`context`(证据 → 分数)、`nearby`(设施/地名/距离)、`planning`、`zones`、`suburb_stats` |
| `app/auth/` | 账号(`passwords` scrypt、`store` 用户/会话表、`routes` `/api/auth/*`,登录失败限流)与收藏(`favorites` `/api/favorites/*`,快照只存事实字段,不对 properties 建外键) |
| `app/i18n.py` | **服务端标签**的英文版 + `check()` 完整性自检 |
| `app/web/` | 单页前端:`index.html` / `app.js` / `app.css` / `i18n.js`,外加 `auth.js`(登录注册弹窗)、`favorites.js`(收藏心与抽屉)、`map-glass.js`(毛玻璃矢量底图)。无构建步骤。 |
| `app/web/showroom/` | 首屏白模沙盘:`showroom.mjs`(主渲染代码)、`asset-loading.mjs`(本次加载独立队列及模型清理顺序)+ 原 GLB、贴图、相机 JSON。模型/贴图约 19MB,已入库;`draco/` 保留 Three 0.170.0 原配解码器和许可证,从同站加载 |
| `db/` | `docker-compose.yml`(pgvector/pg16,15432)、`schema.sql`、`setup_db.py`(一键建库)、`seed/properties.dump`(房源种子) |
| `docs/en/` | 给组员的英文指南:功能、配置(换 LLM)、开发、排错。与根目录 `README.md` 一起是对外入口 |
| `pipeline/` | 一次性数据抓取与基准构建脚本 |
| `eval/` | 幻觉率评估与词汇覆盖评估 |
| `tests/` | 纯脚本测试,`python tests/test_x.py` |
| `_ui-lab/` | **experimental** — 另一套备用前端,自带 8080 服务并把 `/api/*` 反代到主站。**不碰 `app/`**,未集成 |
| `design/`、`qisuo-redesign/` | 设计稿,非线上代码 |
| `design/white-city/` | 首屏沙盘的**制作端**:`blender/*.py` 是建模/烘焙/后期/导出脚本(源码),`*.md` 是实验记录与复盘。其余是渲染产物、`.blend` 与历史实验页(v3–v24 实时光照路线,已不是主路径)。**整个目录约 2.5GB;`.gitignore` 只放行文本源码(.py/.mjs/.js/.html/.md)和测试要用的 `city-04-assets.json`,二进制留在本机** |
| `_rhine_analysis/` | **与本项目无关**,见 PROJECT_STATE 的 Known Issues |

## 请求流(一次提问)

1. 浏览器 `POST /api/chat {thread_id, message, lang}`
2. `server._run()` 在工作线程里跑图(图是同步的,含 LLM 调用,不能占事件循环),
   事件经队列回到异步端,以 SSE 逐个下发
3. 图依次跑:
   - `parse_intent` — LLM 把自然语言转成结构化参数(唯一一次解析用的 LLM 调用)
   - `search` — pgvector 语义检索 + SQL 硬条件(含 `max_distance_cbd_km`:按坐标算球面直线公里、保留一位小数比较,
     与页面「距 CBD」同口径,缺坐标退回数据集列),初始候选上限5,000；ROI多取1条哨兵判截断，保存本请求假设快照
   - `analyze` — 批量估值 + `formulas.investment_metrics()` 算全套投资指标
   - `enrich` — 对候选算周边证据、抽象属性分数、分项强度、全库排位、规划/学区
   - `rank` — 筛选 + 排序，留前20套给"换一批"；ROI未能认证前20或筛空时在节点内翻倍重跑search/analyze/enrich，单轮上限40,000，给准确范围说明。
     条件分两档:`strength=required` 硬剔除;设施距离与环境偏好默认 `preferred`,不剔除,排序后由
     `_prefer_amenities` 把满足项多的稳定前置,说明写「展示的 N 套中 M 套满足」(相对调整路径里环境偏好仍按门槛)。
     规划条件(含 `planning.RISK_GROUPS` 六类按类排除)一律硬剔除。排序口径另有 `nearest:<kind>`(到 amenity_needs
     里那类设施的距离升序)
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
| `GET /api/property/{id}?lang=` | 按编号实时算一套房的详情(`graph.detail_metrics`:analyze → enrich → present),收藏与并排详情用 | 否 |
| `GET /api/session/{thread_id}` | 只读:该会话在服务端还在不在(`active`、`params`、当前展示房源 id),刷新页面后核对用 | 否 |
| `POST /api/auth/register` · `login` · `logout`,`GET /api/auth/me` | 账号;会话令牌放 HttpOnly `nw_session` Cookie,库里只存 sha256 | 否 |
| `GET/PUT/DELETE /api/favorites[/{property_id}]` | 收藏(需登录);PUT 时服务端从 properties 取快照 | 否 |
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
- **设施同义说法**:`refinement.normalize_amenity_changes` 在应用前把模型写成设施名字段、或对设施做
  relative/prioritize 的变更确定性改写为 `amenity_needs`(默认 1500 米、「再近一点」收紧到约 2/3、
  prioritize 另加 `nearest:` 排序)。
- **首轮的 refine**:没有上一轮时,模型判成 refine 的变更应用到空条件上、作为 `new_search` 返回;
  首轮对环境属性的 relative(「最好安静一点」)改成 preferred + 推断门槛 60;价格等相对调整没有基准仍澄清。
- **删除不存在的条件**(列表项)抛 `ClarifyChange`,不再静默当成生效。

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

`explain` 只拿到页面上看得到的事实(`graph._explain_fact`):去掉车位、坐标、内部编号;土地/建筑面积
记录为 0 视为缺失;附带 `area_suspect`(`graph.area_suspect` 判定自相矛盾的面积记录,`analyze` 里同一处算出、
详情页显示「记录值存疑」)。提示词要求排序方式只能照 `ranking` 口径说。

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

`auth.js`、`favorites.js` 与 `app.js` 不互相引用,只通过 window 事件与少量全局通信:
`nw:lang`(切语言)、`nw:auth`(登录状态变化)、`nw:detail`(详情打开/关闭,带房源 id 或
令牌与 `user` 标记,用于「关闭详情回到收藏抽屉」);全局 `nwAuth`、`nwFav`、`nwOpenDetail`、
`nwCompareIds`。并排详情(最多 3 列、按段对齐、只看不同、最优标记)在 `app.js` 的 compare 区块。

地图:Leaflet 负责图钉、取景、测距;底图由 `map-glass.js` 懒加载 MapLibre GL +
maplibre-gl-leaflet,用 OpenFreeMap 的 positron 矢量样式逐图层改色后挂进 Leaflet 的瓦片层;
没有 WebGL 或 CDN/样式取不到时退回 OSM 栅格瓦片(带浅色滤镜)。面板是「一整块厚玻璃」:
`.map-frost`(四周 backdrop-filter 磨砂,左侧最厚)+ `.map-glass`(边缘斜面光与高光),
二者都 `pointer-events:none`;取景内边距与磨砂宽度一致,房源落在中间通透区。
选中房源只给图钉加中性光晕(原黄色颜料已撤,最终样式待所有者定)。

首屏背景有两套,互为回退:桌面和手机支持 WebGL2 且资产加载成功时都用 `showroom.mjs` 的白模沙盘,
否则用 `app.js` 里 `drawCity()` 生成的 SVG 城市。切换由 `<div id="app">` 上的
`data-showroom="ready"` 驱动,CSS 决定谁可见。手机共用原模型、贴图与构图,输入框保留窄屏可用宽度;初始化、显示及转场交互不再受 900px 门槛限制。
支持判断使用唯一实际 renderer,创建失败保留 SVG,不额外分配 WebGL 探测上下文。182 个内嵌图像与外部贴图共用本次加载的并发 2 队列,成功或失败均释放 slot;不改全局加载器。DRACO 上限 1 worker,即使模型先失败,也等待另一个解析及已提交的解码任务结束,拒绝关闭后的新任务,再释放 worker。
城市目标保持原 DPR 上限 2 与 4×MSAA;户型目标在首次可见转场帧才克隆分配,首屏使用透明 1×1 占位贴图。后续转场与退出重入复用同一目标,resize 同步尺寸。全部原贴图仍会解码和驻留;限并发不等于降低最终显存需求。

工作区交互(2026-10-05/06):
- 详情窗在工作区由 `dockDetail` 贴在对话栏上(按栏实测尺寸,仍可拖),列表与地图完整可见;并排对比三栏布局盖
  「对话 + 列表」、两栏布局只取够放 n 列的宽度。首页与窄屏不变。标题栏拖动在按下任何控件时不触发(否则
  `setPointerCapture` 会吞掉栏内按钮的 click)。
- 点地图图钉 = 开详情 + `focusCard` 把列表滚到同号房卡;房卡 ↔ 图钉悬停联动(`hlPin`/`hlCard`)。
- 排序菜单由 `sortOptions` 按当前条件生成:只列条件里真有的 `nearest:<kind>`,点名地点才列「离「X」从近到远」。
- 「+ 添加条件」打开 `openAddMenu`,只列未设的条件,复用条件卡的编辑框直接 `refine`(不经过 LLM)。
- 刷新恢复:每轮回答后 `saveSession` 把「原话 + 完整回答 + 当轮结果快照」存 sessionStorage(最多 20 轮),
  加载时沿用原 thread_id 逐轮重放(旧回答的编号仍指向当时那批),再查 `/api/session/{id}`,
  服务端会话不在或不一致就按原条件自动 `refine` 一次;「新对话」清除。
- 条件卡按实际行为分组:required 的设施距离/环境偏好与规划条件在「必须满足」,preferred 在「优先考虑」。

注意:Leaflet 的全局是 `L`,所以文案表叫 `T`,不要再引入名为 `L` 的局部变量。
