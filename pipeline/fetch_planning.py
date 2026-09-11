"""一次性抓取维州规划**分区**与**叠加层**,产出 data/planning.geojson.gz。V7。

    python pipeline/fetch_planning.py

## 为什么需要这个 —— 它回答的是"未来",而且是**法条**不是预测

买家最关心、系统此前完全答不了的三个问题:

    "隔壁那块空地以后会不会盖起高楼挡住我?"
    "这房子我买下来能不能推倒重建 / 加建?"
    "这个区未来是变密还是保持现状?"

分区(Zone)规定每块地**法律上**能盖什么、能盖多高;叠加层(Overlay)是叠在
分区之上的额外限制(历史保护、限高、政府征收……)。两者都写在《维州规划纲要》
里,是白纸黑字的法条 —— **查出来就是确定答案,不需要 AI 推测**。

这一点对本项目很关键。曾评估过的"AI 监测 Council 开发申请(DA)"是从非结构化
PDF 里让模型提取意图,结果无法核对、错了也不会报警;而分区是结构化 GIS 多边形,
点落在哪个面里是确定的,对不上就是查错了。同一个需求,一个可核对,一个不可核对,
本项目只做前者。

## 数据

来源:Vicmap Planning,经 Victorian Open Data Platform 的 WFS 发布,
**CC BY 4.0**(需署名),周更。查询时不联网。
  https://opendata.maps.vic.gov.au/geoserver/wfs

    open-data-platform:plan_zone     分区    大墨尔本约 2.2 万个多边形
    open-data-platform:plan_overlay  叠加层  大墨尔本约 10.0 万个多边形

## 三个坑,每个都会让结果**静默错掉**

1. **WFS 2.0 的 bbox 是 `lon,lat` 顺序**,写成 `lat,lon` 不会报错,会返回 0 条。
   这个 bug 我踩过,所以下面用常量拼接并在抓完后校验条数。
2. **必须带 sortBy 分页。** GeoServer 不保证无序分页的稳定性,少了 sortBy
   翻页会重复或漏掉要素 —— 而且不报错。
3. **坐标精度**。GeoServer 默认吐 15 位小数,那是纳米级精度,纯属浪费。
   截到 6 位(约 0.1 米)已远超地籍需要,体积能省一半。

## 输出格式:为什么是 JSONL 而不是一个大 GeoJSON

原始数据 345 MB。用 `json.load()` 一次读进来,光 Python 的 dict/list/float 开销
就要 **2.4 GB 内存** —— 实测,而几何对象本身只占 0.39 GB。

所以这里写成**每行一个 Feature** 的 JSONL(gzip 压缩)。读取端可以逐行解析、
立刻转成几何对象再丢掉那一行的字典,峰值内存降到 0.4 GB。学区那份只有 0.8 MB,
用整块 GeoJSON 没问题;这份大两个数量级,格式必须跟着换。

## 必须一直挂着的限制

**分区是当前(抓取日)的,房源成交是 2016–2018 年的。** 这里问的是"**如果现在
买下这套房**,周围法律上能盖什么",是现在时问题,用当前分区是对的;
但**不能**用它回溯解释 2017 年的成交价 —— 那需要当年的分区快照,我们没有。
"""

import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parents[1] / "data" / "planning.jsonl.gz"
BASE = "https://opendata.maps.vic.gov.au/geoserver/wfs"
UA = "CSIT998-capstone-student-project/1.0"

# 大墨尔本范围(南,西,北,东)—— 和 OSM、学区抓取用的是同一个框
BBOX = (-38.50, 144.50, -37.40, 145.60)

PAGE = 5_000        # GeoServer 单次上限通常是 10000,取一半留余量
PRECISION = 6       # 经纬度小数位。6 位 ≈ 0.1 米

LAYERS = {
    "zone": "open-data-platform:plan_zone",
    "overlay": "open-data-platform:plan_overlay",
}


def _bbox_param() -> str:
    """WFS 2.0 的 bbox 是 **lon,lat** 顺序。写反了不会报错,会返回 0 条。"""
    south, west, north, east = BBOX
    return f"{west},{south},{east},{north},EPSG:4326"


def _get(params: dict) -> bytes:
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(request, timeout=600).read()
        except Exception as exc:                      # noqa: BLE001
            if attempt == 3:
                raise
            print(f"    第 {attempt + 1} 次失败({type(exc).__name__}),等 {5 * (attempt + 1)}s 重试")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def _hits(type_name: str) -> int:
    import re
    raw = _get({"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": type_name, "resultType": "hits",
                "bbox": _bbox_param()}).decode("utf-8", "replace")
    match = re.search(r'numberMatched="(\d+)"', raw)
    if not match:
        raise SystemExit(f"拿不到 {type_name} 的要素总数,返回的是:\n{raw[:400]}")
    return int(match.group(1))


def _round_coords(node):
    """把坐标截到 PRECISION 位。就地递归,避免为一亿个浮点数再建一份列表。"""
    if node and isinstance(node[0], (int, float)):
        return [round(float(node[0]), PRECISION), round(float(node[1]), PRECISION)]
    return [_round_coords(item) for item in node]


def _pick(properties: dict, *names):
    """按优先级取第一个非空字段。分区层和叠加层的字段名不完全一致,
    而且官方改过一次 —— 硬编码一个名字会在某次周更后静默变成 None。"""
    for name in names:
        value = properties.get(name)
        if value not in (None, ""):
            return value
    return None


def fetch_layer(kind: str, type_name: str) -> list[dict]:
    total = _hits(type_name)
    print(f"\n{kind}({type_name}):{total:,} 个多边形")
    features, start = [], 0
    while start < total:
        raw = _get({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": type_name, "outputFormat": "application/json",
            "bbox": _bbox_param(),
            "count": str(PAGE), "startIndex": str(start),
            # 分页必须带 sortBy:GeoServer 不保证无序分页稳定,
            # 少了它翻页会重复或漏要素,而且不报错。
            "sortBy": "pfi",
        })
        page = json.loads(raw).get("features", [])
        if not page:
            print(f"  startIndex={start:,} 返回 0 条,提前结束(总数可能刚变过)")
            break
        for feature in page:
            properties = feature["properties"]
            features.append({
                "type": "Feature",
                "properties": {
                    "kind": kind,
                    "code": _pick(properties, "zone_code", "overlay_code"),
                    "description": _pick(properties, "zone_description", "overlay_description"),
                    "lga": _pick(properties, "lga"),
                },
                "geometry": {"type": feature["geometry"]["type"],
                             "coordinates": _round_coords(feature["geometry"]["coordinates"])},
            })
        start += len(page)
        print(f"  {start:,}/{total:,}")
    return features


def main() -> None:
    features = []
    for kind, type_name in LAYERS.items():
        got = fetch_layer(kind, type_name)
        # bbox 写反(lat,lon)会安静地返回 0 条 —— 这里必须炸,不能写出一个空文件
        if not got:
            raise SystemExit(
                f"{kind} 一条都没抓到。先检查 bbox 是不是写成了 lat,lon —— "
                "WFS 2.0 要的是 lon,lat,写反了不报错、只返回 0 条。")
        features.extend(got)

    no_code = sum(1 for f in features if not f["properties"]["code"])
    if no_code:
        raise SystemExit(
            f"有 {no_code:,} 个要素没有 code —— 官方大概改了字段名,"
            "检查 _pick() 里的候选名再跑。")

    OUT.parent.mkdir(exist_ok=True)
    # 每行一个 Feature。gzip:分区多边形的坐标串重复度高,压缩比很好。
    raw_bytes = 0
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=6) as handle:
        for feature in features:
            line = json.dumps(feature, ensure_ascii=False, separators=(",", ":"))
            raw_bytes += len(line) + 1
            handle.write(line + "\n")

    print(f"\n已写入 {OUT}"
          f"(原始 {raw_bytes / 1e6:.1f} MB -> 压缩后 {OUT.stat().st_size / 1e6:.1f} MB)\n")

    for kind in LAYERS:
        subset = [f["properties"] for f in features if f["properties"]["kind"] == kind]
        counter = Counter(p["code"] for p in subset)
        label = "分区" if kind == "zone" else "叠加层"
        print(f"  {label} {len(subset):,} 个,{len(counter)} 种代码。最常见:")
        for code, n in counter.most_common(8):
            desc = next(p["description"] for p in subset if p["code"] == code)
            print(f"    {code:<10}{n:>7,}   {desc}")
        print()

    print("  ⚠️ 分区是**当前**的,房源成交是 2016–2018 年的。")
    print("     问的是「现在买下,周围法律上能盖什么」—— 现在时问题,用当前分区是对的;")
    print("     但不能用它回溯解释 2017 年的成交价,那需要当年的分区快照,我们没有。")
    print("\n  数据来源:Vicmap Planning / Victorian Open Data Platform,CC BY 4.0,交付文档需署名。")


if __name__ == "__main__":
    main()
