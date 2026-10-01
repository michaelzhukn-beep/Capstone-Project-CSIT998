"""全库数据审计:确定性部分(不调 LLM)。对应 TEST_PLAN.md 的 A–I 节。

    python -m eval.audit.data_audit

每项检查输出 PASS / FAIL / INFO 和证据,汇总写到 eval/audit/results/data_audit.md,
失败样本写到 eval/audit/results/data_audit_samples.json。

**独立重算(ORA)的实现刻意不 import 被测函数**:印花税表、haversine、线段距离、
租金匹配都在这里重写一遍。拿被测代码去验被测代码,错了也会一致地错。
"""

import csv
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.db import get_connection  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results"
RNG = np.random.default_rng(7)
R_EARTH = 6_371_000.0
CBD = (-37.8136, 144.9631)                # Melbourne GPO

results: list[dict] = []
samples: dict[str, list] = {}


def record(code, title, status, detail, sample=None):
    results.append({"code": code, "title": title, "status": status, "detail": detail})
    if sample:
        samples[code] = sample[:30]
    print(f"[{status:<4}] {code} {title}\n       {detail}")


def hav(lat1, lon1, lat2, lon2):
    """独立 haversine,标量或 numpy 广播。"""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    dp = p2 - p1
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def load_rows():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT id, suburb, address, property_type, price, bedrooms, bathrooms,
                              car_spaces, land_size, building_area, distance_cbd,
                              latitude, longitude, annual_rent, sale_date, rent_source
                       FROM properties ORDER BY id""")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ------------------------------------------------------------------ A 基础列

def audit_base(rows):
    n = len(rows)
    nulls = {k: sum(1 for r in rows if r[k] is None)
             for k in ("price", "bedrooms", "bathrooms", "latitude", "longitude", "annual_rent",
                       "car_spaces", "land_size", "building_area", "distance_cbd")}
    hard = {k: v for k, v in nulls.items()
            if k in ("price", "bedrooms", "bathrooms", "annual_rent") and v}
    record("A1", "行数与必填列空值", "PASS" if n == 20_800 and not hard else "FAIL",
           f"{n} 行;空值 {nulls}(无坐标的 {nulls['latitude']} 套不参与一切地理计算)")

    bad = [r["id"] for r in rows if r["latitude"] is not None
           and not (-38.6 < r["latitude"] < -37.3 and 144.3 < r["longitude"] < 145.8)]
    record("A2", "经纬度在墨尔本范围", "PASS" if not bad else "FAIL", f"越界 {len(bad)} 套", bad)

    ext = [r for r in rows if r["price"] <= 0 or r["bedrooms"] > 8 or r["bathrooms"] > 6
           or (r["car_spaces"] or 0) > 10 or r["bedrooms"] == 0 or r["bathrooms"] == 0]
    record("A3", "价格/房间数极端值", "INFO" if ext else "PASS",
           f"{len(ext)} 套:卧室 0 = {sum(r['bedrooms'] == 0 for r in rows)},"
           f"浴室 0 = {sum(r['bathrooms'] == 0 for r in rows)},卧室>8 = {sum(r['bedrooms'] > 8 for r in rows)},"
           f"车位>10 = {sum((r['car_spaces'] or 0) > 10 for r in rows)}",
           [{k: r[k] for k in ("id", "address", "suburb", "price", "bedrooms", "bathrooms", "car_spaces")} for r in ext])

    diffs = []
    for r in rows:
        if r["distance_cbd"] is None or r["latitude"] is None:
            continue
        km = float(hav(r["latitude"], r["longitude"], *CBD)) / 1000
        diffs.append((abs(km - r["distance_cbd"]), r, km))
    d = np.array([x[0] for x in diffs])
    worst = sorted(diffs, key=lambda x: -x[0])
    from app.amenities import nearby
    shown = [abs(nearby.distance_to_cbd_km(r["latitude"], r["longitude"], r["distance_cbd"])
                 - float(hav(r["latitude"], r["longitude"], *CBD)) / 1000) for r in rows if r["latitude"] is not None]
    record("A4", "展示与打分用的距 CBD = 坐标直线距离", "PASS" if max(shown) <= 0.06 else "FAIL",
           f"最大偏差 {max(shown):.3f} km")
    record("A4b", "数据集自带 distance_cbd 列与坐标直线距离(仅估值模型仍在用)", "INFO",
           f"|差| 中位 {np.median(d):.2f} km,p95 {np.percentile(d, 95):.2f} km,>3km {int((d > 3).sum())} 套"
           f"(数据集的 Distance 是按邮编/区给的,非逐套)",
           [{"id": r["id"], "address": r["address"], "suburb": r["suburb"],
             "distance_cbd": r["distance_cbd"], "coord_km": round(km, 2)} for _, r, km in worst[:30]])

    zero_land = sum(1 for r in rows if r["land_size"] == 0)
    zero_bld = sum(1 for r in rows if r["building_area"] == 0)
    from app.amenities.context import _size_m2
    tiny = [r for r in rows if r["building_area"] and 0 < r["building_area"] < 20]
    used = [r for r in rows if (v := _size_m2(r)) is not None and v < 20]
    record("A5", "明显录错的建筑面积(<20㎡)不被拿去打分", "FAIL" if used else "PASS",
           f"land_size=0: {zero_land};building_area=0: {zero_bld};0<building_area<20㎡: {len(tiny)},"
           f"打分时仍用到 <20㎡ 面积的 {len(used)}",
           [{k: r[k] for k in ("id", "address", "property_type", "bedrooms", "building_area", "land_size")} for r in used])

    types = Counter(r["property_type"] for r in rows)
    record("A6", "房型取值", "PASS" if set(types) <= {"house", "apartment", "townhouse"} else "FAIL", str(dict(types)))


# ------------------------------------------------------------------ B 租金

def _quarter(d: date) -> str:
    y = d.year
    cands = [(date(y - 1, 12, 31), f"Dec {y - 1}"), (date(y, 3, 31), f"Mar {y}"),
             (date(y, 6, 30), f"Jun {y}"), (date(y, 9, 30), f"Sep {y}"),
             (date(y, 12, 31), f"Dec {y}"), (date(y + 1, 3, 31), f"Mar {y + 1}")]
    return min(cands, key=lambda c: abs((c[0] - d).days))[1]


def audit_rent(rows):
    mapping = {r["property_suburb"]: r for r in csv.DictReader(open(ROOT / "data/suburb_precinct_mapping.csv", encoding="utf-8"))}
    prec, reg = {}, {}
    for b in csv.DictReader(open(ROOT / "data/rent_benchmarks_long.csv", encoding="utf-8")):
        if not b["median_weekly_rent"]:
            continue
        key = (b["dwelling_sheet"], b["precinct"] if b["granularity"] == "precinct" else b["region"], b["quarter"])
        (prec if b["granularity"] == "precinct" else reg)[key] = float(b["median_weekly_rent"])

    code = {"house": "h", "townhouse": "t", "apartment": "u"}
    mism, tiers, better = [], Counter(), []
    for r in rows:
        tiers[r["rent_source"]] += 1
        m = mapping.get(r["suburb"])
        if not m or not r["sale_date"]:
            continue
        q = _quarter(r["sale_date"])
        t = code[r["property_type"]]
        b = r["bedrooms"]
        sheet = (f"{min(max(b, 2), 4)} bedroom house" if t in "ht" else f"{min(max(b, 1), 3)} bedroom flat")
        weekly, src = None, None
        if m["matched_precinct"] and (sheet, m["matched_precinct"], q) in prec:
            weekly, src = prec[(sheet, m["matched_precinct"], q)], "precinct_exact_sheet"
        elif m["matched_precinct"] and ("All properties", m["matched_precinct"], q) in prec:
            weekly, src = prec[("All properties", m["matched_precinct"], q)], "precinct_all_properties"
        elif m["region"] and (sheet, m["region"], q) in reg:
            weekly, src = reg[(sheet, m["region"], q)], "region_exact_sheet"
        elif m["region"] and ("All properties", m["region"], q) in reg:
            weekly, src = reg[("All properties", m["region"], q)], "region_all_properties"
        if weekly is None:
            continue
        exp = round(weekly * 52)
        if exp != r["annual_rent"]:
            item = {"id": r["id"], "address": r["address"], "suburb": r["suburb"], "type": r["property_type"],
                    "bedrooms": r["bedrooms"], "db_rent": r["annual_rent"], "db_source": r["rent_source"],
                    "oracle_rent": exp, "oracle_source": src}
            mism.append(item)
            if r["rent_source"].endswith("all_properties") and src.endswith("exact_sheet"):
                better.append(item)
    record("B1", "年租金独立重配(用数据库里显示的卧室数)", "FAIL" if mism else "PASS",
           f"不一致 {len(mism)} 套,其中 {len(better)} 套是:库里用了「全部房型」中位数,"
           f"但按显示的卧室数本可匹配到同卧室数的租金(join 用的是原始 Bedroom2,空值没用 Rooms 补)",
           mism)
    exact = tiers.get("precinct_exact_sheet", 0)
    record("B2", "租金匹配粒度占比", "INFO",
           f"{dict(tiers)};同区同卧室数只占 {exact / len(rows):.1%}")

    gy = [(r["annual_rent"] / r["price"], r) for r in rows if r["price"]]
    lo = [x for x in gy if x[0] < 0.015]
    hi = [x for x in gy if x[0] > 0.10]
    record("B4", "毛回报率极端值", "INFO",
           f"<1.5%: {len(lo)} 套;>10%: {len(hi)} 套;最高 {max(g for g, _ in gy):.1%}",
           [{"id": r["id"], "address": r["address"], "type": r["property_type"], "price": r["price"],
             "rent": r["annual_rent"], "yield": round(g, 4)} for g, r in sorted(hi, key=lambda x: -x[0])])


# ------------------------------------------------------------------ C 公式

def oracle_duty(p):
    # SRO Victoria,非自住,2008-05-06 ~ 2021-06-30 合同
    if p <= 25_000:
        return p * 0.014
    if p <= 130_000:
        return 350 + (p - 25_000) * 0.024
    if p <= 960_000:
        return 2_870 + (p - 130_000) * 0.06
    return p * 0.055


def audit_formulas(rows):
    from app.analytics import assumptions
    from app.analytics.formulas import investment_metrics, stamp_duty_vic

    rate, fees = assumptions.opex_rate(), assumptions.other_acquisition_costs()
    bad_duty, bad_inv = [], []
    for r in rows:
        p, rent = r["price"], r["annual_rent"]
        inv = investment_metrics(p, rent, rate, fees)
        od = oracle_duty(p)
        if abs(inv["stamp_duty"] - od) > 1:
            bad_duty.append({"id": r["id"], "price": p, "sys": inv["stamp_duty"], "oracle": od})
        opex = rent * rate
        noi = rent - opex
        total = p + od + fees
        exp = {"gross_yield": rent / p, "operating_expenses": opex, "noi": noi,
               "cap_rate": noi / p, "total_cost": total, "roi": noi / total}
        for k, v in exp.items():
            tol = 1.5 if k in ("operating_expenses", "noi", "total_cost") else 1e-5
            if abs(inv[k] - v) > tol:
                bad_inv.append({"id": r["id"], "field": k, "sys": inv[k], "oracle": v})
                break
    record("C1", "印花税独立重算(全库)", "FAIL" if bad_duty else "PASS", f"不一致 {len(bad_duty)} 套", bad_duty)
    record("C2", "收益指标独立重算(全库)", "FAIL" if bad_inv else "PASS",
           f"不一致 {len(bad_inv)} 套(opex {rate:.0%},杂费 {fees:,.0f})", bad_inv)

    jumps = []
    for edge in (25_000, 130_000, 960_000):
        a, b = stamp_duty_vic(edge), stamp_duty_vic(edge + 1)
        jumps.append(f"{edge:,}: {a:,} -> {b:,}")
    mono = all(stamp_duty_vic(p) <= stamp_duty_vic(p + 1000) for p in range(1000, 3_000_000, 1000))
    record("C3", "印花税分档边界与单调性", "PASS" if mono else "FAIL",
           "边界 " + ";".join(jumps) + f";1千~300万按千元步进单调: {mono}(960k 处 +130 元跳变是法定表本身的形态)")

    none_cases = [investment_metrics(None, 30000, rate, fees), investment_metrics(500000, None, rate, fees),
                  investment_metrics(0, 30000, rate, fees)]
    # opex / NOI 不依赖价格,缺价格时照样算得出,这是对的;只查"本该算不出却给了 0"的
    zeros = [c for c in none_cases for k, v in c.items() if v == 0]
    record("C5", "缺输入返回 None 而非 0", "PASS" if not zeros else "FAIL",
           json.dumps(none_cases, ensure_ascii=False))


# ------------------------------------------------------------------ D 估值

def audit_valuation(rows):
    from app.analytics.valuation import predict_values

    feats = [{k: r[k] for k in ("suburb", "address", "property_type", "bedrooms", "bathrooms", "car_spaces",
                                "land_size", "building_area", "distance_cbd", "latitude", "longitude")} for r in rows]
    v1 = predict_values(feats)
    v2 = predict_values(feats)
    record("D3", "同输入两次预测一致", "PASS" if v1 == v2 else "FAIL", f"{sum(a != b for a, b in zip(v1, v2))} 套不一致")

    order_bad, pos = [], Counter()
    for r, v in zip(rows, v1):
        seq = [v["interval_low"], v["range_low"], v["predicted_price"], v["range_high"], v["interval_high"]]
        if None in seq or not all(a < b for a, b in zip(seq, seq[1:])):
            order_bad.append({"id": r["id"], "seq": seq})
        p = r["price"]
        position = "below" if p < v["interval_low"] else "above" if p > v["interval_high"] else "within"
        gap = (v["predicted_price"] - p) / p
        pos[position] += 1
        if (position == "below" and gap <= 0) or (position == "above" and gap >= 0):
            order_bad.append({"id": r["id"], "position": position, "gap": gap})
    record("D1/D2", "区间嵌套顺序、position 与 gap 符号一致(全库)", "FAIL" if order_bad else "PASS",
           f"违反 {len(order_bad)};分布 {dict(pos)}(below 占 {pos['below'] / len(rows):.1%})", order_bad)

    # D6 单调性:加面积 / 加卧室 / 加浴室,估值下降超过 3% 的比例
    idx = RNG.choice(len(rows), 2000, replace=False)
    base = [feats[i] for i in idx]
    out = {}
    for label, mut in (("building_area×1.3", lambda f: {**f, "building_area": f["building_area"] * 1.3} if f["building_area"] else None),
                       ("land_size×1.3", lambda f: {**f, "land_size": f["land_size"] * 1.3} if f["land_size"] else None),
                       ("bedrooms+1", lambda f: {**f, "bedrooms": f["bedrooms"] + 1}),
                       ("bathrooms+1", lambda f: {**f, "bathrooms": f["bathrooms"] + 1})):
        pairs = [(f, m) for f in base if (m := mut(f)) is not None]
        a = predict_values([f for f, _ in pairs])
        b = predict_values([m for _, m in pairs])
        drops = [(x["predicted_price"], y["predicted_price"], f) for x, y, (f, _) in zip(a, b, pairs)
                 if y["predicted_price"] < x["predicted_price"] * 0.97]
        out[label] = f"{len(drops)}/{len(pairs)}"
    record("D6", "单调性:只加面积/房间,估值下降 >3% 的比例", "INFO", str(out))
    return v1


# ------------------------------------------------------------------ E 设施距离

def audit_amenities(rows):
    from app.amenities import nearby
    from app.amenities.registry import SOURCES

    data = nearby._load()
    idx = RNG.choice(len(rows), 500, replace=False)
    lats = [rows[i]["latitude"] for i in idx]
    lons = [rows[i]["longitude"] for i in idx]
    worst, bad = {}, []
    for kind, src in SOURCES.items():
        g = data["by_kind"].get(kind)
        if g is None:
            bad.append({"kind": kind, "error": "osm_points.csv 里没有这一类"})
            continue
        glat, glon = np.degrees(g["lat"]), np.degrees(g["lon"])
        if src["measure"] == "nearest":
            sys_m, _ = nearby.nearest_batch(lats, lons, kind)
            ora = np.array([hav(a, b, glat, glon).min() for a, b in zip(lats, lons)])
            diff = np.abs(sys_m - ora)
        else:
            sys_c = nearby.count_within_batch(lats, lons, kind, src["radius_m"])
            ora = np.array([(hav(a, b, glat, glon) <= src["radius_m"]).sum() for a, b in zip(lats, lons)])
            diff = np.abs(np.asarray(sys_c) - ora)
        worst[kind] = float(diff.max())
        if diff.max() > (1.0 if src["measure"] == "nearest" else 0):
            bad.append({"kind": kind, "max_diff": float(diff.max())})
    record("E1/E2", "BallTree 最近距离/半径计数 vs 暴力 haversine(500 套 × 29 类)",
           "FAIL" if bad else "PASS", f"最大偏差(米或个) {json.dumps({k: round(v, 3) for k, v in worst.items()})}", bad)


_SEG_CACHE: dict[int, tuple] = {}


def _segments(lines):
    """一组折线 -> 全部线段端点的两个 (n,2) 经纬度数组。按 id 缓存,同一组只打包一次。
    逐条折线现建小数组的旧写法在本机(Python 3.14 + numpy 2.4)上触发过 access violation。"""
    key = id(lines)
    if key not in _SEG_CACHE:
        a, b = [], []
        for pts in lines:
            if len(pts) == 1:
                a.append(pts[0]); b.append(pts[0])
            a.extend(pts[:-1]); b.extend(pts[1:])
        _SEG_CACHE[key] = (np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64), lines)
    return _SEG_CACHE[key][:2]


def _seg_dist_m(plat, plon, lines):
    """点到一组折线的最近距离(局部等距投影,Richmond 这种 5km 范围误差 <0.1%)。"""
    if not lines:
        return math.inf
    A, B = _segments(lines)
    kx = 111_320 * math.cos(math.radians(plat))
    ky = 110_574
    ax, ay = (A[:, 1] - plon) * kx, (A[:, 0] - plat) * ky
    bx, by = (B[:, 1] - plon) * kx, (B[:, 0] - plat) * ky
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = np.clip(-(ax * dx + ay * dy) / np.where(L > 0, L, 1.0), 0.0, 1.0)
    px, py = ax + dx * t, ay + dy * t
    return float(np.sqrt(px * px + py * py).min())


def audit_lines_richmond(rows, evidence_by_id, scores_by_id):
    """E3 / F5:用 design/white-city/_osm_raw.json 的原始线段做精确距离。"""
    raw = json.load(open(ROOT / "design/white-city/_osm_raw.json", encoding="utf-8"))
    S, W, N, E = -37.8385, 144.9660, -37.8120, 145.0340
    groups = defaultdict(list)
    parks = []
    for e in raw["elements"]:
        t, geom = e.get("tags", {}), e.get("geometry")
        if not geom:
            continue
        pts = [(g["lat"], g["lon"]) for g in geom]
        hw = t.get("highway")
        if hw in ("motorway", "trunk", "primary"):
            groups["major_road"].append(pts)
        elif hw == "secondary":
            groups["secondary_road"].append(pts)
        elif hw == "tertiary":
            groups["tertiary_road"].append(pts)
        elif t.get("railway") == "rail" and not t.get("service"):
            groups["railway"].append(pts)
        if t.get("leisure") in ("park", "garden") and len(pts) >= 4:
            parks.append(pts)

    inside = [r for r in rows if S < r["latitude"] < N and W < r["longitude"] < E]
    out, samp = {}, []
    for kind in ("major_road", "secondary_road", "tertiary_road", "railway"):
        diffs = []
        for r in inside:
            ev = evidence_by_id.get(r["id"]) or {}
            sys_m = ev.get(kind + "_m")
            if sys_m is None:
                continue
            edge = min(hav(r["latitude"], r["longitude"], S, r["longitude"]), hav(r["latitude"], r["longitude"], N, r["longitude"]),
                       hav(r["latitude"], r["longitude"], r["latitude"], W), hav(r["latitude"], r["longitude"], r["latitude"], E))
            exact = _seg_dist_m(r["latitude"], r["longitude"], groups[kind])
            if exact > edge:          # 最近的线可能在缓存范围外,判不了
                continue
            diffs.append(sys_m - exact)
            if sys_m - exact > 50:
                samp.append({"id": r["id"], "address": r["address"], "suburb": r["suburb"], "kind": kind,
                             "system_m": sys_m, "exact_m": round(exact), "quiet": scores_by_id.get(r["id"], {}).get("quiet")})
        d = np.array(diffs)
        out[kind] = (f"n={len(d)} 系统-精确:中位 {np.median(d):+.0f}m,p90 {np.percentile(d, 90):+.0f}m,"
                     f"最大 {d.max():+.0f}m,>50m 的 {int((d > 50).sum())} 套 ({(d > 50).mean():.0%})") if len(d) else "n=0"
    over = sum(1 for s in samp)
    record("E3", "线状源距离 vs Richmond 原始 OSM 线段精确距离", "FAIL" if over else "PASS",
           ";".join(f"{k}: {v}" for k, v in out.items()),
           sorted(samp, key=lambda x: -(x["system_m"] - x["exact_m"])))

    # F5:紧邻三级路(不计入安静分)的房源,安静分分布
    near_t, far_t = [], []
    for r in inside:
        q = scores_by_id.get(r["id"], {}).get("quiet")
        if q is None:
            continue
        dt = _seg_dist_m(r["latitude"], r["longitude"], groups["tertiary_road"])
        (near_t if dt <= 25 else far_t if dt >= 150 else []).append((q, r, dt))
    hi_near = [x for x in near_t if x[0] >= 70]
    med_near = float(np.median([x[0] for x in near_t])) if near_t else None
    med_far = float(np.median([x[0] for x in far_t])) if far_t else None
    separated = med_near is not None and med_far is not None and med_far - med_near >= 5
    # Richmond 片区整体吵,远离三级路的房子多半贴着主干道/次干道,两组中位数会被其他噪音源拉平,
    # 所以这里只查"紧邻三级路还拿高分"这一种错;"分数分不分得开"交给全库分层的 F5b
    record("F5", "Richmond 片区紧邻三级路(≤25m)却安静分 ≥70", "PASS" if not hi_near else "FAIL",
           f"Richmond 片区:≤25m 的 {len(near_t)} 套安静分中位 {np.median([x[0] for x in near_t]) if near_t else '-'};"
           f"≥150m 的 {len(far_t)} 套中位 {np.median([x[0] for x in far_t]) if far_t else '-'};≤25m 且 ≥70 分 {len(hi_near)} 套",
           [{"id": r["id"], "address": r["address"], "quiet": q, "tertiary_m": round(dt)} for q, r, dt in hi_near])

    # E4:公园按中心点存储
    from shapely.geometry import Point, Polygon
    polys = []
    for pts in parks:
        try:
            pg = Polygon([(p[1], p[0]) for p in pts])
            if pg.is_valid and pg.area > 0:
                polys.append((pg, pts))
        except Exception:     # noqa: BLE001
            pass
    gaps = []
    park_lines = [pts for _, pts in polys]      # 固定一份,供 _segments 按 id 缓存
    for r in inside:
        sys_m = (evidence_by_id.get(r["id"]) or {}).get("park_m")
        if sys_m is None:
            continue
        pt = Point(r["longitude"], r["latitude"])
        if not any(pg.distance(pt) < 0.004 for pg, _ in polys):
            continue
        edge = 0.0 if any(pg.contains(pt) for pg, _ in polys) else _seg_dist_m(r["latitude"], r["longitude"], park_lines)
        if sys_m - edge > 100:
            gaps.append({"id": r["id"], "address": r["address"], "park_m_system": sys_m, "park_edge_m": round(edge)})
    record("E4", "近公园:系统距离比到公园边界(原始 OSM 轮廓)远 >100m", "FAIL" if gaps else "PASS",
           f"Richmond 片区 {len(inside)} 套中 {len(gaps)} 套", sorted(gaps, key=lambda x: x["park_edge_m"] - x["park_m_system"]))


# ------------------------------------------------------------------ F 属性分

def audit_scores(rows):
    from app.amenities import context
    from app.amenities.registry import ATTRIBUTES, BY_TYPE_KEYS

    t0 = time.time()
    evs = context.collect_evidence_batch(rows)
    print(f"       (全库证据 {time.time() - t0:.1f}s)")
    scs = [context.scores(ev, r["property_type"], r["bedrooms"]) for ev, r in zip(evs, rows)]
    ev_by_id = {r["id"]: ev for r, ev in zip(rows, evs)}
    sc_by_id = {r["id"]: s for r, s in zip(rows, scs)}

    out_of = [(r["id"], k, v) for r, s in zip(rows, scs) for k, v in s.items() if not (0 <= v <= 100)]
    missing = {a: sum(1 for s in scs if a not in s) for a in ATTRIBUTES}
    record("F1", "分数范围 0–100 / 缺失属性数", "FAIL" if out_of else "PASS",
           f"越界 {len(out_of)};缺失 {missing}", out_of)

    # F2 分位基准是否过期
    base = context._load_baseline()
    shifts = {}
    for key, q in base["quantiles"].items():
        vals = np.array([ev[key] for ev in evs if key in ev], dtype=float)
        if not len(vals) or key in BY_TYPE_KEYS:
            continue
        # 对每个基准分位点 q_i,全库里 < q_i 的比例和 <= q_i 的比例应把名义分位 i/n 夹在中间。
        # 用区间而不是单点比较,是为了不被大量并列值(计数类证据大半是 0)误判。
        vals.sort()
        worst = 0.0
        for i, qi in enumerate(q):
            p = i / (len(q) - 1)
            lo = np.searchsorted(vals, qi, side="left") / len(vals)
            hi = np.searchsorted(vals, qi, side="right") / len(vals)
            worst = max(worst, lo - p, p - hi)
        shifts[key] = round(float(worst), 3)
    bad = {k: v for k, v in shifts.items() if v > 0.05}
    record("F2", "分位基准 vs 当前全库重算(p10/p50/p90 在基准表里的分位偏移)",
           "FAIL" if bad else "PASS", f"偏移 >0.05 的:{bad or '无'};全部 {shifts}")

    # F3 方向:单个分项往"好"的方向推,分数不应下降
    viol = []
    idx = RNG.choice(len(rows), 1500, replace=False)
    for i in idx:
        ev, r = evs[i], rows[i]
        s0 = scs[i]
        for attr, spec in ATTRIBUTES.items():
            if attr not in s0:
                continue
            for key, (direction, _) in spec["parts"].items():
                if key not in ev:
                    continue
                v = ev[key]
                better = {"far": v * 2 + 100, "near": v * 0.5, "many": v * 2 + 5, "few": max(0, v * 0.5 - 1)}[direction]
                s1 = context.scores({**ev, key: better}, r["property_type"], r["bedrooms"]).get(attr)
                if s1 is not None and s1 < s0[attr]:
                    viol.append({"id": r["id"], "attr": attr, "key": key, "from": v, "to": better, "score": [s0[attr], s1]})
    record("F3", "方向变形测试(1500 套 × 全部分项)", "FAIL" if viol else "PASS", f"违反 {len(viol)}", viol)

    mono_bad = [a for a in ATTRIBUTES
                if any((context.score_rank(a, s) or 0) > (context.score_rank(a, s + 1) or 0) for s in range(0, 100))]
    record("F4", "score_rank 随分数单调", "FAIL" if mono_bad else "PASS", f"不单调的属性 {mono_bad}")

    def corr(a, b):
        pairs = [(s[a], s[b]) for s in scs if a in s and b in s]
        x = np.array(pairs, dtype=float)
        return round(float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]), 2)
    cbd = np.array([[s.get("transport", np.nan), r["distance_cbd"] or np.nan] for s, r in zip(scs, rows)], dtype=float)
    cbd = cbd[~np.isnan(cbd).any(1)]
    c1, c2 = corr("quiet", "lively"), round(float(np.corrcoef(cbd[:, 0], cbd[:, 1])[0, 1]), 2)
    record("F6", "常识相关性", "PASS" if c1 < -0.3 and c2 < -0.3 else "FAIL",
           f"安静 vs 热闹 r={c1};交通分 vs 距 CBD r={c2}")

    # F5b 三级路/电车线确实进了安静分:只看离主干道、次干道、铁路都 >=400 m 的房源(排除其他噪音源的混杂),
    # 紧邻三级路(<=25 m)的安静分应明显低于远离三级路(>=300 m)的
    calm = [(ev, s) for ev, s in zip(evs, scs) if "quiet" in s
            and min(ev.get("major_road_m", 0), ev.get("secondary_road_m", 0), ev.get("railway_m", 0)) >= 400]
    near_q = [s["quiet"] for ev, s in calm if ev.get("tertiary_road_m", 9999) <= 25]
    far_q = [s["quiet"] for ev, s in calm if ev.get("tertiary_road_m", 0) >= 300]
    gap = (float(np.median(far_q)) - float(np.median(near_q))) if near_q and far_q else None
    record("F5b", "控制其他噪音源后,紧邻三级路的安静分明显更低(全库分层)",
           "PASS" if gap is not None and gap >= 5 else "FAIL",
           f"主干道/次干道/铁路都 ≥400m 的房源里:三级路 ≤25m 的 {len(near_q)} 套中位 "
           f"{np.median(near_q) if near_q else '-'},≥300m 的 {len(far_q)} 套中位 {np.median(far_q) if far_q else '-'},差 {gap}")

    # F7 宽敞按房型
    med = {t: np.median([s["spacious"] for s, r in zip(scs, rows) if r["property_type"] == t and "spacious" in s])
           for t in ("house", "apartment", "townhouse")}
    record("F7", "「宽敞」按房型分别排位(各房型中位应接近 50)", "PASS" if all(35 <= v <= 65 for v in med.values()) else "FAIL",
           str({k: float(v) for k, v in med.items()}))
    return ev_by_id, sc_by_id


# ------------------------------------------------------------------ G/H/I 事实层

def audit_zones(rows):
    from shapely.geometry import Point, shape

    from app.amenities import zones
    lats = [r["latitude"] for r in rows]
    lons = [r["longitude"] for r in rows]
    sys_z = zones.zone_for_batch(lats, lons)

    raw = json.loads((ROOT / "data/school_zones.geojson").read_text(encoding="utf-8"))
    feats = [(f["properties"]["level"], f["properties"]["school"], shape(f["geometry"])) for f in raw["features"]]
    multi, bad = Counter(), []
    idx = RNG.choice(len(rows), 400, replace=False)
    for i in idx:
        pt = Point(lons[i], lats[i])
        hits = defaultdict(list)
        for level, name, g in feats:
            if g.contains(pt):
                hits[level].append(name)
        for level in ("primary", "secondary"):
            names = hits.get(level, [])
            got = sys_z[i].get(level)
            if len(names) > 1:
                multi[level] += 1
            if (got is None and names) or (got is not None and got not in names):
                bad.append({"id": rows[i]["id"], "level": level, "system": got, "oracle": names})
    record("G1", "学区归属 vs 原始多边形逐个 contains(400 套)", "FAIL" if bad else "PASS", f"不一致 {len(bad)}", bad)

    # G2 全库重叠
    data = zones._load()
    from shapely import points as shapely_points
    pts = shapely_points(np.array(lons), np.array(lats))
    over = {}
    samp = []
    for level, bucket in data.items():
        pairs = bucket["tree"].query(pts, predicate="within")
        cnt = Counter(int(p) for p in pairs[0])
        m = [p for p, c in cnt.items() if c > 1]
        over[level] = len(m)
        for p in m[:10]:
            samp.append({"id": rows[p]["id"], "address": rows[p]["address"], "level": level,
                         "zones": [bucket["names"][int(z)] for pp, z in zip(*pairs) if int(pp) == p]})
    none_p = sum(1 for z in sys_z if "primary" not in z)
    none_s = sum(1 for z in sys_z if "secondary" not in z)
    record("G2/G3", "同学段命中多个学区 / 无学区", "FAIL" if any(over.values()) else "PASS",
           f"多重命中(系统只报第一个){over};无小学学区 {none_p},无中学学区 {none_s}", samp)


def audit_crime(rows):
    from app.amenities import suburb_stats
    miss = Counter(r["suburb"] for r in rows if suburb_stats.crime_for(r["suburb"]) is None)
    record("H1", "每个 suburb 能查到罪案率", "FAIL" if miss else "PASS",
           f"查不到的 {len(miss)} 个区、{sum(miss.values())} 套:{dict(miss.most_common(15))}")
    d = suburb_stats._load()
    lga = defaultdict(set)
    for s, v in d["by_suburb"].items():
        lga[v["lga"]].add(v["rate_per_100k"])
    incons = {k: sorted(v) for k, v in lga.items() if len(v) > 1}
    record("H2", "同一 LGA 下各区罪案率应相同(数据是 LGA 级)", "FAIL" if incons else "PASS",
           f"不一致的 LGA {len(incons)} 个;数据年份 {d['year']}(成交价 2016–2018)", [incons])


def audit_planning(rows):
    from app.amenities import planning
    lats = [r["latitude"] for r in rows]
    lons = [r["longitude"] for r in rows]
    t0 = time.time()
    info = planning.for_batch(lats, lons)
    print(f"       (全库规划 {time.time() - t0:.1f}s)")
    no_zone = sum(1 for x in info if "zone" not in x)
    unk_zone = Counter(x["zone"] for x in info if x.get("density") == "unknown")
    unk_ov = Counter(o["code"] for x in info for o in x.get("overlays", []) if o["effect"] == "other")
    record("I2", "无分区 / 未分类分区与叠加层代码", "FAIL" if unk_zone or unk_ov else "PASS",
           f"无分区 {no_zone};未分类分区 {dict(unk_zone.most_common(10))};未分类叠加层 {dict(unk_ov.most_common(10))}")

    bad = []
    for r, x in zip(rows, info):
        cr = planning.can_redevelop(x)
        if "zone" not in x and cr is not None:
            bad.append({"id": r["id"], "why": "无分区却给了 can_redevelop"})
        if "zone" in x:
            has_build = any(o["effect"] == "build" for o in x.get("overlays", []))
            if cr == has_build:
                bad.append({"id": r["id"], "why": "can_redevelop 与 build 叠加层矛盾"})
    record("I3", "can_redevelop / risks 与叠加层一致", "FAIL" if bad else "PASS", f"矛盾 {len(bad)}", bad)

    # I1 分区归属:抽样用原始多边形 bounds 过滤 + covers 判定
    data = planning._load()["zone"]
    bounds = np.array([g.bounds for g in data["geoms"]])
    from shapely.geometry import Point
    mism = []
    for i in RNG.choice(len(rows), 300, replace=False):
        x, y = lons[i], lats[i]
        cand = np.where((bounds[:, 0] <= x) & (bounds[:, 2] >= x) & (bounds[:, 1] <= y) & (bounds[:, 3] >= y))[0]
        hits = sorted({data["code"][int(c)] for c in cand if data["geoms"][int(c)].contains(Point(x, y))})
        got = info[i].get("zone")
        if (got is None and hits) or (got is not None and got not in hits) or len(hits) > 1:
            mism.append({"id": rows[i]["id"], "system": got, "oracle": hits})
    record("I1", "分区归属 vs 原始多边形独立判定(300 套)", "FAIL" if mism else "PASS", f"不一致或多重 {len(mism)}", mism)

    box = planning._boxes([-37.82], [145.0], 350)[0]
    minx, miny, maxx, maxy = box.bounds
    w = float(hav(-37.82, minx, -37.82, maxx))
    h = float(hav(miny, 145.0, maxy, 145.0))
    record("I4", "±350m 方框实际尺寸", "PASS" if abs(w - 700) < 5 and abs(h - 700) < 5 else "FAIL", f"东西 {w:.0f}m × 南北 {h:.0f}m")


# ------------------------------------------------------------------

def main():
    t0 = time.time()
    rows = load_rows()
    print(f"载入 {len(rows)} 行\n")
    audit_base(rows)
    audit_rent(rows)
    audit_formulas(rows)
    audit_valuation(rows)
    geo = [r for r in rows if r["latitude"] is not None]
    audit_amenities(geo)
    ev_by_id, sc_by_id = audit_scores(geo)
    audit_lines_richmond(geo, ev_by_id, sc_by_id)
    audit_zones(geo)
    audit_crime(rows)
    audit_planning(geo)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# 数据审计结果\n\n运行于 {time.strftime('%Y-%m-%d %H:%M')},耗时 {time.time() - t0:.0f}s。"
             f"失败样本见 `data_audit_samples.json`。\n",
             "| 状态 | 编号 | 检查 | 结果 |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['status']} | {r['code']} | {r['title']} | {r['detail'].replace('|', '/')} |")
    (OUT_DIR / "data_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_DIR / "data_audit_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n{Counter(r['status'] for r in results)},写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
