"""设施距离与环境偏好的「优先 / 必须」,以及面积「记录值存疑」(2026-10-06)。离线,不调用 LLM。

    python tests/test_preferred_distance_offline.py

1. 设施距离默认「优先」:近的排前面,远的不剔除;说明里写清展示的几套里有几套在范围内。
   只有 strength=required 才硬剔除。旧会话里没有 strength 的条件按「优先」处理。
2. 面积记录自相矛盾的标「存疑」,郊外真实的大地块不标;交给说明模型的事实里带着同一份标记。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.orchestration import graph as g          # noqa: E402

checks = 0


def run(needs, dists):
    metrics = [{"id": i, "price": 500_000 + i, "gross_yield": 0.04, "planning": {},
                "amenities": {"train_station": {"distance_m": d}}} for i, d in enumerate(dists)]
    state = {"params": {**{k: None for k in g.PARAM_KEYS}, "amenity_needs": needs},
             "metrics": metrics, "lang": "zh", "user_query": "q"}
    return g.rank(state)


dists = [3000, 400, 2500, 900, 5000, 700, 1200]
# 优先:一套不剔除,范围内的(400/900/700/1200)排前面,组内保持原顺序
out = run([{"kind": "train_station", "max_distance_m": 1500, "strength": "preferred"}], dists)
order = [m["amenities"]["train_station"]["distance_m"] for m in out["more"]]
assert order == [400, 900, 700, 1200, 3000, 2500, 5000], order
assert "优先距火车站 1500 米内" in out["ranking"] and "展示的 5 套中 4 套满足" in out["ranking"], out["ranking"]
checks += 2
# 旧会话没有 strength:按优先
out = run([{"kind": "train_station", "max_distance_m": 1500}], dists)
assert len(out["more"]) == len(dists)
checks += 1
# 必须:超出的剔除
out = run([{"kind": "train_station", "max_distance_m": 1000, "strength": "required"}], dists)
assert sorted(m["amenities"]["train_station"]["distance_m"] for m in out["more"]) == [400, 700, 900]
assert "要求距火车站 1000 米内" in out["ranking"]
checks += 2
# 参数闸门:只认 required,其余一律 preferred
san = g._sanitize({"intent": "new_search", "amenity_needs": [
    {"kind": "train_station", "max_distance_m": 800, "strength": "required"},
    {"kind": "primary_school", "max_distance_m": 1500, "strength": "必须"},
    {"kind": "park"}]}, "q")
assert [n["strength"] for n in san["amenity_needs"]] == ["required", "preferred", "preferred"]
checks += 1

# 环境偏好(2026-10-06 起同样默认「优先」):首轮不剔除,达标的排前面;「必须」才硬筛
def run_attr(strength, goals=None):
    ms = [{"id": i, "price": 1, "gross_yield": 0.04, "planning": {}, "context_scores": {"quiet": q}}
          for i, q in enumerate([30, 80, 55, 90, 20, 65, 70])]
    need = {"attribute": "quiet", "min_score": 60, "operator": "gte", "strength": strength, "value_source": "inferred"}
    params = {**{k: None for k in g.PARAM_KEYS}, "abstract_needs": [need], "relative_preferences": goals}
    return g.rank({"params": params, "metrics": ms, "lang": "zh", "user_query": "q"})
out = run_attr("preferred")
assert [m["context_scores"]["quiet"] for m in out["more"]] == [80, 90, 65, 70, 30, 55, 20], out["more"]
assert "优先「安静」评分 ≥ 60" in out["ranking"] and "展示的 5 套中 4 套满足" in out["ranking"]
out = run_attr("required")
assert [m["context_scores"]["quiet"] for m in out["more"]] == [80, 90, 65, 70]
assert "已筛出「安静」评分 ≥ 60 的" in out["ranking"]
out = run_attr(None)                                # 旧会话没有 strength:按优先
assert len(out["more"]) == 7
checks += 5

# 面积存疑:矛盾的标,真实的大地块不标
cases = [
    ({"property_type": "house", "land_size": 433_014, "distance_cbd": 2.5}, (True, False)),     # Fitzroy 43 公顷
    ({"property_type": "house", "land_size": 146_699, "distance_cbd": 54.6}, (False, False)),   # 郊外农庄,真实
    ({"property_type": "house", "land_size": 732, "building_area": 6791, "distance_cbd": 12}, (False, True)),   # 建筑 9 倍于地
    ({"property_type": "house", "land_size": 44_500, "building_area": 44_515, "distance_cbd": 51.8}, (False, True)),
    ({"property_type": "apartment", "land_size": 37_000, "building_area": 80, "distance_cbd": 5}, (True, False)),  # 整栋楼的地
    ({"property_type": "apartment", "land_size": 300, "building_area": 1200, "distance_cbd": 3}, (False, False)),  # 公寓不比地
    ({"property_type": "townhouse", "land_size": 250, "building_area": 15, "distance_cbd": 8}, (False, True)),    # 多半填的是「平方」
    ({"property_type": "house", "land_size": 0, "building_area": None, "distance_cbd": 8}, (False, False)),
    ({"property_type": "house", "land_size": 600, "building_area": 250, "distance_cbd": 8}, (False, False)),
]
for m, (land, bld) in cases:
    f = g.area_suspect(m)
    assert (f["land"], f["building"]) == (land, bld), (m, f)
    checks += 1
assert g._explain_fact({"property_type": "house", "land_size": 433_014, "distance_cbd": 2.5})["area_suspect"]["land"] is True
checks += 1

print(f"距离优先/必须 + 面积存疑 全部通过:{checks} 项检查(离线,不调用 LLM)")
