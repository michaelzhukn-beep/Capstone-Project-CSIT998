"""幻觉率评估:三组对照。提案承诺的交付物。

    python -m eval.run_eval              # 跑全部三组
    python -m eval.run_eval --arms A C   # 只跑其中几组
    python -m eval.run_eval --report     # 不重跑,只用已有结果重新出报告

三组对照:
  A 纯 LLM        —— 什么数据都不给,直接让它推荐房源
  B LLM + 原始数据 —— 给它真实检索结果,**让它自己算指标**
  C 本系统        —— 确定性计算 + LLM 只负责解释

**为什么必须有 B 组。** 只跟 A 组比说明不了什么:一个没有数据的模型当然会编,
那是稻草人。真正要证明的是后半句主张 ——「即使给了真数据,让 LLM 自己算指标
依然不可靠,所以公式必须由代码算」。这一条只有 B 组能回答。

**为什么评判不用 LLM 当裁判。** 用模型验模型,结论没有说服力,而且这个项目
通篇在讲"数字要可追溯",评估环节自己却拿模型的判断当结论,自相矛盾。
这里的分工是:
  - LLM 只做**抽取**:把自由文本里的数值声明变成结构化记录(纯解析,不判对错)
  - **核对全部由代码对着数据库做**:这套房存在吗?价格对得上吗?回报率算对了吗?
抽取器本身也要验 —— 见 --check-extractor。
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.amenities import nearby                                    # noqa: E402
from app.core.db import close_pool, get_connection                  # noqa: E402
from app.orchestration.graph import GRAPH, _ask, new_session        # noqa: E402
from app.search.search import search_properties                     # noqa: E402
from eval.questions import CATEGORIES, QUESTIONS                    # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results"
RAW_PATH = OUT_DIR / "answers.json"
REPORT_PATH = OUT_DIR / "report.md"

# ---------------------------------------------------------------- 三组的回答生成

_ARM_A_SYSTEM = """你是墨尔本房产投资助手。根据用户的问题推荐 3~5 套具体房源。

每套请给出:所在区、门牌地址、售价、卧室数、卫生间数、年租金、毛租金回报率。
最后简短说明推荐理由。用中文回答。"""

_ARM_B_SYSTEM = """你是墨尔本房产投资助手。下面会给你从数据库检索到的**真实房源记录**。

请从中挑 3~5 套推荐给用户,每套给出:所在区、门牌地址、售价、卧室数、卫生间数、
年租金,以及**你计算的毛租金回报率**(毛租金回报率 = 年租金 ÷ 售价)。
最后简短说明推荐理由。用中文回答。

只能使用给定记录里的房源,不要添加记录之外的房源。"""


def answer_arm_a(question: str) -> str:
    """A 组:纯 LLM,不给任何数据。"""
    return _ask(_ARM_A_SYSTEM, question, temperature=0.3)


def answer_arm_b(question: str) -> str:
    """B 组:先检索,把原始记录塞进提示词,让 LLM 自己算指标。

    检索用的是和 C 组同一个 search_properties(),所以两组看到的房源池一样 ——
    差别只在"指标由谁算"。这是这组对照的全部意义,不能让检索质量掺进来。
    """
    rows = search_properties(semantic_query=question, limit=10)
    if not rows:
        rows_text = "(数据库没有检索到任何房源)"
    else:
        keep = ("suburb", "address", "property_type", "price", "bedrooms",
                "bathrooms", "car_spaces", "distance_cbd", "annual_rent")
        rows_text = json.dumps([{k: r.get(k) for k in keep} for r in rows],
                               ensure_ascii=False, indent=2)
    return _ask(_ARM_B_SYSTEM, f"用户的问题:{question}\n\n检索到的真实房源记录:\n{rows_text}",
                temperature=0.3)


def answer_arm_c(question: str) -> str:
    """C 组:本系统。每道题开一个新会话,免得上一题的状态影响下一题。"""
    import uuid
    result = GRAPH.invoke({"user_query": question}, config=new_session(uuid.uuid4().hex))
    metrics = result.get("metrics") or []
    if not metrics:
        return result.get("answer", "")
    # 把结构化结果和自然语言说明拼在一起 —— 这就是用户实际看到的东西,
    # 评估的对象必须是用户看到的东西,不能只评那段说明。
    lines = []
    for i, m in enumerate(metrics, 1):
        line = (f"{i}. {m.get('suburb')} {m.get('address')} · "
                f"售价 ${m.get('price'):,} · {m.get('bedrooms')}房{m.get('bathrooms')}卫")
        if m.get("annual_rent") is not None:
            line += f" · 年租金 ${m['annual_rent']:,}"
        if m.get("gross_yield") is not None:
            line += f" · 毛租金回报率 {m['gross_yield'] * 100:.2f}%"
        for kind, hit in (m.get("amenities") or {}).items():
            line += f" · 最近{nearby.KIND_ZH.get(kind, kind)} {hit['distance_m']}米"
        if m.get("near_place"):
            line += f" · 距{m['near_place']['name']} {m['near_place']['distance_m']}米"
        lines.append(line)
    return "\n".join(lines) + "\n\n" + (result.get("answer") or "")


ARMS = {
    "A": ("纯 LLM(无数据)", answer_arm_a),
    "B": ("LLM + 原始数据(自己算指标)", answer_arm_b),
    "C": ("本系统(代码算数)", answer_arm_c),
}

# ---------------------------------------------------------------- 抽取(LLM 只做解析)

_EXTRACT_SYSTEM = """你是一个信息抽取器。从下面这段房产推荐文本里,把提到的**每一套房**
抽成结构化记录。

只输出一个 JSON 对象,不要 markdown 代码块,不要解释。格式:

{
  "properties": [
    {"suburb": "Richmond", "address": "39 York St", "price": 1000000,
     "bedrooms": 3, "bathrooms": 1, "annual_rent": 39000, "gross_yield": 0.039,
     "distances": [{"what": "火车站", "meters": 400}]}
  ],
  "refused": false,
  "refusal_reason": null
}

规则:
- 文本里**没有提到**的字段填 null,不要猜、不要算。
- price / annual_rent 是澳元整数。"24 万"->240000,"$1,182,000"->1182000。
- gross_yield 是**小数**:文本里写"8.0%"就填 0.08,写"3.29%"就填 0.0329。
- address 只填门牌+街道(如 "39 York St"),不要带区名和邮编;没写就 null。
- distances 收集所有"距离某某多少米/公里"的说法,公里换算成米。
- 如果文本表示**没有找到符合条件的房源**(或明确说数据库里没有这类数据),
  refused 填 true,refusal_reason 填一句话概括原因,properties 填 []。
- 如果文本只是解释概念、没有推荐具体房源,properties 填 []、refused 填 false。

你的任务只是**照抄**,不要判断对错,不要补全缺失的数字。"""


def extract_claims(text: str) -> dict:
    if not text or not text.strip():
        return {"properties": [], "refused": False, "refusal_reason": None}
    raw = _ask(_EXTRACT_SYSTEM, text, temperature=0.0)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return {"properties": [], "refused": False, "refusal_reason": None,
                "_extract_failed": True}
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return {"properties": [], "refused": False, "refusal_reason": None,
                "_extract_failed": True}
    parsed.setdefault("properties", [])
    parsed.setdefault("refused", False)
    return parsed


# ---------------------------------------------------------------- 核对(全部由代码做)

_NORM = re.compile(r"[^a-z0-9]+")


def _norm_addr(text) -> str:
    return _NORM.sub("", str(text).lower()) if text else ""


_property_index: dict | None = None


def _load_index() -> dict:
    """把全库读进内存,按"区+地址"和"区+价格"两种方式建索引。

    核对必须是**确定性**的:同一段文本核对多少次,结果都要一样。
    所以这里不做模糊匹配,只做规范化后的精确匹配。
    """
    global _property_index
    if _property_index is not None:
        return _property_index
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, suburb, address, price, bedrooms, bathrooms, annual_rent "
                    "FROM properties")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    by_addr, by_suburb_price, suburbs = {}, defaultdict(list), set()
    addr_only = defaultdict(list)
    for row in rows:
        suburbs.add(row["suburb"].lower())
        if row["address"]:
            by_addr[(row["suburb"].lower(), _norm_addr(row["address"]))] = row
            addr_only[_norm_addr(row["address"])].append(row)
        by_suburb_price[(row["suburb"].lower(), row["price"])].append(row)
    _property_index = {"by_addr": by_addr, "by_suburb_price": by_suburb_price,
                       # 门牌地址全库唯一的占 98.4%,所以"只凭地址"匹配是安全的。
                       # 必须支持这条路径:模型常用表格列房源、只写地址不重复区名,
                       # 要求"区+地址"同时对上会把真实房源误判成编造 —— 那是**核对器
                       # 的假阴性**,不是被测系统的幻觉。评估工具的缺陷算到被测对象
                       # 头上,比不做评估更糟。
                       "addr_only": {a: rs[0] for a, rs in addr_only.items() if len(rs) == 1},
                       "suburbs": suburbs, "rows": rows}
    return _property_index


def verify_property(claim: dict) -> dict:
    """核对一条房源声明。返回每一项的判定,全部由代码对着数据库做。"""
    index = _load_index()
    suburb = (claim.get("suburb") or "").strip().lower()
    addr = _norm_addr(claim.get("address"))
    price = claim.get("price")

    result = {"claim": claim, "suburb_exists": suburb in index["suburbs"] if suburb else None,
              "matched_by": None, "exists": False, "suburb_ok": None,
              "price_ok": None, "rent_ok": None, "yield_ok": None, "yield_error_pp": None}

    row = None
    if suburb and addr:
        row = index["by_addr"].get((suburb, addr))
        if row:
            result["matched_by"] = "地址"
    if row is None and addr:
        # 只报了地址没报区(表格式输出很常见)。地址全库唯一才认。
        row = index["addr_only"].get(addr)
        if row:
            result["matched_by"] = "地址"
            if suburb:
                result["suburb_ok"] = suburb == row["suburb"].lower()
    if row is None and suburb and isinstance(price, (int, float)):
        candidates = index["by_suburb_price"].get((suburb, int(price)))
        if candidates:
            row = candidates[0]
            result["matched_by"] = "区+价格"
    if row is None:
        return result

    result["exists"] = True
    result["db"] = {k: row[k] for k in ("id", "suburb", "address", "price",
                                        "bedrooms", "bathrooms", "annual_rent")}
    if isinstance(price, (int, float)):
        result["price_ok"] = int(price) == row["price"]
    if isinstance(claim.get("annual_rent"), (int, float)):
        # 允许 1% 的四舍五入误差(LLM 常把 19,240 写成"约 1.92 万")
        result["rent_ok"] = abs(claim["annual_rent"] - row["annual_rent"]) <= row["annual_rent"] * 0.01
    claimed_yield = claim.get("gross_yield")
    if isinstance(claimed_yield, (int, float)) and row["price"]:
        truth = row["annual_rent"] / row["price"]
        result["yield_error_pp"] = round((claimed_yield - truth) * 100, 3)
        # 容差 0.1 个百分点 —— 比"保留一位小数"再松一点,不跟四舍五入较劲
        result["yield_ok"] = abs(claimed_yield - truth) <= 0.001
    return result


def verify_distances(claim: dict, verified: dict) -> list[dict]:
    """核对"距某某多少米"。只在房源能对上号时才核 —— 房子都是编的,距离无从谈起。"""
    out = []
    if not verified.get("exists"):
        return out
    row_id = verified["db"]["id"]
    index = _load_index()
    row = next((r for r in index["rows"] if r["id"] == row_id), None)
    if row is None:
        return out
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT latitude, longitude FROM properties WHERE id = %s", (row_id,))
        pos = cur.fetchone()
    if not pos or pos[0] is None:
        return out

    zh_to_kind = {v: k for k, v in nearby.KIND_ZH.items()}
    near = nearby.nearest_by_kind(pos[0], pos[1])
    for item in claim.get("distances") or []:
        what, meters = item.get("what"), item.get("meters")
        if not isinstance(meters, (int, float)):
            continue
        kind = zh_to_kind.get(what)
        if kind is None:
            kind = next((k for k, zh in nearby.KIND_ZH.items()
                         if what and (what in zh or zh[:2] in str(what))), None)
        if kind is None or kind not in near:
            out.append({"what": what, "claimed_m": meters, "checkable": False})
            continue
        truth = near[kind]["distance_m"]
        out.append({"what": what, "claimed_m": meters, "truth_m": truth,
                    "checkable": True,
                    # 容差 50 米或 10% —— 直线距离取整会有出入,但不该差出量级
                    "ok": abs(meters - truth) <= max(50, truth * 0.10)})
    return out


# ---------------------------------------------------------------- 跑与汇总

def run(arms: list[str]) -> dict:
    OUT_DIR.mkdir(exist_ok=True)
    data = json.loads(RAW_PATH.read_text(encoding="utf-8")) if RAW_PATH.exists() else {}
    for question in QUESTIONS:
        bucket = data.setdefault(question["id"], {"question": question})
        for arm in arms:
            label, fn = ARMS[arm]
            print(f"  [{arm}] {question['id']} {question['text'][:26]}…", end="", flush=True)
            started = time.time()
            try:
                text = fn(question["text"])
            except Exception as exc:
                text = f"(生成失败:{type(exc).__name__}: {exc})"
            bucket[arm] = {"label": label, "text": text, "seconds": round(time.time() - started, 1)}
            print(f" {time.time() - started:.0f}s")
            RAW_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def grade(data: dict, arms: list[str]) -> dict:
    """对已有回答做抽取 + 核对。抽取结果会缓存,重复跑不重复花钱。"""
    for question in QUESTIONS:
        bucket = data.get(question["id"])
        if not bucket:
            continue
        for arm in arms:
            entry = bucket.get(arm)
            if not entry or "graded" in entry:
                continue
            print(f"  核对 [{arm}] {question['id']}…", end="", flush=True)
            claims = extract_claims(entry["text"])
            verified = [verify_property(c) for c in claims.get("properties", [])]
            distances = [d for c, v in zip(claims.get("properties", []), verified)
                         for d in verify_distances(c, v)]
            entry["graded"] = {"claims": claims, "verified": verified, "distances": distances}
            print(f" {len(verified)} 套房")
            RAW_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _pct(numerator, denominator) -> str:
    return f"{numerator / denominator * 100:.0f}% ({numerator}/{denominator})" if denominator else "—"


def summarise(data: dict, arms: list[str]) -> str:
    stats = {arm: defaultdict(int) for arm in arms}
    per_category = {arm: defaultdict(lambda: defaultdict(int)) for arm in arms}

    for question in QUESTIONS:
        bucket = data.get(question["id"]) or {}
        category = question["category"]
        for arm in arms:
            entry = bucket.get(arm)
            if not entry or "graded" not in entry:
                continue
            s, c = stats[arm], per_category[arm][category]
            graded = entry["graded"]
            s["questions"] += 1
            c["questions"] += 1

            for v in graded["verified"]:
                s["props"] += 1
                c["props"] += 1
                # **地址对上才算真的存在。** "区+价格"能对上不代表房是真的:
                # 编一个 "Richmond, $800,000",库里 328 套 Richmond 里碰巧有
                # 一套正好这个价,是很可能的事。实测 A 组 39 套"对上"的全部
                # 是这么撞出来的,门牌地址**一套都没对上**。
                # 而且这类匹配下"价格一致"是循环论证 —— 价格相等本来就是
                # 匹配条件本身,不是核对结论。
                if v["matched_by"] == "地址":
                    s["addr_ok"] += 1
                    c["addr_ok"] += 1
                    for key in ("price_ok", "rent_ok", "yield_ok"):
                        if v[key] is True:
                            s[key] += 1
                        elif v[key] is False:
                            s[key + "_bad"] += 1
                    for key in ("price", "rent", "yield"):
                        if v[key + "_ok"] is not None:
                            s[key + "_checked"] += 1
                elif v["matched_by"] == "区+价格":
                    s["coincidence"] += 1
                    # 这类只核对租金和回报率 —— 那两项不是匹配条件,能说明问题
                    for key in ("rent_ok", "yield_ok"):
                        if v[key] is True:
                            s[key + "_coin"] += 1
                        if v[key] is not None:
                            s[key + "_coin_checked"] += 1
                else:
                    s["not_found"] += 1
            for d in graded["distances"]:
                if d.get("checkable"):
                    s["dist_checked"] += 1
                    if d.get("ok"):
                        s["dist_ok"] += 1

            if category == "out_of_scope":
                s["oos_q"] += 1
                # **重新定义过的指标。** 原先用的是"有没有拒答",对 B 组不公平:
                # B 明确说了"检索结果里没有悉尼的房源",然后推荐了墨尔本的作为
                # 替代 —— 那是诚实行为,不该判成幻觉。
                # 真正要测的是:**它有没有声称一套位于库外地区的房源存在。**
                # 这个判定是确定性的:声称的区名在不在全库 338 个区里。
                for v in graded["verified"]:
                    claimed_suburb = (v["claim"].get("suburb") or "").strip().lower()
                    s["oos_props"] += 1
                    if claimed_suburb and v["suburb_exists"] is False:
                        s["oos_fabricated"] += 1

    lines = ["# 幻觉率评估报告", "",
             f"生成时间:{datetime.now():%Y-%m-%d %H:%M}  ·  题目 {len(QUESTIONS)} 道", "",
             "## 设计", "",
             "三组对照,同一批问题:", "",
             "| 组 | 设置 | 想验证什么 |",
             "|---|---|---|",
             "| A | 纯 LLM,不给任何数据 | 它会不会凭空编房源 |",
             "| B | LLM + 真实检索结果,**让它自己算指标** | 给了真数据,它算得对吗 |",
             "| C | 本系统:确定性计算 + LLM 只解释 | 本项目的主张 |", "",
             "**B 组是关键。** 只跟 A 组比说明不了什么 —— 没有数据的模型当然会编,",
             "那是稻草人。要证明的是后半句主张:即使给了真数据,让 LLM 自己算指标",
             "依然不可靠,所以公式必须由代码算。", "",
             "**评判不由 LLM 做。** LLM 只负责把自由文本里的数值声明抽成结构化记录",
             "(纯解析),**所有核对都由代码对着数据库完成**:这套房存在吗?价格对得上吗?",
             "回报率等于 年租金÷售价 吗?距离和实际算出来的一致吗?", "",
             "## 总表", "",
             "| 指标 | " + " | ".join(f"{a}:{ARMS[a][0]}" for a in arms) + " |",
             "|---|" + "---|" * len(arms)]

    def row(name, fn):
        return f"| {name} | " + " | ".join(fn(stats[a]) for a in arms) + " |"

    lines += [
        row("提及房源数", lambda s: str(s["props"])),
        row("**门牌地址真实存在**", lambda s: _pct(s["addr_ok"], s["props"])),
        row("仅「区+价格」偶合", lambda s: _pct(s["coincidence"], s["props"])),
        row("完全对不上", lambda s: _pct(s["not_found"], s["props"])),
        "| | | | |",
        row("价格与库一致 †", lambda s: _pct(s["price_ok"], s["price_checked"])),
        row("年租金与库一致 †", lambda s: _pct(s["rent_ok"], s["rent_checked"])),
        row("**回报率算对率** †", lambda s: _pct(s["yield_ok"], s["yield_checked"])),
        row("年租金一致(偶合那批)", lambda s: _pct(s["rent_ok_coin"], s["rent_ok_coin_checked"])),
        row("距离核对通过率", lambda s: _pct(s["dist_ok"], s["dist_checked"])),
        row("**越界编造房源**(声称的区库里没有)", lambda s: _pct(s["oos_fabricated"], s["oos_props"])),
        "",
        "† 只在**门牌地址对得上**的房源里统计。靠「区+价格」撞上的那批不算,",
        "因为价格相等本来就是匹配条件,拿它当核对结论是循环论证。",
        "",
        "**「门牌地址真实存在」才是有意义的那一行。** 编一个「Richmond,80 万」,",
        "库里 328 套 Richmond 里碰巧有一套正好这个价,是很容易发生的事;",
        "但编一个门牌号还能对上,概率极低。",
    ]

    lines += ["", "## 分类别:门牌地址真实存在率", "",
              "| 类别 | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for key, label in CATEGORIES.items():
        cells = []
        for arm in arms:
            c = per_category[arm][key]
            cells.append(_pct(c["addr_ok"], c["props"]) if c["props"] else "—")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    lines += ["", "## 结论", "", _CONCLUSION]
    return "\n".join(lines) + "\n"


# 结论是人写的,不是脚本算的 —— 数字能自动生成,"这些数字说明了什么"不能。
# 每改一次评估设计或题目,这一段都要重读一遍还成不成立。
_CONCLUSION = """### 1. 纯 LLM 会大规模编造,这一点没有悬念

A 组提到 96 套房,**门牌地址能对上的只有 6 套(6%)**,而这 6 套连价格都对不上
(0/6)—— 说明连这 6 个也是撞上的,不是记住的。被问到悉尼、布里斯班时,
**74% 的房源声称位于库里根本不存在的区**(如 Liverpool、Parramatta),
配着精确到个位的售价和回报率。

### 2. 一个原本的假设被推翻了:LLM 的算术没问题

设计这套评估时,我们预期 B 组会在计算上出错,从而证明"公式必须由代码算"。
**实测不成立:B 组回报率算对率 99%(86/87)**,它甚至会把算式写出来
("20,553 ÷ 430,000 ≈ 4.78%")。给了真数据之后,它引用的房源 100% 真实,
价格、租金也几乎全对。

**这个结果必须如实写进报告。** 如果只报 A 与 C 的对比,会得出一个站不住的
结论 ——「LLM 不可靠所以要用我们的架构」。真实情况是:在"照抄和四则运算"
这件事上,现在的 LLM 已经相当可靠。

### 3. 真正的差别不在算术,在两个地方

**(a) 「最高/最便宜」这类问题,B 系统性答错 —— 而且每一步算术都是对的。**

题目 m1:「80 万以下、租金回报率最高的两房,回报率是多少」

符合条件的房源全库共 **2,815 套**。

| | 给出的最高回报率 | 说明 |
|---|---|---|
| 数据库真值 | **11.24%** | Albion 8/6 Ridley St,$145,000 / 年租金 $16,296 |
| B 组 | 5.87% | Meadow Heights 2/11 Opal Ct,算式写对了,房源也是真的 |
| C 组 | **11.24%** | 同上,且前 3 名与真值逐条一致 |

B 只能看到塞进提示词的那 10 条语义检索结果,它在这 10 条里挑出了最高的一个,
每个数字都算对了,**但答案是错的**。"最高"是需要在**全集**上比较的问题,
不是把数据喂进上下文就能解决的 —— 这是检索与排序的架构问题。

**这一条曾经是 C 自己也没做到的。** 早期版本的 C 只在 120 套语义候选里排序,
答出 8.02%,比 B 的 10 条好得多但仍不是真值。当时实测过一次更严重的例子:
"100 万以下三房独栋"符合条件的有 4,370 套,返回的"最安静 5 套"在全集里
其实排第 85/89/103/113/243 名,与真值**零重合**。

修法是把候选池从 120 放大到 5,000,并把周边设施、环境证据的计算全部改成
批量(BallTree / STRtree),否则放大候选池会让每次查询多花十几秒。
现在 C 在这道题上给出的就是全库真值。

**仍要说清楚的口径:** 5,000 是候选**上限**,不是全库 20,800。当符合硬条件的
房源超过 5,000 套时,排序依然是在子集上做的,系统每次输出都如实标注
(「在语义最相关的 N 套候选里挑」;本题符合条件 2,815 套 < 5,000,所以是全集)。
要在任何规模下都保证是全库最优,得让检索层支持按指标排序 ——
那要改 `search_properties()` 的签名,属于跨线契约,不能单方面动。

**(b) 数据缺失时,B 只有"编"或"不答"两条路,C 有第三条。**

题目 g1:「Richmond 三房的 NOI 和 Cap Rate 分别是多少」。数据集不含运营支出。

- B:「记录中未提供运营费用,无法直接计算 NOI 和 Cap Rate」—— 诚实,
  但用户什么也没拿到。
- C:按**标注为假设**的 28% 运营支出率算出 NOI $28,454、Cap Rate 3.1%,
  并在同一句话里声明「基于假设支出计算,并非实际成交数据」。

第三条路是「明码标价的假设」:数字给了,依据也给了,用户可以自己改
(`:opex 30`)。被禁止的从来不是使用假设,而是把假设当数据端上来。

### 4. 一处 C 组没挡住的漏网(如实记录)

题目 o5:「帮我找 Zhongshan Road 上的房子」。系统返回了 5 套 Notting Hill 的
真实房源,没有指出墨尔本没有这条路。

原因是**街道名不是可筛选的维度**:`search_properties()` 支持按区(suburb)
精确筛选,所以"悉尼""布里斯班"能被数据库当场判死;但它没有 street 参数,
街道名只能落进语义查询,于是退化成了模糊匹配。

这不是编造(5 套房都是真的),但确实答非所问。要修需要在检索层增加街道维度 ——
同样属于跨线契约。已记录在案。

### 5. 这套评估自身的可信度

- **判定不由 LLM 做。** LLM 只负责把自由文本抽成结构化记录,所有核对都是
  代码对着数据库跑的,可重复、可复核。
- **核对器自身的缺陷会被算成被测系统的幻觉,所以要先验核对器。** 第一版核对器
  要求「区名 + 门牌」同时匹配,把 B 组用表格列出、只写门牌不重复区名的 5 套
  真实房源判成了编造。发现后改成「门牌地址全库唯一即可单独匹配」
  (98.4% 的地址满足),B 组的分数从 94% 回到 100%。
- **"区 + 价格"能对上不算数。** 编一个「Richmond,80 万」,库里 328 套 Richmond
  中碰巧有一套正好这个价,是很容易发生的事;而且这类匹配下"价格一致"是循环
  论证。所以主指标只认门牌地址。
- **样本量有限**:20 道题、3 组、258 条房源声明。类别间的差异(尤其 n<20 的
  类别)不宜过度解读。"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", nargs="+", default=["A", "B", "C"], choices=list(ARMS))
    parser.add_argument("--report", action="store_true", help="不重跑,只用已有结果出报告")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    if args.report:
        data = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    else:
        print(f"生成回答({len(QUESTIONS)} 题 × {len(args.arms)} 组)……")
        data = run(args.arms)
    print("抽取 + 核对……")
    data = grade(data, args.arms)
    report = summarise(data, args.arms)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"原始回答:{RAW_PATH}\n报告:{REPORT_PATH}")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
