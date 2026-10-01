# 网页车位意图 v4：审核、选择性合入与最小浏览器验证（2026-10-01）

结论：**v4定向状态修复与已审查前置修订已合入当前主项目，定向回归和最小实际前端浏览器验证通过。** 这是有限语言规则与合成场景的结论，不等于真实LLM/估值模型/数据库验证或全量无bug。

## 合入范围

1. graph.py的前置意图修订：明确/歧义/公共设施及专名区分；清理明确自带车位的派生描述，公共public parking重叠保护；核验提示及解析失败路径。已有facts副本排除car_spaces保持。
2. v4生命周期：_sanitize的preserve_property_parking/allow_property_parking由refine流程传入。上轮canonical标签仍存在时保留；通过既有source逐字证据验证的结构化remove才抑制重加。只改预算、明确取消、无结果回滚及新搜索重置已检查。
3. app/i18n.py仅补房源车位 -> property car spaces，供英文条件卡使用。
4. 新增两份离线脚本test_parking_intent_offline.py、test_parking_lifecycle_offline.py。生命周期脚本移除固定机器路径，用项目ROOT读取refinement，新增非法取消source保留旧状态断言。
5. 既有ROI离线夹具仅一行ns.setdefault保留已有标准库re，原42项断言不改。首尝试发现假re导致dict.finditer异常后立即回退本轮产品改动；复测通过后才重新合入。最初完整日志被重跑替换，实际观察摘要明确记录在logs/first_attempt_summary.json，不将摘要冒充原日志。

不改正式前端app.js/favorites.js及其之前的可靠车位移除；不修改数据、模型、数据库或认证权限。不迁移、回填、重导入、重训、commit/push/部署。不启动真实应用或使用付费API。Claude各隔离候选未改。

## 主源码离线结果

| 脚本 | 结果 | 实际范围 |
|---|---:|---|
| test_parking_intent_offline.py | 47/47 | 真实AST函数、合成输入、假LLM；公共/专名/否定/混合及派生描述、英文映射 |
| test_parking_lifecycle_offline.py | 17/17 | 实际parse/refinement/apply_changes/回滚函数；预算保留、取消、重置、非法取消来源 |
| test_parking_output_copy_offline.py | 24/24 | facts副本、0/None/3模型特征值与metrics保留 |
| test_parking_visibility_ui.mjs | 11/11 | 实际详情metadata表达式、收藏共用renderer |
| test_roi_review_repair_offline.py | 42/42 | 既有ROI排序/扩容/快照/披露，内存SQL与假模型 |
| test_i18n_semantics.cjs | 65/65 | 既有来源文案组合 |

日志均在D:/projects/capstone-audit-20261001-parking-v4/logs/。未扩大无关业务功能。

## 实际前端最小Chrome验证

已安装Chrome以无头模式、独立D盘profile运行。实际主项目app.js/auth.js/favorites.js/i18n.js/app.css原样由随机localhost夹具服务提供；仅HTML副本移除外部字体、地图库和showroom模块、注入测试driver。未关闭浏览器安全设置。页面CSP只允许本地资源/连接，夹具没有上游转发或数据库/LLM路径，未匹配API一律拒绝。使用合成账号响应，无登录/收藏写入。

**中文29/29、英文29/29，通过；拒绝请求0；JavaScript错误0。**

验证内容：

- 搜索详情：car_spaces=0/null/3均无车位行，床/卫/类型/距离仍显示；规划PO Parking/停车控制保留。
- 收藏详情：另用101/102/103三个合成收藏，触发实际/api/property路径再调用实际nwOpenDetail；0/null/3均无车位行。
- 主动车位请求：用户实际发送问句，页面显示无法核验/未按车位筛选说明；英文条件卡无中文canonical标签泄漏。
- 公共car park、中文公共停车场、The Garage Cafe、Parking Overlay问句不被假标为房源车位未支持。
- 所有页面资源与API请求由夹具白名单处理，未匹配请求0；本任务服务器PID已核实后关闭。

合成响应的核验文案由当前主源码_sanitize/explain（假模型输出）生成；meta来自当前translate_meta，投资数字来自当前公式的合成输入。**这验证真实DOM和前端流程，不证明真实LLM解析/生成会遵守提示词。** 无Leaflet/坐标/首屏动画，未测试地图、GPU视觉或生产登录。原始响应、请求记录、DOM、Chrome日志及结束记录见browser/fixture.json、result.zh.json、result.en.json、dom.zh.html、dom.en.html、session_closed.json。

## 精确差异与保护

只在相同基线下逐hunk构建修改，保留主文件原上下文/换行，不覆盖累计隔离文件。graph逻辑与v4候选一致；保留原换行后主字节哈希与候选哈希可不同。

| 文件 | before SHA-256 | after SHA-256 |
|---|---|---|
| app/orchestration/graph.py | 6CD682ABBE7A16318C6C1D07DB030737934AC3D00F1AAF422EC233F1C07FF986 | 71DA27222CB799752E8DE75A35FA2516DCF7AD3347ED390B652E0935EC2E8507 |
| app/i18n.py | B15E1BEFBD5255CC0CADFBB9863E02D5B77E68D23EA2F9CD4D6A028B5CECB78A | A39EEA4A3ECA48CB16DEDBB40037E202D07D90C7C074CFD75836F0AFFD5599FD |
| tests/test_roi_review_repair_offline.py | 0C858E9D20A865137AEE783253E4796C27E8CC2947A872DDF3C23AF9D58B73D2 | 9D94BEC9F7E230A4056FB779CF2ECEC06D69BC51F986991F03B4C411D29E0712 |

选定差异selected.patch、原字节before/、合入账本manifest.json均在D:/projects/capstone-audit-20261001-parking-v4/。前端、formulas/search/refinement/valuation及auth/store保护哈希保持，原79条dirty条目全部保留；代码合入后81条只增两项测试，记录收尾增加本报告。

## 仍未验证与限制

- 真实LLM分类、自然语言事实/数字描述及提示词遵守；真实PG/数据/估值模型与完整E2E。
- 未识别说法与混合歧义并非穷尽。Garage Cafe混合请求派生裸garage无法安全归属时仍保留歧义和未核验记录，不声称该文本已完美去除所有车位词。
- 底层旧0无法区分未知与真实0；当前选择是网页省略，保留模型特征。取消的映射/迁移/回填没有重新启动。
- ROI仍为此前部分修复：单轮40,000上限与真实后处理费用/并发假设限制见MERGE_WAVE08_ROI_2026-10-01.md，本轮不扩大该功能。
- 未提交、推送或部署，动画任务保持暂停。

Shared state updated:
- PROJECT_STATE: yes
- TODO: yes
- ARCHITECTURE: yes
- DECISIONS: yes
