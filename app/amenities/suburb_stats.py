"""按区查表的统计数据(目前只有罪案率)。V6。

数据来自 data/suburb_crime.csv(由 pipeline/fetch_crime_stats.py 一次性生成,
Crime Statistics Agency Victoria)。查询时不联网。

## 为什么单独一个模块,不塞进 registry.SOURCES

注册表管的是"OSM 上的点/线/面 -> 距离或密度"。这里的数据形态完全不同:
**按区名查一张表**,没有坐标、没有距离。硬塞进去只会让"数据源"失去意义。

## 粒度:必须一直挂着的那句话

**这是 LGA 级的数据,不是 suburb 级。** 大墨尔本约 31 个 LGA,同一个 LGA 内
所有房源拿到同一个值 —— 比系统里其余属性(点级、米级)粗一个数量级。

为什么不用 suburb 级:官方 suburb 级表里**只有原始案件数,没有人口分母**。
拿计数跨区比较是错的 —— CBD 案件多是因为人多、流动量大,不是"更危险"。
没有分母的计数推不出治安结论,那正是本项目一贯反对的东西。

## 和"警察局距离"的区别

这个项目此前明确拒绝把"距最近警察局"当治安指标 —— 市中心警局最密集,
犯罪率通常也最高,那是典型的伪科学。现在用的是**官方发布的每 10 万人罪案率**,
有出处、有分母、可核对。两者不是一回事。
"""

import csv
from pathlib import Path

_CSV = Path(__file__).resolve().parents[2] / "data" / "suburb_crime.csv"

_data: dict | None = None


def _load() -> dict:
    global _data
    if _data is not None:
        return _data
    if not _CSV.exists():
        raise RuntimeError(
            f"罪案数据缺失({_CSV.name})。请先运行:python pipeline/fetch_crime_stats.py")
    rows = {}
    year = None
    with _CSV.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows[row["suburb"].strip().lower()] = {
                "lga": row["lga"],
                "rate_per_100k": float(row["rate_per_100k"]),
            }
            year = row.get("year") or year
    _data = {"by_suburb": rows, "year": year}
    return _data


def warm_up() -> dict:
    data = _load()
    return {"suburbs": len(data["by_suburb"]), "year": data["year"]}


def crime_for(suburb) -> dict | None:
    """查一个区的罪案率。查不到返回 None —— **不拿平均值兜底**。
    "这个区没数据"和"这个区是平均水平"是两回事。"""
    if not suburb:
        return None
    return _load()["by_suburb"].get(str(suburb).strip().lower())


def describe(info: dict | None) -> str:
    """写成人话。粒度限制必须跟着数字一起出现,不能只在文档里写一次。"""
    if not info:
        return "该区无罪案数据"
    data = _load()
    return (f"所在 {info['lga']} 区罪案率 {info['rate_per_100k']:,.0f} 起/10 万人"
            f"({data['year']} 年,**LGA 级**数据,同区所有房源相同)")
