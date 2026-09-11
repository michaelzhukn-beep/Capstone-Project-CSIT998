"""学区归属与 LGA 罪案率的验收。V6。

    python tests/test_zones_crime.py

需要数据库(用真实房源坐标做抽样核对),不需要 LLM、不联网。

这两份数据是**新加的两种数据形态**,和注册表里的 OSM 点/线/面都不一样:

    学区    多边形归属判断 -> 产出**事实**(在谁的学区内),不是评分
    罪案率  按区名查表     -> 产出 LGA 级的数,粒度比点级粗一个数量级

所以它们各自独立成模块,这套测试也单独写。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.amenities import nearby, suburb_stats, zones
from app.amenities.registry import ATTRIBUTES, UNSUPPORTED
from app.core.db import close_pool, get_connection

# ---------------------------------------------------------------- 学区

info = zones.warm_up()
assert info.get("primary", 0) > 500, f"小学学区只有 {info.get('primary')} 个,数据大概没抓全"
assert info.get("secondary", 0) > 100, f"中学学区只有 {info.get('secondary')} 个"

# 几个已知点。这些是墨尔本常见区,应当都落在某个公立学区内。
for label, lat, lon in (("Richmond", -37.8197, 144.9976),
                        ("Balwyn", -37.8100, 145.0800),
                        ("Point Cook", -37.9000, 144.7500)):
    z = zones.zone_for(lat, lon)
    assert "primary" in z and "secondary" in z, f"{label} 没落在学区内:{z}"
    assert z["primary"] and z["secondary"]

# 没有坐标就返回空,不编造
assert zones.zone_for(None, None) == {}
assert zones.zone_for_batch([], []) == []
assert "无" in zones.describe({}) or "不在" in zones.describe({})

# 按校名找学区
hits = zones.find_zone("Balwyn Primary School", "primary")
assert hits and all(h["level"] == "primary" for h in hits)
assert any("balwyn" in h["school"].lower() for h in hits)
# 限定了学段就不能跨学段返回
assert all(h["level"] == "secondary" for h in zones.find_zone("Balwyn", "secondary"))
# 找不到就是找不到 —— **绝不退而求其次给个名字相近的学校**
assert zones.find_zone("完全不存在的学校") == []
assert zones.find_zone("") == []

# 在不在指定学区内
inside = zones.in_zone_batch([-37.8100], [145.0800], zones.find_zone("Balwyn Primary School", "primary"))
assert len(inside) == 1
assert zones.in_zone_batch([-37.81], [145.08], []) == [False]

# ---------------------------------------------------------------- 学区 ≠ 距离
#
# 这是整个模块存在的理由,所以必须钉住:如果哪天"最近的学校"和"所属学区"
# 高度一致了,说明数据或算法出了问题(或者口径又被搞混了)。

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT suburb, latitude, longitude FROM properties "
                "WHERE latitude IS NOT NULL ORDER BY id LIMIT 600")
    rows = cur.fetchall()

lats = [r[1] for r in rows]
lons = [r[2] for r in rows]
zone_rows = zones.zone_for_batch(lats, lons)
_, nearest_names = nearby.nearest_batch(lats, lons, "primary_school")

covered = sum(1 for z in zone_rows if z.get("primary"))
assert covered / len(rows) > 0.9, f"只有 {covered}/{len(rows)} 套房落在小学学区内,太低"

same = sum(1 for z, name in zip(zone_rows, nearest_names)
           if z.get("primary") and name
           and z["primary"].lower().split()[0] == name.lower().split()[0])
ratio = same / covered
# 实测约 54%。放宽到 30%~85% 当护栏:
#   高于 85% 说明两者几乎等价,那这个模块就没必要存在(多半是算错了)
#   低于 30% 说明匹配逻辑有问题
assert 0.30 < ratio < 0.85, (
    f"「最近的小学」与「所属学区小学」一致率是 {ratio:.0%} —— "
    "实测应在 54% 上下。太高说明两者被算成了同一回事,太低说明匹配有问题")

# ---------------------------------------------------------------- 罪案率

crime_info = suburb_stats.warm_up()
assert crime_info["suburbs"] > 1000, f"只有 {crime_info['suburbs']} 个区有罪案数据"
assert crime_info["year"]

melbourne = suburb_stats.crime_for("Melbourne")
brighton = suburb_stats.crime_for("Brighton")
assert melbourne and brighton
# CBD 的罪案率必须显著高于海边富人区 —— 这条对不上说明数据接错了
assert melbourne["rate_per_100k"] > brighton["rate_per_100k"] * 2, (
    f"CBD {melbourne['rate_per_100k']:,.0f} vs Brighton {brighton['rate_per_100k']:,.0f},"
    "两者关系不合常理")
assert melbourne["lga"] and brighton["lga"]

# 查不到就返回 None,**不拿平均值兜底** ——
# "这个区没数据"和"这个区是平均水平"是两回事
assert suburb_stats.crime_for("完全不存在的区") is None
assert suburb_stats.crime_for(None) is None
assert suburb_stats.crime_for("") is None

# 粒度限制必须跟着数字一起出现,不能只写在文档里
text = suburb_stats.describe(melbourne)
assert "LGA" in text, "罪案率的说明里没提粒度"
assert "同区所有房源相同" in text
assert "无" in suburb_stats.describe(None)

# 全库每个区都要能查到 —— 覆盖率不足会让部分房源静默缺这一项
with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT suburb FROM properties")
    suburbs = [r[0] for r in cur.fetchall()]
missing = [s for s in suburbs if suburb_stats.crime_for(s) is None]
assert not missing, f"这些区查不到罪案数据:{missing[:10]}"

# ---------------------------------------------------------------- 和注册表的关系

# 「治安较好」属性必须存在,而且依据的是罪案率、不是警察局距离。
# 警察局离得近**不等于**治安好(市中心警局最密集),那是本项目明确拒绝过的伪科学。
assert "low_crime" in ATTRIBUTES
assert "crime_rate_per_100k" in ATTRIBUTES["low_crime"]["parts"]
assert "police_m" not in ATTRIBUTES["low_crime"]["parts"]
assert "LGA" in ATTRIBUTES["low_crime"]["note"], "属性说明里必须写明粒度"

# 仍然不支持的是**更细的**治安数据,不是治安本身
assert any("街道" in k for k in UNSUPPORTED)
assert all("low_crime" in v or "治安" in v or "犯罪" in v
           for k, v in UNSUPPORTED.items() if "治安" in k or "犯罪" in k)

close_pool()
print("学区归属 + LGA 罪案率 全部通过。")
