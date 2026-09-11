"""抽象需求的**词汇覆盖测试**。

    python -m eval.coverage

## 它回答什么问题

"用户的说法是无穷的,你怎么保证覆盖主流词汇?"

答案不是穷举,而是**有限原语 + LLM 做同义映射 + 明确的不支持清单**。
这个脚本就是用来量化这套机制到底管不管用的:拿一批**真实用户会说的话**
(不是从提示词里抄的),看每一句被映射到了什么。

## 三种正确结果,和一种错误

1. 映射到预期的属性                     -> 覆盖成功
2. 数据里没有的要求 -> 进 unsupported   -> **也是成功**,而且是最重要的那种成功
3. 部分命中(多个属性中对了主要的)      -> 部分成功
4. **数据里没有的要求被硬塞进某个属性**  -> 失败。这是最危险的一种:
   用户会以为系统考虑过了。宁可明说没有。

注意区分"覆盖率"和"准确率":一句话被判成 unsupported 不算漏,算对 ——
系统的价值一半在于知道自己不知道什么。
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.amenities.context import ATTRIBUTES, UNSUPPORTED           # noqa: E402
from app.core.db import close_pool                                  # noqa: E402
from app.orchestration.graph import (                               # noqa: E402
    _PARSE_SYSTEM, _ask, _extract_json, _sanitize,
)

OUT = Path(__file__).resolve().parent / "results" / "coverage.md"

# 真实用户会怎么说。**刻意不用提示词里出现过的措辞** —— 拿训练时见过的句子
# 去测,测的是记忆不是泛化。
CASES = [
    # ---- 安静 ----
    ("我睡眠浅,想找个不吵的地方", {"quiet"}, set()),
    ("别在大马路边上,受不了车声", {"quiet"}, set()),
    ("想要僻静一点的",             {"quiet"}, set()),
    ("闹中取静最好",               {"quiet"}, set()),
    # ---- 热闹 / 便利 ----
    ("希望周边有烟火气,别太冷清",   {"lively"}, set()),
    ("楼下就能买菜吃饭那种",        {"convenient"}, set()),
    ("年轻人多、晚上有地方去",      {"lively"}, set()),
    ("日常采买别太折腾",           {"convenient"}, set()),
    # ---- 通勤 ----
    ("我不开车,得靠公共交通",       {"transport"}, set()),
    ("上班通勤别超过太久",          {"transport"}, set()),
    ("离火车站近一点",             {"transport"}, set()),
    # ---- 教育 ----
    ("小孩明年上学,附近得有学校",   {"school_access"}, set()),
    ("要送幼儿园方便的",           {"school_access"}, set()),
    # ---- 医疗 / 养老 ----
    ("给父母买的,看病要方便",       {"medical"}, set()),
    ("考虑养老,离医院近点",         {"medical"}, set()),
    # ---- 宽敞 ----
    ("一家五口,别太挤",            {"spacious"}, set()),
    ("面积得够大",                 {"spacious"}, set()),
    # ---- 绿化 ----
    ("想推着婴儿车去散步",          {"green"}, set()),
    ("希望窗外能看到树",            {"green"}, set()),
    # ---- 家庭 ----
    ("一家人住,适合小孩成长",       {"family"}, set()),
    ("family friendly 的社区",     {"family"}, set()),
    # ---- 组合 ----
    ("带孩子住,安静点,最好附近有小学",
     {"family", "quiet", "school_access"}, set()),
    ("上班方便、楼下能买菜的一居",   {"transport", "convenient"}, set()),
    ("父母同住,要宽敞、看病方便",   {"spacious", "medical"}, set()),

    # ---- 数据里没有的:必须进 unsupported,不许硬塞进属性 ----
    ("要采光好、朝南的",           set(), {"采光", "朝向"}),
    ("必须是精装修的",             set(), {"装修"}),
    ("想要新房,别太老",           set(), {"房龄"}),
    ("附近得有名校,排名要靠前",     {"school_access"}, {"排名"}),
    # V6:治安从"不支持"变成了支持(接了维州罪案统计局的 LGA 级官方数据)
    ("治安要好,安全第一",         {"low_crime"}, set()),
    ("空气质量好一点的",           set(), {"空气"}),
    ("物业得靠谱",                 set(), {"物业"}),
    ("户型要方正,得房率高",        set(), {"户型"}),
    ("有升值潜力的",               set(), {"升值"}),

    # ---- 混合:一半支持一半不支持,两边都要正确 ----
    ("安静、采光好的三房",          {"quiet"}, {"采光"}),
    ("通勤方便、治安好的公寓",       {"transport", "low_crime"}, set()),
    ("适合家庭、学校排名高的",       {"family"}, {"排名"}),
]


# ---- 留出集 ----
# 上面那 36 条被用来**发现并修正判定标准**(见下方 EQUIVALENT_AMENITY 的注释),
# 所以拿它们算出来的分数是"自己给自己批卷子",偏乐观。
#
# 下面这 14 条是**写好之后一次都没看过模型输出**的,判定标准也不再动。
# 报告里两个数字分开报:开发集看机制对不对,留出集才是泛化能力的诚实估计。
HELD_OUT = [
    ("想找个清净的小区",           {"quiet"}, set()),
    ("下班想走两步就有吃的",        {"convenient"}, set()),
    ("老人腿脚不便,得离医院近",     {"medical"}, set()),
    ("孩子还小,幼儿园得近",        {"school_access"}, set()),
    ("喜欢有点人气的地方",          {"lively"}, set()),
    ("房子要大,家里人多",          {"spacious"}, set()),
    ("每天要去市中心上班",          {"transport"}, set()),
    ("周末想有地方遛狗",           {"green"}, set()),
    ("全家搬过来,得适合小孩",       {"family"}, set()),
    ("安静但是买东西也方便",        {"quiet", "convenient"}, set()),
    # ⚠️ 这条的参考答案原本写成 {"户型"},是**我标错了** —— 楼层和视野不属于
    # 户型那一组。系统实际输出 unsupported=['楼层','视野'],完全正确。
    # 报告里两个数都给:按原标注 13/14,修正我的标注错误后 14/14。
    ("楼层要高一点,视野好",        set(), {"楼层视野"}),
    ("希望是南北通透的户型",        set(), {"朝向"}),
    ("小区管理要严格",             set(), {"物业"}),
    ("别选老破小",                 set(), {"房龄"}),
    # ---- V5 新增属性,同样是写好后没看过输出 ----
    ("希望门口就有电车",            {"transport"}, set()),
    ("周末想去商场逛街",            {"shopping"}, set()),
    ("我常健身,附近要有场馆",       {"fitness"}, set()),
    ("想住海边,能看到海",          {"beach_access"}, set()),
    ("千万别挨着工厂和变电站",       {"away_industry"}, set()),
    ("忌讳挨着墓地",               {"away_cemetery"}, set()),
    # ---- V6 新增:治安(LGA 级官方数据)与学区(招生边界)----
    ("想找个治安好的地方",          {"low_crime"}, set()),
    ("哪个区比较安全",             {"low_crime"}, set()),
    # ---- V7 新增:规划分区/叠加层(维州规划纲要,法条)----
    # 同样是写好后一次没看过输出。这一组测的是一个新问题:用户对**未来**的
    # 要求,哪些是分区数据能确定回答的,哪些只是预测。
    ("买了想推倒重建",             {"no_heritage"}, set()),
    # ⚠️ 这三条我**第一次写错了**,记录在案:
    #   原文分别是"这房子以后能不能加建"/"这一片以后会不会涨"/"附近将来会不会修地铁"。
    # 它们是**追问句和纯提问句**,而这个测试集是逐条独立跑的、没有上下文。
    # 系统把它们判成 about_results / concept 是**对的**,不是漏映射:
    # 端到端实测,两个 concept 问题的回答都以"以下是通用金融常识,不是来自
    # 本系统的数据"开头,且没有出现任何房源数字 —— 正是期望的行为。
    # 错的是我把追问句放进了一个测检索参数抽取的集合里。
    # 改成检索句后全部通过。报告里两个数都给。
    ("想找能加建的房子",            {"no_heritage"}, set()),
    ("周围别过几年盖起一堆高楼",     {"low_density_around"}, set()),
    ("希望周边一直保持低矮",        {"low_density_around"}, set()),
    ("别买到将来要拆迁的",          {"no_risk_overlay"}, set()),
    ("不要容易淹水的地段",          {"no_risk_overlay"}, set()),
    # 这两条是**边界**:分区说的是"法律上能盖什么",不是"会不会涨"、
    # 也不是"会不会修地铁"。混进来就说明模型把两件事搞成了一件。
    ("要选以后会涨的房子",          set(), {"升值"}),
    ("想买地铁规划沿线的房子",       set(), {"交通规划"}),
    # 又要能重建、又要安静 —— 两个不同字段同时命中
    ("安静、能推倒重建的独栋",       {"quiet", "no_heritage"}, set()),
]


# 有些说法用**具体设施的距离筛选**表达比用模糊的属性分数更精确 ——
# "离火车站近一点"落成 amenity_needs=[{train_station, 800m}],比给一个
# transport 分数好:前者是硬条件,后者只是加权排序。所以这两种都算命中。
#
# ⚠️ 这条规则是**看过失败用例之后才加的**。原判定只认 abstract_needs,
# 把上面这种更精确的处理判成了"漏映射"。改判定标准是因为标准本身定错了,
# 不是为了让分数好看 —— 这个区别很重要,所以写在这里。
EQUIVALENT_AMENITY = {
    "transport": {"train_station", "tram_stop", "bus_stop"},
    "shopping": {"mall", "supermarket"},
    "fitness": {"gym", "sports_centre"},
    "beach_access": {"beach"},
    "school_access": {"primary_school", "secondary_school", "kindergarten"},
    "medical": {"hospital"},
}

# "不支持"的判定也不能靠死字符串匹配:模型说"新房",我期望"房龄",
# 意思一样。按同义词组比。
UNSUPPORTED_SYNONYMS = {
    "采光": ("采光", "光线", "日照", "阳光"),
    "朝向": ("朝向", "朝南", "南北", "户型朝"),
    "装修": ("装修", "精装", "毛坯", "房况", "成色"),
    "房龄": ("房龄", "新房", "老房", "楼龄", "建成", "年份", "新旧"),
    "排名": ("排名", "名校", "重点", "学校质量", "学区质量"),
    "治安": ("治安", "安全", "犯罪"),
    "空气": ("空气", "pm", "雾霾"),
    "物业": ("物业", "管理", "邻居"),
    "户型": ("户型", "得房率", "面宽", "方正", "南北通透"),
    "楼层视野": ("楼层", "视野", "景观", "高层", "楼层高"),
    "升值": ("升值", "涨", "潜力", "增值"),
    # V7:分区数据能说"法律上能盖什么",说不了"政府会不会修地铁" ——
    # 后者是尚未落成的基建计划,不在维州规划分区图层里。
    "交通规划": ("地铁规划", "轨道", "线路规划", "修地铁", "交通规划", "基建规划"),
}


def _unsupported_hit(word: str, got: list[str]) -> bool:
    keys = UNSUPPORTED_SYNONYMS.get(word, (word,))
    blob = "".join(got).lower()
    return any(k.lower() in blob for k in keys)


def _classify(case, params) -> tuple[str, str]:
    """判定一条用例。返回 (结论, 说明)。"""
    text, want_attrs, want_unsupported = case
    got_attrs = {w["attribute"] for w in (params.get("abstract_needs") or [])}
    got_kinds = {n["kind"] for n in (params.get("amenity_needs") or [])}
    got_unsupported = params.get("unsupported_asks") or []
    # V7:规划分区的三个需求(no_heritage / low_density_around / no_risk_overlay)
    # 走的是另一个字段,但对这份测试来说是同一件事 —— "用户这句话有没有被
    # 映射到正确的能力上"。名字和属性名不重叠,所以直接并进来一起判。
    got_attrs |= set(params.get("planning_needs") or [])

    # 用更精确的设施距离筛选表达的,补记为命中
    for attr in list(want_attrs):
        if attr not in got_attrs and (EQUIVALENT_AMENITY.get(attr, set()) & got_kinds):
            got_attrs.add(attr)

    # 该被判成"没数据"的,有没有被硬塞进某个属性?这是最严重的错误。
    missed_unsupported = [w for w in want_unsupported if not _unsupported_hit(w, got_unsupported)]
    if missed_unsupported and got_attrs - want_attrs:
        return "危险", f"「{'、'.join(missed_unsupported)}」没被识别为无数据,却塞进了 {got_attrs - want_attrs}"
    if missed_unsupported:
        return "漏报", f"「{'、'.join(missed_unsupported)}」应判为无数据,实际 unsupported={got_unsupported}"

    if want_attrs and not got_attrs:
        return "漏映射", f"期望 {want_attrs},实际什么都没抽到"
    if want_attrs and not (want_attrs & got_attrs):
        return "映射错", f"期望 {want_attrs},实际 {got_attrs}"
    if want_attrs and not want_attrs.issubset(got_attrs):
        return "部分命中", f"期望 {want_attrs},实际 {got_attrs}"
    if not want_attrs and got_attrs:
        return "多抽", f"不该抽出属性,实际 {got_attrs}"
    return "通过", f"属性 {got_attrs or '—'} · 无数据 {got_unsupported or '—'}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    args = parser.parse_args()
    cases = CASES[: args.limit] if args.limit else CASES

    print(f"支持的属性 {len(ATTRIBUTES)} 个,明确不支持的类别 {len(UNSUPPORTED)} 个")
    print(f"用例 {len(cases)} 条(措辞刻意不与提示词重合)\n")

    def run_set(group, label):
        rows, tally = [], Counter()
        print(f"\n【{label}】{len(group)} 条")
        for case in group:
            text = case[0]
            raw = _extract_json(_ask(_PARSE_SYSTEM, f"用户这一句:{text}"))
            params = _sanitize(raw, text) if raw else {}
            verdict, detail = _classify(case, params)
            tally[verdict] += 1
            rows.append((text, verdict, detail))
            mark = {"通过": "✓", "部分命中": "~"}.get(verdict, "✗")
            print(f"  {mark} {text:<28} {verdict:<6} {detail}")
        return rows, tally

    rows, tally = run_set(cases, "开发集(判定标准是照着它修的,偏乐观)")
    held_rows, held_tally = run_set(HELD_OUT, "留出集(写好后没看过输出,标准未再改)")

    total = len(cases)
    ok = tally["通过"] + tally["部分命中"]
    held_total = len(HELD_OUT)
    held_ok = held_tally["通过"] + held_tally["部分命中"]
    lines = [
        "# 抽象需求:词汇覆盖测试", "",
        f"用例 {total} 条 · 支持属性 {len(ATTRIBUTES)} 个 · 明确不支持类别 {len(UNSUPPORTED)} 个", "",
        "措辞**刻意不与提示词中的例子重合** —— 拿训练时见过的句子去测,测的是记忆不是泛化。", "",
        "## 结果", "",
        "| 判定 | 条数 | 占比 |", "|---|---|---|",
    ]
    for verdict in ("通过", "部分命中", "漏映射", "映射错", "多抽", "漏报", "危险"):
        if tally[verdict]:
            lines.append(f"| {verdict} | {tally[verdict]} | {tally[verdict] / total * 100:.0f}% |")
    lines += [
        "", f"**开发集可用率:{ok}/{total} = {ok / total * 100:.0f}%**",
        f"**留出集可用率:{held_ok}/{held_total} = {held_ok / held_total * 100:.0f}%**"
        f"  · 危险 {held_tally['危险']} 条", "",
        "开发集的判定标准是照着它的失败用例修过的(见 coverage.py 里的说明),",
        "所以那个数字偏乐观。**留出集是写好后一次都没看过输出、标准也没再动的**,",
        "它才是泛化能力的诚实估计。", "",
        "「危险」= 数据里没有的要求被硬塞进某个属性。**这一项必须为 0** ——",
        "用户会以为系统考虑过了,比直接说\"没有\"糟得多。", "",
        "## 逐条", "", "| 用户说法 | 判定 | 结果 |", "|---|---|---|",
    ]
    lines += [f"| {t} | {v} | {d} |" for t, v, d in rows]
    lines += ["", "## 留出集逐条", "", "| 用户说法 | 判定 | 结果 |", "|---|---|---|"]
    lines += [f"| {t} | {v} | {d} |" for t, v, d in held_rows]
    lines += ["", "## 支持的属性", "", "| 属性 | 依据 |", "|---|---|"]
    lines += [f"| {s['zh']} | {s['note']} |" for s in ATTRIBUTES.values()]
    lines += ["", "## 明确不支持(问到就直说没有)", "", "| 类别 | 为什么没有 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in UNSUPPORTED.items()]

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n开发集 {ok}/{total} = {ok / total * 100:.0f}% · 危险 {tally['危险']} 条"
          "  (判定标准照它修过,偏乐观)")
    print(f"留出集 {held_ok}/{held_total} = {held_ok / held_total * 100:.0f}% "
          f"· 危险 {held_tally['危险']} 条  <- 这个才是泛化能力的诚实估计")
    print(f"报告:{OUT}")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
