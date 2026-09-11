"""编排层的验收:参数过闸、排序、估值模型。V2 补上的测试。

第一版只有 formulas 有测试,graph.py(最复杂的一块)一行都没有 —— 这是欠账。
这里补的是**不需要调 LLM** 的部分:_sanitize 和 rank 都是纯函数,
喂手写字典就能测,一分钱 API 费都不花。

    python tests/test_orchestration.py

需要数据库在跑(导入 graph.py 会建连接池),但不需要 LLM_API_KEY。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics import assumptions
from app.analytics.valuation import predict_value, predict_values, warm_up
from app.orchestration.graph import (
    PARAM_KEYS, RESULT_LIMIT, _route, _sanitize, enrich, present, rank,
)

# ---------------------------------------------------------------- _sanitize

# 用户没提的字段一律 None,绝不能是 0 或空串
p = _sanitize({}, "随便找找")
assert set(p) == set(PARAM_KEYS)
assert p["semantic_query"] == "随便找找"
assert all(p[k] is None for k in PARAM_KEYS if k != "semantic_query")

# max_price=0 是第一版点名的最危险静默失败:它会返回空列表且不报错
assert _sanitize({"max_price": 0}, "x")["max_price"] is None
assert _sanitize({"max_price": -5}, "x")["max_price"] is None
assert _sanitize({"bedrooms": ""}, "x")["bedrooms"] is None
assert _sanitize({"bedrooms": True}, "x")["bedrooms"] is None      # True 是 int 的子类
assert _sanitize({"max_price": 800000.0}, "x")["max_price"] == 800000

# 房型必须在枚举内(数据库有 CHECK 约束,乱填只会返回空)
assert _sanitize({"property_type": "villa"}, "x")["property_type"] is None
assert _sanitize({"property_type": " HOUSE "}, "x")["property_type"] == "house"

# 上下限矛盾时放弃下限,而不是白白返回空结果
p = _sanitize({"min_price": 900000, "max_price": 800000}, "x")
assert p["max_price"] == 800000 and p["min_price"] is None

# 地名一律原样填,由数据库裁决有没有 —— 不让 LLM 用世界知识替数据库做判断
assert _sanitize({"suburb": "Sydney"}, "x")["suburb"] == "Sydney"

# V2:排序口径必须在白名单内
assert _sanitize({"sort_by": "gross_yield"}, "x")["sort_by"] == "gross_yield"
assert _sanitize({"sort_by": "whatever"}, "x")["sort_by"] is None

# V2:回报率门槛。模型很容易把 5% 写成 5,按常识修正而不是返回空结果
assert _sanitize({"min_gross_yield": 0.05}, "x")["min_gross_yield"] == 0.05
assert _sanitize({"min_gross_yield": 5}, "x")["min_gross_yield"] == 0.05
assert _sanitize({"min_gross_yield": -1}, "x")["min_gross_yield"] is None

# ---------------------------------------------------------------- rank


def _m(i, yield_, price, cap=None):
    return {"id": i, "gross_yield": yield_, "price": price, "cap_rate": cap}


POOL = [_m(1, 0.03, 900_000), _m(2, 0.08, 300_000), _m(3, 0.05, 500_000),
        _m(4, None, 700_000), _m(5, 0.06, 400_000), _m(6, 0.04, 600_000),
        _m(7, 0.07, 350_000)]


def _run(params):
    return rank({"metrics": list(POOL), "params": params})


# 不给排序口径 -> 保持语义相关度顺序,只截断
out = _run({})
assert [m["id"] for m in out["metrics"]] == [1, 2, 3, 4, 5]
assert "按语义相关度排序" in out["ranking"]

# 按回报率排序,且必须截到 RESULT_LIMIT 套
out = _run({"sort_by": "gross_yield"})
assert [m["id"] for m in out["metrics"]] == [2, 7, 5, 3, 6]
assert len(out["metrics"]) == RESULT_LIMIT
assert "毛租金回报率从高到低" in out["ranking"]
# 算不出指标的那套(id=4)要被排除,而不是当成 0 排最后
assert all(m["gross_yield"] is not None for m in out["metrics"])

# 价格升序
assert [m["id"] for m in _run({"sort_by": "price_asc"})["metrics"]] == [2, 7, 5, 3, 6]

# 门槛筛选
out = _run({"min_gross_yield": 0.06})
assert {m["id"] for m in out["metrics"]} == {2, 5, 7}
assert "已筛掉" in out["ranking"]

# 门槛太高,一套都不剩 -> 不硬筛,给结果并说明。空列表会让用户分不清
# 「没房源」和「门槛定太高」,那是两回事。
out = _run({"min_gross_yield": 0.99})
assert len(out["metrics"]) == RESULT_LIMIT
assert "没有一套达到" in out["ranking"]

# 排序字段全为 None -> 退回相关度顺序,并说明,而不是崩
out = _run({"sort_by": "cap_rate"})
assert len(out["metrics"]) == RESULT_LIMIT
assert "已按相关度排序" in out["ranking"]

# ---------------------------------------------------------------- valuation

meta = warm_up()
assert meta["feature_order"], "模型元信息缺 feature_order"
# 线上拿不到 year_built,它绝不能出现在特征里 —— 否则训练/线上不一致
assert "year_built" not in meta["feature_order"]

f = {"suburb": "Richmond", "property_type": "house", "bedrooms": 3, "bathrooms": 2,
     "car_spaces": 1, "land_size": 300.0, "building_area": 140.0,
     "distance_cbd": 2.4, "latitude": -37.82, "longitude": 144.99}
v = predict_value(f)
assert v["is_stub"] is False, "V2 的估值必须是真模型,不能再是占位值"
assert isinstance(v["predicted_price"], int) and v["predicted_price"] > 0
assert v["range_low"] < v["predicted_price"] < v["range_high"]
assert 0 < v["typical_error_pct"] < 0.5

# 批量与逐条必须逐字一致,否则就是偷偷换了算法
assert predict_values([f, f]) == [v, v]
assert predict_values([]) == []

# 缺失特征不许崩(线上 land_size / building_area 有近一半是空的)
sparse = dict(f, land_size=None, building_area=None)
assert predict_value(sparse)["predicted_price"] > 0

# 多一间卧室应该更贵 —— 模型至少要符合这个常识,否则特征多半接错了
assert predict_value(dict(f, bedrooms=4))["predicted_price"] > v["predicted_price"]

# ---------------------------------------------------------------- assumptions

assert 0 < assumptions.opex_rate() < 1
assert assumptions.other_acquisition_costs() >= 0
snap = assumptions.snapshot()
assumptions.set_rate("opex_rate", 0.35)
assert assumptions.opex_rate() == 0.35
assumptions.set_rate("other_acquisition_costs", 3500)
assert assumptions.other_acquisition_costs() == 3500
assumptions.set_rate("other_acquisition_costs", snap["other_acquisition_costs"])
assert assumptions.snapshot() != snap, "快照必须反映改动"
try:
    assumptions.set_rate("opex_rate", 1.5)
except ValueError:
    pass
else:
    raise AssertionError("超出 [0,1) 的假设值必须被拒绝")
assumptions.set_rate("opex_rate", snap["opex_rate"])   # 还原


# ---------------------------------------------------------------- V3:设施参数过闸

p = _sanitize({"amenity_needs": [{"kind": "train_station", "max_distance_m": 800}]}, "x")
assert p["amenity_needs"] == [{"kind": "train_station", "max_distance_m": 800}]

# 不在九类之内的设施直接丢掉,不猜
assert _sanitize({"amenity_needs": [{"kind": "casino", "max_distance_m": 500}]}, "x")["amenity_needs"] is None
# 提了设施但没说距离 -> 给默认值,而不是当成 0(0 会筛掉所有房源)
got = _sanitize({"amenity_needs": [{"kind": "hospital"}]}, "x")["amenity_needs"]
assert got == [{"kind": "hospital", "max_distance_m": 1500}]
assert _sanitize({"amenity_needs": [{"kind": "hospital", "max_distance_m": 0}]}, "x")["amenity_needs"]     == [{"kind": "hospital", "max_distance_m": 1500}]
assert _sanitize({"amenity_needs": "不是数组"}, "x")["amenity_needs"] is None

# 具名地点
p = _sanitize({"near_place": {"name": "Monash University", "kind": "university",
                              "max_distance_m": 3000}}, "x")
assert p["near_place"] == {"name": "Monash University", "kind": "university",
                           "max_distance_m": 3000}
# 类别不在九类里就置 None(仍然可以按名字找,只是范围不收窄)
assert _sanitize({"near_place": {"name": "X", "kind": "casino"}}, "x")["near_place"]["kind"] is None
assert _sanitize({"near_place": {"name": "   "}}, "x")["near_place"] is None
assert _sanitize({"near_place": "字符串不行"}, "x")["near_place"] is None

# 没有 near_place 时,按距它排序毫无意义 -> 降级成语义相关度
assert _sanitize({"sort_by": "near_place_distance"}, "x")["sort_by"] is None
assert _sanitize({"sort_by": "near_place_distance",
                  "near_place": {"name": "Monash University"}}, "x")["sort_by"] == "near_place_distance"

# ---------------------------------------------------------------- V3:条件路由

assert _route({"intent": "new_search"}) == "search"
assert _route({"intent": "refine"}) == "search"
assert _route({"intent": "about_results"}) == "explain"
assert _route({"intent": "concept"}) == "explain"
assert _route({}) == "explain", "意图缺失时不该白跑一趟数据库"

# ---------------------------------------------------------------- V3:enrich + 按设施筛

# Richmond 一带的两个点:一个靠近市区,一个在远郊
CITY = {"id": 1, "latitude": -37.8197, "longitude": 144.9976, "price": 500_000, "gross_yield": 0.05}
FAR = {"id": 2, "latitude": -38.2000, "longitude": 145.4000, "price": 400_000, "gross_yield": 0.06}

out = enrich({"metrics": [dict(CITY), dict(FAR)],
              "params": {"amenity_needs": [{"kind": "train_station", "max_distance_m": 800}]}})
city, far = out["metrics"]
assert city["amenities"]["train_station"]["distance_m"] < far["amenities"]["train_station"]["distance_m"]
# enrich 只算**筛选**要用的那几类。展示用的挪到 present 了 ——
# 给几千套候选都算一遍展示数据、其中 99.9% 转手就丢,是纯浪费。
assert set(city["amenities"]) == {"train_station"},     f"enrich 不该算筛选之外的设施,实际算了 {set(city['amenities'])}"
assert city["near_place"] is None

# present 给最终留下的那几套补上展示用的设施
shown = present({"metrics": [dict(city)]})["metrics"][0]
assert {"train_station", "hospital"} <= set(shown["amenities"]),     "present 应当补齐默认展示的设施"
# 已经算过的不该被覆盖成另一个值
assert shown["amenities"]["train_station"] == city["amenities"]["train_station"]
assert present({"metrics": []}) == {}

# 具名地点解析不到时,必须如实记下来,而不是假装算过
out = enrich({"metrics": [dict(CITY)],
              "params": {"near_place": {"name": "完全不存在的大学", "kind": "university"}}})
assert out["place_lookup"]["error"], "找不到的地点必须报错,不能静默"
assert out["metrics"][0]["near_place"] is None

# 设施筛选:市区那套留下,远郊那套被筛掉
enriched = enrich({"metrics": [dict(CITY), dict(FAR)],
                   "params": {"amenity_needs": [{"kind": "train_station", "max_distance_m": 1000}]}})["metrics"]
out = rank({"metrics": enriched,
            "params": {"amenity_needs": [{"kind": "train_station", "max_distance_m": 1000}]}})
assert [m["id"] for m in out["metrics"]] == [1]
assert "已筛出距火车站 1000 米内的" in out["ranking"]

# 门槛严到一套不剩时:不硬筛,如实说明,并告诉用户最近的有多远
out = rank({"metrics": enriched,
            "params": {"amenity_needs": [{"kind": "train_station", "max_distance_m": 1}]}})
assert len(out["metrics"]) == 2, "一套不剩时应保留结果并说明,而不是返回空列表"
assert "已忽略该条件" in out["ranking"] and "最近的也有" in out["ranking"]


# ---------------------------------------------------------------- V4:抽象需求

p = _sanitize({"abstract_needs": [{"attribute": "quiet", "min_score": 75}]}, "x")
assert p["abstract_needs"] == [{"attribute": "quiet", "min_score": 75}]

# 不在四类之内的属性丢掉,不猜
assert _sanitize({"abstract_needs": [{"attribute": "sunny", "min_score": 60}]}, "x")["abstract_needs"] is None
# 提了属性但没给门槛/给了非法门槛 -> 用默认 60,而不是 0(0 等于没筛)
for bad in ({"attribute": "quiet"}, {"attribute": "quiet", "min_score": 0},
            {"attribute": "quiet", "min_score": 500}, {"attribute": "quiet", "min_score": True}):
    assert _sanitize({"abstract_needs": [bad]}, "x")["abstract_needs"] ==         [{"attribute": "quiet", "min_score": 60}], bad

# 安静与热闹互斥(实测相关系数 -0.80),同时要就保留先出现的那个并记下冲突
p = _sanitize({"abstract_needs": [{"attribute": "quiet", "min_score": 60},
                                  {"attribute": "lively", "min_score": 60}]}, "x")
assert [w["attribute"] for w in p["abstract_needs"]] == ["quiet"]
assert p["_conflict"] == "lively"
p = _sanitize({"abstract_needs": [{"attribute": "lively", "min_score": 60},
                                  {"attribute": "quiet", "min_score": 60}]}, "x")
assert [w["attribute"] for w in p["abstract_needs"]] == ["lively"]
assert p["_conflict"] == "quiet"
# 不冲突的组合要留全
p = _sanitize({"abstract_needs": [{"attribute": "lively", "min_score": 60},
                                  {"attribute": "convenient", "min_score": 60}]}, "x")
assert len(p["abstract_needs"]) == 2 and "_conflict" not in p

# 抽象属性可以当排序口径 —— 这一条曾经漏掉,导致 LLM 抽对了却被过闸函数丢掉
for attr in ("quiet", "lively", "convenient", "green"):
    assert _sanitize({"sort_by": attr}, "x")["sort_by"] == attr

# ---------------------------------------------------------------- V4:按环境属性筛与排

Q = [{"id": 1, "context_scores": {"quiet": 90}, "price": 1},
     {"id": 2, "context_scores": {"quiet": 40}, "price": 2},
     {"id": 3, "context_scores": {"quiet": 70}, "price": 3},
     {"id": 4, "price": 4},                                    # 没算过环境分
     {"id": 5, "context_scores": {"quiet": 65}, "price": 5}]

out = rank({"metrics": list(Q), "params": {"abstract_needs": [{"attribute": "quiet", "min_score": 60}]}})
assert {m["id"] for m in out["metrics"]} == {1, 3, 5}
assert "已筛出「安静」评分 ≥ 60 的" in out["ranking"]

out = rank({"metrics": list(Q), "params": {"sort_by": "quiet"}})
assert [m["id"] for m in out["metrics"]] == [1, 3, 5, 2], "应按安静分降序,没分的排除"

# 门槛太高时不硬筛,并告诉用户候选里最高是多少
out = rank({"metrics": list(Q), "params": {"abstract_needs": [{"attribute": "quiet", "min_score": 99}]}})
assert len(out["metrics"]) == RESULT_LIMIT
assert "候选里最高只有 90" in out["ranking"]

# 冲突要如实写进排序口径说明里
out = rank({"metrics": list(Q), "params": {"_conflict": "lively"}})
assert "互斥" in out["ranking"] and "已忽略「热闹」" in out["ranking"]

print("编排层 + 估值 + 假设 + 设施 + 抽象需求 全部通过。")
