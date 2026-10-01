# 数据正确性测试清单

目标:界面上出现的**每一个数**都有一条可重复执行的检查。人眼抽查只用在规则判不了的地方。

四种检查手法:

| 代号 | 手法 | 能抓什么 |
|---|---|---|
| **INV** | 全库不变式:对 20,800 套全部跑一遍规则 | 越界、互相矛盾、空值伪装成 0 |
| **ORA** | 独立重算:不走系统代码,用另一套实现再算一遍,逐条比对 | 公式写错、索引/坐标错、缓存过期 |
| **MET** | 变形测试:输入做"不该改变结论"或"必然让结论变好/变坏"的改动 | 方向写反、LLM 解析不稳 |
| **AUD** | 人工审计:分层抽样,出一张对照表给人看 | 数据本身和现实不符(规则无从判断) |

脚本:`python -m eval.audit.data_audit`(确定性部分,不调 LLM)、
`python -m eval.audit.pipeline_audit`(排序筛选,不调 LLM)、
`python -m eval.audit.parse_audit`(LLM 解析稳定性)、`python -m eval.audit.explain_audit`(解释用词)。结果写到 `eval/audit/results/`。
Bug 记录:`eval/audit/BUGS.md`。

---

## A. 房源基础列(数据库直读)

| # | 检查 | 手法 |
|---|---|---|
| A1 | 行数 20,800;price / bedrooms / bathrooms / 经纬度 / annual_rent 无空值 | INV |
| A2 | 经纬度落在墨尔本范围内 | INV |
| A3 | price > 0;bedrooms、bathrooms、car_spaces 非负且在合理范围;极端值列清单 | INV |
| A4 | distance_cbd(数据集自带)与坐标到 CBD 的直线距离一致 | ORA |
| A5 | land_size / building_area:0 不能被当作真实面积使用 | INV |
| A6 | 房型只有 house / apartment / townhouse | INV |

## B. 年租金(DFFH 中位租金按区与卧室数匹配)

| # | 检查 | 手法 |
|---|---|---|
| B1 | 用 `rent_benchmarks_long.csv` + 映射表按数据库里的 bedrooms 独立重配,和 annual_rent 比对 | ORA |
| B2 | rent_source 各档占比;非"本区+同卧室数"的比例 | INV |
| B3 | 界面/LLM 对租金来源的措辞与实际粒度一致(不是这套房的租金) | AUD |
| B4 | 毛回报率极端值(<1.5% 或 >10%)清单 | INV |

## C. 投资公式

| # | 检查 | 手法 |
|---|---|---|
| C1 | 印花税:按 SRO 2008–2021 非自住税率表独立实现,全库逐条比对 | ORA |
| C2 | gross_yield / opex / NOI / cap_rate / total_cost / ROI 全库独立重算 | ORA |
| C3 | 分档边界(25k / 130k / 960k)两侧连续性与单调性 | MET |
| C4 | `/api/recalc` 与 analyze 同输入同输出;越界假设被拒 | ORA |
| C5 | 任一输入缺失时输出 None,不是 0 | INV |

## D. 估值与 80% 区间

| # | 检查 | 手法 |
|---|---|---|
| D1 | 全库:interval_low < range_low < pred < range_high < interval_high | INV |
| D2 | valuation_position 与 price、区间一致;predicted_gap 符号与 position 一致 | INV |
| D3 | 同一输入两次预测结果一致 | MET |
| D4 | 留出集分房型覆盖率接近 80%(已有测试,复跑) | ORA |
| D5 | 训练集内/外房源误差差异(已知问题,复测数值) | INV |
| D6 | 单调性:同一套房只加面积/卧室,估值不应明显下降(统计违反比例) | MET |

## E. 设施距离与计数(29 类 OSM 源)

| # | 检查 | 手法 |
|---|---|---|
| E1 | BallTree 最近距离 vs 暴力 haversine,抽 500 套 × 全部 nearest 类 | ORA |
| E2 | 半径计数 vs 暴力计数,nightlife 300m / shop 800m | ORA |
| E3 | 线状源(主干道/次干道/铁路):50m 重采样点距离 vs Richmond 原始 OSM 线段精确距离 | ORA |
| E4 | 面状源(公园/墓地按中心点存储)导致的"紧邻大公园却显示很远" | ORA+AUD |
| E5 | 学校小学/中学的名字归类规则抽查 | AUD |
| E6 | present 展示距离与 enrich 筛选距离同源同值 | INV |

## F. 15 个环境属性分

| # | 检查 | 手法 |
|---|---|---|
| F1 | 分数在 0–100;证据覆盖不足时属性不出现 | INV |
| F2 | 分位基准是否过期:用当前数据全库重算分位点,与 context_baseline.json 比对 | ORA |
| F3 | 方向:每个分项单独往"更好"方向推,分数不降 | MET |
| F4 | score_rank 随分数单调 | INV |
| F5 | 安静分高却紧邻未计入的道路(三级路/住宅路/电车线)—— 用 Richmond 原始 OSM 统计 | ORA |
| F6 | 相关性常识:安静 vs 热闹负相关;交通 vs 距 CBD 负相关 | INV |
| F7 | 按房型分位的"宽敞":公寓与独栋分开排 | INV |

## G. 学区 / H. 罪案率 / I. 规划

| # | 检查 | 手法 |
|---|---|---|
| G1 | 学区归属:抽样用 geojson 原始多边形 `contains` 独立判定 | ORA |
| G2 | 同一学段命中多个学区的房源(系统只取第一个) | INV |
| G3 | 没有任何学区的房源比例 | INV |
| H1 | 每个 suburb 能否查到罪案率;查不到的清单 | INV |
| H2 | 同名 suburb 映射到的 LGA 抽查 | AUD |
| I1 | 分区归属:抽样用原始多边形独立判定 | ORA |
| I2 | 未分类的分区 / 叠加层代码 | INV |
| I3 | can_redevelop / risks 与 overlays 一致;查不到分区时为 None | INV |
| I4 | ±350m 方框:东西向宽度是否真的是 700m | ORA |

## J. 排序与筛选(rank,不调 LLM)

| # | 检查 | 手法 |
|---|---|---|
| J1 | 每种 sort_by:结果确实按该键有序 | INV |
| J2 | 每种筛选:结果全部满足门槛;筛空时说明文字给出的"最近/最高"值正确 | INV |
| J3 | "在全部 N 套里挑"的 N 与真实符合硬条件的数量一致(候选池是否被截断) | ORA |
| J4 | 估值排序备注里的"只有 k 套落在区间外"数字正确 | ORA |
| J5 | 换一批:第 2–4 批与第 1 批排序连续、不重复 | INV |

## K. 意图解析(LLM)

| # | 检查 | 手法 |
|---|---|---|
| K1 | 同义改写 × 每句 3 次:价格/卧室/房型/区/排序/筛选解析一致 | MET |
| K2 | 数字单位:「80万」「$800k」「800,000」解析成同一个数 | MET |
| K3 | 不支持的需求(步行时间、学校排名)进 unsupported_asks,不被悄悄忽略 | MET |

## L. 解释文字(LLM)

| # | 检查 | 手法 |
|---|---|---|
| L1 | 回答里出现的每个数都能在 metrics 里找到(已有 eval/run_eval.py C 组) | ORA |
| L2 | 区间内的房源不被说成低估/高估 | MET |
