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

# 估值方向由原话决定,不信 LLM:实测「售价低于估值的两房」3/3 被 LLM 解析成"卖贵了"
for query, llm_sort, expected in [
    ("Richmond 附近,售价低于估值的两房", "predicted_gap_neg", "predicted_gap"),
    ("找估值低于售价的房子", "predicted_gap", "predicted_gap_neg"),
    ("被低估的两房", None, "predicted_gap"),
    ("卖贵了的房子", None, "predicted_gap_neg"),
    ("undervalued houses in Richmond", "predicted_gap_neg", "predicted_gap"),
    ("回报最高且被低估的", "gross_yield", "gross_yield"),   # 用户要的是别的排序,不覆盖
    ("高估值的房子", None, None),                            # 「估值高」不是方向词
]:
    got = _sanitize({"sort_by": llm_sort}, query)["sort_by"]
    assert got == expected, f"«{query}» 期望 {expected},得到 {got}"
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

# 门槛太高时明确没有兼容结果,不能自动删除条件。
out = _run({"min_gross_yield": 0.99})
assert out["metrics"] == []
assert "没有候选达到" in out["ranking"]

# 排序字段全为 None -> 退回相关度顺序,并说明,而不是崩
out = _run({"sort_by": "cap_rate"})
assert len(out["metrics"]) == RESULT_LIMIT
assert "已按相关度排序" in out["ranking"]

# 审计 BUG-02:按回报率挑房时,售价远低于估值(超过典型误差 3 倍)的异常成交要先剔掉并说明,
# 否则 $131,000 的 Caulfield 独栋会以 32% 回报率排第一
ODD = [dict(_m(1, 0.32, 131_000), predicted_gap=1.19, valuation_error_pct=0.094),
       dict(_m(2, 0.06, 500_000), predicted_gap=0.05, valuation_error_pct=0.094),
       dict(_m(3, 0.05, 600_000), predicted_gap=-0.20, valuation_error_pct=0.094)]
for params in ({"sort_by": "gross_yield"}, {"min_gross_yield": 0.04}):
    out = rank({"metrics": list(ODD), "params": params})
    assert 1 not in [m["id"] for m in out["metrics"]], params
    assert "已剔除 1 套售价远低于模型估值" in out["ranking"]
# 按价格排序不受影响:那是用户明说要看最便宜的
assert rank({"metrics": list(ODD), "params": {"sort_by": "price_asc"}})["metrics"][0]["id"] == 1

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

# 保形区间:必须是校准过的(meta 有 conformal 段),而且比"约半数落入"的典型误差区间宽
assert v["interval_level"] == 0.8, "展示用的区间应为 80% 把握"
assert v["interval_low"] < v["range_low"] < v["predicted_price"] < v["range_high"] < v["interval_high"]
assert 0.75 <= v["interval_coverage"] <= 0.85, "实测覆盖率偏离标称太多,区间名不副实"
for ptype, info in meta["conformal"]["levels"]["0.8"].items():
    # 每一类房型都要在留出数据上验证过:平均覆盖率贴近标称,而不是只有整体达标
    assert 0.77 <= info["coverage_mean"] <= 0.83, f"{ptype} 的 80% 区间实测覆盖 {info['coverage_mean']:.1%}"
# 公寓误差比独栋大,区间必须更宽 —— 共用一个宽度会让公寓的区间名不副实
apt = predict_value(dict(f, property_type="apartment"))
assert (apt["interval_high"] / apt["predicted_price"]) > (v["interval_high"] / v["predicted_price"])

# 分割保形分位数的定义:第 ceil((n+1)·level) 小的残差;样本不够时是无穷大(如实表示"不知道")
from app.analytics.calibrate_valuation import conformal_q
import math as _math
assert conformal_q([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0], 0.8) == 8.0
assert conformal_q([1.0, 2.0, 3.0], 0.9) == _math.inf

# 批量与逐条必须逐字一致,否则就是偷偷换了算法
assert predict_values([f, f]) == [v, v]
assert predict_values([]) == []

# 审计 BUG-03:库内房源用离折估值(没见过它的那一折模型)。Caulfield 这栋 4 房 155 ㎡ 独栋登记成交价
# $131,000,定稿模型见过它、估 $286,690 并把售价包进区间;离折估值必须回到同区独栋的百万级
PYNE = {"suburb": "Caulfield", "address": "30 Pyne St", "property_type": "house", "bedrooms": 4,
        "bathrooms": 1, "car_spaces": 2, "land_size": 499.0, "building_area": 155.0,
        "distance_cbd": 8.9, "latitude": -37.8864, "longitude": 145.0242, "price": 131000}
pyne = predict_values([PYNE])[0]
assert pyne["cross_fitted"] and pyne["predicted_price"] > 1_000_000, pyne
assert PYNE["price"] < pyne["interval_low"], "异常低价必须落在区间之外"
# 查不到(库外输入 / 不带售价)就用定稿模型,并如实标出来
assert predict_values([{k: val for k, val in PYNE.items() if k != "price"}])[0]["cross_fitted"] is False

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
assert "要求距火车站 1000 米内" in out["ranking"]

# 门槛严到一套不剩时:不返回违反条件的房源。
out = rank({"metrics": enriched,
            "params": {"amenity_needs": [{"kind": "train_station", "max_distance_m": 1}]}})
assert out["metrics"] == [] and "同时满足" in out["ranking"]


# ---------------------------------------------------------------- V4:抽象需求

p = _sanitize({"abstract_needs": [{"attribute": "quiet", "min_score": 75}]}, "x")
assert p["abstract_needs"] == [{"attribute": "quiet", "min_score": 75}]

# 不在四类之内的属性丢掉,不猜
assert _sanitize({"abstract_needs": [{"attribute": "sunny", "min_score": 60}]}, "x")["abstract_needs"] is None
# 提了属性但没给门槛/给了非法门槛 -> 用默认 60,而不是 0(0 等于没筛)
for bad in ({"attribute": "quiet"}, {"attribute": "quiet", "min_score": -1},
            {"attribute": "quiet", "min_score": 500}, {"attribute": "quiet", "min_score": True}):
    assert _sanitize({"abstract_needs": [bad]}, "x")["abstract_needs"] ==         [{"attribute": "quiet", "min_score": 60}], bad

for boundary in (0, 100):
    need = {"attribute": "quiet", "min_score": boundary, "operator": "eq"}
    assert _sanitize({"abstract_needs": [need]}, "x")["abstract_needs"] == [need]
for invalid in ("eval", {}, None):
    need = {"attribute": "quiet", "min_score": 40, "operator": invalid}
    assert _sanitize({"abstract_needs": [need]}, "x")["abstract_needs"][0]["operator"] == "gte"
explicit = [{"attribute": "quiet", "min_score": 60, "operator": "lt"},
            {"attribute": "lively", "min_score": 60, "operator": "gte"}]
assert _sanitize({"abstract_needs": explicit}, "x")["abstract_needs"] == explicit

# 负相关不是逻辑互斥,无论顺序如何均保留两项。
p = _sanitize({"abstract_needs": [{"attribute": "quiet", "min_score": 60},
                                  {"attribute": "lively", "min_score": 60}]}, "x")
assert [w["attribute"] for w in p["abstract_needs"]] == ["quiet", "lively"]
assert "_conflict" not in p
p = _sanitize({"abstract_needs": [{"attribute": "lively", "min_score": 60},
                                  {"attribute": "quiet", "min_score": 60}]}, "x")
assert [w["attribute"] for w in p["abstract_needs"]] == ["lively", "quiet"]
assert "_conflict" not in p
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

# 门槛太高时明确没有兼容结果。
out = rank({"metrics": list(Q), "params": {"abstract_needs": [{"attribute": "quiet", "min_score": 99}]}})
assert out["metrics"] == [] and "同时满足" in out["ranking"]

# 明确比较符号必须影响结果,尤其 > / ≥、< / ≤ 在边界处不能混淆。
for op, ids, symbol in (("gte", {1, 3}, "≥"), ("gt", {1}, ">"),
                        ("lte", {2, 3, 5}, "≤"), ("lt", {2, 5}, "<"), ("eq", {3}, "=")):
    need = {"attribute": "quiet", "min_score": 70, "operator": op}
    for lang in ("zh", "en"):
        out = rank({"metrics": list(Q), "params": {"abstract_needs": [need]}, "lang": lang})
        assert {m["id"] for m in out["metrics"]} == ids, (op, out["metrics"])
        assert symbol + " 70" in out["ranking"]
for op in ("lt", "eq"):
    out = rank({"metrics": list(Q), "params": {"abstract_needs": [
        {"attribute": "quiet", "min_score": 0, "operator": op}]}})
    assert out["metrics"] == [] and "已忽略" not in out["ranking"]
edges = [{"id": 10, "context_scores": {"quiet": 0}}, {"id": 11, "context_scores": {"quiet": 100}}]
for value, expected in ((0, 10), (100, 11)):
    out = rank({"metrics": edges, "params": {"abstract_needs": [
        {"attribute": "quiet", "min_score": value, "operator": "eq"}]}})
    assert [m["id"] for m in out["metrics"]] == [expected]

# 旧会话的互斥标记不再引发条件删除。
out = rank({"metrics": list(Q), "params": {"_conflict": "lively"}})
assert "互斥" not in out["ranking"] and "已忽略" not in out["ranking"]

print("编排层 + 估值 + 假设 + 设施 + 抽象需求 全部通过。")
