"""抽象需求匹配的验收:环境证据与"安静/热闹"评分。V4。

不需要数据库、不需要 LLM、不联网 —— 只读 data/context_points.csv 和基准线。

    python tests/test_context.py

**这套测试的重点是"分数和现实对不对得上"**,不是"函数不报错"。一个不报错
但把 Chapel St 判成安静的评分,比报错还糟。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.amenities.context import (
    ATTRIBUTES, UNSUPPORTED, collect_evidence, describe_evidence, scores, warm_up,
)

info = warm_up()
assert info["baseline"], "缺分位基准,请先跑 pipeline/build_context_baseline.py"
assert info["points"] > 100_000, f"地理点太少({info['points']})"
assert info["attributes"] >= 10 and info["unsupported"] >= 8
# 属性用到的证据都要有分位表 —— 缺一项,对应属性会安静地算不出分
assert not info["missing_quantiles"], f"这些证据缺分位表:{info['missing_quantiles']}"

# ---------------------------------------------------------------- 证据本身

CBD = (-37.8183, 144.9671)          # Flinders St 站
CHAPEL = (-37.8400, 144.9930)       # South Yarra,Chapel St 商圈
OUTER = (-37.9800, 144.7000)        # Werribee South,远郊

ev_cbd, ev_chapel, ev_outer = (collect_evidence(*CBD), collect_evidence(*CHAPEL),
                               collect_evidence(*OUTER))
for ev in (ev_cbd, ev_chapel, ev_outer):
    assert len(ev) >= 25, f"证据项太少:{len(ev)}"
    assert all(isinstance(v, (int, float)) and v >= 0 for v in ev.values())

# 没有坐标就返回空,不编造
assert collect_evidence(None, None) == {}
assert collect_evidence(-37.8, None) == {}

# 远郊到主干道、铁路必须比市中心远得多
assert ev_outer["major_road_m"] > ev_cbd["major_road_m"] * 5
assert ev_outer["railway_m"] > ev_cbd["railway_m"] * 5
# 市中心的夜间场所和商店必须远多于远郊
# (夜间场所只数酒吧/夜店/pub,不含餐厅快餐 —— 审计 BUG-09;Flinders St 一带实测 18 家)
assert ev_cbd["nightlife_300m"] > 10 and ev_outer["nightlife_300m"] == 0
assert ev_cbd["shop_800m"] > 100 and ev_outer["shop_800m"] < 5

# ---------------------------------------------------------------- 评分对不对得上现实

s_cbd, s_chapel, s_outer = scores(ev_cbd), scores(ev_chapel), scores(ev_outer)
# 只给了地理证据、没给设施距离和房源字段,所以只有依赖地理证据的属性能算出来。
# 证据不足的属性**直接不出现**,不是给个 50 分假装"中等" —— 这是刻意的设计。
# 只给坐标(没给房源字段)时,依赖地理的属性都该算得出来;
# 依赖房源字段的(宽敞)算不出来就**不该出现**,而不是给个 50 分假装"中等"。
# 只给坐标、不给房源字段时能算出来的那些。「宽敞」要面积、「治安较好」要区名,
# 都属于房源字段,拿不到就**不该出现**,而不是给个 50 分假装"中等"。
GEO_BASED = {"quiet", "lively", "green", "transport", "school_access", "medical",
             "fitness", "shopping", "beach_access", "away_industry", "away_cemetery"}
for sc in (s_cbd, s_chapel, s_outer):
    assert GEO_BASED <= set(sc), f"只靠坐标也该算得出 {GEO_BASED - set(sc)}"
    assert set(sc) <= set(ATTRIBUTES)
    assert all(0 <= v <= 100 for v in sc.values())
    assert "spacious" not in sc, "没有面积数据却给出了「宽敞」分 —— 不该拿中位数兜底"
    assert "low_crime" not in sc, "没有区名却给出了「治安较好」分 —— 不该拿平均值兜底"

# 这几条是"评分有没有意义"的底线,不是可选的
assert s_outer["quiet"] > 85, f"远郊安静分只有 {s_outer['quiet']},评分不可信"
assert s_chapel["quiet"] < 25, f"Chapel St 商圈安静分居然有 {s_chapel['quiet']}"
assert s_cbd["lively"] > 90, f"CBD 热闹分只有 {s_cbd['lively']}"
assert s_outer["lively"] < 15, f"远郊热闹分居然有 {s_outer['lively']}"
# 证据齐全时,九个属性都应该算得出来
full = collect_evidence(*CBD, None, {"distance_cbd": 2.0, "building_area": 120.0,
                                     "suburb": "Melbourne"})
full_scores = scores(full, "apartment", bedrooms=2)
missing_attrs = set(ATTRIBUTES) - set(full_scores)
assert not missing_attrs, f"证据齐全时应算全部属性,缺了 {missing_attrs}"

# 安静与热闹必须是相反的方向 —— 在一批真实坐标上验,不是只看两个点
rng = np.random.default_rng(7)
lats = -37.6 - rng.random(120) * 0.5
lons = 144.8 + rng.random(120) * 0.6
pairs = [(scores(e)["quiet"], scores(e)["lively"])
         for e in (collect_evidence(a, b) for a, b in zip(lats, lons)) if e]
q = np.array([p[0] for p in pairs], dtype=float)
l = np.array([p[1] for p in pairs], dtype=float)
corr = float(np.corrcoef(q, l)[0, 1])
assert corr < -0.6, f"安静与热闹的相关系数是 {corr:.3f},两者应当明显反向"
# 但也不该完全是同一个数取反,否则分开两个属性就没意义
assert corr > -0.995, f"相关系数 {corr:.3f},安静和热闹几乎就是同一个指标"
assert q.std() > 10, "安静分几乎没有区分度"

# ---------------------------------------------------------------- 审计回归

from app.amenities import nearby  # noqa: E402
from app.amenities.context import _size_m2  # noqa: E402

# BUG-06:明显录错的建筑面积(4 房独栋 1 ㎡,是把卧室数填进了面积列)不当真,退回地块面积
assert _size_m2({"building_area": 1.0, "land_size": 319.0, "bedrooms": 4}) == 319.0
assert _size_m2({"building_area": 4.0, "land_size": None, "bedrooms": 4}) is None
assert _size_m2({"building_area": 55.0, "land_size": 0.0, "bedrooms": 1}) == 55.0     # 一房小公寓是真的
assert _size_m2({"building_area": 120.0, "land_size": 400.0, "bedrooms": 3}) == 120.0
assert _size_m2({"building_area": 15.0, "land_size": 15.0, "bedrooms": 3}) is None     # 两列都录错就不打分

# BUG-05:距 CBD 按坐标算,不用数据集按区给的值(Werribee 全区写 14.7 km,实际约 28 km)
werribee = (-37.8990, 144.6610)
assert 25 < nearby.distance_to_cbd_km(*werribee, fallback=14.7) < 32
assert nearby.distance_to_cbd_km(None, None, fallback=14.7) == 14.7
assert nearby.distance_to_cbd_km(None, None) is None
ev_w = collect_evidence(*werribee, None, {"distance_cbd": 14.7})
assert ev_w["distance_cbd_km"] > 25, "证据里的距 CBD 仍在用数据集的错值"

# BUG-01:公园按边界量距,不按中心点。249 Punt Rd 紧挨 Yarra Park,原来按中心点报 301 米,原始轮廓实测 39 米
punt = nearby.nearest(-37.8201, 144.9898, "park")
assert punt["distance_m"] < 60 and punt["name"] == "Yarra Park", punt
# 按名字找到的公园,距离也量到它的边界(边界点按 osm_id 找回来),不是量到中心点
albert = nearby.find_place("Albert Park", "park")
edge_lat, edge_lon = nearby._load()["edges"][albert[0]["osm_id"]][0]
assert nearby.distance_to_place(edge_lat, edge_lon, albert)["distance_m"] == 0
assert nearby.distance_between(edge_lat, edge_lon, albert[0]["latitude"], albert[0]["longitude"]) > 300

# BUG-08:三级路、电车线是独立证据,并计入安静分
assert {"tertiary_road_m", "tram_line_m"} <= set(ATTRIBUTES["quiet"]["parts"])
assert "tertiary_road_m" in ev_cbd and "tram_line_m" in ev_cbd

# ---------------------------------------------------------------- 证据描述

lines = describe_evidence(ev_cbd)
assert len(lines) == len(ev_cbd)
# 可以只描述关心的那几项 —— 29 项全列出来会淹没重点
assert len(describe_evidence(ev_cbd, ["major_road_m"])) == 1
assert all(any(ch.isdigit() for ch in line) for line in lines), "每条证据都要带数字"
assert describe_evidence({}) == []

# 缺基准时不该崩,只是给不出分数
assert scores({}) == {}

# ---------------------------------------------------------------- 不支持清单

assert len(UNSUPPORTED) >= 8, "明确列出'没有这项数据'的类别太少"
# 治安必须在不支持清单里:库里有警察局位置,但警察局离得近**不等于**治安好
# (市中心警局最密集)。把它做成一个"安全评分"是典型的伪科学。
assert any("治安" in k for k in UNSUPPORTED)
assert all(v.strip() for v in UNSUPPORTED.values()), "每一项都要写清为什么没有"
# 不支持的类别不能和支持的属性重名 —— 那会让系统自相矛盾
assert not (set(UNSUPPORTED) & {v["zh"] for v in ATTRIBUTES.values()})

print("抽象需求匹配(环境证据 + 评分) 全部通过。")
