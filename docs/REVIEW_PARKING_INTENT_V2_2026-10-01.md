# 房源车位意图 v2 独立复审（2026-10-01）

结论：**revise，不合入。** 三个原始反例已修好，但两类新反例未解决。不修改主项目源码，不动 Claude 候选；此前可靠 UI/facts 修订及 ROI 修订保留。

## 已核实

- 候选从当前主 graph.py SHA-256 6CD682ABBE7A16318C6C1D07DB030737934AC3D00F1AAF422EC233F1C07FF986 开始；主文件仍一致。
- 候选 graph SHA-256 37616F67B23C85185FA691A0D83D51503C7C881CF61C42257D9010807A6D78A8。
- 稳定补丁 PARKING_INTENT_V2.patch SHA-256 DA2945079A6081CBE1537D207DAFC6F825905AE28830C434637A1C87582139A6。
- 检查点实际文件名为 PARKING_INTENT_V2_CHECKPOINT.md。
- 原 near a public car park、靠近公共停车场、near The Garage Cafe 的分类、semantic_query 和 description_query 均保留。英语 without a garage 及公共停车场混合房源garage例通过。
- 候选现有37/37离线断言通过；独立补充8项中5通过/3失败。均为AST真实函数、假依赖与合成输入，不导入应用，不使用环境配置、DB、模型或LLM。

## R-PV2-01：公共设施保护跨越房源要求

| 用户输入 | 模拟解析字段 | 实际 | 期待 |
|---|---|---|---|
| 靠近公园，房子要有停车位 | house near park with parking | kind=None、无房源车位unsupported、原parking保留 | kind=property、无法核验说明；保留公园要求、去掉自带车位条件 |
| 靠近商场，公寓自带停车位 | apartment near shopping with parking | 同上 | 同上，保留商场 |

根因：_PUBLIC_PARKING_RE 的“靠近/附近/周边/旁边 + .{0,8}? + 停车场/位”吞掉逗号和房源所有关系。_property_parking_spans 因与此公共span重叠而忽略真正的自带车位要求；_parking_kind 也把它保护掉，返回None，连条件式核验提示也没有。

最小修订：限制公共设施保护范围，不能跨句/分句边界或房源所有关系；原3项公共设施/地点例须保持通过。再查无标点的相同混合输入，避免只为逗号断言改正则。

## R-PV2-02：解析后的裸词仍进入检索

用户原话“房子要有车位”，假解析 semantic_query=three bedroom house garage、description_query=garage。

实际：kind=property、unsupported_asks=[房源车位]，但两个字段完全保留garage。期待：明确自带车位要求不重新成为语义检索条件，保留three bedroom house等其余意思。

根因：_sanitize 虽知道用户明确问房源车位，却只用 _property_parking_spans 清理生成字段。该识别器需要with/要有等所有关系；LLM若把短语压成garage，清理器不认识它。实际 search 把semantic_query传给search_properties，后者调用模型encode并按pgvector相似度排序；description_query也可能在后续prepare_refinement重建时进入semantic_query。因此这不是只影响文案的测试技巧。**没有调用真实模型/PG，未证明某次真实结果排序实际改变。**

最小修订：在用户已明确自带车位的前提下，处理解析器的等价缩写/翻译字段，同时保护公共设施/地点名；含义不明的原始查询仍保留。不能对所有garage词全局删除，也不能只靠提示词保证解析器不生成裸词。

## 验证和浏览器门槛

- 日志：D:/projects/capstone-audit-20261001-parking-v2/logs/candidate_37.log。
- 原始输入与实际字段：同目录 independent_flow_review.json。
- 独立期待/实际及5通过3失败：independent_assertions.json。
- 同目录 manifest.json / before/ / git_status.before.txt 保存哈希、补丁、原主字节和dirty快照。未改主源码，未新增主项目测试，未部署/push/commit。
- 按“审核通过后再做浏览器”的门槛，本轮未启动真实浏览器或服务；此前合入的UI表达式11项不能当作真实浏览器证据。新发现的两个根因先交最小修订，不扩大重测。
- 通过后沿用前一报告的纯静态upstream＋合成响应方案：详情及收藏详情双语0/null/正数均无车位行，Parking/专名原文保留；主动自带车位请求的声明从假解析/LLM响应生成，拒绝所有未匹配API/外部请求，不写DB/不调用真实LLM。不关闭浏览器安全设置。
- 真实LLM遵守提示词、真实模型/PG、所有动态语言和完整网页仍未验证。旧库映射跟进/迁移/回填取消，估值特征与数据保留。

Shared state updated:
- PROJECT_STATE: yes
- TODO: yes
- ARCHITECTURE: no
- DECISIONS: no
