# WAVE08 ROI 审查检查点（2026-10-01）

> 后续状态：WAVE08及三项最小补充已合入，主源码回归通过，当前结论见 [有限合入记录](MERGE_WAVE08_ROI_2026-10-01.md)。以下保留为合入前审查检查点。

## 当前结论

**离线补丁已准备；主产品尚未合入。** 原 WAVE07B 的三个反例在冻结 WAVE08 上均已通过；独立进一步发现文案精度、回滚缓存和回滚上限提示三个小问题，已在审查者独立暂存副本做最小修正并逐项验证。等待协调任务的只读 PostgreSQL 结果，随后才能决定是否选择性合入并在主源码运行必要回归。不能把暂存修正或 Claude 报告写成主项目已修。

主项目仍使用旧 ROI 毛回报率预选；既有 DEF0001/0010/0011 和其他修订保留。本次没有读取 .env、修改 Claude 副本、访问 DB、启动服务、写真实数据或调用模型/LLM/API；所有审计产物在 D 盘。

审查者目录 `D:/projects/capstone-audit-20261001-roi08`：
- `frozen/`：从稳定 WAVE08 diff 重建并与 work 文本比对一致的审查对象。
- `stage/`：冻结补丁加以下三个最小补充。
- `MERGE_READY.json`：主文件写前 SHA-256、冻结/暂存源码指纹及未合入状态。
- `selected_vs_main.diff`：四文件待合入的精确差异；不使用累计隔离副本整文件覆盖。

## 逐步反馈与不变量

| 项目 | 不变量/反例 | 冻结 WAVE08 结果 | 最小修订及定向复测 |
|---|---|---|---|
| 原距离筛空 | 5000 个高 ROI 候选距指定地点5000m，第5001个距50m，要求100m内 | 返回5001，查询[5001,10001] | 原修订已通过，无额外算法改动 |
| 原收益门槛筛空 | 5000套1000000/50000，第5001套10000/550，毛回报率≥.053 | 返回5001，查询[5001,10001] | 原修订已通过 |
| 原费用漂移 | SQL前费用199999，之后进程全局变0 | 指标仍使用199999的请求快照；排序与该快照一致 | 原修订已通过；故意丢快照的路径撤回认证，新搜索刷新快照也通过 |
| 新文案精度 | 指标 opex=.284、当前全局=.2；解释必须写28.4%而非28% | zh/en 都写28% | 两处 `{opex:.0%}` -> `{opex:.1%}`；2/2通过，与原 describe 的一位小数口径相同，ROI公式未改 |
| 新回滚缓存 | 已展示费用2000；新请求费用3000且无兼容结果，恢复旧房源时所有相关缓存也应恢复 | 旧指标2000，但 assumption_snap / roi_pool 各3000 | `refinement.snapshot` 仅加 roi_pool、assumption_snap 两个键，沿用deepcopy与缺键None；回滚后全为2000，原ID/条件保留，旧状态None通过 |
| 新回滚上限提示 | 新请求扩到cap仍空，恢复旧结果；本轮notice应说明池外仍可能匹配 | `_no_match` 只往notes写cap，但 `_unmatched_refinement` 恢复旧结果时丢notes，notice没有cap说明 | 把同一cap_note同时接到确定性turn_notice，不覆盖旧ranking；zh/en分别通过，临时roi_limit/_roi_unproven不持久化 |

`targeted_review.log` / `targeted_results.json`：冻结 WAVE08 **5/8** 通过，失败是两种语言精度和缓存回滚。该缓存反例也保存了没有cap说明的原notice。

最小补充逐项日志：`precision_after.log`、`rollback_after.log`、`rollback_and_cap_after.log`、`rollback_and_cap_en_after.log`。

组合暂存补丁：`targeted_stage_review.AFTER_HARNESS_FIX.log` / `targeted_stage_results.json` **8/8**。第一次组合脚本仍读取未合入的主项目旧refinement.py，产生7/8；只修正审计路径后8/8，不是暂存产品修正失败，不隐藏初次日志。

脚本 AST 执行 actual search/analyze/rank/formulas；DB为内存SQLite，估值、rent_source与地理富化替代。费用漂移为确定性交错，不是HTTP并发实验。没有真实payload发生率证据。

## WAVE08 本体核对

- 假设键名与主 assumptions.py / API一致：`opex_rate`、`other_acquisition_costs`。首search读取一次snapshot，扩容沿用；analyze和每套指标assumptions使用同一份。没经过search的按ID详情路径仍用原全局读取方式。
- 精度保证增加首20套ROI重算一致性检查；不一致时不认证、不无意义扩容，并披露假设不同。数学认证只限可证明的前缀，不能将40,000上限当无限全局保证。
- 空筛选会扩容；未解析的学区或指定地点属于确定性不可能条件，不扩容。中间轮不会对SSE输出半成品。
- relative_preferences 文案已按实际search_order=roi及截断/取完区分，不再称语义相关5000；旧错误注释已改。
- 各SQL筛选继续走同一SEARCH_KEYS，候选_COLUMNS未删字段。最终估值、rent_source、地理证据依赖仍按原analyze/enrich调用。真实模型和几何路径没有在本轮跑。
- 瞬态roi_limit不进State，_roi_unproven在rank出节点前移除；新增持久快照字段必须随回滚恢复，以上最小补充处理了这个一致性缺口。

Claude冻结报告的专项33/33、精确30/30、扩容22/22与公式回归为**Claude已有证据**，本轮未重复整套重测；独立检查结果单列如上。若合入，需从主源码运行相应定向与必要相关回归。

## 仍需协调证据与限制

- **只读 PostgreSQL验证尚未回传给本审查轮。** 已请求报告路径；不并行发起数据库负载。开发库归属由协调任务确认 capstone_postgres:15432、共享卷旧容器停止；本轮未独立核验/启动任何容器。
- PG表达式、实际筛选/候选顺序、查询计划及数据域需对照协调报告。对测试对象不能仅靠SQLite通过就下真实数据库结论。
- 40,000为单轮上限，完整5k/10k/20k/40k扩容最坏重算75,000套；20,800源行时分析/富化累计55,800套，SQL返回额外3个哨兵（共55,803）。哨兵在search裁掉后不送analyze，不能把55,803都称估值计算量。
- 原0.67秒/33MB仅合成Python+SQLite，真实PG/XGBoost/设施、规划与环境计算未测；没有缓存去重或时间预算。
- `server.py`最终done事件仍读全局假设，虽然当前app.js的done处理不消费这个字段，API一致性仍是残留核查项，未修且不得宣称整链路假设完全一致。
- `_assumption_lines`的二次快照检查不能对ABA变化保证原子性；按ID详情也仍分次读全局值。本轮只解决本请求正常search/expand/analyze路径，真实HTTP并发未测。
- 真LLM遵守新提示词、真实浏览器、真实模型/地理计算均未验证；没有迁移、重导入、重训、部署、commit或push。

## 下一步

取得只读PG报告后逐项核对，而非重跑数据库。若证据支持，再按MERGE_READY四文件指纹确认无新修改，选择性应用selected_vs_main差异，加入上述最小修正的定向回归；运行主源码回归并更新ARCHITECTURE/当前状态，DEF-0007仍标部分修复。若PG结果或基线有冲突，保留此暂存检查点，不整文件覆盖。
