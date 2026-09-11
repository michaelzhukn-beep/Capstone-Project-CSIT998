"""临时 CLI 入口。V1_TASKS.md 第 7 步,V2 扩展。第三版被 Streamlit 取代。

    python run.py

启动时会预热 embedding 模型和估值模型。预热是关键:嵌入模型 500MB,首次加载
几十秒。不预热的话用户第一个问题会卡住几十秒 —— 演示现场看起来就像崩了。
预热没让系统变快,只是把这段等待从"用户等"挪到"启动等",而启动时没人盯着。
顺带,估值模型文件缺失这类问题也会在启动时暴露,而不是等用户提问时才炸。
"""

import sys

# Windows 控制台默认 GBK,中文和 ⚠️ 会直接抛 UnicodeEncodeError。
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# stdin 也必须重设,而且理由更隐蔽:交互式控制台走的是 Windows 的 UTF-16 API,
# 没问题;但只要输入是**管道**(演示脚本、`echo ... | python run.py`、CI),
# Python 3.14 就按 GBK 解码,UTF-8 的中文字节会被解成含**孤立代理字符**
# (如 '\udcae')的字符串。这种字符串 Python 自己拿得住,但 sentence-transformers
# 底层那个 Rust 分词器一碰就抛
#   TypeError: TextEncodeInput must be Union[TextInputSequence, ...]
# —— 报错点离病根十万八千里,查起来很费劲。errors="replace" 是最后一道保险:
# 万一真喂进来非 UTF-8 的字节,变成 U+FFFD,不会再产生孤立代理字符。
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

import uuid                                          # noqa: E402

from app.amenities import context, nearby, planning, suburb_stats, zones  # noqa: E402
from app.analytics import assumptions                 # noqa: E402
from app.analytics.valuation import warm_up           # noqa: E402
from app.core.db import close_pool                    # noqa: E402
from app.orchestration.graph import GRAPH, new_session  # noqa: E402
from app.search.search import _get_model              # noqa: E402

_PROPERTY_TYPE_ZH = {"house": "独栋", "apartment": "公寓", "townhouse": "联排"}

HELP = """可用命令:
  :new          开一个新会话(清空对话记忆,重新开始)
  :history      看这轮会话说过什么
  :opex 28      把「运营支出占租金的比例」改成 28%(影响 NOI / Cap Rate / ROI)
  :fees 2000    把「印花税之外的购置开销」改成 $2000(影响 ROI)
  :assume       查看当前生效的假设
  :help         这份帮助
  exit          退出

直接输入问题即可。**支持多轮**,可以接着上一句问:
  > 80 万以下回报率最高的两房
  > 再便宜点,而且要离火车站近          <- 在上一轮条件上改
  > 第 2 套为什么估值这么高              <- 追问上一轮结果,不重新检索
  > cap rate 是什么意思                  <- 问概念
也支持周边设施与环境氛围:
  > 有小孩,想找离幼儿园和小学都在 1 公里内的三房
  > 离莫纳什大学近的两房公寓
  > 要在 Balwyn 小学学区内的三房      <- 招生边界内,不是"离得近"
  > 治安好一点的区,三房独栋          <- LGA 级官方罪案率
  > 想买老房子推倒重建,周围别盖高楼    <- 维州规划分区/叠加层(法条)
  > 别买到将来要征收或会淹水的
  > 安静一点的三房,别靠马路
  > 带孩子住,要安静、附近有小学
  > 父母同住,看病方便、房子宽敞
数据里没有的要求(采光/朝向/装修/房龄/学校排名/物业/户型/升值潜力),
系统会明说没有,而不是拿别的凑数。"""


def _money(value) -> str:
    return f"${value:,}" if isinstance(value, int) else "暂无数据"


def _pct(value, digits: int = 1) -> str:
    """比例 -> 百分号。格式化是展示层的活,系统内部一律保持纯小数。"""
    return f"{value * 100:.{digits}f}%" if isinstance(value, float) else "暂无数据"


def _valuation_line(m: dict) -> str:
    """估值一行。第一版这里是固定占位值 + ⚠️;V2 是真模型,改成标注误差区间。"""
    if m.get("valuation_is_stub"):
        return f"   估值 {_money(m.get('predicted_price'))}  ⚠️ 占位值,非真实模型"

    lo, hi = (m.get("valuation_range") or [None, None])
    band = f"({_money(lo)} ~ {_money(hi)})" if isinstance(lo, int) else ""
    line = f"   模型估值 {_money(m.get('predicted_price'))} {band}".rstrip()

    gap = m.get("predicted_gap")
    err = m.get("valuation_error_pct")
    if isinstance(gap, float) and isinstance(err, float):
        # 模型典型误差约 9%,差距没超过它就是噪声,不许说成"低估/高估"。
        if abs(gap) <= err + 0.01:
            line += "  · 与售价基本相符"
        else:
            line += f"  · 比售价{'高' if gap > 0 else '低'} {abs(gap) * 100:.0f}%"
    return line


def _render(result: dict) -> str:
    # 问概念时没有房源可列,直接给回答
    if result.get("intent") == "concept":
        return result.get("answer", "")

    metrics = result.get("metrics") or []
    if not metrics:
        return result.get("answer", "没有找到符合条件的房源。")

    asked = (result.get("params") or {}).get("abstract_needs") or []
    if result.get("intent") == "about_results":
        header = f"(以下仍是上一轮那 {len(metrics)} 套,未重新检索)"
    else:
        header = f"找到 {len(metrics)} 套 · {result.get('ranking', '')}".rstrip(" ·")
    lines: list[str] = [header]
    for i, m in enumerate(metrics, 1):
        ptype = _PROPERTY_TYPE_ZH.get(m.get("property_type"), m.get("property_type") or "")
        head = f"{i}. {m.get('suburb')} · {_money(m.get('price'))} · "
        head += f"{m.get('bedrooms')} 房 {m.get('bathrooms')} 卫"
        if ptype:
            head += f" · {ptype}"
        lines.append(head)

        rent = m.get("annual_rent")
        rent_note = f"(年租金 {_money(rent)})" if isinstance(rent, int) else ""
        lines.append(f"   毛租金回报率 {_pct(m.get('gross_yield'))} {rent_note}".rstrip())

        # 这三个建立在假设上,所以行尾统一挂一个 ~ 号提示,末尾集中说明假设值。
        lines.append(
            f"   NOI {_money(m.get('noi'))}~ · "
            f"Cap Rate {_pct(m.get('cap_rate'))}~ · "
            f"ROI {_pct(m.get('roi'))}~"
        )
        lines.append(_valuation_line(m))

        amenities = m.get("amenities") or {}
        if amenities:
            bits = [f"{nearby.KIND_ZH.get(k, k)} {v['distance_m']}米"
                    for k, v in amenities.items() if v.get("distance_m") is not None]
            if bits:
                lines.append("   周边(直线距离):" + " · ".join(bits))
        place = m.get("near_place")
        if place:
            lines.append(f"   距「{place['name']}」{place['distance_m']} 米")

        # 学区是**事实**不是评分,所以每套都报,像地址一样。
        sz = m.get("school_zones")
        if sz is not None:
            lines.append("   " + zones.describe(sz))
        if "crime" in m:
            lines.append("   " + suburb_stats.describe(m["crime"]))
        # 规划分区也是**事实**(法条),和学区、罪案率一样每套都报。
        if m.get("planning"):
            lines.append("   " + planning.describe(m["planning"]))

        scores = m.get("context_scores") or {}
        if scores:
            # 只显示用户真正问到的属性及其依据。14 个属性 × 29 项证据全列出来
            # 会把重点淹掉 —— 用户问"安静",不需要看到"距最近海滩 5310 米"。
            wanted = [w["attribute"] for w in (asked or [])]
            if result.get("params", {}).get("sort_by") in scores:
                wanted.append(result["params"]["sort_by"])
            shown_keys = [k for k in dict.fromkeys(wanted) if k in scores] or list(scores)[:5]
            shown = " · ".join(f"{context.ATTRIBUTE_ZH[k]} {scores[k]}" for k in shown_keys)
            lines.append(f"   环境评分(0~100,全库相对位置):{shown}")

            ev = m.get("context_evidence") or {}
            keys = [k for attr in shown_keys for k in context.evidence_for(attr)]
            bits = context.describe_evidence(ev, list(dict.fromkeys(keys)))
            if bits:
                lines.append("   ↳ 依据:" + " · ".join(bits))
        lines.append("")

    asks = ((result.get("params") or {}).get("unsupported_asks")) or []
    if asks:
        lines.append("⚠️ 以下要求本系统没有数据,**未纳入筛选**:" + "、".join(asks))
        lines.append("")

    lines.append("~ 基于假设,非实测数据:")
    for line in assumptions.describe():
        lines.append(f"   · {line}")
    errs = {m.get("property_type"): m.get("valuation_error_pct") for m in metrics}
    for ptype, err in sorted(errs.items(), key=lambda kv: str(kv[0])):
        if isinstance(err, float):
            zh = _PROPERTY_TYPE_ZH.get(ptype, ptype)
            lines.append(f"   · {zh}估值典型误差 ±{err * 100:.1f}%,区间内约含一半房源")
    lines.append("")
    lines.append("说明:" + (result.get("answer") or "").strip())
    return "\n".join(lines)


def _handle_command(line: str) -> bool:
    """返回 True 表示这行是命令、已处理完,不要当成提问。"""
    if not line.startswith(":"):
        return False
    parts = line[1:].split()
    cmd = parts[0].lower() if parts else ""

    if cmd == "help":
        print(HELP)
    elif cmd == "assume":
        for item in assumptions.describe():
            print("  ·", item)
    elif cmd in ("opex", "fees"):
        # :opex 收百分数(28 -> 0.28),:fees 收澳元金额(2000 -> 2000)
        key = "opex_rate" if cmd == "opex" else "other_acquisition_costs"
        try:
            raw = float(parts[1])
        except (IndexError, ValueError):
            hint = ":opex 28   (百分数)" if cmd == "opex" else ":fees 2000   (澳元)"
            print(f"  用法:{hint}")
            return True
        try:
            assumptions.set_rate(key, raw / 100 if cmd == "opex" else raw)
        except ValueError as exc:
            print("  ", exc)
            return True
        print(f"  已改:{assumptions.describe()[0 if cmd == 'opex' else 1]}")
    else:
        print(f"  未知命令 :{cmd},输入 :help 看用法")
    return True


def main() -> None:
    print("正在加载 embedding 模型(首次运行需下载约 500MB,请稍候)……")
    _get_model()
    meta = warm_up()
    m = meta["metrics"]
    print(f"估值模型已加载:{meta['algorithm']} · 训练 {meta['rows']:,} 行 · R² {m['r2']:.3f}")
    # 分房型报误差,不报那个被别墅撑起来的整体数字
    by_type = meta.get("error_by_type") or {}
    if by_type:
        parts = [f"{_PROPERTY_TYPE_ZH.get(k, k)} ±{v['mdape'] * 100:.1f}%"
                 for k, v in sorted(by_type.items())]
        print("  典型误差(按房型):" + " · ".join(parts))
    ctx_info = context.warm_up()
    amenity_info = nearby.warm_up()
    # 12 万个规划多边形。放在启动时加载,不放在第一次查询里 —— 否则第一个
    # 问题会莫名其妙多等半秒到十几秒(取决于 WKB 缓存在不在)。
    plan_info = planning.warm_up()
    print(f"地理数据已加载:{ctx_info['points']:,} 个点 · {ctx_info['sources']} 类数据源 · "
          f"{ctx_info['attributes']} 个环境属性 · {ctx_info['unsupported']} 类明确不支持")
    print(f"规划分区已加载:{plan_info.get('zone', 0):,} 个分区面 · "
          f"{plan_info.get('overlay', 0):,} 个叠加层面(Vicmap Planning)")
    print("  可查设施:" + " · ".join(
        f"{zh}{amenity_info['by_kind'].get(k, 0):,}" for k, zh in nearby.KIND_ZH.items()))
    if not ctx_info["baseline"]:
        print("  ⚠️ 缺分位基准,环境评分不可用:python pipeline/build_context_baseline.py")
    if ctx_info["missing_quantiles"]:
        print(f"  ⚠️ 这些证据缺分位表,相关属性算不出分:{ctx_info['missing_quantiles']}")
    print("模型加载完成,可以提问。输入 :help 看命令,exit 退出。\n")

    # 一个 thread_id 就是一段会话。同一个 id 的多次 invoke 会接着上一次的状态跑,
    # 多轮对话就是这么来的。:new 换一个新 id = 清空记忆重新开始。
    session = new_session(uuid.uuid4().hex)
    try:
        while True:
            try:
                question = input("> ").strip()
            except EOFError:
                break
            if not question:
                continue
            if question.lower() in {"exit", "quit", "q", "退出"}:
                break
            if question == ":new":
                session = new_session(uuid.uuid4().hex)
                print("  已开新会话,之前的对话不再影响后续提问。")
                print()
                continue
            if question == ":history":
                state = GRAPH.get_state(session).values
                for turn in state.get("history") or []:
                    print(f"  {turn['role']}: {turn['text']}")
                if not (state.get("history")):
                    print("  (本轮会话还没有内容)")
                print()
                continue
            if _handle_command(question):
                print()
                continue

            try:
                result = GRAPH.invoke({"user_query": question}, config=session)
            except Exception as exc:
                # 一个问题失败不该拖垮整个会话 —— 验收要求"连问 5 个不崩"。
                print(f"\n出错了:{type(exc).__name__}: {exc}\n")
                continue

            print()
            print(_render(result))
            print()
    except KeyboardInterrupt:
        print()
    finally:
        close_pool()
        print("已退出。")


if __name__ == "__main__":
    main()
