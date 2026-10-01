"""排序与筛选审计(TEST_PLAN.md J 节)。直接跑 search → analyze → enrich → rank → present,
**跳过 parse_intent 和 explain,不调 LLM** —— 参数手写,结果对着数据库和规则逐条核。

    python -m eval.audit.pipeline_audit
"""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.db import get_connection            # noqa: E402
from app.orchestration import graph as g          # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
results, samples = [], {}


def record(code, title, status, detail, sample=None):
    results.append({"code": code, "title": title, "status": status, "detail": detail})
    if sample:
        samples[f"{code} {title}"] = sample[:20]
    print(f"[{status:<4}] {code} {title}\n       {detail}")


def run(raw, query="找房"):
    params = g._sanitize(raw, query)
    state = {"user_query": query, "params": params, "lang": "zh", "history": []}
    state.update(g.search(state))
    state.update(g.analyze(state))
    pool = len(state["metrics"])
    state.update(g.enrich(state))
    all_metrics = state["metrics"]
    state.update(g.rank(state))
    state.update(g.present(state))
    return params, state, pool, all_metrics


def sql_count(p):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT count(*) FROM properties
            WHERE (%(max_price)s IS NULL OR price <= %(max_price)s)
              AND (%(min_price)s IS NULL OR price >= %(min_price)s)
              AND (%(bedrooms)s IS NULL OR bedrooms = %(bedrooms)s)
              AND (%(bathrooms)s IS NULL OR bathrooms = %(bathrooms)s)
              AND (%(property_type)s IS NULL OR property_type = %(property_type)s)
              AND (%(suburb)s IS NULL OR lower(suburb) = lower(%(suburb)s))""",
                    {k: p.get(k) for k in ("max_price", "min_price", "bedrooms", "bathrooms", "property_type", "suburb")})
        return cur.fetchone()[0]


def key_of(sort_by):
    if sort_by in g._ABSTRACT_KEYS:
        return lambda m: (m.get("context_scores") or {}).get(sort_by), True
    if sort_by == "price_asc":
        return lambda m: m["price"], False
    if sort_by == "price_desc":
        return lambda m: m["price"], True
    if sort_by == "predicted_gap_neg":
        return lambda m: m["predicted_gap"], False
    if sort_by == "near_place_distance":
        return lambda m: (m.get("near_place") or {}).get("distance_m"), False
    return lambda m: m.get(sort_by), True


def check_sorted(code, label, state, sort_by):
    key, rev = key_of(sort_by)
    seq = [key(m) for m in state["more"]]
    ok = all((a >= b) if rev else (a <= b) for a, b in zip(seq, seq[1:]))
    ids = [m["id"] for m in state["more"]]
    dup = len(ids) != len(set(ids))
    first5 = [m["id"] for m in state["metrics"]] == ids[:5]
    record(code, f"{label}:有序 / 换一批连续不重复", "PASS" if ok and not dup and first5 else "FAIL",
           f"前 20 个键值 {[round(x, 4) if isinstance(x, float) else x for x in seq]};重复 {dup};前 5 与第一批一致 {first5}")


def check_scope(code, label, params, state, pool):
    n = sql_count(params)
    note = state["ranking"]
    m = re.search(r"在符合条件的全部 (\d+) 套里挑|在语义最相关的 (\d+) 套候选里挑", note)
    said = m and int(m.group(1) or m.group(2))
    if "在全库符合条件的房源里挑" in note:
        # 只有检索层真的按这个口径取候选时才许这么说
        said = "全库"
        truthful = g._SQL_ORDER.get(params.get("sort_by")) is not None and state.get("search_order") is not None
    else:
        truthful = (said == n) if (m and m.group(1)) else (m is not None and n >= g.CANDIDATE_LIMIT)
    record(code, f"{label}:口径「全部 N 套」与数据库一致", "PASS" if truthful and pool == min(n, g.CANDIDATE_LIMIT) else "FAIL",
           f"SQL 硬条件命中 {n};候选池 {pool};说明里写 {said}")


def main():
    t0 = time.time()

    # J1/J3 投资指标排序
    for sort_by in ("gross_yield", "cap_rate", "roi", "price_asc", "price_desc"):
        params, st, pool, allm = run({"max_price": 800000, "sort_by": sort_by})
        check_sorted("J1", sort_by, st, sort_by)
        check_scope("J3", sort_by, params, st, pool)
        if sort_by == "gross_yield":
            top = st["metrics"][0]
            record("J1b", "毛回报率第一名是否可信", "FAIL" if top["gross_yield"] > 0.12 else "PASS",
                   f"第一名 #{top['id']} {top['address']} {top['suburb']} 售价 {top['price']:,} 年租 {top['annual_rent']:,} "
                   f"回报 {top['gross_yield']:.1%};估值 {top['predicted_price']:,} 区间 {top['valuation_interval']} "
                   f"position={top['valuation_position']}",
                   [{k: m[k] for k in ("id", "address", "suburb", "property_type", "price", "annual_rent", "gross_yield",
                                       "predicted_price", "valuation_position")} for m in st["metrics"]])
        if sort_by in ("price_asc", "gross_yield"):
            # 真值:数据库里硬条件内的**全部**房源,按同一口径排。回报率还要套上系统的异常价剔除规则
            # (售价比离折估值低出典型误差 3 倍以上的不参与),否则比的不是同一件事。
            from app.analytics.valuation import predict_values
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""SELECT id, suburb, address, property_type, price, bedrooms, bathrooms, car_spaces,
                                      land_size, building_area, distance_cbd, latitude, longitude, annual_rent
                               FROM properties WHERE price <= 800000""")
                cols = [d[0] for d in cur.description]
                every = [dict(zip(cols, r)) for r in cur.fetchall()]
            if sort_by == "price_asc":
                truth_vals = sorted(r["price"] for r in every)[:5]
                got_vals = [m["price"] for m in st["metrics"]]
            else:
                vals = predict_values(every)
                ok_rows = [r for r, v in zip(every, vals)
                           if not ((v["predicted_price"] - r["price"]) / r["price"] > 3 * v["typical_error_pct"])]
                truth_vals = sorted((round(r["annual_rent"] / r["price"], 6) for r in ok_rows), reverse=True)[:5]
                got_vals = [round(m["gross_yield"], 6) for m in st["metrics"]]
            record("J1c", f"{sort_by}:前 5 名的键值 = 全库(硬条件内)真实前 5", "PASS" if got_vals == truth_vals else "FAIL",
                   f"系统 {got_vals};数据库 {truth_vals}(候选池 {pool} / 命中 {sql_count(params)})")

    # J4 估值排序备注
    for sort_by in ("predicted_gap", "predicted_gap_neg"):
        params, st, pool, allm = run({"suburb": "Richmond", "sort_by": sort_by})
        check_sorted("J1", sort_by, st, sort_by)
        side = "below" if sort_by == "predicted_gap" else "above"
        kept = [m for m in allm if m.get("predicted_gap") is not None
                and abs(m["predicted_gap"]) <= 3 * (m.get("valuation_error_pct") or 0.10)]
        outside = sum(1 for m in kept if m["valuation_position"] == side)
        mm = re.search(r"(\d+) 套里,只有 (\d+) 套", st["ranking"])
        dm = re.search(r"已剔除 (\d+) 套", st["ranking"])
        ok = mm and int(mm.group(1)) == len(kept) and int(mm.group(2)) == outside \
            and (int(dm.group(1)) if dm else 0) == pool - len(kept)
        record("J4", f"{sort_by}:备注里的剔除数 / 区间外套数", "PASS" if ok else "FAIL",
               f"独立计:保留 {len(kept)},区间外 {outside},剔除 {pool - len(kept)};备注:{st['ranking']}")
        top = st["metrics"][:5]
        wrong_dir = [m["id"] for m in top if (m["predicted_gap"] <= 0 if side == "below" else m["predicted_gap"] >= 0)]
        record("J4b", f"{sort_by}:前 5 名方向正确", "FAIL" if wrong_dir else "PASS",
               f"gap {[round(m['predicted_gap'], 3) for m in top]};position {[m['valuation_position'] for m in top]}")

    # J1/J2 环境属性排序 + 门槛
    params, st, pool, allm = run({"property_type": "house", "max_price": 1500000, "sort_by": "quiet",
                                  "abstract_needs": [{"attribute": "quiet", "min_score": 80}]})
    check_sorted("J1", "quiet", st, "quiet")
    check_scope("J3", "quiet+house<=1.5M", params, st, pool)
    below = [m["id"] for m in st["more"] if m["context_scores"]["quiet"] < 80]
    record("J2", "安静 ≥80 门槛全部满足", "FAIL" if below else "PASS", f"不满足 {below}")
    # 排位是否全局最高:在全部候选里独立算最大值
    best = max((m.get("context_scores") or {}).get("quiet", -1) for m in allm)
    record("J2b", "安静排序第一名 = 候选全集最高分", "PASS" if st["metrics"][0]["context_scores"]["quiet"] == best else "FAIL",
           f"第一名 {st['metrics'][0]['context_scores']['quiet']},全集最高 {best}")

    # 设施距离门槛
    params, st, pool, allm = run({"max_price": 900000, "amenity_needs": [{"kind": "train_station", "max_distance_m": 600}],
                                  "sort_by": "gross_yield"})
    far = [(m["id"], m["amenities"]["train_station"]["distance_m"]) for m in st["more"]
           if m["amenities"]["train_station"]["distance_m"] > 600]
    record("J2", "火车站 600m 门槛全部满足", "FAIL" if far else "PASS", f"不满足 {far}")
    # present 展示的距离与 enrich 筛选时的一致(E6)
    from app.amenities import nearby
    disp = nearby.nearest_by_kind_batch([m["latitude"] for m in st["metrics"]], [m["longitude"] for m in st["metrics"]],
                                        ("train_station",))
    diff = [(m["id"], m["amenities"]["train_station"]["distance_m"], d["train_station"]["distance_m"])
            for m, d in zip(st["metrics"], disp) if m["amenities"]["train_station"]["distance_m"] != d["train_station"]["distance_m"]]
    record("E6", "展示距离与筛选距离同值", "FAIL" if diff else "PASS", f"不一致 {diff}")

    # 筛空时"最近的也有 X 米"
    params, st, pool, allm = run({"suburb": "Werribee", "amenity_needs": [{"kind": "beach", "max_distance_m": 50}],
                                  "sort_by": "price_asc"})
    closest = min(m["amenities"]["beach"]["distance_m"] for m in allm)
    mm = re.search(r"最近的也有 (\d+) 米", st["ranking"])
    record("J2c", "筛空说明里的最近距离", "PASS" if mm and int(mm.group(1)) == closest else "FAIL",
           f"独立算 {closest};说明:{st['ranking']}")

    # 回报率门槛
    params, st, pool, allm = run({"max_price": 700000, "min_gross_yield": 0.05, "sort_by": "price_desc"})
    low = [m["id"] for m in st["more"] if m["gross_yield"] < 0.05]
    record("J2", "回报率 ≥5% 门槛全部满足", "FAIL" if low else "PASS", f"不满足 {low};{st['ranking']}")

    # 规划
    params, st, pool, allm = run({"suburb": "Kew", "planning_needs": ["no_heritage"], "sort_by": "price_asc"})
    bad = [m["id"] for m in st["more"] if not g.planning.can_redevelop(m.get("planning") or {})]
    record("J2", "无限制改建叠加层(Kew)全部满足", "FAIL" if bad else "PASS",
           f"不满足 {bad};候选 {pool};{st['ranking']}")

    # 具名地点
    params, st, pool, allm = run({"max_price": 900000, "near_place": {"name": "Monash University", "max_distance_m": 3000},
                                  "sort_by": "near_place_distance"})
    check_sorted("J1", "near_place_distance", st, "near_place_distance")
    over = [m["id"] for m in st["more"] if m["near_place"]["distance_m"] > 3000]
    np_ = st["metrics"][0]["near_place"] if st["metrics"] else None
    record("J2", "距 Monash University 3km 门槛", "FAIL" if over else "PASS",
           f"不满足 {over};第一名匹配到 {np_};lookup {st.get('place_lookup')}")

    OUT.mkdir(parents=True, exist_ok=True)
    lines = [f"# 排序与筛选审计\n\n运行于 {time.strftime('%Y-%m-%d %H:%M')},耗时 {time.time() - t0:.0f}s。\n",
             "| 状态 | 编号 | 检查 | 结果 |", "|---|---|---|---|"]
    lines += [f"| {r['status']} | {r['code']} | {r['title']} | {r['detail'].replace('|', '/')} |" for r in results]
    (OUT / "pipeline_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "pipeline_audit_samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
