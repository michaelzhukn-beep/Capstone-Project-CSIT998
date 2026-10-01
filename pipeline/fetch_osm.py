"""一次性抓取所有地理数据,产出 data/osm_points.csv。V5。

    python pipeline/fetch_osm.py

**查询是从 app/amenities/registry.py 的 SOURCES 生成的,不是手写的。**
这是整个改动的要点:加一个数据源只需在注册表里加一条,这个脚本自动会去抓。
手写查询的话,注册表和查询迟早对不上,而且不会报错 —— 只是那个源永远是空的。

取代了 V3/V4 的 fetch_amenities.py 和 fetch_context.py。那两个脚本各自维护
一份查询,注册表出现后就没有存在的理由了。

**这是一次性脚本,不是查询时调用的。** 抓下来的 CSV 进仓库,系统运行时只读
本地文件、不联网:演示不能因为别人的 API 挂了而崩,而且答辩当天用的必须和
今天测的是同一份数据。

数据来源:OpenStreetMap(经 Overpass API),ODbL 许可,交付物需署名。
"""

import csv
import hashlib
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.amenities.registry import RESAMPLE_M, SOURCES              # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "osm_points.csv"
# 公共 Overpass 端点会限流,高峰期直接 504。挨个试,别让一次性脚本
# 变成"看运气"的脚本 —— 你或队友哪天要重跑,不该卡在这里。
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
BBOX = "-38.50,144.50,-37.40,145.60"      # 大墨尔本
UA = "CSIT998-capstone-student-project/1.0"

ALIAS_TAGS = ("alt_name", "short_name", "official_name", "name:en", "name:zh")


def _build_query(geometries: tuple[str, ...], only: str | None = None) -> str:
    """从注册表生成 Overpass 查询。点用 out center,线和面用 out geom。
    only 指定时只查这一个源 —— 线与面带完整几何,全部塞进一次请求会超出公共端点的内存上限。"""
    clauses = []
    for kind, source in SOURCES.items():
        if source["geometry"] not in geometries or not source["overpass"]:
            continue
        if only and kind != only:
            continue
        for fragment in source["overpass"].split(";"):
            fragment = fragment.strip()
            if fragment:
                clauses.append(f"  {fragment}({BBOX});")
    out = "out geom;" if "point" not in geometries else "out center tags;"
    return "[out:json][timeout:900][maxsize:1073741824];\n(\n" + "\n".join(clauses) + "\n);\n" + out


def _fetch(query: str, label: str) -> list[dict]:
    print(f"正在请求 {label}……")
    # 设了 OSM_CACHE_DIR 就把原始响应按查询内容存一份:十几个请求中途失败时,重跑不必全部重下,
    # 也少给公共端点添负担。
    cache_dir = os.environ.get("OSM_CACHE_DIR")
    cache = (Path(cache_dir) / (hashlib.sha1(query.encode()).hexdigest()[:16] + ".json")) if cache_dir else None
    if cache and cache.exists():
        print(f"  读缓存 {cache.name}")
        return json.loads(cache.read_bytes())["elements"]
    payload = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(4):
        for endpoint in ENDPOINTS:
            try:
                started = time.time()
                request = urllib.request.Request(endpoint, data=payload,
                                                 headers={"User-Agent": UA})
                raw = urllib.request.urlopen(request, timeout=600).read()
                print(f"  {endpoint} · {len(raw) / 1e6:.1f} MB · {time.time() - started:.0f}s")
                elements = json.loads(raw)["elements"]
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(raw)
                # 线与面按源逐个请求,连着发会被公共端点 429 限流。每次成功后歇一会儿。
                time.sleep(15)
                return elements
            except Exception as exc:
                print(f"  {endpoint} 失败({type(exc).__name__}: {exc}),换下一个")
        if attempt < 3:
            wait = 60 * (attempt + 1)
            print(f"  全部端点失败,等 {wait} 秒重试一轮……")
            time.sleep(wait)
    raise SystemExit(f"取不到 {label} 数据。稍后重试。")


def _resample(geometry: list[dict], step_m: int) -> list[tuple[float, float]]:
    """沿折线每 step_m 米取一个点,**在线段中间插值**,首尾顶点都保留。

    旧版只是跳过相距不足 step_m 的原始顶点、从不插值:一段只有两个顶点的 800 米直路
    只剩两个端点,路中间的房子会被算成离路 400 米。道路顶点通常够密,审计时没暴露;
    公园边界常是几百米的直边,改按边界采样后这个缺陷就会直接变成错数。
    用简易的度->米换算即可 —— 这里只决定采样位置,最终距离由 haversine 算。
    """
    pts = [(p["lat"], p["lon"]) for p in geometry if "lat" in p and "lon" in p]
    if not pts:
        return []
    out = [pts[0]]
    carry = 0.0                      # 上一个采样点之后已经走过的距离
    for (a_lat, a_lon), (b_lat, b_lon) in zip(pts, pts[1:]):
        seg = math.hypot((b_lat - a_lat) * 111_000, (b_lon - a_lon) * 88_000)
        if seg == 0:
            continue
        pos = step_m - carry
        while pos <= seg:
            t = pos / seg
            out.append((a_lat + (b_lat - a_lat) * t, a_lon + (b_lon - a_lon) * t))
            pos += step_m
        carry = (carry + seg) % step_m
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _outlines(element: dict) -> list[list[dict]]:
    """一个要素的所有轮廓线。way 自带 geometry;relation(大公园常是多边形关系)
    的轮廓散在各个成员里 —— 只读 element["geometry"] 会让这些公园整个消失。"""
    if element.get("geometry"):
        return [element["geometry"]]
    return [m["geometry"] for m in element.get("members") or [] if m.get("geometry")]


def _aliases(tags: dict, name: str) -> str:
    return " | ".join(dict.fromkeys(
        (tags.get(k) or "").strip() for k in ALIAS_TAGS
        if (tags.get(k) or "").strip() and (tags.get(k) or "").strip() != name))


def _school_levels(tags: dict) -> list[str]:
    """学校按 isced:level 拆小学/中学 —— 国际标准教育阶段编码
    (0=学前 1=小学 2=初中 3=高中),实测覆盖 95%,比猜校名可靠。
    P-12 学校(isced:level="1-3")**同时**算进两类:家长问"附近有小学吗",
    一所 P-12 当然算。"""
    nums = set()
    for part in (tags.get("isced:level", "") or "").replace(";", ",").split(","):
        part = part.strip()
        if "-" in part:
            try:
                lo, hi = (int(x) for x in part.split("-", 1))
                nums.update(range(lo, hi + 1))
            except ValueError:
                pass
        elif part.isdigit():
            nums.add(int(part))
    out = []
    if 1 in nums:
        out.append("primary_school")
    if nums & {2, 3}:
        out.append("secondary_school")
    if out:
        return out
    # 没有 isced 标签的那 5%:退回校名关键词,澳洲校名相当规范
    name = (tags.get("name") or "").lower()
    if "primary" in name or "preparatory" in name:
        return ["primary_school"]
    if any(w in name for w in ("secondary", "high school", "college")):
        return ["secondary_school"]
    # 实在判断不出来就两边都算 —— 宁可多算,不要让一所真实存在的学校
    # 从"附近有没有学校"里凭空消失
    return ["primary_school", "secondary_school"]


def _rule_hits(rule, tags: dict) -> bool:
    """注册表里的 match 规则命不命中这个要素的标签。"""
    if not rule:
        return False
    key, values = rule
    got = tags.get(key)
    if got is None:
        return False
    return True if values == "*" else got in values


def _match_kinds(tags: dict) -> list[str]:
    """一个 OSM 要素属于注册表里的哪几个源。一个要素可能属于多个。

    **完全按注册表里显式声明的 match 规则判定**,不从 Overpass 查询字符串
    反解 —— 反解是靠字符串匹配猜标签,加一个带正则的源就会悄悄失配,
    而且不报错,只是那个源永远是空的。
    """
    if tags.get("amenity") == "school":
        # 学校要按教育阶段拆成小学/中学,不能简单按标签归类
        return _school_levels(tags)
    return [kind for kind, source in SOURCES.items()
            if not source.get("school_level")
            and (_rule_hits(source.get("match"), tags)
                 or _rule_hits(source.get("extra_match"), tags))
            and not _rule_hits(source.get("exclude"), tags)]


def _coords(element: dict):
    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]
    center = element.get("center")
    return (center["lat"], center["lon"]) if center else None


def main() -> None:
    rows = []

    # ---- 点要素 ----
    for element in _fetch(_build_query(("point",)), "点要素(站点、学校、商店……)"):
        tags = element.get("tags", {})
        position = _coords(element)
        if position is None:
            continue
        name = (tags.get("name") or "").strip()
        # 别名也存:墨尔本机场正式名 "Melbourne Airport",本地人叫 "Tullamarine"。
        # 只存正式名的话,"离 Tullamarine 近"就查不到。
        aliases = _aliases(tags, name)
        for kind in _match_kinds(tags):
            if SOURCES[kind]["geometry"] != "point":
                continue
            rows.append({"kind": kind, "name": name, "alt_names": aliases,
                         "latitude": round(position[0], 5),
                         "longitude": round(position[1], 5), "osm_id": "", "role": ""})

    # ---- 线与面 ----
    # role:空 = 一个具名的点(点要素本身,或面要素的中心);edge = 沿线/沿边界的采样点。
    # 面要素的边界点也带着名字和 osm_id:最近的那个边界点属于哪个公园,名字就报哪个;
    # 按名字查"离 Albert Park 多远"时,用 osm_id 把这个公园的整圈边界找回来。
    shaped = [k for k, v in SOURCES.items() if v["geometry"] in ("line", "area") and v["overpass"]]
    fetched = ((kind, element) for kind in shaped
               for element in _fetch(_build_query(("line", "area"), only=kind), f"线与面:{SOURCES[kind]['zh']}"))
    for fetched_kind, element in fetched:
        tags = element.get("tags", {})
        # 每次请求只查一个源,所以一个要素只归给它被查出来的那个源 ——
        # 否则同时带 leisure=park 和 landuse=cemetery 的要素会在两次请求里各记一遍
        kinds = [fetched_kind] if fetched_kind in _match_kinds(tags) else []
        if not kinds:
            continue
        osm_id = f"{element.get('type', '')[:1]}{element.get('id', '')}"
        name = (tags.get("name") or "").strip()
        aliases = _aliases(tags, name)
        for kind in kinds:
            area = SOURCES[kind]["geometry"] == "area"
            if area and "lat" in element and "lon" in element:
                # 只标了一个点的小公园:就这一个点,没有边界
                rows.append({"kind": kind, "name": name, "alt_names": aliases,
                             "latitude": round(element["lat"], 5), "longitude": round(element["lon"], 5),
                             "osm_id": osm_id, "role": ""})
                continue
            if area and element.get("bounds"):
                b = element["bounds"]
                rows.append({"kind": kind, "name": name, "alt_names": aliases,
                             "latitude": round((b["minlat"] + b["maxlat"]) / 2, 5),
                             "longitude": round((b["minlon"] + b["maxlon"]) / 2, 5),
                             "osm_id": osm_id, "role": ""})
            for outline in _outlines(element):
                for lat, lon in _resample(outline, RESAMPLE_M):
                    rows.append({"kind": kind, "name": name if area else "", "alt_names": "",
                                 "latitude": round(lat, 5), "longitude": round(lon, 5),
                                 "osm_id": osm_id if area else "", "role": "edge"})

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["kind", "name", "alt_names", "latitude", "longitude", "osm_id", "role"])
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["kind"] for r in rows if r["role"] != "edge")
    edges = Counter(r["kind"] for r in rows if r["role"] == "edge")
    named = Counter(r["kind"] for r in rows if r["name"] and r["role"] != "edge")
    print(f"\n已写入 {OUT}({len(rows):,} 行,{OUT.stat().st_size / 1e6:.1f} MB)\n")
    print(f"  {'数据源':<20}{'要素':>10}{'边界点':>10}{'有名字':>9}{'注册表登记':>12}  一致?")
    problems = []
    for kind, source in SOURCES.items():
        got, expect = counts.get(kind, 0), source.get("count")
        if source["geometry"] in ("point", "area") and expect:
            # 点要素(和面要素的中心点)抓到的数量应当和注册表登记的数量接近。差太多说明
            # 查询写错了,或者 OSM 上的数据变了 —— 两种都需要人看一眼。
            ok = 0.5 <= got / expect <= 2.0
        else:
            ok = got + edges.get(kind, 0) > 0     # 线只有采样点,只能查"非空"
        mark = "✓" if ok else "✗ 要查"
        if not ok:
            problems.append(kind)
        print(f"  {source['zh']:<18}{got:>10,}{edges.get(kind, 0):>10,}{named.get(kind, 0):>9,}"
              f"{(expect or '—'):>12}  {mark}")

    if problems:
        print(f"\n⚠️ 这些源和注册表登记的数量对不上,查一下查询写对没有:{problems}")
    print("\n  数据来源:© OpenStreetMap contributors,ODbL 许可,交付文档需署名。")


if __name__ == "__main__":
    main()
