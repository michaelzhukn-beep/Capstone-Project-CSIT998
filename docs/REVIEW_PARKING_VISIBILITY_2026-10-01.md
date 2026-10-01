# 网页房源车位输出：独立审核与选择性合入（2026-10-01）

结论：**accept 可靠输出部分，revise 输入识别/文字清理部分；完整需求尚未完成。**

## 已合入的最小改动

- app/web/app.js：详情 metadata 移除车位项；收藏打开同一详情 renderer。结果卡和收藏列表原本已无车位项。
- app/web/i18n.js：仅删除中英两项 carSpaces 标签。
- app/orchestration/graph.py：explain 新建每行字典，发给 LLM 的 facts 排除 car_spaces。原 metrics 对象及字段保留；analyze 与全部非 explain 顶层 AST 完全未改。
- 新增 tests/test_parking_output_copy_offline.py 与 tests/test_parking_visibility_ui.mjs。未拷贝整份累计差异；此前 ROI、距离/价格格式和 0% 修订保留。

本轮不改底层数据/估值模型、API 或收藏快照。**不继续旧库映射跟进、迁移、回填、重导入或重训**。未调用真实 DB、模型或 LLM，未联网、提交、推送或部署。

## 拒绝的分支与最小反例

原稳定候选：D:/projects/capstone-test-20260930-1340/wave07/work/parking_visibility_candidate/PARKING_VISIBILITY.patch，SHA-256 DD832630708805043BF3FDA050751F2FED46DD218830F0A387075F56C75EEE67。

候选 _PARKING_ASK_RE 把公共设施/地点名也当房源车位；_without_property_parking 用同一词表删除检索文本。AST 加载实际函数后观察：

| 输入 | 期待分类 | 实际分类 | 被改后的检索文字 |
|---|---|---|---|
| near a public car park | 公共设施 | 房源车位 | near a public |
| 靠近公共停车场 | 公共设施 | 房源车位 | 靠近公共 场 |
| near The Garage Cafe | 地点名称 | 房源车位 | near The Cafe |
| a house with a garage | 房源车位 | 房源车位 | a house with a |
| Parking Overlay houses | 规划条件 | 非房源车位 | 原文保留 |

不变量：公共设施/地点名不得被当作房源车位事实；明确房源车位要求不得被表示为已筛选或已满足。候选只证明 Parking Overlay 排除，未满足前一个不变量，因此**整套识别、semantic/description 清理、解析失败车位分支及相关动态提示均未合入**。当前主项目明确车位要求仍没有这套确定性兜底，不能宣称完整修复。

下一最小修订应先区分语义目标、保护地点原文，再处理房源车位；仅增加英文词边界不能修好以上完整短语。混合“靠近公共停车场且房子有车位”需单独验证，不能一律保护 parking 而漏掉真正车位要求。有限规则不能代表所有动态输入穷尽。

证据：D:/projects/capstone-audit-20261001-parking/classifier_counterexamples.json；reproduce_classifier.py 只读运行稳定候选生成。未更改 Claude 隔离副本。

## 主源码离线回归

| 检查 | 原基线 | 主项目选择性合入后 | 限度 |
|---|---:|---:|---|
| explain 副本 / 模型特征 AST | 18通过/6失败 | 24/24通过 | 实际函数，0/None/3合成值；假模型/LLM |
| 详情 / 收藏 UI 表达式 | 6通过/5失败 | 11/11通过 | 双语0/null/3，实际metadata表达式；非浏览器 |
| 距离/价格/排位格式 | 本轮不重跑基线 | 35/35通过 | 既有离线回归 |
| 来源文案 | 本轮不重跑基线 | 65/65通过 | 静态组合 |
| ROI 审查回归 | 本轮不重跑基线 | 42/42通过 | AST/合成数据/内存SQL |
| app.js / i18n.js 语法 | — | 两项exit0 | Node语法 |

日志：D:/projects/capstone-audit-20261001-parking/logs/。初版审核夹具错误要求模型输入字典对象身份不变，23通过/1失败；代码本来会提取特征字典。修正为完整特征值一致后24/24通过，未为断言改变产品。analyze 全部特征仍取原值（含车位）；API metrics 保留0/None/3。new_search/refine/about_results 双语、编号偏移、LLM失败及原 metrics 不变已验证。

候选报告66/66仅覆盖其有限夹具，未覆盖本次设施/地点反例；不能作为全分支合入证据。没有新增真实数据、PG、估值模型或 LLM 输出证据。

## 精确差异和保留证据

| 文件 | 合入前 SHA-256 | 当前 SHA-256 |
|---|---|---|
| app/web/app.js | CD3F2067150129DF7125670FA6D0F9B2F888DE67E66A5F6B712B25861935A628 | C85DC11AFAD603C403C4CA0DAD8AB9A3D124540A16CCC1A615CBE938ECB3DD87 |
| app/web/i18n.js | 28F370042BF89B3D3BA12589968759C484358ECBBE089CF0C441DA8B8F3F6370 | 17F125E46634CBE82AB7E9076F486A6EBC7BBCAD87C8BBDE3EB980D567E8976E |
| app/orchestration/graph.py | 05A8C8B7E69357F2F065BD3F2BD06F75AC6B54B04B6083D3D88C54100F986E67 | 6CD682ABBE7A16318C6C1D07DB030737934AC3D00F1AAF422EC233F1C07FF986 |

选定差异：D:/projects/capstone-audit-20261001-parking/selected.patch；原字节备份：同目录 before/；合入账本：manifest.json。保护文件 formulas、search、refinement、valuation、favorites、auth/store 的 SHA 均保持本轮前值。原74条git dirty条目全部仍在，代码合入后76条仅增加两份定向测试；记录收尾再增加本报告，见 git_status.final.txt。未覆盖/删除原变更。

## 最小真实浏览器验证计划（未执行）

1. 用现有 tests/test_conversation_browser.mjs 隔离 fixture 与已安装无头 Chrome，先配只提供静态资源的本地 upstream 和 D 盘合成数据。默认 upstream 为8520，不能假定无真实服务；确认详情/收藏/auth/chat请求全部被本地 fixture 拦截，拒绝未匹配请求，不用真实账户/DB/LLM。不改浏览器安全设置。
2. 中英各查车位0/null/3的详情与收藏详情：metadata 无车位项，床/卫/房型/距离不变；结果卡、收藏列表也无车位数量。核对控制台/请求错误。
3. 规划 Parking Overlay 保留，公共设施/Garage Cafe名称不被删除。识别修订通过前不标这些交互已验收。
4. 后端只用假解析/LLM查明确车位需求、追问第2套、解析失败及混合规划/设施需求，确认未表示车位已筛选或满足。真实 LLM 遵守及完整页面验收另行验证，不自动消耗付费API。

Shared state updated:
- PROJECT_STATE: yes
- TODO: yes
- ARCHITECTURE: yes
- DECISIONS: yes
