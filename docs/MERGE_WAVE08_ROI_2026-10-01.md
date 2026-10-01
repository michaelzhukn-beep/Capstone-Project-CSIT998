# WAVE08 ROI 有限合入与主源码回归（2026-10-01）

## 结论

**WAVE08 及审查者三个最小修订已选择性合入主项目，DEF-0007 标为部分修复。** 根据冻结差异、原反例、主文件基线及协调只读 PG 检查点，当前证据足以把候选预选从毛回报率改为 ROI 预排序，并在同筛选/同假设下作有界扩容与最终 Python ROI 重排。不能宣称全面修复、所有动态组合穷尽，或任意数据量的全局最优。

主目录 `D:/projects/Capstone-Project-CSIT998`；审计目录 `D:/projects/capstone-audit-20261001-roi08`。本轮没有执行任何 DB 命令、模型/地理计算、LLM或网络请求，没有迁移、重导入、重训、部署、commit、push或生产数据写入；PG证据由协调任务只读取得。本地HEAD核对为 `60309963f512d1919a45da85077fff7eb7d9ca6d`，本轮未提交。

## 实际修改

| 文件 | 已合入行为 |
|---|---|
| app/analytics/formulas.py | 单一税档表生成不取整ROI SQL、同式 Python 预估及取整误差界认证；用户最终数值仍走 investment_metrics |
| app/search/search.py | 白名单新增roi预排序，显式要求opex/fees，语义距离后加id稳定兜底，保留原SQL硬筛选和候选字段 |
| app/orchestration/graph.py | ROI多取1条哨兵辨截断；同请求假设快照；首池筛空或前20名未认证时翻倍重跑search/analyze/enrich；最终按Python公式；不可能的地点/学区不扩容；不一致时撤回认证；相对分支按真实ROI候选来源披露；解释沿用指标当时假设 |
| app/orchestration/refinement.py | 旧结果回滚同时恢复roi_pool及assumption_snap，原ID和条件保留 |

三个审查者最小补充：旧支出比例提示 `{opex:.0%}` 改 `{opex:.1%}`，准确显示28.4%；回滚快照添加上述两个键；达到上限而恢复旧结果时，将同一上限说明加到本轮确定性turn_notice，不改旧ranking。未带入车位迁移、未改UI/认证和其他产品文件。

新增离线回归：tests/test_roi_review_repair_offline.py、test_roi_exact_offline.py、test_roi_expand_e2e_offline.py。专项脚本保留原33项，加精度/回滚/上限/旧状态9项；只把原“28%”固定格式期待更新为一位小数“28.0%”，并另加28.4%真实边界，不为通过测试改变ROI业务意义。

## 基线保护与精准证据

写前四文件SHA-256全部匹配MERGE_READY；按selected diff逐hunk核对及应用，保留原行尾和未改上下文，不复制累计隔离文件覆盖。生成结果的规范化文本与独立审查stage一致；源码备份在merge_backup/，精确差异selected_vs_main.diff，完整写前/写后及新测试指纹merge_manifest.json。

| 文件 | 写前 SHA-256 | 合入后 SHA-256 |
|---|---|---|
| formulas.py | 37D14CF1734726923EE810E0AB414739081BFBF904ABAF5DA1D2A45920CEBD46 | 54FD41EFA3472603C62D21F558BBDA36EB9BA1BF5125F7E3E5748318389AC92D |
| search.py | 9367473D32FE77A570396189DBBFB5DFB2505F88E9059E29CC8A76797FF59BE8 | F137E19F4B4CBF5C53C8B996813DBD3313A60F18C95A5FAA45381096644BC191 |
| graph.py | 2B52C0F96E06D54C25C0A2B41A5ADBAB8AF5267A9B1CFE28AF83A477CABF089E | 05A8C8B7E69357F2F065BD3F2BD06F75AC6B54B04B6083D3D88C54100F986E67 |
| refinement.py | 97B22E31FD059AB8C9EB4CC256CCFC674A8D52D4E2444DC830E2F81565B1C226 | 136E70141E2DD30CABF8F898AB08B73D08CFC8189AAA010701972A7CA55E4F16 |

既有Cookie/格式修订源指纹未变，Git原有未提交状态条目保留核对在preservation_after_merge.json。状态条目保留不是全体dirty文件内容审计；本轮仅四份指定产品源、新三项测试及相关记录写入。

## 主项目实际回归

| 检查 | 结果 | 审计日志 |
|---|---|---|
| 专项修复/状态不变量 | 42/42通过 | main_roi_review_repair.log |
| ROI候选、公式/认证边界 | 30/30通过 | main_roi_exact.log |
| 扩容/筛选/稳定并列与合成大输入 | 脚本通过，22条ok输出含1条恒真informational，不将其计作实质覆盖 | main_roi_expand.log |
| 原投资公式 | 通过 | main_formulas.log |

ROI脚本从合入后主源码AST执行实际search/analyze/rank/formulas；DB为内存SQLite，估值、rent_source和几何富化使用替代。原距离/收益筛空5001反例、费用199999→0固定快照与不一致撤回认证、zh/en28.4%、回滚2000/3000缓存、双语cap notice及旧状态None都在专项回归中。不是实际API/浏览器/真实模型端到端验证。

## 协调只读 PostgreSQL 证据及为何允许有限合入

来源：`D:/projects/capstone-test-20260930-1340/wave07/artifacts/PG_READONLY_CHECKPOINT.md`，冻结副本PG_READONLY_CHECKPOINT.frozen.md；校验SQL哈希 `820D29D483F512B1E1A2C7E0658B09B4B3751E0ADC9BA50E89AC50F520BCB890`，本审查只读取报告、执行说明与输出。

- 本地真实表20,800行，price/annual_rent是非空整数、price非正值0行，支持本轮认证的数据域；不扩大为其他数据库也如此。
- ROI表达式已由真实PG解析并执行；一个费用2000/opex28%的聚合检查中取整界违规0，不取整与PG取整top20重叠20、top50排位差0。**这是PG与PG近似比较，不是Python逐行精确对比**；离线近值反例、认证余量与扩容仍必要。
- 候选C1 LIMIT5001的一次EXPLAIN ANALYZE实际扫20,800行、返回5,001行，执行246.070ms，external merge临时盘6872kB（约6.9MB）。使用库内一条embedding作为查询向量，未跑应用query encoding；不能把它当真实用户搜索、网络取数、模型、几何或E2E耗时。
- 只读事务、10秒语句超时、2秒锁超时且ROLLBACK，没有返回房源记录、没有写入。

这补足了SQL可执行性及真实表上的有限数据域/误差界证据，允许当前有界改动合入。未要求重复或扩大PG负载；性能/完整管线仍保留为后续风险。

## 部分修复的实际限制与下一项

1. 单轮ROI候选上限40,000。若前缀无法认证且数据仍超上限，只能在已取池里返回并诚实披露；没有无限全局保证。完整5k→10k→20k→40k最坏重算75,000套；当前20,800全取路径分析/富化55,800套，SQL含3个额外哨兵为55,803。
2. 真实PG只测C1一次；其余费用/筛选、LIMIT10001及后续轮的耗时未测。246ms不是总延迟，也不能乘次数当实测。排序会扫全部符合SQL条件者并可能溢盘，embedding并列排序开销仅计划推断，未单独验证；未改这个排序契约。
3. 真实XGBoost、rent_source数据库查取与地理/规划富化的扩容成本未测。没有缓存去重、应用总时间预算或取消机制新增；下一项是一个本地受控的真实analyze/enrich扩容基准，再据证据定预算，勿无限重测。
4. server.py的done事件仍读当前全局假设（当前app.js不消费该字段）；按ID详情仍分次读全局假设；解释的二次快照检查不保证ABA原子性。不得宣称整个API/并发链路完全一致。
5. 真实LLM遵守提示词、真实浏览器和真实端到端未验；原截断对真实结果的发生率仍没有比较。旧库车位仍由另一个任务负责，无迁移/匹配/修复授权在本轮执行。
6. 夜间919/53/33/132/701清单计数仍是原快照，未根据这些有限回归重新计算覆盖。DEF-0007由未合入改为**已合入部分修复**，不得写成全量已解。
