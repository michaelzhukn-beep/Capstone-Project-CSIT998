# 房源车位意图 v3 独立复审（2026-10-01）

结论：**此前两个根因已修；发现多轮记录保留阻断，暂不合主。** 主项目源码（含已合入的UI/facts与ROI修订）保持原值。

## 已解决与有限验证

- v3中文公共设施保护不再跨越逗号/房源关系；“靠近公园，房子要有停车位”“靠近商场，公寓自带停车位”现在正确识别明确要求，并保留公园/商场。
- 明确原始车位请求派生出的three bedroom house garage / garage，可清理成three bedroom house / None。
- 原三项公共设施/专名反例、无逗号混合、英语without garage、中文不要车位均观察到正确行为。
- 原稳定v3现有45/45离线断言通过。只读AST使用合成输入；不导入应用、不读配置、不用DB/模型/LLM。
- 主graph基线SHA-256 6CD682ABBE7A16318C6C1D07DB030737934AC3D00F1AAF422EC233F1C07FF986；v3候选 8FF5B6291C6C5EF82AC33BB726DEB1E5A5616F62AC021AE471A90FB05CDFE2D7；完整v3补丁 EF4C61CE4761ACF1AD315FCF5D126056C83F2B625A47467D5B410BF0BF9FF8DE。

## 审核副本的两处小修（未合入）

1. 新派生尾词规则会把混合查询的house near public parking with garage改成house near public；误删公共parking。审查副本添加public parking公共短语识别，并在派生尾词删除前检查公共span重叠；结果保留house near public parking，去掉的仅是with garage。
2. 新动态标签房源车位在app/i18n.py的UNSUPPORTED_KEY_EN没有映射。meta_en把这张表提供给前端，条件卡找不到键会回显中文，虽explain另有英文helper。审查副本仅补property car spaces映射。

两处小修后的原45项+两项新增检查=47/47通过。源码和回归只在D:/projects/capstone-audit-20261001-parking-v3/staged/。完整审查候选差异为reviewer_corrected_candidate.patch；相对于原v3的公共保护小差异为reviewer_public_protection_only.patch。未修改Claude隔离候选。

## 新阻断：R-PV3-01 多轮清掉未取消的要求

不变量：只改预算时，原来未被取消的车位无法核验记录应继续保留；不能为了避免新公共设施请求误伤，清掉已有会话要求。

最小反例（真实_sanitize和prepare_refinement，合成参数）：

- 原始请求a house with a garage，经_sanitize得到unsupported_asks=[房源车位]、semantic_query=house。
- 下一句仅“预算改成80万”，复制这些参数、只设max_price=800000，调用prepare_refinement(raw, previous, user_query=本轮原话)。
- 实际unsupported_asks变为None。用户没有取消车位要求。
- 该结果在原v3和加公共保护/翻译小修后的副本都存在；47项夹具未覆盖它。

根因：_sanitize先无条件过滤所有房源车位canonical标签，仅在**本轮原话**kind=property时加回。新搜索中抑制模型误标公共设施是合理的，但refine输入来自上轮有效参数；同一清理方式丢失会话来源。prepare_refinement的第二次_sanitize同样如此。

用户影响：条件卡和后续说明不再保留此前要求无法核验的记录，削弱“保留未修改要求”的产品约定；可能让人误读为新结果满足旧需求。**未使用真实LLM，不声称已观察到模型虚假满足车位。** 需按新搜索/已有会话来源处理标签，验证仅改预算、明确取消、公共设施新查询及混合来源，不能继续只改词表。

证据：refinement_warning_loss.json及review_refinement.py；independent_flow_review.json保存原v3的公共parking误删及其余实际字段。日志logs/v3_original_45.log、logs/staged_parking_intent.log分别记录45/47项结果。

## 当前边界与后续

- 未合并任何本轮源码/测试到主项目；前述可靠输出修订、ROI、认证、格式修订及原有变更保持。保护哈希和dirty记录见manifest.json、git_status.final.txt。
- 按审核通过后再进浏览器的门槛，本轮未启动浏览器或外部服务；此前UI表达式检查不能当作真实页面证据。最小静态+合成响应浏览器计划仍见REVIEW_PARKING_VISIBILITY_2026-10-01.md：详情/收藏详情双语0/null/正数均无车位行，公共Parking/专名保留，主动请求显示无法核验/未筛选。
- 没有付费API、真实LLM、真实PG、模型、迁移、回填、重导入或重训；动画任务保持暂停。
- 识别是有限语言规则，不宣称无限动态输入穷尽。来源保留根因解决前不以45或47项通过宣称完整修复。

Shared state updated:
- PROJECT_STATE: yes
- TODO: yes
- ARCHITECTURE: no
- DECISIONS: no
