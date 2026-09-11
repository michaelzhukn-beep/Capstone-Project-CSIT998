"""规划分区与叠加层的验收。V7。

    python tests/test_planning.py

需要数据库(用真实房源坐标做全量核对),不需要 LLM、不联网。

这份数据和系统里已有的三种形态都不同:

    周边设施  点/线/面 -> 距离或密度 -> 评分
    学区      多边形   -> 归属       -> 事实
    罪案率    按区查表 -> LGA 级的数 -> 事实
    分区(这里) 多边形 -> **法条**   -> 事实 + 周边构成

所以它和 zones.py 一样在注册表之外,测试也单独写。

这套测试里最重要的一条是**未分类率的护栏**:Vicmap 会新增分区代码
(HCTZ 就是 2025 年规划改革新加的,一出现就让 24% 的房源归到了"未分类"),
而未分类是**静默失效** —— 分区照样查得到,只是 density 变成 unknown,
所有基于 density 的筛选悄悄失灵。护栏把这件事变成"错了会响"。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter

from app.amenities import planning
from app.core.db import close_pool, get_connection
from app.orchestration.graph import _PLANNING_NEEDS, PARAM_KEYS, RANK_KEYS

# ---------------------------------------------------------------- 数据加载

info = planning.warm_up()
assert info.get("zone", 0) > 20_000, f"分区只有 {info.get('zone')} 个,数据大概没抓全"
assert info.get("overlay", 0) > 90_000, f"叠加层只有 {info.get('overlay')} 个"

# ---------------------------------------------------------------- 代码归类
#
# 前缀匹配必须按长度降序,否则短前缀会抢走长代码。这几条钉住已知的坑:

assert planning._family("GRZ3")[2] == "medium"
assert planning._family("NRZ1")[2] == "low"
assert planning._family("RGZ1")[2] == "high"
assert planning._family("PPRZ")[2] == "open"
# HCTZ 是 2025 年新增的分区(近车站强制加密),曾经是最大的一块未分类
assert planning._family("HCTZ2")[2] == "high"
# IN1Z 不能被更短的前缀抢走
assert planning._family("IN1Z")[0] == "IN1Z"
assert planning._family("IN1Z")[2] == "industrial"
# 旧代码仍在用:R1Z 的官方 description 就是 GENERAL RESIDENTIAL ZONE
assert planning._family("R1Z")[2] == "medium"
assert planning._family("B1Z")[2] == "high"
# PPRZ / PCRZ / PUZ / PDZ / PZ 五个 P 开头的不能互相串
assert planning._family("PCRZ")[2] == "open"
assert planning._family("PUZ6")[2] == "public"
assert planning._family("PZ")[2] == "industrial"
# 认不出来的必须**原样暴露成 unknown**,不能被硬塞进某个已知类别
assert planning._family("ZZZ9")[2] == "unknown"
assert planning._family(None)[2] == "unknown"

assert planning._overlay_family("HO315")[2] == "build"      # 历史保护限制改建
assert planning._overlay_family("PAO1")[2] == "risk"        # 政府将来征收
assert planning._overlay_family("DCPO1")[2] == "cost"
# AEO(机场环境/噪声)和 EAO(环境审计/土壤污染)只差一个字母顺序,
# 含义完全不同,不能串。MAEO 是墨尔本机场专用的那一版。
assert planning._overlay_family("AEO")[1].startswith("机场环境")
assert planning._overlay_family("EAO")[1].startswith("须做环境审计")
assert planning._overlay_family("MAEO1")[1].startswith("墨尔本机场")
# RFO(乡村洪道)不能被 FO(洪道)抢走;RXO(道路封闭)不能被 RO(重建区)抢走
assert planning._overlay_family("RFO")[0] == "RFO"
assert planning._overlay_family("RXO")[0] == "RXO"

# ---------------------------------------------------------------- 单点查询

# Richmond 内城。这一带是 GRZ + 大量历史保护叠加层。
richmond = planning.for_one(-37.8206, 145.0003)
assert richmond.get("zone"), f"Richmond 查不到分区:{richmond}"
assert richmond.get("nearby_total", 0) > 5, "Richmond 周边分区一块都没查到,空间查询有问题"

# 没有坐标就返回空,不编造
assert planning.for_one(None, None) == {}
assert planning.for_batch([], []) == []
assert "无" in planning.describe({}) or "无规划" in planning.describe({})

# can_redevelop:查不到数据必须是 None,**不能是 True**
assert planning.can_redevelop({}) is None
assert planning.can_redevelop({"zone": "GRZ1"}) is True
assert planning.can_redevelop(
    {"zone": "GRZ1", "overlays": [{"code": "HO1", "effect": "build"}]}) is False
# 风险类叠加层不影响"能不能改建"这个判断 —— 那是两个不同的问题
assert planning.can_redevelop(
    {"zone": "GRZ1", "overlays": [{"code": "PAO1", "effect": "risk"}]}) is True
assert planning.risks({}) == []

# describe 必须写明"方形范围",不能说成"半径" —— 那是两个不同的东西
text = planning.describe(richmond)
assert "方形" in text, f"describe 没说明是方形范围:{text}"
assert "分区" in text

# ---------------------------------------------------------------- 全库核对

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude, suburb FROM properties "
                "WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
    rows = cur.fetchall()

lats = [r[0] for r in rows]
lons = [r[1] for r in rows]
result = planning.for_batch(lats, lons)
assert len(result) == len(rows)

covered = sum(1 for r in result if r.get("zone"))
assert covered / len(rows) > 0.99, f"只有 {covered}/{len(rows)} 套房查到分区,太低"

# ---- 护栏一:未分类率 ----
#
# 这是整套测试里最重要的一条。Vicmap 每周更新,新增代码是常态
# (HCTZ 一出现就让 24% 的房源变成 unknown)。未分类不会报错,只会让所有
# 基于 density 的筛选**静默失灵**。所以这里把它变成"错了会响"。
density = Counter(r.get("density") for r in result)
unknown_share = density.get("unknown", 0) / len(rows)
worst = Counter(r["zone"] for r in result if r.get("density") == "unknown").most_common(5)
assert unknown_share < 0.02, (
    f"{unknown_share:.1%} 的房源落在**未分类**的分区上,最常见的是 {worst} —— "
    "官方多半新增了分区代码。去 app/amenities/planning.py 的 _ZONE_FAMILIES "
    "把它们加上,否则所有基于 density 的筛选会静默失灵。")

# ---- 护栏二:区分度 ----
#
# 一个所有房源都同分的指标是没用的。如果哪天某一档占了九成以上,
# 说明要么数据错了,要么分类口径垮了 —— 两种都得立刻知道。
top_share = max(density.values()) / len(rows)
assert top_share < 0.75, (
    f"单一 density 档位占了 {top_share:.0%},这个指标区分不出房源:{density.most_common()}")
assert density.get("low", 0) > 1000 and density.get("high", 0) > 500, (
    f"低密度或高密度的房源太少,分类多半有问题:{density.most_common()}")

# ---- 护栏三:三个筛选条件都要真的能筛 ----
#
# 一个恒真或恒假的筛选条件比没有更糟:用户以为筛过了。
for need, (zh, predicate) in _PLANNING_NEEDS.items():
    hits = sum(1 for r in result if predicate(r))
    share = hits / len(rows)
    assert 0.02 < share < 0.98, (
        f"筛选条件「{need}」命中 {share:.1%} 的房源 —— 接近恒真或恒假,"
        f"等于没筛。({zh})")

# ---- 叠加层 ----
with_overlay = sum(1 for r in result if r.get("overlays"))
assert with_overlay / len(rows) > 0.3, "有叠加层的房源不到三成,叠加层大概没接上"
heritage = sum(1 for r in result if any(o["family"] == "HO" for o in r.get("overlays", [])))
assert heritage > 100, f"只有 {heritage} 套落在历史保护叠加层里,墨尔本不该这么少"

# ---------------------------------------------------------------- 与编排层对接

# 参数键必须进 RANK_KEYS —— 漏了的话筛选只会作用在最后 5 套上,
# 而不是全部候选。V6 的 school_zone 就踩过这个坑。
assert "planning_needs" in RANK_KEYS
assert "planning_needs" in PARAM_KEYS

# 提示词里每个示例都必须带这个字段。模型跟示例走不跟字段说明走 ——
# V4 的 abstract_needs 就是因为示例里没有,整个字段从来没被输出过。
import json  # noqa: E402

from app.orchestration.graph import _PARSE_SYSTEM  # noqa: E402

examples = [line for line in _PARSE_SYSTEM.splitlines()
            if line.startswith('{"intent"')]
assert len(examples) >= 10, f"提示词里只找到 {len(examples)} 个示例,是不是被改坏了"
for line in examples:
    parsed = json.loads(line)
    fields = set(parsed) - {"intent"}          # intent 是意图,不是检索参数
    assert fields == set(PARAM_KEYS), (
        f"示例的字段和 PARAM_KEYS 对不上:\n  多了 {fields - set(PARAM_KEYS)}\n"
        f"  少了 {set(PARAM_KEYS) - fields}\n  {line[:120]}")
    for value in parsed["planning_needs"]:
        assert value in _PLANNING_NEEDS, f"示例里用了词表外的 planning_needs:{value}"

# 至少要有一个示例**真的用到**这个字段,否则模型只会学会永远填 []
assert any(json.loads(line)["planning_needs"] for line in examples), (
    "没有一个示例真的用到 planning_needs —— 模型会学成永远填空数组")

# 词表之外的值必须被丢掉,不能假装筛过
from app.orchestration.graph import _sanitize  # noqa: E402

cleaned = _sanitize({"planning_needs": ["no_heritage", "no_such_thing", "no_heritage"]}, "")
assert cleaned["planning_needs"] == ["no_heritage"], cleaned["planning_needs"]
assert _sanitize({"planning_needs": []}, "")["planning_needs"] is None

close_pool()
print(f"规划分区 全部通过。未分类 {unknown_share:.2%},"
      f"density 分布 {dict(density.most_common(4))}")
