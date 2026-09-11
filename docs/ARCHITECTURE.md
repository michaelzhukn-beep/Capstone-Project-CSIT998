# ARCHITECTURE

> 这份文件描述**系统现在实际是怎么工作的**。不写理想架构;真要写规划,标 `planned`。
> 只在架构真的变了才更新(判据见 `AGENTS.md` §4)。

最后更新:2026-09-11

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
| `app/search/search.py` | 语义检索 + SQL 硬条件。嵌入模型在进程内。 |
| `app/analytics/` | `valuation`(XGB 推理)、`train_valuation`(训练)、`formulas`(投资公式)、`assumptions`(可调假设 + 边界) |
| `app/amenities/` | `registry`(数据源与属性的唯一注册表)、`context`(证据 → 分数)、`nearby`(设施/地名/距离)、`planning`、`zones`、`suburb_stats` |
| `app/i18n.py` | **服务端标签**的英文版 + `check()` 完整性自检 |
| `app/web/` | 单页前端:`index.html` / `app.js` / `app.css` / `i18n.js`。无构建步骤。 |
| `pipeline/` | 一次性数据抓取与基准构建脚本 |
| `eval/` | 幻觉率评估与词汇覆盖评估 |
| `tests/` | 纯脚本测试,`python tests/test_x.py` |
| `_ui-lab/` | **experimental** — 另一套备用前端,自带 8080 服务并把 `/api/*` 反代到主站。**不碰 `app/`**,未集成 |
| `design/`、`qisuo-redesign/` | 设计稿,非线上代码 |
| `_rhine_analysis/` | **与本项目无关**,见 PROJECT_STATE 的 Known Issues |

## 请求流(一次提问)

1. 浏览器 `POST /api/chat {thread_id, message, lang}`
2. `server._run()` 在工作线程里跑图(图是同步的,含 LLM 调用,不能占事件循环),
   事件经队列回到异步端,以 SSE 逐个下发
3. 图依次跑:
   - `parse_intent` — LLM 把自然语言转成结构化参数(唯一一次解析用的 LLM 调用)
   - `search` — pgvector 语义检索 + SQL 硬条件,最多取 `CANDIDATE_LIMIT = 5000` 套
   - `analyze` — 批量估值 + `formulas.investment_metrics()` 算全套投资指标
   - `enrich` — 对候选算周边证据、抽象属性分数、分项强度、全库排位、规划/学区
   - `rank` — 软条件筛选 + 排序,产出 `ranking` 口径说明;留前 20 套给"换一批"
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

`refine` / `rebatch` 都走 `GRAPH.update_state(..., as_node=...)`,把新状态当作某个节点的
输出写进会话,再从它后面继续 —— 这是"不重跑整张图"的机制。

## 数据流与真实性分层

三类数字在代码里就是分开的,前端也按三类上不同标记:

- **实测/法定** — 数据库字段、维州法定印花税(`formulas.stamp_duty_vic`)
- **基于假设** — NOI / Cap Rate / ROI,依赖 `assumptions`(运营支出比例、过户杂费)
- **模型预测** — `valuation.predict_values()`,带按房型的典型误差

`formulas.investment_metrics()` 是**唯一**一处把这些串起来的实现,`analyze` 节点和
`/api/recalc` 共用它 —— 前端不自己算公式。

## 抽象属性(安静/热闹/…)

`app/amenities/registry.py` 是**唯一**的注册表:数据源、证据项、属性权重、
不支持项清单全在这里。提示词片段、`/api/meta`、评分、英文标签都从它生成。
加一个数据源只改这一个文件;`tests/test_registry.py` 会挡住"加了源却忘了配别处"。

打分:原始证据 → 用 `data/context_baseline.json` 的分位表转成 0~1 → 按权重合成
0~100。合成分**本身不是分位数**,所以另存了 `score_quantiles`,`context.score_rank()`
把分数翻译成"高于全库百分之几"。

## 国际化

| 类别 | 位置 | 切换方式 |
|---|---|---|
| 界面文案(按钮、段标题、整句) | `app/web/i18n.js` | 换 `T` 表后重渲染 |
| 服务端标签(属性名、设施名、排序口径、规划分区) | `app/i18n.py` | 重取 `/api/meta?lang=` |
| LLM 生成的说明、rank 的口径 | `graph.py`(`_t()` + 提示词追加段) | 重跑一次 `refine` |

原则:**一个字符串只有一个出处**。注册表在后端,它的英文也在后端。

## 前端结构

单页,无构建。`app.js` 一个 IIFE,内部按区块组织:状态 → 工具 → 对话 → 条件卡 →
结果卡 → 地图 → 详情窗 → 首屏词条 → 语言切换 → 启动。

注意:Leaflet 的全局是 `L`,所以文案表叫 `T`,不要再引入名为 `L` 的局部变量。
