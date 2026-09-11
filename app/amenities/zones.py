"""学校招生学区归属。V6。

数据来自 data/school_zones.geojson(由 pipeline/fetch_school_zones.py 一次性
抓取,维州教育部 / DataVic,**CC BY 4.0**)。查询时不联网。

## 它和「教育配套」属性的区别 —— 这是本模块存在的全部理由

    教育配套(school_access)  = 离最近的学校**多远**   -> 一个 0~100 的评分
    学区(这里)               = 落在**谁的**招生边界内 -> 一个确定的事实

澳洲说的"学区房"指后者。一套距学校 393 米的房子完全可能属于另一个学区 ——
拿距离回答学区,**比"不支持"更糟**:它给出一个看起来合理、实际答错的结果。

所以这里产出的不是分数,是**事实**:「所属小学学区:Ashwood Primary School」。
事实不需要权重,也不需要分位数,它要么是,要么不是。

## 两个必须一直挂着的限制

1. **只覆盖公立学校。** 私立和教会学校不按地理划片招生,数据里没有,
   系统也不会声称有。
2. **边界是 2026 年的**,房源成交是 2016–2018 年的。这里问的是"现在买下会
   落在谁的学区",是现在时问题,用当前边界是对的;做历史回溯则不能这么用。
"""

import json
from pathlib import Path

import numpy as np
from shapely import STRtree, points as shapely_points
from shapely.geometry import shape

_GEOJSON = Path(__file__).resolve().parents[2] / "data" / "school_zones.geojson"

LEVEL_ZH = {"primary": "小学", "secondary": "中学"}
LEVELS = tuple(LEVEL_ZH)

_data: dict | None = None


def _load() -> dict:
    """读进多边形,每个学段建一棵 STRtree(空间索引)。

    为什么要空间索引:725 个小学学区 × 几千套候选房 = 几百万次多边形判断。
    STRtree 先用外接框粗筛,再做精确判断,快两个数量级。
    """
    global _data
    if _data is not None:
        return _data
    if not _GEOJSON.exists():
        raise RuntimeError(
            f"学区数据缺失({_GEOJSON.name})。"
            "请先运行:python pipeline/fetch_school_zones.py")

    raw = json.loads(_GEOJSON.read_text(encoding="utf-8"))
    by_level: dict[str, dict] = {}
    for feature in raw["features"]:
        level = feature["properties"]["level"]
        bucket = by_level.setdefault(level, {"geoms": [], "names": [], "year": []})
        bucket["geoms"].append(shape(feature["geometry"]))
        bucket["names"].append(feature["properties"]["school"])
        bucket["year"].append(feature["properties"].get("boundary_year"))

    _data = {
        level: {"tree": STRtree(bucket["geoms"]),
                "geoms": bucket["geoms"],
                "names": bucket["names"],
                "year": bucket["year"]}
        for level, bucket in by_level.items()
    }
    return _data


def warm_up() -> dict:
    data = _load()
    return {level: len(v["names"]) for level, v in data.items()}


def zone_for_batch(lats, lons) -> list[dict]:
    """一批坐标各自落在哪些学区里。返回 [{"primary": 校名, "secondary": 校名}, ...]。

    落不进任何学区就**不出现那个键** —— 不放 None 进去假装查过。
    (郊区边缘、非住宅用地确实可能不在任何公立学区内。)
    """
    n = len(list(lats))
    out: list[dict] = [{} for _ in range(n)]
    usable = [i for i in range(n) if lats[i] is not None and lons[i] is not None]
    if not usable:
        return out

    pts = shapely_points(np.array([lons[i] for i in usable], dtype=float),
                         np.array([lats[i] for i in usable], dtype=float))
    for level, bucket in _load().items():
        # STRtree 先按外接框粗筛,predicate="within" 再做精确的点在面内判断。
        # 只粗筛不精判会把"外接框重叠但实际不在里面"的算进来 —— 学区边界是
        # 不规则多边形,这个差别很大。
        pairs = bucket["tree"].query(pts, predicate="within")
        for point_idx, zone_idx in zip(pairs[0], pairs[1]):
            out[usable[int(point_idx)]].setdefault(level, bucket["names"][int(zone_idx)])
    return out


def zone_for(lat, lon) -> dict:
    """单个坐标的学区归属。"""
    if lat is None or lon is None:
        return {}
    return zone_for_batch([lat], [lon])[0]


def find_zone(school: str, level: str | None = None) -> list[dict]:
    """按校名找学区(用户说"我要在 X 小学的学区内")。

    返回 [{"level":..., "school":..., "index":...}, ...]。找不到就返回空 ——
    **绝不退而求其次给个名字相近的学校**,那和"要机场给小学"是同一类错误。
    """
    if not school or not school.strip():
        return []
    needle = school.strip().lower()
    hits = []
    for lvl, bucket in _load().items():
        if level and lvl != level:
            continue
        for i, name in enumerate(bucket["names"]):
            if name and needle in name.lower():
                hits.append({"level": lvl, "school": name, "index": i})
    # 名字完全相等的优先;否则按名字长度升序(短的通常就是那所学校本身,
    # 长的往往是某个分校区)
    exact = [h for h in hits if h["school"].lower() == needle]
    return exact or sorted(hits, key=lambda h: len(h["school"]))[:8]


def in_zone_batch(lats, lons, zone_hits: list[dict]) -> list[bool]:
    """一批坐标是否落在指定的那些学区里(任一个即可)。"""
    n = len(list(lats))
    out = [False] * n
    if not zone_hits:
        return out
    usable = [i for i in range(n) if lats[i] is not None and lons[i] is not None]
    if not usable:
        return out
    pts = shapely_points(np.array([lons[i] for i in usable], dtype=float),
                         np.array([lats[i] for i in usable], dtype=float))
    data = _load()
    for hit in zone_hits:
        geom = data[hit["level"]]["geoms"][hit["index"]]
        inside = geom.contains(pts)
        for k, i in enumerate(usable):
            if inside[k]:
                out[i] = True
    return out


def describe(zones: dict) -> str:
    """把学区归属写成人话。没查到就说没查到,不猜。"""
    if not zones:
        return "不在任何公立学校学区内(或该坐标无学区数据)"
    return " · ".join(f"{LEVEL_ZH[level]}学区 {name}"
                      for level, name in zones.items() if level in LEVEL_ZH)
