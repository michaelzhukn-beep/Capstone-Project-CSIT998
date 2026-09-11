"""算出各项环境证据的分位数基准,产出 data/context_baseline.json。V5。

**要算哪些证据由 app/amenities/registry.py 决定**,这个脚本不维护自己的清单。

    python pipeline/build_context_baseline.py

**为什么需要这一步。** "距最近主干道 640 米"本身说明不了什么 —— 640 米在
市中心算很远,在远郊算很近。要让"安静"这个词有意义,必须知道这个数在全库
里排第几。所以先从全库抽样,把每项证据的分布(分位点)算出来存下来。

**为什么只存分位点,不存每套房的距离。** 存每套房就要用 property id 当键,
而 id 是 B 那边重新灌库时会变的。缓存和数据库悄悄对不上,是最难查的一类 bug。
分位点是**分布的统计量**,只要底层数据没大变就一直有效,而且只有几百个数字。

抽样而不是全量:分位数只需要足够的样本量,5,000 套已经远超所需
(每个分位点上百个样本),而全量要多算 4 倍时间却改变不了小数点后两位。
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.amenities.context import collect_evidence, scores          # noqa: E402
from app.amenities.registry import (                                # noqa: E402
    BY_TYPE_KEYS, all_evidence_keys, evidence_label, used_evidence_keys,
)
from app.core.db import close_pool, get_connection                  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "context_baseline.json"
SAMPLE = 5_000
SEED = 42
N_QUANTILES = 100      # 存 101 个分位点,精度到 1%
MIN_PER_TYPE = 200     # 某个房型的样本少于这个数就不给它单独的分位表

_SQL = """
    SELECT latitude, longitude, suburb, property_type, land_size, building_area,
           distance_cbd, bedrooms
    FROM properties
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
"""


def main() -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_SQL)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    print(f"全库有坐标的房源:{len(rows):,}")

    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(rows), size=min(SAMPLE, len(rows)), replace=False)
    sample = [rows[i] for i in idx]
    print(f"抽样 {len(sample):,} 套,按注册表计算 {len(all_evidence_keys())} 项证据……")

    collected = {key: [] for key in all_evidence_keys()}
    by_type = {}
    score_samples: dict[str, list] = {}
    for n, row in enumerate(sample, 1):
        # 走和线上完全同一条路径(collect_evidence)。基准线和线上用不同算法
        # 算出来的分位数是对不上的,那种 bug 极难发现。
        ev = collect_evidence(row["latitude"], row["longitude"], None, row)
        for key, value in ev.items():
            collected.setdefault(key, []).append(value)
        bucket = by_type.setdefault(str(row["property_type"]), {k: [] for k in BY_TYPE_KEYS})
        for key in BY_TYPE_KEYS:
            if key in ev:
                bucket[key].append(ev[key])
        # 属性分本身的分布。为什么要存这个:属性分是各分项分位数的**加权平均**,
        # 它自己不是分位数 —— 一加权,极端值就被拉回中间,分布挤在中段。
        # 所以「安静 92」到底算多好,光看这个数说不出来。有了这张表,界面才敢写
        # 「全库前 3%」这种话;没有它就只能写「0~100」,而 0~100 等于没说。
        for attr, value in scores(ev, row.get("property_type"), row.get("bedrooms")).items():
            score_samples.setdefault(attr, []).append(value)
        if n % 500 == 0:
            print(f"  {n:,}/{len(sample):,}")

    probs = np.linspace(0, 1, N_QUANTILES + 1)

    def quantiles_of(values):
        return [round(float(v), 2) for v in np.quantile(np.array(values, dtype=float), probs)]

    quantiles, summary = {}, {}
    for key, values in collected.items():
        if not values:
            continue
        arr = np.array(values, dtype=float)
        quantiles[key] = quantiles_of(values)
        summary[key] = {"n": len(arr), "p10": float(np.quantile(arr, 0.10)),
                        "p50": float(np.quantile(arr, 0.50)),
                        "p90": float(np.quantile(arr, 0.90))}

    # 按房型的分位表。样本太少的房型不给单独的表 —— 200 个样本以下算出来的
    # 分位数噪声太大,不如退回全库表(scores() 里已有这个回退)。
    quantiles_by_type = {}
    for ptype, buckets in by_type.items():
        table = {k: quantiles_of(v) for k, v in buckets.items() if len(v) >= MIN_PER_TYPE}
        if table:
            quantiles_by_type[ptype] = table

    # 分数 -> 全库百分位。101 个分位点,和证据表同一个精度。
    score_quantiles = {a: quantiles_of(v) for a, v in score_samples.items() if len(v) >= 500}

    OUT.write_text(json.dumps({
        "built_on": str(date.today()),
        "sample_size": len(sample),
        "seed": SEED,
        "source": "OpenStreetMap contributors (ODbL), via pipeline/fetch_osm.py",
        "quantiles": quantiles,
        "quantiles_by_type": quantiles_by_type,
        "score_quantiles": score_quantiles,
        "summary": summary,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n已写入 {OUT}\n")
    print(f"  {'证据项':<24}{'p10':>10}{'中位数':>10}{'p90':>10}")
    for key, s in summary.items():
        label, unit = evidence_label(key)
        print(f"  {label:<22}{s['p10']:>10.0f}{s['p50']:>10.0f}{s['p90']:>10.0f}  {unit}")

    print("\n  属性分的分布,界面靠它把分数翻译成「全库前百分之几」")
    for attr, qs in sorted(score_quantiles.items()):
        print(f"    {attr:<12}p10 {qs[10]:>5.0f}  中位 {qs[50]:>5.0f}  p90 {qs[90]:>5.0f}  n={len(score_samples[attr]):,}")

    print("\n  按房型单独建表:")
    for ptype, table in sorted(quantiles_by_type.items()):
        for key, qs in table.items():
            print(f"    {ptype:<12}{evidence_label(key)[0]}  中位数 {qs[50]:.0f}")

    # 属性用到的证据都有分位表了吗?缺一项,对应属性就会安静地算不出来。
    missing = used_evidence_keys() - set(quantiles) - set(BY_TYPE_KEYS) - {"bedrooms_many"}
    if missing:
        print(f"\n⚠️ 这些证据被属性用到、却没有分位表:{sorted(missing)}")
        print("   对应的属性会算不出分数(而且不报错)。检查 SOURCES 里的查询。")
    else:
        print("\n  ✓ 所有属性用到的证据都有分位表")
    print("\n  拿到手先看一眼这些数字合不合常理 —— 中位数明显不对就说明数据或算法有问题。")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
