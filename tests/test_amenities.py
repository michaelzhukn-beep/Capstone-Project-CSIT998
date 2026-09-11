"""周边设施查询的验收。V3。

不需要数据库、不需要 LLM、不联网 —— 只读 data/amenities.csv。

    python tests/test_amenities.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.amenities.nearby import (
    KINDS, KIND_ZH, _haversine_m, count_within, distance_to_place, find_place,
    nearest, nearest_by_kind, walk_minutes, warm_up,
)

RICHMOND = (-37.8197, 144.9976)

# ---------------------------------------------------------------- 数据本身

info = warm_up()
assert info["total"] > 100_000, f"点太少({info['total']}),数据大概没抓全"
for kind in KINDS:
    assert info["by_kind"].get(kind, 0) > 0, f"{kind} 一个点都没有"
# 各类别数量要合常理 —— OSM 完整度参差,这几条是最低限度的体检
assert info["by_kind"]["primary_school"] > 500
assert info["by_kind"]["train_station"] > 100       # 墨尔本都市圈约 220 个站
assert info["by_kind"]["tram_stop"] > 1000          # 全球最大有轨电车网
assert info["by_kind"]["airport"] < 100             # 机场不该有几百个


def _one(lat, lon):
    """把单个坐标包成 _haversine_m 要的那种分组结构。"""
    return {"lat": np.radians(np.array([lat])), "lon": np.radians(np.array([lon]))}


# ---------------------------------------------------------------- 距离算法

# Flinders Street 站 -> Richmond 站,已知直线距离约 2.1 公里
d = float(_haversine_m(-37.8183, 144.9671, _one(-37.8236, 144.9905))[0])
assert 2000 < d < 2300, f"两站距离算成了 {d:.0f} 米,和已知的约 2.1 公里对不上"

# 同一个点到自己的距离必须是 0
assert float(_haversine_m(-37.8, 145.0, _one(-37.8, 145.0))[0]) < 1

# 不能用平面勾股糊弄:墨尔本在南纬 38°,东西方向要乘 cos(38°)≈0.79。
# 取同纬度、经度差 0.1° 的两点,真实距离约 8.8 公里;若按平面算会是 11.1 公里。
east = float(_haversine_m(-37.82, 144.90, _one(-37.82, 145.00))[0])
assert 8500 < east < 9000, f"东西向距离 {east:.0f} 米,像是没做纬度修正"

# ---------------------------------------------------------------- 按类别

near = nearest_by_kind(*RICHMOND)
assert set(near) == set(KINDS)
# V5 新增的源也要能查到
assert near["tram_stop"]["distance_m"] < 3000, "Richmond 附近应该有电车站"
assert near["supermarket"]["distance_m"] < 3000
assert nearest(*RICHMOND, "train_station")["distance_m"] == near["train_station"]["distance_m"]
assert count_within(*RICHMOND, "shop", 800) > 0
assert count_within(None, None, "shop", 800) is None
assert nearest(None, None, "train_station") is None
for kind, hit in near.items():
    assert hit["distance_m"] >= 0
    assert hit["name"], f"{kind} 的最近点没有名字"
# Richmond 在市区,这些设施都该很近;机场当然远
assert near["train_station"]["distance_m"] < 2000
assert near["bank"]["distance_m"] < 2000
assert near["airport"]["distance_m"] > 5000

# 只要指定类别时,不该白算其余的
subset = nearest_by_kind(*RICHMOND, kinds=("train_station",))
assert set(subset) == {"train_station"}

# 没有坐标就返回空,不要编一个距离出来
assert nearest_by_kind(None, None) == {}

# ---------------------------------------------------------------- 具名查找

# 同一机构的多个校区都要返回 —— "离 Monash 近"指的是离任一校区近
monash = find_place("Monash University", "university")
assert len(monash) >= 4, f"Monash 只找到 {len(monash)} 个点,校区应该不止"
assert all("monash" in p["name"].lower() for p in monash)
# 按词匹配必须排除掉这些同名但无关的东西
assert not any("science school" in p["name"].lower() for p in monash), \
    "John Monash Science School 是中学,不该混进 Monash 大学"

# 词序无关:用户说 "Melbourne University",OSM 里叫 "The University of Melbourne"
a = {p["name"] for p in find_place("University of Melbourne", "university")}
b = {p["name"] for p in find_place("Melbourne University", "university")}
assert a == b and a, "词序不同应当命中同一批点"

# 别名:墨尔本机场正式名是 Melbourne Airport,俗称 Tullamarine
tulla = find_place("Tullamarine", "airport")
assert len(tulla) == 1 and "airport" in tulla[0]["name"].lower(), \
    f"别名没生效,Tullamarine 找到的是 {[p['name'] for p in tulla]}"

# **最要紧的一条**:类别不对就返回空,绝不退而求其次给个别的东西。
# 曾经这里会把 "Tullamarine Primary School" 当成机场返回 —— 要机场给小学。
for query, kind in (("Tullamarine Primary School", "airport"),
                    ("Flinders Street", "hospital"),
                    ("Monash University", "airport")):
    hits = find_place(query, kind)
    assert all(h["kind"] == kind for h in hits), \
        f"「{query}」限定 {kind} 却返回了 {[(h['name'], h['kind']) for h in hits][:3]}"

# 通用词能被绕过:OSM 里 Flinders Street 站就叫 "Flinders Street",不带 Station
flinders = find_place("Flinders Street Station", "train_station")
assert len(flinders) == 1 and flinders[0]["name"] == "Flinders Street"

# 找不到就是找不到
assert find_place("完全不存在的地方") == []
assert find_place("") == []
assert find_place("   ") == []

# ---------------------------------------------------------------- 到具名地点的距离

d1 = distance_to_place(*RICHMOND, monash)
assert d1 and 0 < d1["distance_m"] < 30_000
# 必须取**最近**的那个校区,不是第一个
all_d = [float(_haversine_m(RICHMOND[0], RICHMOND[1],
                            _one(p["latitude"], p["longitude"]))[0]) for p in monash]
assert abs(d1["distance_m"] - min(all_d)) < 1, "没有取最近的校区"

assert distance_to_place(None, None, monash) is None
assert distance_to_place(*RICHMOND, []) is None

# ---------------------------------------------------------------- 步行时间

assert walk_minutes(None) is None
assert walk_minutes(0) == 1          # 再近也不写"0 分钟"
assert walk_minutes(5000) == 60      # 5 公里 / 5 km·h⁻¹ = 1 小时
assert walk_minutes(800) == 10

assert set(KIND_ZH) == set(KINDS)

print("周边设施 全部通过。")
