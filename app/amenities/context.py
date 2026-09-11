"""抽象需求匹配:把"安静""通勤方便""适合家庭"这类说法翻译成可指认的证据。V5。

## 为什么不能靠语义搜索做这件事

实测:全库 20,800 条 description 去重后只有 **371 个不同的词**,而且
quiet / sunny / renovated / spacious / garden / school / station / noise
这些词**一次都没出现过** —— 描述是从结构化字段拼出来的模板。

拿"安静"去做向量检索,是在一个**根本不含这类信息的语料**里找最近邻。
它不会报错,只会返回一批看起来正常、其实和"安静"无关的房子。

## 架构:有限原语 + LLM 做同义映射 + 明确的不支持清单

用户的说法是无穷的,穷举不可能。所以:

1. **底层是一组有限的原语**(registry.ATTRIBUTES),每个都有可指认的证据;
2. **上层由 LLM 把任意说法映射到原语的组合** —— 同义改写正是 LLM 擅长的,
   而且它只能从固定词表里选,**产不出新数字**;
3. **映射不到任何原语的说法,明确回答"本系统没有这项数据"**
   (registry.UNSUPPORTED),绝不悄悄用一个沾边的属性顶上去。

**属性的定义、权重、同义词全在 app/amenities/registry.py 里**,这个文件只负责
按它算分。加一个新属性不需要改这里。

## 分数是相对位置,而且永远和证据一起返回

原始距离直接加权没有意义(600 米算远还是近?)。所以先映射成**全库分位数**:
0.78 表示"比 78% 的房源更安静"。基准由 pipeline/build_context_baseline.py
抽样算出,**只存分位点、不存每套房的距离** —— 存每套房要用 property id 当键,
而 id 在重新灌库时会变,缓存和数据库悄悄对不上是最难查的一类 bug。

数据来源:OpenStreetMap(© OpenStreetMap contributors,ODbL)。
"""

import json
from pathlib import Path

import numpy as np

from app.amenities import nearby, suburb_stats
from app.amenities.registry import (
    ATTRIBUTE_KEYS, ATTRIBUTES, BY_TYPE_KEYS, CONFLICTS, PROPERTY_EVIDENCE,
    SOURCES, SUBURB_EVIDENCE, UNSUPPORTED, evidence_key, evidence_label,
)

_BASELINE_JSON = Path(__file__).resolve().parents[2] / "data" / "context_baseline.json"

_baseline: dict | None = None


def _as_arrays(table: dict) -> dict:
    """把分位表从 JSON 的 Python list 就地转成 ndarray(只在加载时做一次)。

    为什么必须转:`np.searchsorted` 拿到非 ndarray 会走 `_wrapfunc` -> **`_wrapit`
    兜底路径**,每次调用都现场 `asarray` 一个新数组。而 `scores()` 的调用量是
    候选房源数(最多 5000)× 15 个属性 × 若干证据项 —— 一次查询几万次转换,
    还是在 LangGraph 的线程池里并发跑。

    这不只是慢。实测在 Python 3.14 + numpy 2.4.2 上,这条路径会把进程打崩:
    `Windows fatal exception: code 0xc0000374`(STATUS_HEAP_CORRUPTION),
    栈就停在 `_wrapit` -> `searchsorted` -> 本文件的 `_percentile`。
    同一处还表现为测试里莫名其妙的 `TypeError: 'dict' object is not callable`
    —— 堆被写坏之后对象类型指针错乱的典型症状。
    预转成 ndarray 之后 `searchsorted` 走的是原生快路径,压根不进 `_wrapit`。
    """
    return {k: (np.asarray(v, dtype=np.float64) if isinstance(v, list) else v)
            for k, v in (table or {}).items()}


def _load_baseline() -> dict | None:
    """分位数基准。缺了也能跑 —— 只是给不出"比全库 X% 更安静"这种相对说法。"""
    global _baseline
    if _baseline is None and _BASELINE_JSON.exists():
        raw = json.loads(_BASELINE_JSON.read_text(encoding="utf-8"))
        raw["quantiles"] = _as_arrays(raw.get("quantiles"))
        raw["quantiles_by_type"] = {t: _as_arrays(d)
                                    for t, d in (raw.get("quantiles_by_type") or {}).items()}
        # 同样要转成 ndarray。对 Python list 调 np.searchsorted 会走 numpy 的
        # _wrapit 兜底路径,这条路径在线程池里高频调用时把服务打崩过一次。
        raw["score_quantiles"] = _as_arrays(raw.get("score_quantiles"))
        _baseline = raw
    return _baseline


def score_rank(attr: str, score) -> int | None:
    """一个属性分在全库里排第几(0~100,越大越靠前)。算不出来返回 None。

    为什么非有它不可:属性分是各分项分位数的**加权平均**,它自己**不是**分位数。
    一加权,极端值就被拉回中间,而且每个属性被拉回的程度还不一样。实测:
      家庭友好  p10=33  中位=50  p90=67
      安静      p10=28  中位=57  p90=79
    也就是说「家庭友好 67」已经是全库前 10%,而「安静 67」大概只到前 35%。
    两个 67 在界面上长得一模一样,含义差着三倍。光写「0~100」等于没说 ——
    读者没有参照物。有了这张表才能写「全库前 3%」,那句话不用解释就懂。
    """
    baseline = _load_baseline()
    if score is None or not baseline:
        return None
    q = (baseline.get("score_quantiles") or {}).get(attr)
    if q is None or len(q) < 2:
        return None
    idx = float(np.searchsorted(q, float(score), side="left"))
    return int(round(min(max(idx / (len(q) - 1), 0.0), 1.0) * 100))


def warm_up() -> dict:
    info = nearby.warm_up()
    baseline = _load_baseline()
    crime = suburb_stats.warm_up()
    return {"points": info["total"],
            "sources": len(SOURCES),
            "crime_suburbs": crime["suburbs"],
            "crime_year": crime["year"],
            "attributes": len(ATTRIBUTES),
            "unsupported": len(UNSUPPORTED),
            "baseline": bool(baseline),
            # 基准里缺了哪些证据的分位表 —— 缺了对应属性就算不出来
            "missing_quantiles": sorted(
                {k for spec in ATTRIBUTES.values() for k in spec["parts"]}
                - set((baseline or {}).get("quantiles", {}))
                - set(BY_TYPE_KEYS))}


def _size_m2(prop: dict):
    """"宽敞"用哪个面积:有建筑面积优先(那才是住的面积),否则退回地块面积。
    公寓只有 41% 有地块面积,所以这个回退顺序对公寓尤其要紧。"""
    for key in ("building_area", "land_size"):
        value = prop.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def collect_evidence(lat, lon, amenities: dict | None = None, prop: dict | None = None) -> dict:
    """算出一个坐标 + 一套房的全部原始证据。

    **要算哪些,完全由 registry.SOURCES 决定**,这里没有硬编码的清单。
    amenities 是 enrich 节点已经算好的「最近的各类设施」,直接复用不重算 ——
    同一个距离算两遍,除了浪费还可能因为两条代码路径不一致而算出两个不同的数。
    """
    if lat is None or lon is None:
        return {}
    out = {}
    reuse = amenities or {}
    for kind, source in SOURCES.items():
        key = evidence_key(kind)
        if source["measure"] == "count":
            value = nearby.count_within(lat, lon, kind, source["radius_m"])
        elif kind in reuse and reuse[kind].get("distance_m") is not None:
            value = int(reuse[kind]["distance_m"])          # 复用,不重算
        else:
            hit = nearby.nearest(lat, lon, kind)
            value = hit["distance_m"] if hit else None
        if value is not None:
            out[key] = value

    prop = prop or {}
    out.update(_property_evidence(prop))
    return out


def _property_evidence(prop: dict) -> dict:
    """房源自身列 + 按区查表得来的证据。两者都不来自 OSM,所以单独一处。"""
    out = {}
    if isinstance(prop.get("distance_cbd"), (int, float)):
        out["distance_cbd_km"] = round(float(prop["distance_cbd"]), 1)
    size = _size_m2(prop)
    if size is not None:
        out["size_m2"] = int(round(size))
    crime = suburb_stats.crime_for(prop.get("suburb"))
    if crime:
        # 查不到就**不放这个键** —— "这个区没数据"和"这个区是平均水平"是两回事,
        # 拿平均值兜底会让分数看起来比实际可信。
        out["crime_rate_per_100k"] = round(crime["rate_per_100k"], 1)
    return out


def collect_evidence_batch(rows: list[dict]) -> list[dict]:
    """一次算一批房源的全部证据。**全量排序靠的就是它。**

    逐套调 collect_evidence() 会对每套房、每类数据源各做一次树查询;批量版
    对每类数据源只做一次(一次吃进几千个坐标)。实测 4,370 套房从 7 秒降到
    0.7 秒 —— 这 10 倍换来的是"能在全部符合条件的房源里排序",而不是只在
    120 套语义候选里排。那不是性能优化,是正确性:实测原来给出的"最安静的
    5 套",在全量 4,370 套里只排到第 85~243 名。
    """
    if not rows:
        return []
    lats = [r.get("latitude") for r in rows]
    lons = [r.get("longitude") for r in rows]
    usable = [i for i, (a, b) in enumerate(zip(lats, lons)) if a is not None and b is not None]
    out: list[dict] = [{} for _ in rows]
    if not usable:
        return out

    sub_lats = [lats[i] for i in usable]
    sub_lons = [lons[i] for i in usable]
    for kind, source in SOURCES.items():
        key = evidence_key(kind)
        if source["measure"] == "count":
            counts = nearby.count_within_batch(sub_lats, sub_lons, kind, source["radius_m"])
            if counts is None:
                continue
            for n, i in enumerate(usable):
                out[i][key] = int(counts[n])
        else:
            metres, _ = nearby.nearest_batch(sub_lats, sub_lons, kind)
            if metres is None:
                continue
            for n, i in enumerate(usable):
                out[i][key] = int(round(float(metres[n])))

    for i in usable:
        out[i].update(_property_evidence(rows[i]))
    return out


def _percentile(value, quantiles) -> float | None:
    """原始值 -> 它在全库里的分位数(0~1)。

    算不出来返回 None,**不用 0.5 兜底** —— "不知道"和"正好中位数"是两回事,
    混在一起会让分数看起来比实际可信。
    """
    # 不能写 `not quantiles`:分位表现在是 ndarray,对多元素数组求真值会抛
    # "truth value of an array is ambiguous"。长度 < 2 也要挡掉,否则下面除以 0。
    if value is None or quantiles is None or len(quantiles) < 2:
        return None
    n = len(quantiles) - 1
    idx = float(np.searchsorted(quantiles, value, side="left"))
    return min(max(idx / n, 0.0), 1.0)


# 一个属性至少要有这么大比例的权重拿得到证据,才肯给分。
MIN_WEIGHT_COVERAGE = 0.6


def scores(ev: dict, property_type: str | None = None, bedrooms=None) -> dict:
    """算各抽象属性的 0~100 分。证据不足的属性**直接不出现**。

    为什么不用中位数补缺:一套房如果没有面积数据,"宽敞"这一项就是不知道。
    拿 0.5 顶上去会得到 50 分,看起来像"中等宽敞",实际是"我不知道" ——
    这正是本项目一以贯之要避免的事:把"没有"伪装成"中等"。

    方向由注册表里的 near / far / many / few 决定:
      near / few —— 分位数取反(越近、越少,这个属性越强)
      far / many —— 分位数直接用
    """
    baseline = _load_baseline()
    if not ev or not baseline:
        return {}
    q = baseline.get("quantiles", {})
    by_type = (baseline.get("quantiles_by_type") or {}).get(str(property_type), {})

    def part_value(key: str, direction: str) -> float | None:
        if key == "bedrooms_many":
            return (None if not isinstance(bedrooms, (int, float))
                    else min(max((bedrooms - 1) / 4, 0.0), 1.0))
        table = by_type.get(key) if key in BY_TYPE_KEYS else None
        # 同样不能用 `table or ...`:分位表是 ndarray,or 会去求它的真值。
        # 按房型的表优先,没有才退回全库的表。
        pct = _percentile(ev.get(key), q.get(key) if table is None else table)
        if pct is None:
            return None
        return 1 - pct if direction in ("near", "few") else pct

    out = {}
    for name, spec in ATTRIBUTES.items():
        total = available = 0.0
        for key, (direction, weight) in spec["parts"].items():
            value = part_value(key, direction)
            if value is not None:
                total += value * weight
                available += weight
        if available >= MIN_WEIGHT_COVERAGE * sum(w for _, w in spec["parts"].values()):
            out[name] = round(total / available * 100)
    return out


def part_strength(ev: dict, property_type: str | None = None, bedrooms=None) -> dict:
    """每一项证据**各自**有多强(0~100),不是加总后的属性分。

    为什么需要它:总分是加权平均,一个很差的分项会被其他项拉平。
    一套房"安静 65 分"却离次干道只有 43 米 —— 光看总分和一串原始数字,
    读者不知道 43 米算近还是远,也不知道正是它把分数拖下来的。
    有了分项强度,界面就能指出「距最近次干道 43 米」这一项只有 8 分,
    "为什么这个分数"才有得追溯。

    返回 {属性名: {证据键: 0~100}},方向已经归一化过 ——
    数值越大表示这一项对该属性越有利(远离主干道 = 高,离超市近 = 高)。
    """
    baseline = _load_baseline()
    if not ev or not baseline:
        return {}
    q = baseline.get("quantiles", {})
    by_type = (baseline.get("quantiles_by_type") or {}).get(str(property_type), {})

    def one(key: str, direction: str):
        if key == "bedrooms_many":
            if not isinstance(bedrooms, (int, float)):
                return None
            return round(min(max((bedrooms - 1) / 4, 0.0), 1.0) * 100)
        table = by_type.get(key) if key in BY_TYPE_KEYS else None
        pct = _percentile(ev.get(key), q.get(key) if table is None else table)
        if pct is None:
            return None
        return round((1 - pct if direction in ("near", "few") else pct) * 100)

    out = {}
    for name, spec in ATTRIBUTES.items():
        parts = {k: v for k, v in ((key, one(key, d)) for key, (d, _) in spec["parts"].items())
                 if v is not None}
        if parts:
            out[name] = parts
    return out


def describe_evidence(ev: dict, keys=None) -> list[str]:
    """把原始证据写成人话。只陈述测量值,不下判断。

    keys 给定时只描述那几项 —— 27 个源全列出来会淹没重点,
    通常只列用户这次真正问到的那几项。
    """
    out = []
    for key in (keys or ev):
        if key not in ev:
            continue
        label, unit = evidence_label(key)
        out.append(f"{label} {ev[key]} {unit}")
    return out


def evidence_for(attribute: str) -> tuple[str, ...]:
    """某个属性依据哪几项证据。输出分数时用它挑出该列哪几条依据。"""
    spec = ATTRIBUTES.get(attribute)
    return tuple(spec["parts"]) if spec else ()


def explain_attribute(name: str) -> str:
    spec = ATTRIBUTES.get(name)
    return f"「{spec['zh']}」= {spec['note']}" if spec else ""


ATTRIBUTE_ZH = {k: v["zh"] for k, v in ATTRIBUTES.items()}
