"""一次性抓取维州公立学校**招生学区边界**,产出 data/school_zones.geojson。V6。

    python pipeline/fetch_school_zones.py

## 为什么需要这个 —— 它修的是一个"口径错误",不是加功能

澳洲(尤其中国买家)说的"学区房"指的是**在学校的招生边界内**,不是"离学校近"。
一套距学校 393 米的房子完全可能属于另一个学区。

在这之前,系统的「教育配套」属性测的是**距离**,拿它回答"学区"是答非所问 ——
**这比"不支持"更糟**,因为它给出了一个看起来合理、实际答错了的结果。

## 数据

来源:维州教育部,经 DataVic 发布,**CC BY 4.0**(需署名)。
  https://discover.data.vic.gov.au/dataset/victorian-government-school-zones-2026

包里同时有 shapefile 和 GeoJSON,**GeoJSON 用的是 CRS84(即 WGS84 经纬度)**,
和房源坐标同一个坐标系,不需要投影转换。

中学按年级分了 7 到 12 六个文件。这里只取 **Year 7** —— 那是决定入学的那一档,
家长买房时关心的就是"孩子上初一能进哪所"。

## 两个必须写进文档的限制

1. **只覆盖公立学校。** 私立和教会学校不按地理划片招生,本数据里没有,
   系统也不会声称有。
2. **边界是 2026 年的,房源成交是 2016–2018 年的。** 但这里的问题问的是
   "**如果现在买下这套房**,会落在谁的学区",是个现在时问题,用当前边界是对的。
   要做历史回溯分析则不能用。
"""

import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parents[1] / "data" / "school_zones.geojson"
URL = ("https://www.education.vic.gov.au/Documents/about/research/datavic/"
       "dv418_DataVic_School_Zones_2026_MAR26.zip")
UA = "CSIT998-capstone-student-project/1.0"

# 大墨尔本范围(南,西,北,东)—— 和 OSM 抓取用的是同一个框
BBOX = (-38.50, 144.50, -37.40, 145.60)

# 包内文件 -> 我们的学段标签
WANTED = {
    "Primary_Integrated_2026.geojson": "primary",
    "Secondary_Integrated_Year7_2026.geojson": "secondary",
}


def _bounds(geometry) -> tuple[float, float, float, float]:
    """算一个 GeoJSON 几何的经纬度外接框。不引入依赖,自己走一遍坐标。"""
    lats, lons = [], []

    def walk(coords):
        if coords and isinstance(coords[0], (int, float)):
            lons.append(coords[0])
            lats.append(coords[1])
            return
        for item in coords:
            walk(item)

    walk(geometry["coordinates"])
    return min(lats), min(lons), max(lats), max(lons)


def _intersects_bbox(geometry) -> bool:
    south, west, north, east = BBOX
    min_lat, min_lon, max_lat, max_lon = _bounds(geometry)
    return not (max_lat < south or min_lat > north or max_lon < west or min_lon > east)


def main() -> None:
    print(f"正在下载维州学校学区边界……\n  {URL}")
    request = urllib.request.Request(URL, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(request, timeout=600).read()
    print(f"  {len(raw) / 1e6:.1f} MB")

    archive = zipfile.ZipFile(io.BytesIO(raw))
    features, stats = [], {}
    for name, level in WANTED.items():
        match = next((n for n in archive.namelist() if n.endswith(name)), None)
        if match is None:
            raise SystemExit(f"包里找不到 {name} —— 数据结构变了,检查一下再跑")
        data = json.loads(archive.read(match).decode("utf-8"))
        crs = ((data.get("crs") or {}).get("properties") or {}).get("name", "")
        # 坐标系必须是 CRS84/WGS84。若哪年官方改成 VicGrid,这里要立刻炸,
        # 而不是把投影坐标当经纬度用 —— 那会让所有学区判断静默错位。
        if "CRS84" not in crs and "4326" not in crs:
            raise SystemExit(f"{name} 的坐标系是 {crs!r},不是 WGS84,需要先做投影转换")

        kept = 0
        for feature in data["features"]:
            if not _intersects_bbox(feature["geometry"]):
                continue
            properties = feature["properties"]
            features.append({
                "type": "Feature",
                "properties": {
                    "level": level,
                    "school": properties.get("School_Name") or properties.get("Campus_Name"),
                    "year_level": properties.get("Year_Level"),
                    "boundary_year": properties.get("Boundary_Year"),
                },
                "geometry": feature["geometry"],
            })
            kept += 1
        stats[level] = (kept, len(data["features"]))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                              ensure_ascii=False), encoding="utf-8")

    print(f"\n已写入 {OUT}({OUT.stat().st_size / 1e6:.1f} MB)\n")
    print(f"  {'学段':<12}{'大墨尔本':>10}{'全州':>10}")
    for level, (kept, total) in stats.items():
        label = "小学" if level == "primary" else "中学(Year 7)"
        print(f"  {label:<10}{kept:>10,}{total:>10,}")
    print("\n  只覆盖**公立**学校 —— 私立和教会学校不按地理划片招生,数据里没有。")
    print("  边界年份 2026;房源成交 2016–2018。问的是「现在买下会落在谁的学区」,")
    print("  用当前边界是对的;做历史回溯分析则不能这么用。")
    print("\n  数据来源:维州教育部 / DataVic,CC BY 4.0,交付文档需署名。")


if __name__ == "__main__":
    main()
