"""一次性抓取维州罪案统计,产出 data/suburb_crime.csv。V6。

    python pipeline/fetch_crime_stats.py

## 口径:为什么用 LGA 级的率,而不是 suburb 级的案件数

官方表里两件东西不能混:

    Table 01(LGA 级)   有 `Rate per 100,000 population` —— **正确归一化的率**
    Table 03(suburb 级)只有 `Incidents Recorded` —— **原始案件数,没有人口分母**

拿原始案件数跨区比较是错的:CBD 案件多是因为那里人多、流动量大,不是因为
"更危险"。没有人口分母的计数不能当治安指标 —— 这正是本项目一贯反对的
"看起来有数据支撑、其实推不出结论"。

所以取 **LGA 级的率**,并用 Table 03 自带的 suburb → LGA 对应关系接到房源上。
suburb → LGA 的映射也来自官方表本身,不是我们猜的。

## 必须一直挂着的两个限制

1. **粒度是 LGA 级**(大墨尔本约 31 个),比系统里其余属性(点级、米级)粗
   一个数量级。同一个 LGA 内所有房源拿到同一个分。这在方法上站得住,
   但**必须标注**,不能让人以为它和"距最近主干道 640 米"是同一种精度。
2. **时间对不上**:罪案数据是最近一年的,房源成交是 2016–2018 年的。
   LGA 之间的**相对**排序比较稳定,所以当**相对指标**用是站得住的;
   当绝对值用不行。

数据来源:Crime Statistics Agency Victoria。使用前请在其网站确认当期授权条款,
并在交付文档中署名。
"""

import csv
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.xlsx_reader import read_table                        # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "suburb_crime.csv"
CACHE = Path(__file__).resolve().parents[1] / "data" / "_crime_source.xlsx"
URL = ("https://files.crimestatistics.vic.gov.au/2026-06/"
       "Data_Tables_LGA_Criminal_Incidents_Year_Ending_March_2026_0.xlsx")
# 这个站点会挡掉不像浏览器的请求
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _column(header: list[str], name: str) -> int:
    try:
        return header.index(name)
    except ValueError as exc:
        raise SystemExit(
            f"表里找不到列 {name!r} —— 官方改了表结构,先看一眼再跑。"
            f"现有列:{header}") from exc


def main() -> None:
    if CACHE.exists():
        print(f"用已下载的 {CACHE.name}(删掉它可强制重新下载)")
    else:
        print(f"正在下载维州罪案统计……\n  {URL}")
        request = urllib.request.Request(URL, headers={"User-Agent": UA})
        CACHE.write_bytes(urllib.request.urlopen(request, timeout=600).read())
        print(f"  {CACHE.stat().st_size / 1e6:.1f} MB")

    # ---- LGA 级的率 ----
    header, rows = read_table(CACHE, "Table 01")
    c_year = _column(header, "Year")
    c_lga = _column(header, "Local Government Area")
    c_rate = _column(header, "Rate per 100,000 population")
    latest = max(r[c_year] for r in rows if isinstance(r[c_year], int))


    def _number(value):
        """表里有空串和小计行,不是每一格都是数字。转不了就当没有,不猜。"""
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    rate = {}
    for row in rows:
        if row[c_year] != latest:
            continue
        value = _number(row[c_rate])
        if value is not None and row[c_lga]:
            rate[str(row[c_lga]).strip()] = value
    print(f"\nLGA 罪案率({latest} 年至 3 月):{len(rate)} 个 LGA,"
          f"{min(rate.values()):,.0f} ~ {max(rate.values()):,.0f} 每 10 万人")

    # ---- suburb -> LGA(用官方表自带的对应关系)----
    header3, rows3 = read_table(CACHE, "Table 03")
    s_year = _column(header3, "Year")
    s_lga = _column(header3, "Local Government Area")
    s_sub = _column(header3, "Suburb/Town Name")
    s_inc = _column(header3, "Incidents Recorded")
    latest3 = max(r[s_year] for r in rows3 if isinstance(r[s_year], int))

    # 个别 suburb 跨两个 LGA。取案件数更多的那个 —— 那通常是该 suburb 主体
    # 所在的行政区。这是个明确的选择,不是随手取第一个。
    tally: dict[str, dict[str, int]] = {}
    for row in rows3:
        if row[s_year] != latest3 or not row[s_sub]:
            continue
        name = str(row[s_sub]).strip()
        lga = str(row[s_lga]).strip()
        count = row[s_inc] if isinstance(row[s_inc], (int, float)) else 0
        tally.setdefault(name, {})[lga] = tally.setdefault(name, {}).get(lga, 0) + count

    written, skipped = 0, 0
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["suburb", "lga", "rate_per_100k", "year"])
        for suburb, lgas in sorted(tally.items()):
            lga = max(lgas, key=lgas.get)
            if lga not in rate:
                skipped += 1
                continue
            writer.writerow([suburb, lga, round(rate[lga], 1), latest])
            written += 1

    print(f"\n已写入 {OUT}({written:,} 个 suburb;{skipped} 个因 LGA 对不上被跳过)")
    values = sorted(rate.values())
    print(f"  率的分布:最低 {values[0]:,.0f} · 中位 {values[len(values) // 2]:,.0f} "
          f"· 最高 {values[-1]:,.0f}")
    print("\n  ⚠️ 粒度是 **LGA 级**,不是 suburb 级 —— 同一个 LGA 内所有房源同分。")
    print("     比系统里其余属性(点级、米级)粗一个数量级,输出时必须标注。")
    print(f"  ⚠️ 数据是 {latest} 年的,房源成交是 2016–2018 年的。")
    print("     只能当**相对指标**用(哪个区相对更高),不能当绝对值。")
    print("\n  数据来源:Crime Statistics Agency Victoria,交付文档需署名并注明期次。")


if __name__ == "__main__":
    main()
