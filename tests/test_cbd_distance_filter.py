"""「距 CBD ≤ X km」硬条件(外部测试第 3 项,2026-10-05)必须和页面上显示的「距 CBD」同一口径。

    python tests/test_cbd_distance_filter.py

需要数据库,不需要 LLM、不联网。逐套核对全库:SQL 筛出来的集合 == 按 nearby.distance_to_cbd_km
(页面显示用的那个函数)算出 ≤ X 的集合,一套不多、一套不少。

踩过的坑(都由这个测试兜住):
  - 用不取整的距离比较,会漏掉显示为「5.0 km」的 5.04 km 房源;
  - least() 会忽略 NULL,没坐标的房源被算成半个地球周长,全被筛掉;
  - 不传这个参数时,结果必须和原来逐条相同(跨线契约)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.amenities import nearby                      # noqa: E402
from app.core.db import get_connection                # noqa: E402
from app.orchestration import graph as g              # noqa: E402
from app.search.search import search_properties       # noqa: E402

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT id, latitude, longitude, distance_cbd FROM properties")
    rows = cur.fetchall()
shown = {i: nearby.distance_to_cbd_km(lat, lon, d) for i, lat, lon, d in rows}
assert any(lat is None for _, lat, _, _ in rows), "库里应有缺坐标的房源,否则 NULL 分支没被测到"

checks = 0
for limit in (2.3, 5, 10, 12.5, 20, 35):
    expect = {i for i, d in shown.items() if d is not None and d <= limit}
    got = {p["id"] for p in search_properties("house", max_distance_cbd_km=limit, limit=100_000)}
    assert got == expect, f"≤ {limit} km: 漏 {len(expect - got)} 套、多 {len(got - expect)} 套"
    checks += 1

# 不传 = 不筛:和原来逐条一致
assert len(search_properties("house", limit=100_000)) == len(rows)
assert len(search_properties("house", max_distance_cbd_km=None, limit=100_000)) == len(rows)
checks += 2

# 参数闸门:只收 (0, 200] 的数字,保留一位小数
for raw, want in ((20, 20.0), (12.34, 12.3), (0, None), (-5, None), (True, None), (500, None), ("20", None)):
    assert g._sanitize({"intent": "new_search", "max_distance_cbd_km": raw}, "q")["max_distance_cbd_km"] == want, raw
    checks += 1
# 不再列为「不支持」;步行时间仍然是
from app.amenities import registry                     # noqa: E402
assert "到 CBD 的距离要求" not in registry.UNSUPPORTED and "步行/驾车时间" in registry.UNSUPPORTED
checks += 1

print(f"距 CBD 筛选 全部通过:{checks} 项检查(全库 {len(rows)} 套逐套核对,与页面显示同一口径)")
