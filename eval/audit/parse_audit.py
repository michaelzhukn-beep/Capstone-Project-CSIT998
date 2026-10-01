"""意图解析审计(TEST_PLAN.md K 节)。每句话跑 RUNS 次,核对期望字段 + 多次之间是否一致。

    python -m eval.audit.parse_audit

会调真实 LLM(约 CASES × RUNS 次)。
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.orchestration.graph import parse_intent  # noqa: E402

RUNS = 3
OUT = Path(__file__).resolve().parent / "results"

A2 = {"max_price": 800000, "bedrooms": 2, "property_type": "apartment"}


def has_need(kind, max_m=None):
    def f(p):
        for n in p.get("amenity_needs") or []:
            if n["kind"] == kind and (max_m is None or n["max_distance_m"] == max_m):
                return True
        return False
    f.__name__ = f"amenity {kind}<={max_m}"
    return f


def has_attr(attr):
    def f(p):
        return attr in [n["attribute"] for n in p.get("abstract_needs") or []] or p.get("sort_by") == attr
    f.__name__ = f"attr {attr}"
    return f


def unsupported(p):
    return bool(p.get("unsupported_asks"))


CASES = [
    # K2 数字单位 / 同义改写:四句应解析成同一组参数
    ("K2", "80万以下的两房公寓", A2, []),
    ("K2", "预算 $800k,2 bedroom apartment", A2, []),
    ("K2", "800,000 以内 两卧 公寓", A2, []),
    ("K2", "Budget under 800k, 2-bed unit", A2, []),
    ("K2", "150万到200万之间的四房", {"min_price": 1500000, "max_price": 2000000, "bedrooms": 4}, []),
    ("K2", "1.5m以下的 townhouse", {"max_price": 1500000, "property_type": "townhouse"}, []),
    ("K1", "Richmond 附近安静的独栋", {"suburb": "Richmond", "property_type": "house"}, [has_attr("quiet")]),
    ("K1", "richmod 安静的house", {"suburb": "Richmond", "property_type": "house"}, [has_attr("quiet")]),
    ("K1", "租金回报率最高的房子,100万以内", {"sort_by": "gross_yield", "max_price": 1000000}, []),
    ("K1", "回报率至少5%的房子", {"min_gross_yield": 0.05}, []),
    ("K1", "离火车站 500 米内的三房", {"bedrooms": 3}, [has_need("train_station", 500)]),
    ("K1", "Brunswick 3 bed house under 1.2 million, close to tram",
     {"suburb": "Brunswick", "bedrooms": 3, "property_type": "house", "max_price": 1200000}, [has_need("tram_stop")]),
    ("K1", "最便宜的房子", {"sort_by": "price_asc"}, []),
    ("K1", "离 Monash University 3公里内的房子", {}, [lambda p: (p.get("near_place") or {}).get("max_distance_m") == 3000
                                               and "monash" in (p.get("near_place") or {}).get("name", "").lower()]),
    ("K1", "Balwyn High School 学区内的房子", {}, [lambda p: "balwyn high" in ((p.get("school_zone") or {}).get("school") or "").lower()]),
    ("K1", "没有历史保护限制、可以翻建的房子", {}, [lambda p: "no_heritage" in (p.get("planning_needs") or [])]),
    ("K1", "被低估的两房", {"sort_by": "predicted_gap", "bedrooms": 2}, []),
    ("K1", "估值低于售价的房子", {"sort_by": "predicted_gap_neg"}, []),
    ("K3", "步行 10 分钟能到火车站的房子", {}, [unsupported]),
    ("K3", "学校排名前十的学区房", {}, [unsupported]),
    ("K3", "开车 20 分钟能到 CBD 的房子", {}, [unsupported]),
    ("K3", "朝北、采光好的房子", {}, [unsupported]),
]

COMPARE = ("max_price", "min_price", "bedrooms", "bathrooms", "property_type", "suburb", "sort_by",
           "min_gross_yield", "amenity_needs", "abstract_needs", "school_zone", "near_place", "planning_needs")


def one(q):
    state = {"user_query": q, "history": [], "params": None, "metrics": [], "lang": "zh"}
    out = parse_intent(state)
    return out.get("params") or {}


def main():
    t0 = time.time()
    jobs = [c[1] for c in CASES for _ in range(RUNS)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        got = list(ex.map(one, jobs))

    rows, fails = [], 0
    for i, (code, q, expect, preds) in enumerate(CASES):
        runs = got[i * RUNS:(i + 1) * RUNS]
        errs = []
        for p in runs:
            for k, v in expect.items():
                pv = p.get(k)
                if isinstance(v, str) and isinstance(pv, str):
                    ok = pv.lower() == v.lower()
                elif isinstance(v, float):
                    ok = pv is not None and abs(pv - v) < 1e-9
                else:
                    ok = pv == v
                if not ok:
                    errs.append(f"{k}={pv!r}≠{v!r}")
            for f in preds:
                if not f(p):
                    errs.append(f"未满足 {getattr(f, '__name__', 'predicate')}")
        sig = [json.dumps({k: p.get(k) for k in COMPARE}, ensure_ascii=False, sort_keys=True) for p in runs]
        stable = len(set(sig)) == 1
        status = "PASS" if not errs and stable else "FAIL"
        fails += status == "FAIL"
        rows.append({"code": code, "q": q, "status": status, "stable": stable, "errors": sorted(set(errs)),
                     "params": [json.loads(s) for s in sig] if not stable or errs else json.loads(sig[0]),
                     "unsupported": [p.get("unsupported_asks") for p in runs]})
        print(f"[{status}] {code} «{q}» 稳定={stable} {sorted(set(errs)) or ''}")
        if status == "FAIL":
            print("       " + " | ".join(sig))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "parse_audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# 意图解析审计\n\n{len(CASES)} 句 × {RUNS} 次,{time.strftime('%Y-%m-%d %H:%M')},耗时 {time.time() - t0:.0f}s,"
             f"失败 {fails}。明细见 `parse_audit.json`。\n", "| 状态 | 编号 | 说法 | 稳定 | 问题 |", "|---|---|---|---|---|"]
    lines += [f"| {r['status']} | {r['code']} | {r['q']} | {r['stable']} | {'; '.join(r['errors'])} |" for r in rows]
    (OUT / "parse_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n失败 {fails}/{len(CASES)}")


if __name__ == "__main__":
    main()
