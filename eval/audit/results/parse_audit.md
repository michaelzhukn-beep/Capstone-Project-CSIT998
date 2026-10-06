# 意图解析审计

22 句 × 3 次,2026-10-06 19:20,耗时 17s,失败 1。明细见 `parse_audit.json`。

| 状态 | 编号 | 说法 | 稳定 | 问题 |
|---|---|---|---|---|
| PASS | K2 | 80万以下的两房公寓 | True |  |
| PASS | K2 | 预算 $800k,2 bedroom apartment | True |  |
| PASS | K2 | 800,000 以内 两卧 公寓 | True |  |
| PASS | K2 | Budget under 800k, 2-bed unit | True |  |
| PASS | K2 | 150万到200万之间的四房 | True |  |
| PASS | K2 | 1.5m以下的 townhouse | True |  |
| PASS | K1 | Richmond 附近安静的独栋 | True |  |
| PASS | K1 | richmod 安静的house | True |  |
| PASS | K1 | 租金回报率最高的房子,100万以内 | True |  |
| PASS | K1 | 回报率至少5%的房子 | True |  |
| PASS | K1 | 离火车站 500 米内的三房 | True |  |
| PASS | K1 | Brunswick 3 bed house under 1.2 million, close to tram | True |  |
| PASS | K1 | 最便宜的房子 | True |  |
| PASS | K1 | 离 Monash University 3公里内的房子 | True |  |
| PASS | K1 | Balwyn High School 学区内的房子 | True |  |
| PASS | K1 | 没有历史保护限制、可以翻建的房子 | True |  |
| PASS | K1 | 被低估的两房 | True |  |
| PASS | K1 | 估值低于售价的房子 | True |  |
| PASS | K3 | 步行 10 分钟能到火车站的房子 | True |  |
| FAIL | K3 | 学校排名前十的学区房 | False |  |
| PASS | K3 | 开车 20 分钟能到 CBD 的房子 | True |  |
| PASS | K3 | 朝北、采光好的房子 | True |  |
