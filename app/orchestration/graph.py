"""LangGraph 编排。V1_TASKS.md 第 6 步。

管道的六段在这里被串成一条线:
    用户的话 -> 结构化参数 -> 数据库检索 -> 确定性计算 -> LLM 解释 -> 输出

六个节点,一处条件路由,带会话记忆:

            ┌─ 新搜索/收窄 → search → analyze → enrich → rank → present ─┐
parse_intent ┤                                                            ├→ explain → END
            └─ 追问上一轮结果 / 问概念 ──────────────────────────────────┘

演进过程本身值得记一笔:
  第一版 4 个节点一条直线 —— 任务书写的是"先直,再弯",先证明管道通。
  V2 加 rank —— 取数、算数、挑选是三件事,分开之后换排序口径不必碰计算逻辑。
  V3 加 enrich(周边设施)和**这处条件路由** —— 追问上一轮结果、问一个名词
     的意思,都不需要碰数据库,硬走一遍检索既慢又会把上一轮结果冲掉。

分工是这个项目的核心主张,一句话:**LLM 只负责理解和解释,数字全部由代码算。**
parse_intent 和 explain 是仅有的两个 LLM 节点,前者把话变成参数、后者把数字
变成句子;中间的 search / analyze / enrich / rank 一个字节都不经过模型。
"""

import json
from copy import deepcopy
import operator
import re
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.amenities import context, nearby, planning, registry, suburb_stats, zones
from app.analytics import assumptions
from app.analytics.formulas import investment_metrics, roi_certified_prefix, roi_unrounded
from app.analytics.valuation import predict_values
from app.core.config import require_llm_config
from app import i18n
from app.search.search import properties_by_ids, search_properties
from app.orchestration import refinement

# ---------------------------------------------------------------- 状态


class State(TypedDict):
    """在节点之间流转的状态字典。每个节点读它的一部分、写它的一部分。"""

    user_query: str            # 用户原话
    intent: str                # 这句话属于哪一类(见 _INTENTS)
    params: dict               # 抽出的结构化参数
    properties: list[dict]     # 检索结果
    metrics: list[dict]        # 每套房的指标(**当前展示**的那几套)
    # 排序后的前 20 套,**包含 metrics 里那几套**,是一个稳定的池子。
    # 排序是在整个候选池上做完的,第 6 名之后本来就已经算好了,过去在 rank 的
    # 最后一行被直接扔掉。留着它,"换一批"就不必再查库、再重算指标。
    # 必须包含前 5 套:否则换过一次批之后 metrics 变了,池子就再也拼不回来了。
    more: list[dict]
    # 当前这批在池子里的起点。用户看到的编号是 batch_offset + i + 1 ——
    # 说明里的「第 N 套」必须用同一个号,否则和卡片、地图对不上。
    batch_offset: int
    ranking: str               # 最终用了什么排序口径(要能对用户交代)
    # 界面语言。只影响**输出**:排序口径那几句、没结果时的说明、以及 explain
    # 让 LLM 用哪种语言写。解析用户输入不看它 —— 用户用哪种语言问都得能听懂。
    lang: str
    # 检索层按哪一列取的候选(price_asc / price_desc / gross_yield),None = 按语义相关度。
    # 决定排序说明里能不能说"全库"。
    search_order: str | None
    # 按 ROI 取候选池被截断时:{"cutoff": 池里最后一套的不取整 ROI, "other_costs": 当时用的杂费};
    # rank 用它证明前几名不会被池外房源超过(formulas.roi_certified_prefix)。没被截断 = None。
    roi_pool: dict | None
    # 本次请求的假设快照 {"opex_rate","other_costs","display"}:search 读一次,预排序、每轮扩容、analyze 的指标与展示的 assumptions
    # 都用这一份;进程级假设在两个节点之间被 /api/assumptions 改掉也不会让它们各算各的。None = 没经过 search(如按编号取详情)。
    assumption_snap: dict | None
    place_lookup: dict | None  # 具名地点解析结果(找到几个 / 没找到)
    zone_lookup: dict | None   # 学区解析结果(找到几个 / 没找到)
    answer: str                # 最终回答
    refinement_base: dict | None  # 本轮修改前的完整结果,无兼容结果时恢复
    turn_notice: str | None       # 澄清/无兼容结果的确定性说明,不让 LLM 编结果
    # 对话历史。用 operator.add 做 reducer,所以每个节点返回的是"要追加的",
    # 不是"完整的新值"。LangGraph 的状态字段默认是覆盖语义,列表要累积必须
    # 显式声明 reducer,否则第二轮会把第一轮冲掉。
    history: Annotated[list, operator.add]


# ---------------------------------------------------------------- 语言


def _en(state) -> bool:
    return (state or {}).get("lang") == "en"


def _t(state, zh: str, en: str) -> str:
    """两种语言写在同一行,改一句话时另一句就在眼皮底下 ——
    分成两张表的话,改了中文忘了改英文不会报错,只会让英文界面停在旧措辞上。"""
    return en if _en(state) else zh


def _kind_label(state, kind: str) -> str:
    return i18n.KINDS_EN.get(kind, kind) if _en(state) else nearby.KIND_ZH.get(kind, kind)


def _attr_label(state, attr: str) -> str:
    return (i18n.ATTRIBUTES_EN.get(attr, attr) if _en(state)
            else context.ATTRIBUTES[attr]["zh"])


def _sort_label(state, key: str) -> str:
    place = ((state or {}).get("params") or {}).get("near_place")
    if key == "near_place_distance" and place:      # 「指定地点」要说出是哪一个
        return _t(state, f"离「{place['name']}」从近到远", f"Distance to {place['name']}, nearest first")
    return (i18n.sort_labels_en(_SORT_LABEL)[key] if _en(state) else _SORT_LABEL[key])


_PROPERTY_PARKING_ASK = "房源车位"
_PROPERTY_PARKING_LABELS = frozenset({"房源车位", "车位", "停车位", "车库", "car space", "car spaces",
                                      "garage", "garages", "property parking", "property car spaces"})
_PUBLIC_PARKING_RE = re.compile(
    r"公共停车(?:场|位)|停车场|(?:靠近|附近|周边|旁边)(?:有|的|公共){0,2}停车位|停车(?:控制|分区|规划|管制)"
    r"|\bpublic\s+parking\b"
    r"|\bparking\s+(?:overlay|precinct|restriction|control|zone|plan)\b"
    r"|\b(?:near|nearby|close\s+to)\s+(?:(?:a|the)\s+)?(?:public\s+)?car\s+parks?\b"
    r"|\b(?:the\s+)?garage\s+(?:cafe|restaurant|bar)\b", re.I)
_PARKING_TERM_RE = re.compile(r"车位|停车位|停车场|车库|\b(?:car\s+spaces?|car\s+parks?|parking|garages?)\b", re.I)
_PROPERTY_PARKING_RE = (
    re.compile(r"(?:房子|房源|公寓|住宅|这套|第[0-9一二三四五六七八九十]+套).{0,12}?"
               r"(?P<owned>(?:要有|要带|自带|带有|配有|需要|不需要|不要|不带|不能有|没有|有|要)"
               r"(?:至少)?(?:[0-9一二三四五六七八九十]+个?)?(?:车位|停车位|车库))"),
    re.compile(r"(?P<owned>(?:要有|要带|自带|带有|配有|需要|不需要|不要|不带|必须有|必须要)"
               r"(?:至少)?(?:[0-9一二三四五六七八九十]+个?)?(?:车位|停车位|车库))"),
    re.compile(r"\b(?P<owned>(?:with|without|has|have|needs?|wants?|requires?|must\s+have)\s+"
               r"(?:(?:a|an)\s+|at\s+least\s+\d+\s+)?"
               r"(?:car\s+spaces?|car\s+parks?|parking(?:\s+spaces?)?|garages?(?!\s+(?:cafe|restaurant|bar))))\b", re.I),
)
_DERIVED_BARE_SPACE_RE = re.compile(r"(?:garages?|car\s+spaces?|车位|停车位|车库)", re.I)
_DERIVED_AFTER_HOME_RE = re.compile(
    r"\b(?:house|home|property|apartment|flat|unit)\b(?:\s+\w+){0,4}?\s+"
    r"(?P<bare>garages?|car\s+spaces?|parking)\b(?=\s*(?:$|[,;]))", re.I)


def _property_parking_spans(text) -> list[tuple[int, int]]:
    """Only explicit property-owned parking clauses; public places are protected."""
    if not isinstance(text, str):
        return []
    public = [match.span() for match in _PUBLIC_PARKING_RE.finditer(text)]
    spans = []
    for pattern in _PROPERTY_PARKING_RE:
        for match in pattern.finditer(text):
            start, end = match.span("owned")
            if any(start < stop and end > begin for begin, stop in public):
                continue
            spans.append((start, end))
    result = []
    for start, end in sorted(set(spans), key=lambda pair: (pair[0], -(pair[1] - pair[0]))):
        if not result or start >= result[-1][1]:
            result.append((start, end))
    return result


def _parking_kind(text) -> str | None:
    """Property, ambiguous, or absent/public; ambiguity never triggers query deletion."""
    if not isinstance(text, str):
        return None
    if _property_parking_spans(text):
        return "property"
    public = [match.span() for match in _PUBLIC_PARKING_RE.finditer(text)]
    for match in _PARKING_TERM_RE.finditer(text):
        start, end = match.span()
        if not any(start < stop and end > begin for begin, stop in public):
            return "ambiguous"
    return None


def _without_property_parking(text: str) -> str:
    """Remove only recognised owned-parking clauses; leave all other text intact."""
    spans = _property_parking_spans(text)
    if not spans:
        return text
    parts, cursor = [], 0
    for start, end in spans:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return re.sub(r"\s+", " ", "".join(parts)).strip(" ,;，；、")


def _without_derived_property_parking(text: str, original_query: str) -> str:
    """Within an explicit owned-space request, remove narrowly derived labels.

    A bare parser label or a trailing home + label is safe to drop. Public
    parking phrases and named places elsewhere in the text stay unchanged.
    """
    cleaned = _without_property_parking(text)
    bare = cleaned.strip()
    if _DERIVED_BARE_SPACE_RE.fullmatch(bare):
        if bare.casefold().startswith("garage") and re.search(r"\bgarage\s+(?:cafe|restaurant|bar)\b", original_query, re.I):
            return cleaned  # Could name the venue; keep ambiguous derived text.
        return ""
    if bare.casefold() == "parking" and not _PUBLIC_PARKING_RE.search(original_query):
        return ""
    public = [match.span() for match in _PUBLIC_PARKING_RE.finditer(cleaned)]
    for match in reversed(list(_DERIVED_AFTER_HOME_RE.finditer(cleaned))):
        start, end = match.span("bare")
        if any(start < stop and end > begin for begin, stop in public):
            continue  # A derived tail can still name a public facility.
        cleaned = cleaned[:start] + cleaned[end:]
    return re.sub(r"\s+", " ", cleaned).strip(" ,;，；、")


def _unsupported_en(ask: str) -> str:
    return "property car spaces" if ask == _PROPERTY_PARKING_ASK else i18n.UNSUPPORTED_KEY_EN.get(ask, ask)


def _parking_notice(state, kind: str | None) -> str | None:
    if kind == "property":
        return _t(state, "房源自带车位目前无法核验，未按车位筛选；结果不代表满足这项要求。",
                  "A property's own parking spaces cannot currently be verified. No parking filter was applied; the results do not establish this requirement.")
    if kind == "ambiguous":
        return _t(state, "如果你指房源自带车位，目前无法核验；原查询保留，结果不能据此判断有无车位。",
                  "If you mean a property's own parking spaces, they cannot currently be verified. Your query was kept; these results do not establish parking availability.")
    return None


def _unsupported_list(state, asks) -> str:
    if _en(state):
        return ", ".join(_unsupported_en(a) for a in asks)
    return "、".join(asks)


# ---------------------------------------------------------------- LLM 客户端

_client = None
_model_name: str | None = None


def _llm():
    """懒加载 LLM 客户端。缺 key 时在这里炸,而不是在导入时 ——
    这样第 2~5 步(连接池 / 检索 / 公式 / 估值)没配 key 也能跑能测。"""
    global _client, _model_name
    if _client is None:
        from openai import OpenAI  # 局部导入:用不到 LLM 的流程不必付这个 import

        api_key, model, base_url = require_llm_config()
        _client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        _model_name = model
    return _client, _model_name


def _ask(system: str, user: str, temperature: float = 0.0) -> str:
    client, model = _llm()
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _ask_streaming(system: str, user: str, temperature: float = 0.0) -> str:
    """和 _ask 一样,但在 GRAPH.stream(stream_mode="custom") 里会**逐 token 往外推**。

    V8 给网页用的。一次问答约 9 秒,其中七成是 LLM 在写说明 —— 逐字流出去,
    用户 2 秒就开始看到字,感觉上快了一半,而总耗时一点没变。

    不在流式上下文里(CLI 的 invoke、测试)时 get_stream_writer() 会抛
    RuntimeError,这里接住并退回 _ask,行为和以前完全一致。
    """
    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
    except Exception:                      # noqa: BLE001 —— 图外调用没有 runnable 上下文
        writer = None
    if writer is None:
        return _ask(system, user, temperature)

    client, model = _llm()
    stream = client.chat.completions.create(
        model=model,
        temperature=temperature,
        stream=True,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    parts: list[str] = []
    for chunk in stream:
        # 有些服务商会在末尾发一个只带 usage、没有 choices 的块
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            parts.append(delta)
            writer({"token": delta})
    return "".join(parts).strip()


# ---------------------------------------------------------------- 节点 1:parse_intent

# 交给 search_properties() 的参数。**这七个名字必须和它的签名一字不差** ——
# 那是 Member B 的跨线契约。
SEARCH_KEYS = (
    "semantic_query", "max_price", "min_price",
    "bedrooms", "bathrooms", "property_type", "suburb", "max_distance_cbd_km",
)
# V2 新增:排序与指标门槛。这两个**不进数据库**,因为它们依赖的是算出来的指标
# (回报率、Cap Rate),而不是表里的列。所以它们在 rank 节点里生效。
RANK_KEYS = ("sort_by", "min_gross_yield", "amenity_needs", "near_place",
             "abstract_needs", "unsupported_asks", "school_zone", "planning_needs", "relative_preferences")
PARAM_KEYS = SEARCH_KEYS + RANK_KEYS + ("description_query",)
# 由程序根据 changes 计算、模型从不填写的字段。提示词示例里不出现它们
# (tests/test_planning.py 按"PARAM_KEYS 减去这些"检查示例是否齐全)。
PROGRAM_KEYS = ("relative_preferences",)

# 这句话是要干什么。V3 加的,决定走哪条分支。
_INTENTS = ("new_search", "refine", "about_results", "concept", "clarify")

_INT_KEYS = ("max_price", "min_price", "bedrooms", "bathrooms")
_PROPERTY_TYPES = ("house", "apartment", "townhouse")
# 可排序的口径。前四个是「越大越好」,price_asc 是「越小越好」。
_SORT_FIELDS = ("gross_yield", "cap_rate", "roi", "predicted_gap", "predicted_gap_neg",
                "price_asc", "price_desc", "near_place_distance")
# 抽象属性也能当排序口径("最安静的那几套")。它们的分数在 enrich 里算,
# 定义见 app/amenities/context.py。
_ABSTRACT_KEYS = context.ATTRIBUTE_KEYS
# min_score 保留为旧会话/API 的阈值字段;operator 决定比较方向,省略时兼容 ≥。
_SCORE_OPERATORS = {
    "gte": ("≥", operator.ge), "gt": (">", operator.gt),
    "lte": ("≤", operator.le), "lt": ("<", operator.lt), "eq": ("=", operator.eq),
}

# ---------------------------------------------------------------- V7:规划分区
#
# 用户对"未来"的要求。每一项都对应一条**法条**(维州规划纲要里的分区/叠加层),
# 不是模型的推测 —— 所以它们是布尔筛选,不是 0~100 的评分。
#
# 词表故意做得很小。分区数据能支持的确定性结论就这三条,再多就要开始
# 推测"会不会真的盖"了,那不是这份数据能回答的。
_PLANNING_NEEDS = {
    "no_heritage": (
        "没有限制改建的叠加层",
        lambda info: planning.can_redevelop(info) is True),
    "low_density_around": (
        "周边以限制加密的分区为主(法律上不会变成高楼)",
        # 判据:周边没有任何一块地属于"法律上允许高密度开发"的分区。
        # 这是个**否定结论**,而否定结论正是分区数据最强的地方 ——
        # "旁边是 NRZ,法律上不能盖高楼"是确定的;
        # "旁边是 RGZ,会盖高楼"只是可能,数据说不了。
        lambda info: bool(info.get("nearby_total")) and info.get("nearby_high", 0) == 0),
    "no_risk_overlay": (
        "没有已登记的风险叠加层(政府征收、洪泛、山火、土壤污染等)",
        lambda info: "zone" in info and not planning.risks(info)),
    # 按类别精确排除(外部测试第 7 项:「不要机场噪音」「有机场噪音叠加层的全部排除」以前只能变成
    # 「最好安静」这类评分偏好,带机场噪声叠加层的房子照样出现)。都是硬条件,和上面三条一样在 rank 里剔除;
    # 没有规划数据的房源证明不了「没有」,一并剔除并在口径里写明。
    **{"no_" + key: (f"没有{label}",
                     (lambda fams: lambda info: "zone" in info and not planning.has_family(info, fams))(fams))
       for key, (label, fams) in planning.RISK_GROUPS.items()},
}
_SORT_FIELDS = _SORT_FIELDS + _ABSTRACT_KEYS
# 按到某一类设施(amenity_needs 里那一类)的直线距离从近到远:"nearest:train_station"。
# 只有这一类在 amenity_needs 里时才有效 —— 距离只对它们在 enrich 里算全量,
# 而卡片上显示的「火车站 836 m」也正是这个数。和 near_place_distance(点名的**某一个**地点)不是一回事。
NEAREST_PREFIX = "nearest:"
_AMENITY_SORTS = tuple(NEAREST_PREFIX + k for k in nearby.KINDS)
_SORT_FIELDS = _SORT_FIELDS + _AMENITY_SORTS

_PARSE_SYSTEM = """你是房产搜索的参数抽取器。把用户的中文或英文问题转成结构化搜索参数。

这是**多轮对话**。用户消息里会带上前几轮的内容和上一轮的搜索条件,你要先判断
这一句是在干什么,再决定参数怎么填。

只输出一个 JSON 对象,不要 markdown 代码块,不要任何解释文字,不要前后缀。

字段(必须全部出现):
  intent         : 以下四个之一,**这是最重要的一个字段**
                   "new_search"    全新的找房需求,和上一轮无关
                                   例:上轮问 Richmond 三房,这轮说"帮我找便宜的公寓"
                   "refine"        在上一轮基础上改条件,重新找
                                   例:"只看 Richmond 的""再便宜点""改成三房"
                   "about_results" 针对**上一轮已经给出的那几套房**提问,不需要重新找
                   例:"第 3 套详细说说""为什么第 2 套估这个价""哪套最划算"
                   "concept"       问概念、名词、公式,和具体房源无关
                                   例:"什么是 cap rate""毛回报率怎么算的"
                   判断要点:说的是"再/也/还/换成/只要/不要"这类**修改**词,
                   而且没有换掉整个需求 -> refine;
                   提到"第 X 套""这几套""上面那个" -> about_results;
                   完全没有找房意图、纯问知识 -> concept;
                   其余 -> new_search。**第一轮永远是 new_search 或 concept。**

  ↓ 下面这些字段:intent 是 about_results 或 concept 时,全部填 null / [],
    因为这两种情况不会重新检索。intent 是 refine 时**不要填这些字段**,
    只在 changes 里列出本轮修改(格式见文末「多轮修改协议」),没改的条件由程序保留。
    intent 是 new_search 时,只按这一句话填,不要继承上一轮任何条件。

  semantic_query : string —— **必须用英文**。用户对房子本身的描述性要求,
                   翻译成简短的英文关键词(如 "quiet family home with good natural light")。
                   不要把价格、房间数这类硬条件写进来,它们有各自的字段。
                   用户没有描述性要求时,把用户原话的意思翻成英文。
                   为什么必须英文:库里的房源描述全是英文,嵌入模型
                   (nomic-embed-text-v1.5)也是英文模型。实测同一个意思的
                   中文 query 和英文 query,检索结果重合度是 0/5 —— 中文向量
                   落在了和英文语料不同的区域。这一项翻错,后面全白搭。
  max_price      : integer 或 null —— 价格上限,单位澳元
  min_price      : integer 或 null —— 价格下限,单位澳元
  bedrooms       : integer 或 null —— 卧室数(精确匹配)
  bathrooms      : integer 或 null —— 卫生间数(精确匹配)
  property_type  : house / apartment / townhouse 之一,或 null
  sort_by        : 以下之一,或 null —— 用户希望**按什么排序**
                   "gross_yield"    毛租金回报率高的优先(用户说"回报好""租金划算""收租香")
                   "cap_rate"       资本化率高的优先(用户明确说 cap rate / 资本化率)
                   "roi"            投资回报率高的优先(用户明确说 ROI / 投资回报)
                   "predicted_gap"  **估值高于售价**最多的优先 —— 也就是"买得便宜"。
                                    用户说"被低估的""捡漏""性价比""售价低于估值"时用。
                   "predicted_gap_neg"  **估值低于售价**最多的优先 —— 也就是"卖得贵"。
                                    用户明确说"估值低于售价""卖贵了""高于合理价"时用。
                                    ⚠️ 这两个方向**相反,不许弄混**:用户说哪个就填哪个,
                                    不要按"他大概是想找划算的"去猜 —— 猜错的话,
                                    他说出口的话和拿到的结果是反的,而且没人会发现。
                   "price_asc"      便宜的优先(用户说"最便宜""预算紧")
                   "price_desc"     贵的优先(用户说"最好的""不差钱")
                   "near_place_distance"  离 near_place(**点名的某一个地点**)最近的优先
                   "nearest:<kind>"  离某一类设施最近的优先,<kind> 必须是同时写进 amenity_needs 的那一类,
                                    例如用户说"离火车站越近越好""按到车站的距离排" →
                                    sort_by = "nearest:train_station" 且 amenity_needs 含 train_station。
                                    **只有用户明确要求按远近排序/比较("越近越好""最近的排前面""按距离排")才填**;
                                    只说"近车站""车站附近"是距离门槛(amenity_needs),sort_by 照常按其他线索填或填 null
                   或下面 abstract_needs 清单里的任一属性名,按该属性从高到低排序
                   (用户说"最安静的""通勤最方便的""最适合家庭的"时用)
                   用户提了环境要求但没有"最"这类比较级时,可以填对应属性,
                   也可以填 null 让语义相关度决定 —— 提了多个属性时,填最强调的那个。
  min_gross_yield: 小数或 null —— 毛租金回报率的下限。
                   用户说"回报率 5% 以上"就填 0.05,说"至少 4 个点"填 0.04。
                   注意是**小数不是百分数**:5% 要写 0.05,不能写 5。
  amenity_needs  : 数组,用户对**某一类设施**的距离要求。没有就填 []。
                   每项形如 {"kind": "...", "max_distance_m": 1000}
                   kind 只能是下面这些(从注册表生成,不要用清单外的值):
@@AMENITY_KINDS@@
                   max_distance_m 是米。用户说"走路十分钟内"按 800 米算,
                   "五分钟"按 400 米,"很近"按 1000 米,没说距离就填 1500。
                   例:"有小孩,要离幼儿园和小学近"
                     -> [{"kind":"kindergarten","max_distance_m":1500},
                         {"kind":"primary_school","max_distance_m":1500}]
                   点出了具体设施类别时,"离小学近""最好离小学近一点""最好小学近一点""小学近点"
                   **都填这一项、同一个距离**("最好""一点"不改变结果);
                   只说"学校/教育配套好"、没点出哪类学校时,才用 abstract_needs 的 school_access。
  abstract_needs : 数组,用户对**居住环境**的要求。没有就填 []。
                   每项形如 {"attribute": "quiet", "min_score": 60, "operator": "gte"}。
                   operator 可为 gte(≥)、gt(>)、lte(≤)、lt(<)、eq(=);未指定则默认 gte。
                   min_score 是比较阈值,无论比较方向如何均用此字段,允许 0 和 100。
                   例:"安静低于 60 分" -> {"attribute":"quiet","min_score":60,"operator":"lt"}。
                   继续修改条件时必须保留当前 operator,不要把 < / ≤ / = 擅自改回 ≥。
                   attribute **只能**是下面清单里的。你的任务是把用户任意的说法
                   映射到清单上 —— 用户的措辞是无穷的,这份清单是有限的,
                   **映射是你的工作,不要因为用词不同就放弃**。
                   冒号后面是典型说法,不是穷举,同义的说法也要能映射上:

@@ATTRIBUTES@@

                   一句话里可以对应多个属性:
                     "带孩子住,要安静点,最好附近有小学"
                       -> family + quiet(小学点了具体类别,进 amenity_needs: primary_school 1500)
                     "上班方便、楼下能买菜的一居"
                       -> transport + convenient

                   min_score 是 0~100 的门槛,语气越强门槛越高:
                     "安静一点的" -> 60    "要很安静" -> 75    "必须非常安静" -> 85
                   没有明确语气就填 60。

                   quiet 和 lively 可以同时存在,负相关不代表逻辑互斥。不得擅自删除任何一项。
                   strength 为 required/preferred;value_source 为 explicit/inferred,
                   用于区分用户指定的分数与系统根据模糊表达推断的默认门槛。

  unsupported_asks: 数组,用户提了但**本系统没有数据**的要求。没有就填 []。
                   每项是一个简短的中文词。**这一项非常重要:宁可明说没有,
                   也不要硬塞进任何字段里。** 悄悄用一个沾边的条件顶上去,
                   用户会以为系统考虑过了 —— 那比直接说"没有"糟得多。

                   ⚠️ **这条规则管的是上面所有字段,不只是 abstract_needs。**
                   实测出过这样的错:用户说"步行 5 分钟到 CBD",模型填了
                   amenity_needs = [{"kind": "train_station", "max_distance_m": 400}]
                   —— 一个**完全不同**的条件,而且 unsupported_asks 是空的。
                   用户要的是"到 CBD 的步行时间",拿到的是"火车站 400 米内",
                   全程没有任何提示。**近似不是回答,换个条件更不是。**

                   判断标准很简单:如果你填进去的条件,**换成中文念出来和用户
                   原话不是一回事**,那就不要填,放进 unsupported_asks。

                   以下这些都要放进 unsupported_asks,**不要**映射到任何字段:
@@UNSUPPORTED@@

                   房源**自带**车位/车库目前无法核验。明确要求房子带车位或不带车位时,
                   把「房源车位」放进 unsupported_asks,不得当筛选条件、推荐理由,
                   也不要把这项要求写进 semantic_query 或 description_query。
                   附近公共停车场、规划 Parking Overlay、The Garage Cafe 等地点名称
                   与房源自带车位不同:保留其原本搜索意思,不要标成「房源车位」。
                   单独出现 parking/garage 等含义不明的词时保留原查询,不要臆断为房源车位。

                   例:"要采光好、治安好的安静三房"
                     -> abstract_needs 里只有 quiet,
                        unsupported_asks = ["采光", "治安"]
                   例:"80 万以内、4 房、Toorak、步行 5 分钟到 CBD"
                     -> max_price / bedrooms / suburb 照填,
                        amenity_needs = [](**不许**拿火车站顶替),
                        max_distance_cbd_km = null(时间不是距离,**不许**换算成公里),
                        unsupported_asks = ["步行时间"]
  max_distance_cbd_km: 数字或 null —— 到墨尔本 CBD 的**直线**距离上限,单位公里。
                   用户给了数字才填:"离 CBD 20 公里以内" -> 20,"within 10 km of the city" -> 10。
                   没给数字的"离市中心近"不填(那是 transport 等属性的事)。
                   "步行/开车 N 分钟到 CBD"是**时间**不是距离,不填,写进 unsupported_asks(步行时间)。
  school_zone    : 对象或 null —— 用户要求房子落在**某所公立学校的招生学区内**。
                   形如 {"school": "Balwyn Primary School", "level": "primary"}
                   level 是 "primary"(小学)或 "secondary"(中学),不确定填 null。
                   school 要翻成英文校名。

                   **这和 school_access 是两件事,别弄混:**
                     "附近有小学 / 离小学近"   -> amenity_needs 的 primary_school(直线距离)
                     "要在 Balwyn 小学学区内" -> school_zone(招生边界内,是个事实)
                   澳洲说的"学区"指后者。实测只有 54% 的房源"最近的小学"就是
                   "所属学区的小学" —— 拿距离回答学区,近一半会答错。

                   用户只说"学区房"却没点名学校时,填 null:我们没有学校排名数据,
                   无法判断哪个学区"好"。这时把"学校排名"放进 unsupported_asks,
                   同时可以用 school_access 表达"附近有学校"。

                   注意:**只有公立学校有招生学区**。私立、教会学校不划片,
                   用户点名的若是私立学校,填 null 并在 unsupported_asks 里说明。
  planning_needs : 数组,用户对**这块地未来会变成什么样**的要求。没有就填 []。
                   数据来自维州规划分区与叠加层(法条),只有以下三个值可选:

                     "no_heritage"        能自由改建/翻建 —— 这块地上没有历史保护、
                                          限高、须报总体规划一类的限制性叠加层。
                                          例:"想买了推倒重建"、"要能加建"、
                                              "不要历史保护建筑"
                     "low_density_around" 周边法律上不会盖起高楼。
                                          例:"以后不会被挡"、"周围别变成高楼"、
                                              "希望周边一直保持低矮"
                     "no_risk_overlay"    这块地没有**任何**已登记的风险叠加层
                                          (政府将来征收、洪泛、山火、土壤污染、机场噪声……)。
                                          例:"不要任何风险叠加层"、"风险越少越好"
                     下面这几个是**单一类别**的排除,用户点名哪一类就只填哪一类:
                     "no_airport_noise"   没有机场噪声叠加层。例:"不要机场噪音"、"避开机场噪声区"、
                                          "有机场噪音叠加层的全部排除"
                     "no_flood"           没有洪泛/内涝叠加层。例:"不要淹水的地方"、"避开洪水区"
                     "no_bushfire"        没有山火管理叠加层。例:"不要山火风险"
                     "no_acquisition"     没有政府征收叠加层。例:"别买到要被征收/拆迁的"
                     "no_contamination"   没有土壤污染(须环境审计)叠加层。例:"不要土壤污染"
                     "no_erosion"         没有侵蚀/盐渍化管理叠加层

                   **"不要 / 避开 / 排除 / 不能有" + 上面任一类风险 = 对应的 planning_needs(硬排除)**,
                   不要改写成 quiet、away_industry 这类评分偏好 —— 评分只是「最好」,
                   房子照样会出现,用户说的「不要」就落空了。
                   **只有上面这些值,不要发明新的。** 用户提的其它"未来"类要求
                   (房价会不会涨、地铁会不会修过来、学校会不会变好)一律放进
                   unsupported_asks —— 分区数据说的是"法律上能盖什么",
                   **不是**"会不会涨"。这两件事不要混。
  near_place     : 对象或 null —— 用户点名了**某一个具体地点**(不是某一类)。
                   形如 {"name": "Monash University", "kind": "university",
                         "max_distance_m": 3000}
                   name **必须翻成英文的官方名称**,因为设施库里全是英文:
                     "墨尔本大学" -> "University of Melbourne"
                     "莫纳什大学" -> "Monash University"
                     "皇家墨尔本医院" -> "Royal Melbourne Hospital"
                     "南十字星车站" -> "Southern Cross Station"
                   kind 填上面九类里最贴切的那个,能大幅提高匹配准确率。
                   max_distance_m 没提就填 null(只排序、不筛掉)。
                   **区分要点**:"离大学近"是 amenity_needs(哪所都行);
                   "离莫纳什大学近"是 near_place(指定了哪一所)。
  suburb         : string 或 null —— 地名,英文,如 "Richmond"
                   **用户只要提到任何地名(区名、郊区名、城市名),就必须原样
                   翻成英文填进这个字段,哪怕你认为那个地方不在墨尔本。**
                   例如用户说"悉尼",就填 "Sydney"。
                   有没有这个地方由数据库判断,不由你判断 —— 库里没有就返回
                   0 条,系统会如实回答"没找到",这正是我们要的。
                   你替数据库做判断、把地名藏进 semantic_query,会导致系统
                   拿一批别处的房子冒充结果,这是本系统最严重的错误。
                   只有用户完全没提地名时,这一项才填 null。

铁律:**用户没提到的字段一律填 null,绝对不要填 0、空字符串或你猜的默认值。**
max_price=null 的意思是"不筛价格";max_price=0 的意思是"要 0 元以下的房子",
会返回空结果且不报错 —— 这是最严重的错误。

单位换算:中文的"万"是 10000。"80 万" -> 800000。"一百万以内" -> max_price=1000000。
"两房""两室" -> bedrooms=2。"三房两卫" -> bedrooms=3, bathrooms=2。
"公寓" -> apartment,"别墅"/"独栋"/"独立屋"/"排屋" -> house,"联排"/"联排别墅" -> townhouse。

例(第一轮,没有历史):
用户:帮我找 80 万以下、租金回报不错的两房
{"intent": "new_search", "semantic_query": "two bedroom investment property", "max_price": 800000, "min_price": null, "bedrooms": 2, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": "gross_yield", "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [], "unsupported_asks": [], "school_zone": null, "planning_needs": [], "description_query": null}

例(接着上一轮,用户说"再便宜点,而且要离火车站近"):
{"intent": "refine", "changes": [{"action": "relative", "field": "price", "direction": "decrease", "degree": "slight", "source": "再便宜点"}, {"action": "set", "field": "amenity_needs", "value": {"kind": "train_station", "max_distance_m": 800}, "source": "离火车站近"}], "clarification": null}

例(用户:我有小孩,想找离莫纳什大学近、附近有小学的三房):
{"intent": "new_search", "semantic_query": "family home", "max_price": null, "min_price": null, "bedrooms": 3, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": "near_place_distance", "min_gross_yield": null, "amenity_needs": [{"kind": "primary_school", "max_distance_m": 1500}], "near_place": {"name": "Monash University", "kind": "university", "max_distance_m": null}, "abstract_needs": [], "unsupported_asks": [], "school_zone": null, "planning_needs": [], "description_query": null}

例(用户:安静一点的三房独栋,别靠马路):
{"intent": "new_search", "semantic_query": "three bedroom house", "max_price": null, "min_price": null, "bedrooms": 3, "bathrooms": null, "property_type": "house", "suburb": null, "max_distance_cbd_km": null, "sort_by": "quiet", "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [{"attribute": "quiet", "min_score": 60}], "unsupported_asks": [], "school_zone": null, "planning_needs": [], "description_query": null}

例(用户:找个热闹、生活方便的公寓):
{"intent": "new_search", "semantic_query": "apartment", "max_price": null, "min_price": null, "bedrooms": null, "bathrooms": null, "property_type": "apartment", "suburb": null, "max_distance_cbd_km": null, "sort_by": "lively", "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [{"attribute": "lively", "min_score": 60}, {"attribute": "convenient", "min_score": 60}], "unsupported_asks": [], "school_zone": null, "planning_needs": [], "description_query": null}

例(用户:带孩子住,要安静点,最好附近有小学,采光也要好):
{"intent": "new_search", "semantic_query": "family home", "max_price": null, "min_price": null, "bedrooms": null, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": "family", "min_gross_yield": null, "amenity_needs": [{"kind": "primary_school", "max_distance_m": 1500}], "near_place": null, "abstract_needs": [{"attribute": "family", "min_score": 60}, {"attribute": "quiet", "min_score": 60}], "unsupported_asks": ["采光"], "school_zone": null, "planning_needs": [], "description_query": null}

例(用户:父母要住,看病方便点,房子得宽敞,治安也重要):
{"intent": "new_search", "semantic_query": "spacious home", "max_price": null, "min_price": null, "bedrooms": null, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": "medical", "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [{"attribute": "medical", "min_score": 60}, {"attribute": "spacious", "min_score": 60}], "unsupported_asks": ["治安"], "school_zone": null, "planning_needs": [], "description_query": null}

例(用户:要在 Balwyn 小学学区内的三房):
{"intent": "new_search", "semantic_query": "three bedroom home", "max_price": null, "min_price": null, "bedrooms": 3, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": null, "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [], "unsupported_asks": [], "school_zone": {"school": "Balwyn Primary School", "level": "primary"}, "planning_needs": [], "description_query": null}

例(用户:想买个老房子推倒重建,周围以后别盖起高楼):
{"intent": "new_search", "semantic_query": "older house for redevelopment", "max_price": null, "min_price": null, "bedrooms": null, "bathrooms": null, "property_type": "house", "suburb": null, "max_distance_cbd_km": null, "sort_by": null, "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [], "unsupported_asks": [], "school_zone": null, "planning_needs": ["no_heritage", "low_density_around"], "description_query": "older house for redevelopment"}

例(用户:找个安静的三房,别买到将来要拆迁或者会淹水的,顺便说下会不会升值):
{"intent": "new_search", "semantic_query": "quiet three bedroom home", "max_price": null, "min_price": null, "bedrooms": 3, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": "quiet", "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [{"attribute": "quiet", "min_score": 60}], "unsupported_asks": ["升值潜力"], "school_zone": null, "planning_needs": ["no_risk_overlay"], "description_query": null}
(注意:"拆迁"和"淹水"都是 no_risk_overlay 能覆盖的**登记事实**;
 "会不会升值"是预测,分区数据答不了,进 unsupported_asks)

例(用户:第 3 套为什么估值这么高):
{"intent": "about_results", "semantic_query": null, "max_price": null, "min_price": null, "bedrooms": null, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": null, "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [], "unsupported_asks": [], "school_zone": null, "planning_needs": [], "description_query": null}

例(用户:cap rate 是什么意思):
{"intent": "concept", "semantic_query": null, "max_price": null, "min_price": null, "bedrooms": null, "bathrooms": null, "property_type": null, "suburb": null, "max_distance_cbd_km": null, "sort_by": null, "min_gross_yield": null, "amenity_needs": [], "near_place": null, "abstract_needs": [], "unsupported_asks": [], "school_zone": null, "planning_needs": [], "description_query": null}
"""


# 提示词里的属性清单、设施类别、不支持清单**全部从注册表生成**。
# 手写的话,注册表加了一条却忘了改提示词,那个属性就永远不会被触发 ——
# 而且不报错,只是安静地失效。这正是 V4 要改掉的那个毛病。
_PARSE_SYSTEM = (
    _PARSE_SYSTEM
    .replace("@@ATTRIBUTES@@", registry.prompt_block())
    .replace("@@UNSUPPORTED@@", registry.unsupported_block())
    .replace("@@AMENITY_KINDS@@", registry.amenity_kinds_block())
) + refinement.PATCH_PROMPT
assert "@@" not in _PARSE_SYSTEM, "提示词里还有没被替换掉的占位符"


def _extract_json(text: str) -> dict | None:
    """从模型输出里抠出 JSON。容忍代码块围栏和前后废话。"""
    if not text:
        return None
    fenced = re.search(r"`{3}(?:json)?\s*(.+?)\s*`{3}", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _typo_source(suburb: str, user_query: str) -> str | None:
    """用户原话里那个被"纠正"成 suburb 的词。没有纠正过就返回 None。

    起因:用户输入"靠近 Richmonddd 的三房",模型悄悄改成 Richmond 并返回了 5 套,
    全程没有任何提示。纠错本身是好事,**静默**才是问题 —— 万一它纠错纠到
    另一个区去,用户永远不会发现自己看的根本不是想找的地方。

    判据是确定性的,不问模型:如果 suburb 原样出现在用户原话里,就是用户自己
    打的;找不到,说明模型做了推断或纠错。再用编辑距离找出原话里最像的那个词,
    好让提示能说清"你打的是哪个"。
    """
    if not user_query:
        return None
    # 必须按**词边界**比,不能用子串:"Richmond" 是 "Richmonddd" 的前缀,
    # 用 `in` 判断会把明显的拼写错误当成"用户自己打对了"。踩过。
    # 用前后不接字母的断言,顺便也能正确处理 "Box Hill" 这类带空格的地名。
    if re.search(r"(?<![A-Za-z])" + re.escape(suburb) + r"(?![A-Za-z])", user_query, re.I):
        return None
    import difflib
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", user_query)
    hit = difflib.get_close_matches(suburb.lower(), [w.lower() for w in words], n=1, cutoff=0.6)
    if not hit:
        return None
    for w in words:                       # 还原用户打的大小写
        if w.lower() == hit[0]:
            return w
    return hit[0]


# 估值方向的说法 → 排序方向。**由代码判定,不交给 LLM。**
#
# 实测(每种说法重复 3 次):「Richmond 附近,售价低于估值的两房」3/3 被解析成
# predicted_gap_neg(卖贵了),「售价低于估值的房子」1/3 解析反;「被低估」「卖贵了」
# 全对。模型看到"低于"两个字就往"估值低于售价"那边靠 —— 提示词里明写了也挡不住。
# 方向一反,用户拿到的正好是他要的反面,而且结果看起来完全正常,没人会发现。
#
# 注意子串关系:「售价低于估值」含「低于估值」,「估值低于售价」含「低于售价」,
# 两组关键词互不包含,所以不会互相误判。「高估值/低估值」(估值本身高低)用负向断言排除。
_GAP_UP = re.compile(r"(售价|价格|报价|指导价)?低于(模型)?估值|估值高于(售价|价格|报价|指导价)|被低估|低估(?!值)|捡漏"
                     r"|under-?valued|below (its |the )?(model )?(estimate|valuation)|priced below", re.I)
_GAP_DOWN = re.compile(r"(售价|价格|报价|指导价)?高于(模型)?估值|估值低于(售价|价格|报价|指导价)|被高估|高估(?!值)|卖贵"
                       r"|over-?valued|over-?priced|above (its |the )?(model )?(estimate|valuation)|priced above", re.I)


def _valuation_direction(user_query: str, sort_by):
    """用户原话里有明确的估值方向时,排序方向以原话为准。

    只在 LLM 没选排序、或选了两种估值排序之一时介入 —— 用户同时要"回报最高"之类别的排序时,
    不去覆盖它。两个方向的词同时出现(自相矛盾)时不猜,保留 LLM 的结果。
    """
    if sort_by not in (None, "predicted_gap", "predicted_gap_neg"):
        return sort_by
    up, down = bool(_GAP_UP.search(user_query or "")), bool(_GAP_DOWN.search(user_query or ""))
    if up and not down:
        return "predicted_gap"
    if down and not up:
        return "predicted_gap_neg"
    return sort_by


def _sanitize(raw: dict, user_query: str, *, preserve_property_parking=False,
              allow_property_parking=True) -> dict:
    """把模型给的东西收拾成 search_properties() 能安全接收的参数。

    这里是"第一版最容易翻车的地方"的最后一道闸:0、负数、空字符串一律降级成
    None(= 不筛这一项)。宁可搜得宽,不要搜得空。
    """
    params: dict = {key: None for key in PARAM_KEYS}
    if isinstance(raw.get("description_query"), str):
        params["description_query"] = raw["description_query"].strip()[:500] or None

    for key in _INT_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):          # Python 里 True 是 int 的子类,先挡掉
            continue
        if isinstance(value, (int, float)) and value > 0:
            params[key] = int(value)

    # 到 CBD 的直线距离上限(公里)。墨尔本都会区半径不过一百多公里,超出的当成误读丢掉,不硬筛。
    cbd = raw.get("max_distance_cbd_km")
    if isinstance(cbd, (int, float)) and not isinstance(cbd, bool) and 0 < cbd <= 200:
        params["max_distance_cbd_km"] = round(float(cbd), 1)

    ptype = raw.get("property_type")
    if isinstance(ptype, str) and ptype.strip().lower() in _PROPERTY_TYPES:
        params["property_type"] = ptype.strip().lower()

    suburb = raw.get("suburb")
    if isinstance(suburb, str) and suburb.strip():
        params["suburb"] = suburb.strip()
        params["suburb_typed_as"] = _typo_source(params["suburb"], user_query)

    sq = raw.get("semantic_query")
    params["semantic_query"] = sq.strip() if isinstance(sq, str) and sq.strip() else user_query

    # 上下限矛盾(min > max)时放弃下限,而不是白白返回空结果
    if params["min_price"] and params["max_price"] and params["min_price"] > params["max_price"]:
        params["min_price"] = None

    # --- V2 新增两项,同样过闸 ---
    sort_by = raw.get("sort_by")
    if isinstance(sort_by, str) and sort_by.strip() in _SORT_FIELDS:
        params["sort_by"] = sort_by.strip()
    params["sort_by"] = _valuation_direction(user_query, params["sort_by"])

    mgy = raw.get("min_gross_yield")
    if not isinstance(mgy, bool) and isinstance(mgy, (int, float)) and mgy > 0:
        # 模型很容易把 5% 写成 5 而不是 0.05。0.5 的回报率(50%)在现实里不存在,
        # 所以大于 1 的一律当成百分数除以 100 —— 与其返回空结果,不如按常识修正。
        params["min_gross_yield"] = float(mgy) / 100 if mgy > 1 else float(mgy)

    # --- V3 新增:设施需求,同样过闸 ---
    needs = []
    for item in raw.get("amenity_needs") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if not isinstance(kind, str) or kind.strip() not in nearby.KINDS:
            continue        # 类别不在九类之内就丢掉,不猜
        distance = item.get("max_distance_m")
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or distance <= 0:
            distance = 1500  # 用户提了这类设施但没说多远,给个合理默认值
        needs.append({"kind": kind.strip(), "max_distance_m": int(distance)})
    params["amenity_needs"] = needs or None

    wanted = []
    for item in raw.get("abstract_needs") or []:
        if not isinstance(item, dict):
            continue
        attr = item.get("attribute")
        if not isinstance(attr, str) or attr.strip() not in _ABSTRACT_KEYS:
            continue
        floor = item.get("min_score")
        if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not 0 <= floor <= 100:
            floor = 60      # "高于平均水平"这个语气的默认门槛
        need = {"attribute": attr.strip(), "min_score": int(floor)}
        if "operator" in item:
            op = item["operator"]
            need["operator"] = op if isinstance(op, str) and op in _SCORE_OPERATORS else "gte"
        for key, allowed in (("strength", ("required", "preferred")),
                             ("value_source", ("explicit", "inferred"))):
            if item.get(key) in allowed:
                need[key] = item[key]
        wanted.append(need)
    params["abstract_needs"] = wanted or None
    params["relative_preferences"] = refinement.valid_goals(raw.get("relative_preferences")) or None

    asks = [a.strip() for a in (raw.get("unsupported_asks") or [])
            if isinstance(a, str) and a.strip()]
    parking_kind = _parking_kind(user_query)
    had_property_parking = any(ask.casefold() in _PROPERTY_PARKING_LABELS for ask in asks)
    # Only canonical owned-space labels are normalised. Public-facility data
    # gaps and other unsupported asks keep their original meaning.
    asks = [ask for ask in asks if ask.casefold() not in _PROPERTY_PARKING_LABELS]
    if allow_property_parking and (parking_kind == "property" or
                                   (preserve_property_parking and had_property_parking)):
        asks.insert(0, _PROPERTY_PARKING_ASK)
    if allow_property_parking and parking_kind == "property":
        params["semantic_query"] = _without_derived_property_parking(params["semantic_query"], user_query) or "property"
        if params["description_query"]:
            params["description_query"] = _without_derived_property_parking(params["description_query"], user_query) or None
    params["unsupported_asks"] = asks[:6] or None      # 截断,防止模型灌一长串

    # 规划分区要求。词表之外的一律丢掉 —— 模型编一个 "no_noise" 出来,
    # 静默忽略比假装筛过要好。
    wanted_planning = [p for p in (raw.get("planning_needs") or [])
                       if isinstance(p, str) and p in _PLANNING_NEEDS]
    params["planning_needs"] = list(dict.fromkeys(wanted_planning)) or None

    zone = raw.get("school_zone")
    if isinstance(zone, dict) and isinstance(zone.get("school"), str) and zone["school"].strip():
        level = zone.get("level")
        params["school_zone"] = {
            "school": zone["school"].strip(),
            "level": level if level in zones.LEVELS else None,
        }

    place = raw.get("near_place")
    if isinstance(place, dict) and isinstance(place.get("name"), str) and place["name"].strip():
        kind = place.get("kind")
        distance = place.get("max_distance_m")
        params["near_place"] = {
            "name": place["name"].strip(),
            "kind": kind.strip() if isinstance(kind, str) and kind.strip() in nearby.KINDS else None,
            "max_distance_m": int(distance) if (not isinstance(distance, bool)
                                                and isinstance(distance, (int, float))
                                                and distance > 0) else None,
        }

    # near_place_distance 排序离了 near_place 就没意义,降级成语义相关度
    if params["sort_by"] == "near_place_distance" and not params["near_place"]:
        params["sort_by"] = None
    # 同理:按到某类设施的距离排,这一类必须在 amenity_needs 里(否则全量距离没算,排不了)
    if (params["sort_by"] or "").startswith(NEAREST_PREFIX):
        kind = params["sort_by"][len(NEAREST_PREFIX):]
        if not any(n.get("kind") == kind for n in params.get("amenity_needs") or []):
            params["sort_by"] = None

    return params


def prepare_refinement(raw: dict, previous: dict, removed_attributes=(), user_query=None,
                       preserve_property_parking=None, allow_property_parking=True) -> dict:
    """条件卡以当前条件为准,删除偏好时同步清除关联排序和旧检索描述。

    不能靠删英文关键词:同一偏好可能写成 quiet / peaceful / away from traffic。
    条件集合变化时从保留下来的结构化条件重建英文检索描述,评分和门槛仍由原流程执行。
    只切排序/语言时保持原检索描述;不引入一次额外的 LLM 解析。
    """
    if preserve_property_parking is None:
        preserve_property_parking = _PROPERTY_PARKING_ASK in (previous.get("unsupported_asks") or [])
    clean = _sanitize(dict(raw), user_query or raw.get("semantic_query") or previous.get("semantic_query") or "property",
                      preserve_property_parking=preserve_property_parking,
                      allow_property_parking=allow_property_parking)
    old_attrs = {n["attribute"] for n in previous.get("abstract_needs") or []}
    active = {n["attribute"] for n in clean.get("abstract_needs") or []}
    removed = (old_attrs | (set(removed_attributes) & set(_ABSTRACT_KEYS))) - active
    if clean.get("sort_by") in removed:
        clean["sort_by"] = None
    clean["relative_preferences"] = [g for g in clean.get("relative_preferences") or []
                                     if g["field"] not in removed] or None
    old_needs = {n["attribute"]: n for n in previous.get("abstract_needs") or []}
    changed_scores = {n["attribute"] for n in clean.get("abstract_needs") or []
                      if n["attribute"] in old_needs and n != old_needs[n["attribute"]]}
    clean["relative_preferences"] = [g for g in clean.get("relative_preferences") or []
                                     if g["field"] not in changed_scores] or None
    if clean.get("sort_by") != previous.get("sort_by") and clean.get("sort_by"):
        clean["relative_preferences"] = None

    filter_keys = [k for k in PARAM_KEYS if k not in ("semantic_query", "sort_by", "unsupported_asks")]
    changed = bool(removed) or any(previous.get(k) != clean.get(k) for k in filter_keys)
    if changed:
        # 这里的描述只是检索输入,不把条件/门槛冒充房源的事实。
        terms = [clean.get("property_type") or "property"]
        if clean.get("description_query"):
            terms.append(clean["description_query"])
        if clean.get("bedrooms"):
            terms.append(f"{clean['bedrooms']} bedrooms")
        if clean.get("bathrooms"):
            terms.append(f"{clean['bathrooms']} bathrooms")
        if clean.get("suburb"):
            terms.append("in " + clean["suburb"])
        terms.extend(i18n.ATTRIBUTES_EN[n["attribute"]] for n in clean.get("abstract_needs") or [])
        terms.extend(i18n.ATTRIBUTES_EN[g["field"]] for g in clean.get("relative_preferences") or []
                     if g["field"] in _ABSTRACT_KEYS)
        terms.extend("near " + i18n.KINDS_EN.get(n["kind"], n["kind"].replace("_", " "))
                     for n in clean.get("amenity_needs") or [])
        if clean.get("near_place"):
            terms.append("near " + clean["near_place"]["name"])
        if clean.get("school_zone"):
            terms.append("school zone " + clean["school_zone"]["school"])
        terms.extend(i18n.PLANNING_NEEDS_EN[k] for k in clean.get("planning_needs") or [])
        clean["semantic_query"] = "; ".join(terms)
    return clean


HISTORY_TURNS = 4      # 喂给 LLM 的历史轮数。太多会稀释注意力,也费 token。


def _context_message(state: State) -> str:
    """把"上下文"整理成给 LLM 的一段话:前几轮对话 + 上一轮的搜索条件 + 上一轮的结果。

    上一轮的条件必须给,否则"再便宜点"这句话里没有任何数字,LLM 无从得知
    要把 max_price 从 800000 改成多少。
    """
    parts = []
    history = state.get("history") or []
    if history:
        recent = history[-HISTORY_TURNS * 2:]
        lines = "\n".join(f"  {h['role']}: {h['text']}" for h in recent)
        parts.append(f"前几轮对话:\n{lines}")

    last_params = state.get("params") or {}
    if last_params:
        shown = {k: v for k, v in last_params.items() if v not in (None, [], {})}
        parts.append("当前生效的搜索条件(refine 时只在此基础上改;条件卡已删除的要求不能从旧对话恢复,除非用户本轮明确重新提出):\n  "
                     + json.dumps(shown, ensure_ascii=False))

    metrics = state.get("metrics") or []
    if metrics:
        brief = [f"第 {i} 套 {m.get('suburb')} ${m.get('price')} "
                 f"{m.get('bedrooms')}房{m.get('bathrooms')}卫; "
                 f"系统相对评分 {json.dumps(m.get('context_scores') or {}, ensure_ascii=False)}"
                 for i, m in enumerate(metrics, int(state.get('batch_offset') or 0) + 1)]
        parts.append("上一轮给出的房源(about_results 指的就是这几套):\n  "
                     + "; ".join(brief))

    parts.append(f"用户这一句:{state['user_query']}")
    parts.append("界面语言:English" if _en(state) else "界面语言:中文")
    return "\n\n".join(parts)


def parse_intent(state: State) -> dict:
    """LLM 判断这句话要干什么,并抽出结构化参数。失败有兜底,不许崩。"""
    user_query = state["user_query"]
    try:
        raw = _extract_json(_ask(_PARSE_SYSTEM, _context_message(state)))
    except Exception:
        raw = None

    history = [{"role": "用户", "text": user_query}]
    def clarify(message=None):
        return {"intent": "clarify", "params": state.get("params") or {},
                "refinement_base": None, "history": history,
                "turn_notice": message or _t(state,
                    "我还不能确定这次要修改哪项条件,已保留原条件和房源。请说明要增加、取消或调整哪项要求;相对调整需要上一轮有对应的数据。",
                    "I kept your filters and results. Please specify which requirement to add, remove or adjust; a relative adjustment needs matching data from the previous results.")}

    if raw is None:
        if _parking_kind(user_query) == "property":
            return {"intent": "clarify", "params": state.get("params") or {},
                    "refinement_base": None, "history": history,
                    "turn_notice": _parking_notice(state, "property")}
        if state.get("params") or state.get("metrics"):
            return clarify()
        # 兜底:当成全新搜索,退化成纯语义检索。宁可搜得宽,不要崩。
        return {"intent": "new_search",
                "params": {**{k: None for k in PARAM_KEYS}, "semantic_query": user_query},
                "refinement_base": None, "turn_notice": None, "history": history}

    intent = raw.get("intent")
    if not isinstance(intent, str) or intent.strip() not in _INTENTS:
        if state.get("params") or state.get("metrics"):
            return clarify()
        # 分类不出来就按"新搜索"走 —— 那是唯一一条会真正去查数据库的安全路径。
        # 猜成 about_results 的话,系统会拿着上一轮的旧房源回答新问题,更糟。
        intent = "new_search"
    else:
        intent = intent.strip()

    # **确定性兜底:没有上一轮就不可能是"追问上一轮"。**
    # 提示词里写了"第一轮永远是 new_search 或 concept",但 LLM 不一定听。
    # 评估里实测:第一轮问「Richmond 三房的 NOI 和 Cap Rate 是多少」被判成了
    # about_results,系统于是回"还没有搜索结果可供追问" —— 一个正常问题被顶回去了。
    # 这类约束能用代码保证就别指望模型自觉。同理,没有上一轮条件时 refine
    # 也无从"在上一轮基础上改"。
    if intent == "about_results" and not state.get("metrics"):
        intent = "new_search"
    # 第一句就说「最好离小学近一点」,模型常因「一点」判成 refine。没有上一轮可改时,
    # 以前直接拒绝(外部测试第 6 项);现在把这些修改应用到空条件上,当作新搜索。
    # 相对调整(「再便宜点」)没有基准仍会被 apply_changes 拒绝 —— 那确实无从算起。
    fresh = intent == "refine" and not (state.get("params") or state.get("metrics"))

    if intent == "clarify":
        message = raw.get("clarification")
        return clarify(message[:500] if isinstance(message, str) and message.strip() else None)

    if intent == "new_search" and state.get("params"):
        reset_source = raw.get("reset_source")
        if not isinstance(reset_source, str) or not reset_source.strip() or reset_source.casefold() not in user_query.casefold():
            return clarify()

    if intent in ("about_results", "concept"):
        # 这两类不重新检索,参数保持上一轮不动(供输出时交代口径用)
        return {"intent": intent, "params": state.get("params") or {},
                "turn_notice": None, "refinement_base": None, "history": history}

    if intent == "refine":
        try:
            previous = state.get("params") or {}
            changes = raw.get("changes")
            removed_property_parking = any(
                isinstance(change, dict) and change.get("action") == "remove"
                and change.get("field") == "unsupported_asks"
                and isinstance(change.get("value"), str)
                and change["value"].casefold() in _PROPERTY_PARKING_LABELS
                for change in (changes if isinstance(changes, list) else []))
            preserve_property_parking = _PROPERTY_PARKING_ASK in (previous.get("unsupported_asks") or [])
            def sanitize_refinement(params, query):
                return _sanitize(params, query, preserve_property_parking=preserve_property_parking,
                                 allow_property_parking=not removed_property_parking)
            changed = refinement.apply_changes(previous, changes,
                user_query, state.get("metrics") or [], sanitize_refinement, _SORT_FIELDS)
            clean = prepare_refinement(changed, previous, user_query=user_query,
                preserve_property_parking=preserve_property_parking,
                allow_property_parking=not removed_property_parking)
            # 相对目标由程序计算,prepare_refinement 不能重写其基准。
            clean["relative_preferences"] = changed.get("relative_preferences")
        except (refinement.ClarifyChange, TypeError, ValueError, KeyError):
            return clarify()
        if fresh:
            return {"intent": "new_search", "params": clean, "refinement_base": None,
                    "turn_notice": None, "history": history}
        return {"intent": intent, "params": clean, "refinement_base": refinement.snapshot(state),
                "turn_notice": None, "history": history}

    return {"intent": intent,
            "params": _sanitize({**raw, "relative_preferences": None}, user_query),
            "refinement_base": None, "turn_notice": None, "history": history}


# ---------------------------------------------------------------- 节点 2:search

def detail_metrics(ids: list[int], lang: str = "zh") -> list[dict]:
    """按房源编号直接算出与搜索结果**同一口径**的详情数据(收藏夹打开详情用)。

    等同于一次「没有任何偏好条件」的检索:analyze → enrich → present,不经过 rank,不调用 LLM。
    数字都是现在的模型与现在的假设算出来的,不是收藏时的旧值。
    """
    state = {"properties": properties_by_ids(ids), "params": {}, "lang": lang, "user_query": ""}
    if not state["properties"]:
        return []
    for node in (analyze, enrich, present):
        state.update(node(state))
    return state["metrics"]


RESULT_LIMIT = 5        # 最终给用户看几套

# 要按指标/环境属性排序时捞多少套进来算。
#
# **V5 之前这个数是 120,那是个实打实的正确性缺陷。** 实测:「100 万以下三房
# 独栋」符合条件的有 4,370 套,系统给出的"最安静的 5 套"在全量排名里只排到
# 第 85、89、103、113、243 名,与真值重合 0/5。原因很简单 —— 它只在语义最
# 相关的 120 套(占 2.7%)里排序,而语义相关度和"安静"根本没关系。
#
# 提到 5000 的代价实测很小:检索层拉 5000 条只要 64 ms(limit 本来就在
# search_properties 的签名里,不动跨线契约),证据计算换成 BallTree 批量后
# 4,370 套 1.3 秒。换来的是"在**所有**符合硬条件的房源里排序"。
#
# 仍然有上限,所以结果超过它时要**如实告诉用户口径**(见 rank 的说明)。
CANDIDATE_LIMIT = 5000


# 能在 SQL 里排的口径 -> search_properties(order_by=...)。cap_rate 和毛回报率同序
# (运营支出按同一比例扣)。**ROI 不同序**:分母多了分档累进印花税和杂费,按毛回报率截的前 5,000 套
# 可能漏掉真正的 ROI 最高者(DEF-0007),所以 ROI 单独按不取整的 ROI 预排序,
# 并由 rank 证明/扩容(见 formulas.roi_certified_prefix 与 rank)。
_SQL_ORDER = {"price_asc": "price_asc", "price_desc": "price_desc",
              "gross_yield": "gross_yield", "cap_rate": "gross_yield", "roi": "roi"}


def search(state: State) -> dict:
    """调 B 的 search_properties()。这一步没有 LLM 参与。

    要按指标排序(或设了回报率门槛)时,先多捞一些候选进来 —— 因为回报率、
    Cap Rate 这些是**算出来的**,数据库里没有这些列,没法在 SQL 里排序。
    只能捞一批回来自己算、自己排。

    价格和回报率是例外(审计 BUG-04):它们能在 SQL 里排,就让检索层按这一列取前 N 套。
    这样即使硬条件命中超过候选上限,截下来的也是**全库**这一列最靠前的那批,
    后面再按设施、环境、学区筛,也不会漏掉池子外面更靠前的房源。
    其余口径(估值差、环境属性、离某地距离)数据库里没有,仍在语义最相关的候选里挑,
    这个限定会在排序说明里如实标出。
    """
    params = {key: state["params"].get(key) for key in SEARCH_KEYS}
    if not params.get("semantic_query"):
        params["semantic_query"] = state["user_query"]

    # 任何"数据库筛不了、只能捞回来自己筛"的条件,都要扩大候选池。
    # 设施距离尤其如此 —— 数据库里根本没有"离火车站多远"这一列。
    # **凡是数据库筛不了、只能捞回来自己筛的条件,都要放大候选池。**
    # 漏一个进来,那个条件就只在 5 套里生效,等于没生效 —— 而且不报错。
    # 这里干脆用 RANK_KEYS 全集,加新参数时不会再漏。
    needs_pool = any(state["params"].get(k) for k in RANK_KEYS
                     if k != "unsupported_asks")
    limit = CANDIDATE_LIMIT if needs_pool else RESULT_LIMIT
    if state.get("roi_limit"):
        limit = max(limit, int(state["roi_limit"]))      # rank 扩大 ROI 候选池时临时指定(不写回会话状态)
    order_by = _SQL_ORDER.get(state["params"].get("sort_by"))
    extra, roi_pool, snap = {}, None, state.get("assumption_snap")
    if state.get("roi_limit") and snap:
        pass                       # rank 扩容的后续几轮:沿用第一轮的快照,不再读进程级假设
    else:
        display = deepcopy(assumptions.snapshot())          # 只读一次;运营支出和杂费都直接取这一份的键(键名同 /api/recalc 与前端 live.*)。
        snap = {"opex_rate": display["opex_rate"],          # 键缺失就直接报错,不悄悄再去读会变的进程级假设
                "other_costs": display["other_acquisition_costs"],
                "display": display}
    if order_by == "roi":
        extra = {"opex_rate": snap["opex_rate"], "other_costs": snap["other_costs"]}       # ROI 预排序与 analyze 同一份快照
    # ROI 多取 1 套当哨兵:只有哨兵真的存在才算「被截断」(恰好取满 limit 套、后面没有了,不算截断)
    properties = search_properties(**params, limit=limit + (1 if order_by == "roi" else 0), order_by=order_by, **extra)
    if order_by == "roi" and len(properties) > limit:
        properties = properties[:limit]
        last = properties[-1]          # 池被截断:池外任何一套的不取整 ROI ≤ 最后一套的(SQL 按它排序)
        roi_pool = {"cutoff": roi_unrounded(last.get("price"), last.get("annual_rent"), extra["opex_rate"], extra["other_costs"]),
                    "opex_rate": extra["opex_rate"], "other_costs": extra["other_costs"], "limit": limit}
    return {"properties": properties, "search_order": order_by, "roi_pool": roi_pool, "assumption_snap": snap}


# ---------------------------------------------------------------- 节点 3:analyze

def _rent_sources(ids) -> dict:
    """id -> rent_source。查不到(比如测试里的假房源没有 id)就返回空,不猜。"""
    ids = [i for i in ids if isinstance(i, int)]
    if not ids:
        return {}
    from app.core.db import get_connection
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, rent_source FROM properties WHERE id = ANY(%s)", (ids,))
        return dict(cur.fetchall())


def analyze(state: State) -> dict:
    """对每套房调公式 + 估值模型。纯确定性计算,没有 LLM 参与。

    这一步产出的每个数字只有三种来源,没有第四种:
      A. 直接来自数据库某一列(price、annual_rent……)
      B. formulas.py 里的一个公式算出来的
      C. valuation.py 里的模型预测的(带分房型的 80% 保形区间,覆盖率经留出集验证)
    其中 B 类里,NOI / Cap Rate / ROI 依赖假设,所以每一条都随身带着
    `assumptions` 字段 —— 数字走到哪,它依赖的假设就跟到哪。
    """
    snap = state.get("assumption_snap")
    if snap:       # 走过 search:用本次请求的那一份快照(与 ROI 预排序一致),不再读进程级假设
        opex_rate, other_costs, assumption_snapshot = snap["opex_rate"], snap["other_costs"], snap["display"]
    else:          # 没经过 search(如按编号取详情):读当前进程级假设
        opex_rate = assumptions.opex_rate()
        other_costs = assumptions.other_acquisition_costs()
        assumption_snapshot = assumptions.snapshot()

    # 估值一次算完一批。逐条调的话每套都要新建 DataFrame + 调一次模型,
    # 120 套要 2.7 秒;批量只要几十毫秒。
    valuations = predict_values([{
        "suburb": p.get("suburb"),
        # address 本身不是特征,但模型要从它派生 is_unit_address(见 valuation.py)
        "address": p.get("address"),
        "property_type": p.get("property_type"),
        "bedrooms": p.get("bedrooms"),
        "bathrooms": p.get("bathrooms"),
        "car_spaces": p.get("car_spaces"),
        "land_size": p.get("land_size"),
        "building_area": p.get("building_area"),
        "distance_cbd": p.get("distance_cbd"),
        "latitude": p.get("latitude"),
        "longitude": p.get("longitude"),
        # 售价不是特征,模型不看它;只用来查这套库内房源的离折估值(见 crossfit_valuation.py)。
        # 不带它,库内 80% 的房源会拿到训练集里的拟合值 —— 异常成交价会被模型原样背书。
        "price": p.get("price"),
    } for p in state["properties"]])

    # 年租金的匹配粒度(片区 / 大区 / 不分房型)。它决定这个数能说到多具体,所以必须随数字一起走。
    # 单独查一次而不是改检索 SQL:检索的返回字段是跨线契约(见 search.py 顶部说明)。
    rent_sources = _rent_sources([p.get("id") for p in state["properties"]])

    metrics = []
    for prop, valuation in zip(state["properties"], valuations):
        price = prop.get("price")
        annual_rent = prop.get("annual_rent")

        # 运营支出、NOI、Cap Rate、ROI、印花税、总投入 —— 一次算齐。
        #
        # ROI 的口径:第一年、不含贷款的现金回报 = NOI ÷ 总投入。分母用总投入
        # 而不是房价,否则它就和 Cap Rate 是同一个数,报两个指标等于把同一件事
        # 说两遍。总投入 = 房价 + 印花税(法定,精确算)+ 其他购置开销(假设)。
        # 印花税是**分档累进**的 —— 24 万的房子实际税率 3.9%,96 万的才到 5.5%。
        # 用固定比例会高估便宜房的成本、低估它们的 ROI,而系统主推的高回报房
        # 恰恰都是便宜房,偏差正好打在最关键的地方。
        #
        # 详情窗里就地改假设时,前端调 /api/recalc 走的**也是这个函数** ——
        # 前端自己用 JS 再算一遍的话,两边哪天不一致,页面上的数字会安静地错。
        inv = investment_metrics(price, annual_rent, opex_rate, other_costs)

        predicted = valuation["predicted_price"]
        lo, hi = valuation.get("interval_low"), valuation.get("interval_high")
        # 售价相对模型区间的位置。below = 售价低于区间下限(模型认为明显偏便宜);
        # within = 在区间内,**不许**说成低估或高估;above = 高于上限。
        position = None
        if price and lo is not None and hi is not None:
            position = "below" if price < lo else "above" if price > hi else "within"

        metrics.append({
            # --- A. 直接取自数据库的列 ---
            "id": prop.get("id"),
            "suburb": prop.get("suburb"),
            "address": prop.get("address"),
            "property_type": prop.get("property_type"),
            "price": price,
            "bedrooms": prop.get("bedrooms"),
            "bathrooms": prop.get("bathrooms"),
            "car_spaces": prop.get("car_spaces"),
            # 按坐标算的直线距离,不是数据集的 Distance 列(那一列有 106 个区写错,见 nearby.distance_to_cbd_km)。
            # 估值模型的输入仍是原列,在上面 predict_values 那里。
            "distance_cbd": nearby.distance_to_cbd_km(prop.get("latitude"), prop.get("longitude"),
                                                      prop.get("distance_cbd")),
            "annual_rent": annual_rent,
            # 年租金**不是这套房自己的租金**,是 DFFH 公布的片区中位租金(按房型、卧室数、成交季度匹配)。
            # 值:precinct_exact_sheet / precinct_all_properties / region_exact_sheet / region_all_properties
            "rent_source": rent_sources.get(prop.get("id")),
            # 经纬度不展示给用户,但 enrich 节点要用它算周边设施距离
            "latitude": prop.get("latitude"),
            "longitude": prop.get("longitude"),
            # 面积也不直接展示,但「宽敞」这个属性要用它。少带一个字段,
            # 下游算出来的属性就会安静地缺一项 —— 不报错,只是少了。
            "land_size": prop.get("land_size"),
            "building_area": prop.get("building_area"),
            # --- B. formulas.py 算出来的 ---
            "gross_yield": inv["gross_yield"],                       # 只用真实数据
            "operating_expenses": inv["operating_expenses"],         # 基于假设
            "noi": inv["noi"],                                       # 基于假设
            "cap_rate": inv["cap_rate"],                             # 基于假设
            "roi": inv["roi"],                                       # 部分基于假设
            "stamp_duty": inv["stamp_duty"],                         # 法定,有出处
            "total_cost": inv["total_cost"],                         # 房价+印花税+假设开销
            "assumptions": assumption_snapshot,
            # --- C. valuation.py 的模型预测 ---
            "predicted_price": predicted,
            "valuation_is_stub": valuation["is_stub"],
            # True = 这个估值来自没见过这套房的那一折模型;False = 定稿模型(库外输入或数据被改过)
            "valuation_cross_fitted": valuation.get("cross_fitted"),
            "valuation_error_pct": valuation.get("typical_error_pct"),
            "valuation_range": [valuation.get("range_low"), valuation.get("range_high")],
            "valuation_interval": [lo, hi],
            "valuation_interval_level": valuation.get("interval_level"),
            "valuation_interval_coverage": valuation.get("interval_coverage"),
            "valuation_position": position,
            # 估值高于售价多少(小数)。⚠️ 模型典型误差约 9%,所以只有明显超过
            # 这个量级的差距才有讨论价值,不能拿 2% 的差就说"被低估"。
            "predicted_gap": (predicted - price) / price if price and predicted else None,
        })
    return {"metrics": metrics}


# ---------------------------------------------------------------- 节点 4:enrich

# 每次都会显示的设施(不管用户问没问)。挑这四类是因为它们对"住得方不方便"
# 影响最直接,而且 OSM 上覆盖度好。其余五类只在用户点名要求时才算。
DEFAULT_AMENITY_KINDS = ("train_station", "primary_school", "hospital", "bank")


def enrich(state: State) -> dict:
    """给每套候选房算周边设施距离。纯几何计算,没有 LLM 参与。

    放在 rank 之前,因为 rank 要用这些距离来筛("离火车站 800 米内的")。
    放在 analyze 之后,因为它只需要 metrics 里的经纬度,不需要重新取数。

    只算需要的类别:用户点名要求的 + 四个默认展示项。九类全算也不慢,
    但没必要往 LLM 的提示词里塞一堆用户没问的东西。
    """
    params = state.get("params") or {}
    needs = params.get("amenity_needs") or []
    want_context_kinds = (bool(params.get("abstract_needs")) or bool(params.get("relative_preferences"))
                          or params.get("sort_by") in _ABSTRACT_KEYS)
    kinds = tuple(dict.fromkeys(
        [n["kind"] for n in needs]
        + list(DEFAULT_AMENITY_KINDS)
        # 抽象属性(教育配套、医疗方便、通勤)要用到这几类的距离
        + (["secondary_school", "kindergarten"] if want_context_kinds else [])
    ))

    # 具名地点先解析一次,所有房源共用。解析不到就记下来,后面如实交代。
    place = params.get("near_place")
    place_points, place_error = [], None
    if place:
        place_points = nearby.find_place(place["name"], place.get("kind"))
        if not place_points:
            # 找不到就说找不到,**不退而求其次给个别的地方** —— 这和检索层
            # "没搜到就说没搜到"是同一条规矩。
            place_error = f"设施库里找不到「{place['name']}」"

    # 抽象属性(安静/热闹/便利/近公园)要不要算。它比设施距离贵一些
    # (主干道有 69,174 个采样点),所以只在用户真的提了、或要按它排序时才算。
    want_context = (bool(params.get("abstract_needs")) or bool(params.get("relative_preferences"))
                    or params.get("sort_by") in _ABSTRACT_KEYS)

    rows = state["metrics"]
    # 批量算环境证据。候选池放大到几千套之后,逐套算会慢一个数量级 ——
    # 这一步是"全量排序"跑得动的前提。
    evidences = context.collect_evidence_batch(rows) if want_context else [{}] * len(rows)

    lats = [m.get("latitude") for m in rows]
    lons = [m.get("longitude") for m in rows]
    # 这里只算**筛选**真正需要的那几类设施。展示用的(最近的火车站叫什么、
    # 多远)挪到 present 节点,只对最终留下的 5 套算 —— 给 4,375 套都算一遍
    # 展示数据,其中 4,370 套的结果转手就被丢掉了。
    filter_kinds = tuple(dict.fromkeys(n["kind"] for n in needs))
    amenity_rows = (nearby.nearest_by_kind_batch(lats, lons, filter_kinds)
                    if filter_kinds else [{} for _ in rows])

    # 学区归属。只在用户点名了学校时才在这里算全量 —— 否则留到 present,
    # 只对最终 5 套算。725 个多边形 × 几千套房虽然只要几毫秒,但没必要。
    zone_req = params.get("school_zone")
    zone_hits, zone_error = [], None
    in_zone = [True] * len(rows)
    if zone_req:
        zone_hits = zones.find_zone(zone_req["school"], zone_req.get("level"))
        if zone_hits:
            in_zone = zones.in_zone_batch(lats, lons, zone_hits)
        else:
            # 找不到这所学校就如实记下来,**不退而求其次找个名字相近的** ——
            # 那和"要机场给小学"是同一类错误。
            zone_error = f"学区数据里找不到「{zone_req['school']}」(只覆盖公立学校)"

    # 规划分区。和学区一样,只在用户真的提了要求时才对全部候选算 ——
    # 否则留到 present,只对最终 5 套算。12 万个多边形虽然有空间索引,
    # 但给 5,000 套候选各算一遍周边分区构成要 1.7 秒,没必要白花。
    planning_rows = (planning.for_batch(lats, lons)
                     if params.get("planning_needs") else [{}] * len(rows))

    metrics = []
    for m, ev, am in zip(rows, evidences, amenity_rows):
        lat, lon = m.get("latitude"), m.get("longitude")
        entry = dict(m)
        entry["amenities"] = am
        entry["near_place"] = (
            nearby.distance_to_place(lat, lon, place_points) if place_points else None
        )
        if want_context and ev:
            # 证据和分数一起存。分数只是加权汇总,**证据才是能指认来源的东西**,
            # 输出时两个都要给 —— 用户不认同这套权重,可以直接看证据自己判断。
            entry["context_evidence"] = ev
            entry["context_scores"] = context.scores(
                ev, entry.get("property_type"), entry.get("bedrooms"))
            # 每个分项各自多强。总分是加权平均,差的那一项会被拉平 ——
            # 有了它,界面才能指出"是这一项把分数拖下来的"。
            entry["context_parts"] = context.part_strength(
                ev, entry.get("property_type"), entry.get("bedrooms"))
            # 分数在全库的排位。界面上「安静 92」这个数,读者没有参照物就读不出
            # 好到什么程度;「全库前 3%」不用解释。算在这里而不是前端,是为了让
            # 分数和它的排位始终出自同一张表 —— 两边各算一遍,迟早会对不上。
            entry["context_ranks"] = {
                a: r for a, v in entry["context_scores"].items()
                if (r := context.score_rank(a, v)) is not None}
        metrics.append(entry)

    for entry, inside, plan in zip(metrics, in_zone, planning_rows):
        entry["in_requested_zone"] = bool(inside)
        if plan:
            entry["planning"] = plan

    return {"metrics": metrics,
            "place_lookup": {"query": place, "found": len(place_points),
                             "error": place_error} if place else None,
            "zone_lookup": {"query": zone_req, "found": len(zone_hits),
                            "error": zone_error} if zone_req else None}


# ---------------------------------------------------------------- 节点 5:rank

_SORT_LABEL = {
    "gross_yield": "毛租金回报率从高到低",
    "cap_rate": "资本化率从高到低",
    "roi": "投资回报率从高到低",
    "predicted_gap": "估值高于售价的幅度从大到小",
    # 反向。以前没有这个口径:用户说"估值低于售价的",系统照样按上面那条排,
    # 静默给出**相反**的结果。宁可多一个口径,也不能让说出口的话和拿到的结果对不上。
    "predicted_gap_neg": "估值低于售价的幅度从大到小",
    "price_asc": "价格从低到高",
    "price_desc": "价格从高到低",
    "near_place_distance": "离指定地点从近到远",
    **registry.sort_labels(),
    **{NEAREST_PREFIX + k: f"距{v}从近到远" for k, v in nearby.KIND_ZH.items()},
}


def _score_shift(state, goals, needs, previous_rows, shown):
    """「安静 中位 29→40(+11);热闹 中位 100→96」:相对调整的属性及其反向属性怎么变的。"""
    fields = [g["field"] for g in goals if g["field"] in _ABSTRACT_KEYS]
    held = {n["attribute"] for n in needs or []}
    fields += [refinement.OPPOSITE[f] for f in fields if refinement.OPPOSITE.get(f) in held]
    parts = []
    for field in dict.fromkeys(fields):
        before = refinement.baseline_for(previous_rows, field)
        after = refinement.baseline_for(shown, field)
        if before is None or after is None:
            continue
        diff = round(after - before)
        parts.append(f"「{_attr_label(state, field)}」" + _t(state, "中位 ", " median ")
                     + f"{before:.0f}→{after:.0f}({diff:+d})")
    if not parts:
        return None
    # 排序说明整体用 ";" 分条,这里不能再用 ";",否则一行会被拆成两条
    return _t(state, "评分变化(系统相对评分):", "Score change (system relative scores): ") + _t(state, ",", ", ").join(parts)


def _tradeoff_hint(state, params, goals):
    """相对调整走不下去时,说明卡在哪一个反向门槛上,以及它能不能自动让。"""
    moving = {refinement.OPPOSITE.get(g["field"]) for g in goals}
    for need in params.get("abstract_needs") or []:
        if need["attribute"] not in moving:
            continue
        label, floor = _attr_label(state, need["attribute"]), need["min_score"]
        if need.get("value_source") == "explicit" or need.get("strength") == "required":
            return _t(state,
                f"「{label}」≥{floor} 是你明确要求的,系统不会自动降低。如果愿意放宽,请在条件卡里修改或直接告诉我。",
                f"“{label}” ≥{floor} is your explicit requirement, so it will not be lowered automatically. "
                f"Edit it on the filter card or tell me if you want to relax it.")
        if floor > refinement.AUTO_FLOOR:
            return None                                # 还能自动让,不需要打扰用户
        return _t(state,
            f"再往下调需要把「{label}」门槛降到 {refinement.AUTO_FLOOR} 以下,那样就称不上{label}了,需要你确认。"
            f"也可以在条件卡里直接修改分数。",
            f"Going further would take the “{label}” threshold below {refinement.AUTO_FLOOR}, which no longer "
            f"counts as {label.lower()}. Please confirm, or edit the score on the filter card.")
    return None


def _unmatched_refinement(state, notes, relative=False, hint=None):
    message = _t(state,
        "本次检索范围内,没有找到满足现有条件且能适度向该方向调整的房源。" if relative else
        "本次检索范围内,没有找到同时满足这些条件的房源。",
        "No candidates in this search can make a moderate adjustment while meeting your filters." if relative else
        "No candidates in this search meet all these requirements together.")
    if hint:
        message += hint
    base = state.get("refinement_base")
    if base and base.get("metrics"):
        message += _t(state, "已保留上一轮条件和房源。请明确希望放宽哪项要求,或保留当前结果。",
                      " Your previous filters and results are unchanged. Specify a requirement to relax, or keep the current results.")
        return {**base, "turn_notice": message, "refinement_base": None}
    return {"metrics": [], "more": [], "batch_offset": 0,
            "ranking": ";".join([message] + notes), "turn_notice": None, "refinement_base": None}


def _rank_once(state: State) -> dict:
    """按用户要的指标筛选 + 排序,再截到 RESULT_LIMIT 套。没有 LLM 参与。(一次;ROI 候选池扩容见下面的 rank)

    为什么单独一个节点、不塞进 analyze:取数、算数、挑选是三件事。
    分开之后,「换个排序口径」不需要碰计算逻辑,「改公式」不需要碰挑选逻辑。
    第一版只有四个节点是因为当时不需要挑选 —— 现在需要了,就加一个。
    """
    metrics = state["metrics"]
    params = state.get("params") or {}
    sort_by = params.get("sort_by")
    floor = params.get("min_gross_yield")
    notes = []
    roi_unproven = False       # ROI 候选池被截断、且前几名没能证明不会被池外超过 -> 交给 rank 扩大候选池再来一次
    roi_pool_cut = state.get("search_order") == "roi" and bool(state.get("roi_pool"))   # ROI 候选池真的被截断(池外还有房源)

    def _expansion_futile() -> bool:
        """筛选条件本身不可能满足(学区没解析出来、指定地点没找到)时,扩大候选池没有意义,不扩。"""
        zone_req = params.get("school_zone")
        if zone_req and not (state.get("zone_lookup") or {}).get("found"):
            return True
        place = params.get("near_place")
        if place and place.get("max_distance_m"):
            lookup = state.get("place_lookup") or {}
            if lookup.get("error") or not lookup.get("found"):
                return True
        return False

    def _no_match(*args, **kwargs):
        """后置筛选(收益门槛/设施/学区/规划/指定地点/相对目标)把候选池筛空了。池被截断时,空不等于「没有」:
        让 rank 把候选池翻倍重试(roi_unproven 之前就提前返回,是 R07B-01 的根因);条件本身不可能满足就不扩。
        扩到上限仍为空,说明里如实写明候选只是 ROI 预排序的前 N 套。"""
        retry = roi_pool_cut and not _expansion_futile()
        if retry:
            cap_note = _t(state, f"候选池是按投资回报率预排序的前 {len(state['metrics'])} 套(已达扩容上限),池外可能还有符合条件的房源",
                          f"The candidate pool is the top {len(state['metrics'])} properties pre-sorted by ROI (expansion cap reached); "
                          f"properties outside it may still match")
            args[1].append(cap_note)
        out = _unmatched_refinement(*args, **kwargs)
        if retry and out.get("turn_notice"):
            out["turn_notice"] += " " + cap_note   # 恢复旧结果时 ranking 属于旧轮;本轮的候选上限通过确定性 notice 交代。
        return {**out, "_roi_unproven": True} if retry else out

    # 地名被改过就必须说。静默纠错的危险不在纠错本身,而在于纠错纠偏了也没人知道 ——
    # 用户看着一屏"Richmond 的房子",却以为自己搜的是别的地方。
    typed = params.get("suburb_typed_as")
    if typed and params.get("suburb"):
        notes.append(_t(state,
            f"你输入的是「{typed}」,已按「{params['suburb']}」搜索 —— 如果不是这个区,请改一下",
            f"You typed “{typed}”; searched “{params['suburb']}” instead — change it if that is not the suburb you meant"))

    # 先把"你提的这几项我没有数据"讲清楚,再谈筛出了什么 —— 顺序很重要:
    # 用户得先知道哪些要求根本没被考虑,才不会误以为结果满足了全部条件。
    if params.get("unsupported_asks"):
        notes.append(_t(state, "以下要求本系统没有相应数据,未纳入筛选:",
                        "No data for these, so they were not used as filters: ")
                     + _unsupported_list(state, params["unsupported_asks"]))

    # 按回报率挑房之前,先剔掉**售价远低于模型估值**的成交。
    #
    # 起因(审计 BUG-02):「80 万以内回报率最高」第一名是 Footscray 一套卖 $85,000 的公寓(15.9%),
    # 全库真正的第一是 Caulfield 一栋 4 房独栋卖 $131,000(32%),同区其他独栋都在百万以上。
    # 回报率 = 片区中位租金 ÷ 售价,售价一异常回报率就跟着异常,而按回报率排序取的正是最极端的那头。
    # 判据和下面估值差排序同一把尺子:售价比估值低出该房型典型误差 3 倍以上的,多半是数据异常。
    # 只剔「低得离谱」的一侧 —— 售价偏高只会让回报率变低,不会被顶到前面。
    if sort_by in ("gross_yield", "cap_rate", "roi") or floor is not None:
        def _price_suspect(m):
            gap = m.get("predicted_gap")
            return gap is not None and gap > 3 * (m.get("valuation_error_pct") or 0.10)
        suspect = sum(1 for m in metrics if _price_suspect(m))
        if suspect and suspect < len(metrics):
            metrics = [m for m in metrics if not _price_suspect(m)]
            notes.append(_t(state,
                f"已剔除 {suspect} 套售价远低于模型估值的(低出该房型典型误差 3 倍以上,多半是数据异常,"
                f"回报率会被虚高)",
                f"Dropped {suspect} properties priced far below the model estimate (over 3× the typical error "
                f"for the type — usually bad data, which would inflate the yield)"))
        elif suspect:
            # 全部候选都「售价远低于估值」:没有可剔除的对照,但回报率同样可能虚高 —— 不能不吭声
            notes.append(_t(state,
                f"注意:候选全部售价远低于模型估值(低出该房型典型误差 3 倍以上),未剔除,回报率可能虚高",
                f"Note: every candidate is priced far below the model estimate (over 3× the typical error for the "
                f"type); none were dropped, so the yields may be inflated"))

    if floor is not None:
        kept = [m for m in metrics if m.get("gross_yield") is not None and m["gross_yield"] >= floor]
        if kept:
            metrics = kept
            notes.append(_t(state, f"已筛掉毛租金回报率低于 {floor * 100:.1f}% 的",
                            f"Filtered out gross yields below {floor * 100:.1f}%"))
        else:
            metrics = []
            notes.append(_t(state, f"没有候选达到毛回报率 {floor * 100:.1f}% 的要求",
                            f"No candidate meets the gross yield requirement of {floor * 100:.1f}%"))

    # 所有已生效的条件一起求交集。没有交集就是没有兼容结果,
    # 不能按列表先后顺序放弃后面的条件。
    def keep(predicate, zh, en):
        nonlocal metrics
        metrics = [m for m in metrics if predicate(m)]
        notes.append(_t(state, zh, en))

    for need in params.get("amenity_needs") or []:
        kind, limit = need["kind"], need["max_distance_m"]
        label = _kind_label(state, kind)
        keep(lambda m: (m.get("amenities") or {}).get(kind, {}).get("distance_m") is not None
             and m["amenities"][kind]["distance_m"] <= limit,
             f"要求距{label} {limit} 米内", f"Required: nearest {label.lower()} within {limit} m")

    goals = params.get("relative_preferences") or []
    # 相对调整一项(如「再安静一点」)时,反向属性(热闹)的系统推断门槛可以小步让出。
    # 候选先按让出后的门槛取,排序时优先原门槛内的房子,凑不够才真正让出并告知用户。
    relax = refinement.relaxable_need(params.get("abstract_needs"), goals) if goals else None

    def meets(m, need, floor):
        _, compare = _SCORE_OPERATORS.get(need.get("operator", "gte"), _SCORE_OPERATORS["gte"])
        value = (m.get("context_scores") or {}).get(need["attribute"])
        return value is not None and compare(value, floor)

    for need in params.get("abstract_needs") or []:
        attr, floor = need["attribute"], need["min_score"]
        symbol, compare = _SCORE_OPERATORS.get(need.get("operator", "gte"), _SCORE_OPERATORS["gte"])
        label = _attr_label(state, attr)
        if need is relax:
            loose = refinement.relaxed_floor(need)
            metrics = [m for m in metrics if meets(m, need, loose)]
            continue                                   # 说明文字在确定是否让步之后再写
        keep(lambda m: (m.get("context_scores") or {}).get(attr) is not None
             and compare(m["context_scores"][attr], floor),
             f"已筛出「{label}」评分 {symbol} {floor} 的",
             f"Kept only “{label}” scores {symbol} {floor}")

    zone_req = params.get("school_zone")
    if zone_req:
        found = (state.get("zone_lookup") or {}).get("found")
        keep(lambda m: bool(found) and bool(m.get("in_requested_zone")),
             f"要求在「{zone_req['school']}」学区内",
             f"Required: inside the school zone of {zone_req['school']}")
        if not found:
            notes.append(_t(state, "未能解析指定学区,没有将它替换成其他学区",
                            "The requested school zone could not be resolved; no substitute was used"))

    for need in params.get("planning_needs") or []:
        label, predicate = _PLANNING_NEEDS[need]
        keep(lambda m: predicate(m.get("planning") or {}), f"要求{label}",
             f"Required: {i18n.PLANNING_NEEDS_EN.get(need, label)}")

    place = params.get("near_place")
    if place and place.get("max_distance_m"):
        limit = place["max_distance_m"]
        keep(lambda m: (m.get("near_place") or {}).get("distance_m") is not None
             and m["near_place"]["distance_m"] <= limit,
             f"要求距「{place['name']}」在 {limit} 米内",
             f"Required: within {limit} m of {place['name']}")

    if not metrics:
        return _no_match(state, notes)

    if goals:
        base = state.get("refinement_base") or {}
        previous_rows = base.get("metrics") or []
        needs = params.get("abstract_needs")
        new_params, adjust = None, []           # adjust:这次调整付出的代价,排在说明最前面
        if relax:
            label, floor = _attr_label(state, relax["attribute"]), relax["min_score"]
            loose = refinement.relaxed_floor(relax)
            strict = [m for m in metrics if meets(m, relax, floor)]
            ranked = refinement.relative_rank(strict, goals, previous_rows, needs)
            if len(ranked) < RESULT_LIMIT:
                wide = refinement.relative_rank(metrics, goals, previous_rows, needs)
                if len(wide) > len(ranked):
                    ranked, floor = wide, loose
                    new_params = deepcopy(params)
                    for need in new_params["abstract_needs"]:
                        if need["attribute"] == relax["attribute"]:
                            need["min_score"] = loose
                    adjust.append(_t(state,
                        f"为了继续调整,「{label}」门槛已从 ≥{relax['min_score']} 放宽到 ≥{loose}。"
                        f"这个门槛是系统根据你的描述推断的,不是你设定的分数。「{label}」要求仍然保留。",
                        f"To keep adjusting, the “{label}” threshold was relaxed from ≥{relax['min_score']} to ≥{loose}. "
                        f"That threshold was inferred from your wording, not a score you set. The “{label}” requirement is kept."))
            notes.append(_t(state, f"已筛出「{label}」评分 ≥ {floor} 的", f"Kept only “{label}” scores ≥ {floor}"))
        else:
            ranked = refinement.relative_rank(metrics, goals, previous_rows, needs)
        metrics = ranked
        if not metrics:
            return _no_match(state, notes, relative=True, hint=_tradeoff_hint(state, params, goals))
        labels = [_attr_label(state, g["field"]) if g["field"] in _ABSTRACT_KEYS
                  else ({"price": "价格", "near_place_distance": "到指定地点的距离"}.get(g["field"], g["field"])
                        if not _en(state) else g["field"].replace("_", " ")) for g in goals]
        notes.append(_t(state, "保留原条件,相对上一轮适度调整:" + "、".join(labels),
                        "Original filters retained; adjusted relative to the previous results: " + ", ".join(labels)))
        shift = _score_shift(state, goals, needs, previous_rows, metrics[:RESULT_LIMIT])
        if shift:
            notes.append(shift)
        notes.append(_t(state, "调整幅度由候选分布计算,不是用户指定的分数门槛",
                        "The adjustment uses the candidate distribution, not a user-specified score threshold"))
        if state.get("search_order") == "roi":
            # 候选实际来自 ROI 预排序,不是语义相关度;相对目标是在这批候选里重排的,不给「已验证」之类的保证
            if roi_pool_cut:
                notes.append(_t(state, f"比较范围为按投资回报率预排序的前 {len(state['metrics'])} 套候选,并非全库,符合条件的可能更多",
                                f"Compared within the top {len(state['metrics'])} candidates pre-sorted by ROI, not the whole dataset; more may match"))
            else:
                notes.append(_t(state, f"比较范围为符合条件的全部 {len(state['metrics'])} 套",
                                f"Compared within all {len(state['metrics'])} matching properties"))
        elif len(state["metrics"]) >= CANDIDATE_LIMIT:
            notes.append(_t(state, f"比较范围为语义相关的 {CANDIDATE_LIMIT} 套候选,并非全库",
                            f"Compared within {CANDIDATE_LIMIT} semantically relevant candidates, not the whole dataset"))
        if len(metrics) < RESULT_LIMIT:
            # 不悄悄缩成一两套:说清楚只剩几套、再往下调要付出什么。
            sparse = _t(state, f"只有 {len(metrics)} 套能在保留现有条件的同时完成这次调整。",
                        f"Only {len(metrics)} listing(s) can make this adjustment while keeping your filters.")
            adjust += [sparse] + [x for x in [_tradeoff_hint(state, new_params or params, goals)] if x]
        out = {"metrics": metrics[:RESULT_LIMIT], "more": metrics[:RESULT_LIMIT * 4],
               "batch_offset": 0, "ranking": ";".join(adjust + notes), "turn_notice": None,
               "refinement_base": None}
        if new_params:
            out["params"] = new_params
        return out

    # 按估值差排序之前,先把**模型没有分辨力的那一段**剔掉。
    #
    # 起因:"找被低估的房子"返回的前几名是 Coburg 一栋 164㎡ 独栋卖 $145,000
    # (估值差 +399%)、Caulfield 155㎡ 独栋卖 $131,000(+173%)—— 这些不是捡漏,
    # 是脏数据或房型标错。实测全库 |估值差| 中位数只有 8.6%,和模型 9.1% 的
    # 典型误差吻合;但排序取的正是分布最远的那一端,于是模型失效的样本全被顶上来。
    #
    # 判据用模型自己的误差:超过该房型典型误差 **3 倍**的,模型分不出
    # "真便宜"和"我算错了"。系统里已有同源规则(|差|<10% 不许说低估高估),
    # 这条只是把同一把尺子用在排序上。实测滤掉约 3.8%,正好是顶部那批。
    if sort_by in ("predicted_gap", "predicted_gap_neg"):
        def _plausible(m):
            gap = m.get("predicted_gap")
            if gap is None:
                return False
            err = m.get("valuation_error_pct") or 0.10
            return abs(gap) <= 3 * err
        kept = [m for m in metrics if _plausible(m)]
        dropped = len(metrics) - len(kept)
        if kept:
            metrics = kept
            # 排在前面不等于真便宜:只有售价落到模型 80% 区间之外的,差距才超出了模型自身的不确定性。
            # 把这个数说出来,用户才知道"前 5 名"里有几套是真信号、几套只是区间内的正常波动。
            side = "below" if sort_by == "predicted_gap" else "above"
            outside = sum(1 for m in kept if m.get("valuation_position") == side)
            level = next((m.get("valuation_interval_level") for m in kept if m.get("valuation_interval_level")), None)
            if dropped:
                notes.append(_t(state,
                    f"已剔除 {dropped} 套估值差超出模型分辨力的"
                    f"(超过该房型典型误差 3 倍,多半是数据异常而非捡漏)",
                    f"Dropped {dropped} properties whose valuation gap exceeds what the model can "
                    f"resolve (over 3× the typical error for the type — usually bad data, not a bargain)"))
            if level:
                # 一句话说完,不用分号:前端按分号把备注拆成多行
                below = side == "below"
                notes.append(_t(state,
                    f"{'剔除后剩下的' if dropped else '符合条件的'} {len(kept)} 套里,只有 {outside} 套售价{'低于' if below else '高于'}模型 "
                    f"{level:.0%} 把握区间{'下限' if below else '上限'},其余差距都在区间内,"
                    f"属于正常波动,不能算{'便宜' if below else '贵'}",
                    f"Of the {'remaining' if dropped else 'matching'} {len(kept)}, only {outside} are priced {'below' if below else 'above'} the "
                    f"model's {level:.0%} interval — the rest are within it, which is normal variation, "
                    f"not a real {'bargain' if below else 'premium'}"))
        else:
            notes.append(_t(state,
                "注意:候选里每一套的估值差都超出模型分辨力,排序结果不可当作捡漏依据",
                "Note: every candidate's valuation gap is beyond what the model can resolve — "
                "this ranking is not evidence of a bargain"))

    if sort_by:
        # 价格 ≤ 0 是「价格不可用」(和 formulas.stamp_duty_vic 同一口径),不是「最便宜」:不参与价格排序
        if sort_by == "price_asc":
            key, reverse = (lambda m: m.get("price") if (m.get("price") or 0) > 0 else None), False
        elif sort_by == "price_desc":
            key, reverse = (lambda m: m.get("price") if (m.get("price") or 0) > 0 else None), True
        elif sort_by == "predicted_gap_neg":
            # 估值低于售价的幅度从大到小 = predicted_gap 越负越靠前
            key, reverse = (lambda m: m.get("predicted_gap")), False
        elif sort_by in _ABSTRACT_KEYS:
            key, reverse = (lambda m: (m.get("context_scores") or {}).get(sort_by)), True
        elif sort_by == "near_place_distance":
            # 离指定地点越近越好,所以是升序 —— 和其他"越大越好"的指标相反
            key, reverse = (lambda m: (m.get("near_place") or {}).get("distance_m")), False
        elif sort_by.startswith(NEAREST_PREFIX):
            # 到某类设施的最近距离,升序。enrich 已对全部候选算过这一类(它在 amenity_needs 里)
            kind = sort_by[len(NEAREST_PREFIX):]
            key, reverse = (lambda m: ((m.get("amenities") or {}).get(kind) or {}).get("distance_m")), False
        else:
            key, reverse = (lambda m: m.get(sort_by)), True
        usable = [m for m in metrics if key(m) is not None]
        if usable:
            metrics = sorted(usable, key=key, reverse=reverse)
            pool = len(state["metrics"])
            # 口径要说准:候选池没被上限截断时,这就是**全部**符合硬条件的房源,
            # 排序结果是真的"最";被截断了就得说清楚只是前 N 套里的最 ——
            # 除非检索层本来就是按这个口径取的候选,那截下来的就是全库最靠前的那批。
            sql_ordered = state.get("search_order") and _SQL_ORDER.get(sort_by) == state.get("search_order")
            roi_complete = sort_by == "roi" and sql_ordered and not state.get("roi_pool")      # ROI 池没被截断(含扩容到取完)
            if pool < CANDIDATE_LIMIT or roi_complete:
                scope = _t(state, f"在符合条件的全部 {pool} 套里挑", f"chosen from all {pool} matching properties")
            elif sort_by == "roi" and sql_ordered:
                # 候选池按不取整 ROI 预排序,最终按 Python 取整后的 ROI 排。只有「证明得了」的前几名才说精确,
                # 其余如实披露;绝不说全库(roi_certified_prefix 的证明只覆盖池外房源不可能超过这几名)。
                roi_pool = state.get("roi_pool") or {}
                # 证明的前提:这批指标的 ROI 必须是用预排序同一份假设算的(R07B-02)。用 roi_pool 里的假设重算前 20 名核对;
                # 不一致(进程级假设中途被改、或有路径没用请求快照)就撤回「已验证」,也不扩容(扩容改变不了假设)。
                head = metrics[:RESULT_LIMIT * 4]
                consistent = (roi_pool.get("opex_rate") is not None and roi_pool.get("other_costs") is not None and
                              all(investment_metrics(m.get("price"), m.get("annual_rent"), roi_pool["opex_rate"], roi_pool["other_costs"])["roi"] == m.get("roi")
                                  for m in head))
                proven = (roi_certified_prefix([m.get("roi") for m in metrics], roi_pool.get("cutoff"), roi_pool.get("other_costs"))
                          if consistent else 0)
                shown = min(proven, RESULT_LIMIT * 4)
                roi_unproven = consistent and shown < RESULT_LIMIT * 4          # 要证明的是「换一批」能翻到的前 20 名,不只是展示的 5 套
                if not consistent:
                    scope = _t(state, f"在按投资回报率预排序的前 {pool} 套候选里挑;预排序与计算所用的假设不一致,未做验证,符合条件的可能更多",
                               f"chosen from the top {pool} candidates pre-sorted by ROI; the assumptions used for the pre-sort and for the "
                               f"calculation differ, so nothing is verified and more may match")
                elif shown >= RESULT_LIMIT:
                    scope = _t(state, f"在按投资回报率预排序的前 {pool} 套候选里挑;已验证前 {shown} 名不会被候选池外的房源超过",
                               f"chosen from the top {pool} candidates pre-sorted by ROI; the top {shown} are verified "
                               f"not to be beatable by any property outside the pool")
                else:
                    scope = _t(state, f"在按投资回报率预排序的前 {pool} 套候选里挑;未能验证候选池外没有更高者,符合条件的可能更多",
                               f"chosen from the top {pool} candidates pre-sorted by ROI; it could not be verified that nothing "
                               f"outside the pool ranks higher, so more may match")
            elif sql_ordered:
                scope = _t(state, "在全库符合条件的房源里挑", "chosen from every matching property")
            else:
                scope = _t(state, f"在语义最相关的 {pool} 套候选里挑,符合条件的可能更多",
                           f"chosen from the {pool} most semantically relevant candidates; more may match")
            label = _sort_label(state, sort_by)
            notes.append(_t(state, f"按{label}排序({scope})",
                            f"Sorted by: {label} ({scope})"))
        else:
            label = _sort_label(state, sort_by)
            notes.append(_t(state,
                f"注意:候选里没有一套能算出{label},已按相关度排序",
                f"Note: “{label}” could not be computed for any candidate; sorted by relevance instead"))
    else:
        notes.append(_t(state, "按语义相关度排序", "Sorted by semantic relevance"))

    # more:前 20 套(含展示的这 5 套),给"换一批"翻页用。它们已经算好了,不留白不留。
    # 只留 4 批是因为每套 metric 带着设施、规划、学区、各属性评分,体积不小;
    # 而用户翻过四批还没看中的话,更该改条件而不是继续翻。
    return {"metrics": metrics[:RESULT_LIMIT],
            "more": metrics[:RESULT_LIMIT * 4],
            "batch_offset": 0,
            "ranking": ";".join(notes), "turn_notice": None, "refinement_base": None,
            **({"_roi_unproven": True} if roi_unproven else {})}


# ROI 候选池扩容上限(套)。到这个数还没证明就停下,如实披露(见 _rank_once),不无限扩下去。
ROI_EXPAND_CAP = CANDIDATE_LIMIT * 8


def rank(state: State) -> dict:
    """排序节点。ROI 排序时,候选池只是「按不取整 ROI 预排序的前 N 套」:若前 20 名证明不了不会被池外房源超过,
    就在**同一组硬条件**下把候选池翻倍重取、重算(analyze/enrich,最终仍用 formulas.investment_metrics 的取整 ROI),
    再排一次;直到前 20 名都被证明、或候选池取完(此时就是全部符合条件的房源)、或到 ROI_EXPAND_CAP 为止。
    杂费 ≤ 0.5 时证明不了(roi_certified_prefix 返回 0),因此会一路扩到取完。
    循环放在这个节点**里面**而不是图上加回边:server 会把每个节点的输出当成一次结果推给前端,回边会让用户先看到一轮半成品。"""
    current = dict(state)
    out = _rank_once(current)
    extra, expanded = {}, False
    while out.pop("_roi_unproven", False):
        nxt = (current.get("roi_pool") or {}).get("limit", CANDIDATE_LIMIT) * 2
        if nxt > ROI_EXPAND_CAP:
            break                                    # 到上限:保留本轮结果,说明里已如实披露未验证
        current.update(search({**current, "roi_limit": nxt}))
        current.update(analyze(current))
        enriched = enrich(current)
        current.update(enriched)
        extra = {k: v for k, v in enriched.items() if k != "metrics"}
        expanded = True
        out = _rank_once(current)
    if expanded:     # 下游(present/explain)要看到的是最后一轮的候选池、检索口径和 roi_pool
        extra.update(properties=current["properties"], search_order=current["search_order"], roi_pool=current["roi_pool"])
    return {**extra, **out}


# ---------------------------------------------------------------- 节点 5:present


def present(state: State) -> dict:
    """给**最终留下的**那几套补上展示用的周边设施(名字 + 距离)。

    为什么单独一个节点:enrich 要对全部候选(可能几千套)算筛选和打分用的
    数据,那是必须的;但"最近的火车站叫什么名字"只有最后展示的 5 套用得上。
    对几千套算一遍再扔掉 99.9%,是纯粹的浪费 —— 实测这一拆省掉约 1.5 秒。

    取数、算数、挑选、展示,四件事四个节点。
    """
    if state.get("turn_notice"):
        return {"metrics": state.get("metrics") or []}
    metrics = state.get("metrics") or []
    if not metrics:
        return {}
    lats = [m.get("latitude") for m in metrics]
    lons = [m.get("longitude") for m in metrics]
    display = nearby.nearest_by_kind_batch(lats, lons, DEFAULT_AMENITY_KINDS)

    # 学区归属是**事实**,不是评分 —— 每套结果都报,像地址一样。
    zone_rows = zones.zone_for_batch(lats, lons)
    # 规划分区同理:它是法条,不是我们的判断。enrich 里如果已经算过
    # (用户提了规划要求),就用那份,不重算。
    planning_rows = planning.for_batch(lats, lons)

    out = []
    for m, extra, zone, plan in zip(metrics, display, zone_rows, planning_rows):
        entry = dict(m)
        # enrich 里为筛选算过的那几类优先保留,不要被覆盖成同样的值
        entry["amenities"] = {**extra, **(m.get("amenities") or {})}
        entry["school_zones"] = zone
        entry["planning"] = m.get("planning") or plan
        if entry["planning"]:
            # 人话摘要和数据一起走。LLM 直接读 {"nearby": {"high": 9}} 很容易
            # 读成"周边有 9 栋高楼",而它的真实含义是"9 块地法律上允许高密度开发"。
            # 这条摘要就是防这个的 —— 和罪案率的粒度说明是同一条规矩。
            entry["planning"]["summary"] = planning.describe(entry["planning"])
            entry["planning"]["caveat"] = (
                "分区是法律上的**允许**范围,不是对未来的预测;"
                "分区数据是当前的,成交价是 2016–2018 年的,两者不能因果相连")
        # 罪案率也是**事实**(官方发布的数),和学区一样每套都报。
        entry["crime"] = suburb_stats.crime_for(m.get("suburb"))
        out.append(entry)
    return {"metrics": out}


# ---------------------------------------------------------------- 节点 6:explain

_EXPLAIN_SYSTEM = """你是房产投资助手。下面会给你一份已经算好的房源数据(JSON)。

你的任务只有一个:用中文写一段简短说明,帮用户理解这几套房怎么选。

绝对铁律:
1. **只能使用给定 JSON 里出现的数字。禁止计算、禁止推测、禁止补充任何未给出的数值。**
   不要自己算平均值、总价、月租、差额、涨幅 —— 一个都不要算。
2. 某个指标的值是 null,就说"数据不足,暂无法计算",不要跳过、更不要编。
   land_size(土地面积)、building_area(建筑面积)是数据集的记录值,null 表示**没有记录**,
   不要说"没有土地",也不要拿房间数去推测面积。
3. **数字分三类,措辞必须不同,这是本系统最重要的一条规则:**
   - price / bedrooms 等:来自真实成交记录,可以直接陈述。
   - **annual_rent 不是这套房自己的租金**,是一个参考值(周租金基准×52,或推算值),来源看 rent_source。
     提到它必须按 rent_source 区分说法,不许说成"这套房年租金 X":
       · precinct_exact_sheet:"按片区同户型周租金中位数算,年租约 X"
       · precinct_all_properties:"按片区全部房型周租金中位数算"(没有匹配到同户型基准,要点明)
       · region_exact_sheet / region_all_properties:大区基准,是各片区周租金中位数按租赁保证金登记数加权平均,
         **不是大区整体中位数**,也不是这个片区的租金;要点明片区没有匹配到基准
       · assumed_yield:**不是租金基准**,是成交价×假设回报率推算出来的,不许说成官方/DFFH 公布的租金,
         也不许说"该地区没有租金数据"(只是本次查表没匹配到基准),要点明这是推算值
       · rent_source 为 null 或其他值:只说"租金来源不明",不要猜是哪一种
   - gross_yield(毛租金回报率):annual_rent ÷ 这套房的成交价,是**该参考租金水平下的估计**
     (assumed_yield 时是假设值,不是市场信息),可以直接报数,但不要说成这套房实际能收到的回报。
   - 排序口径里的"全部 N 套"指**符合本次条件的** N 套,不是全库,不要写成"全库 N 套"。
   - **noi / cap_rate / roi:建立在假设之上。** 提到它们时必须点明所依据的假设
     (assumptions 字段里有,用户消息里也会给你人话版)。例如:
     "按运营支出占租金 28% 的行业惯例假设测算,净营运收入约 X"。
     绝不能像陈述事实那样说"这套房的 NOI 是 X"。
   - **predicted_price:模型预测值,不是成交价。** 提到它必须带上 80% 把握区间
     (valuation_interval,在模型没见过的成交上验证过覆盖率)。
4. **环境属性(安静/热闹/生活便利/近公园)是 0~100 的相对评分,不是实测量。**
   数据里给了 context_scores(分数)和 context_evidence(算它用的原始证据)。
   提到分数时**必须同时给出至少一条证据**,例如:
     「安静度 82 分 —— 距最近主干道 640 米、周边 300 米内没有酒吧夜店」
   只报分数不给证据是不允许的:分数是我们定的一套加权口径,证据才是可核对的事实。
   分数的含义是**在全库中的相对位置**(82 分 ≈ 比 82% 的房源安静),
   不要说成"绝对很安静"。
5. **关于"低估/高估"要格外克制。** 判断一律看 valuation_position,不看 predicted_gap 的大小:
   - within:售价在模型 80% 把握区间内,**不许**说低估或高估,
     应该说"估值与售价基本相符"。
   - below:**售价低于**区间下限 = **估值高于售价**(模型认为这套偏便宜)。只能这样写:
     "估值明显高于售价"。
   - above:**售价高于**区间上限 = **估值低于售价**(模型认为这套偏贵)。只能这样写:
     "估值明显低于售价"。
     两种情况都要接一句"这只是模型意见,可能反映了模型没看到的因素(如房况、装修、朝向),
     差距特别大时也可能是成交记录本身有误"。**方向不许写反** —— 实测出过把 below 写成
     "估值远低于售价"的错,和卡片上的「估值高于售价」正好相反。
6. **规划分区(planning)是法条,不是评分,也不是预测。** 数据里的 zone 是这块地
   法律上的用途分区,overlays 是压在它上面的额外限制,nearby 是周边分区构成。
   - 可以像陈述事实一样说:"分区 NRZ1(邻里住宅区,限制加密)"、
     "有 HO 历史保护叠加层,改建需额外审批"。
   - **"法律上允许"不等于"一定会发生"。** 周边有允许高密度的地块,只能说
     "法律上允许开发商申请建高密度住宅",**不能**说"将来会盖起高楼"。
     反过来,"周边都是限制加密的分区,法律上不能建高楼"是可以直接说的 ——
     否定结论比肯定结论强得多,这个不对称要保持住。
   - **分区说不了房价会不会涨。** 不许用分区推测升值潜力、租金走势。
   - 分区是**当前**的,而成交价是 2016–2018 年的,不要把两者因果地连起来。
7. 用户消息里会给出**本次结果的排序口径**。如果是按某个指标排的,要在开头
   一句话交代清楚(例如"以下按毛租金回报率从高到低排列")。
   **提到排序方式时只能照这条口径说**:口径是"按语义相关度排序"时,不许说成按价格、
   按离某处远近、按某个评分排 —— 结果实际是怎么排的,说明就怎么说。
   若口径里写明了"在语义最相关的 N 套候选里挑",也要如实带上这个限定,
   不能让用户误以为这是全库最高。
8. 不要提到 JSON、字段名、id 这些技术细节。用"第 N 套""Glen Iris 这套"来指代。
   **"第 N 套"里的 N 必须取该房源的 `display_no` 字段**,不是它在列表里的顺序。
   用户界面上的卡片编号就是 display_no,写错了用户就对不上是哪一套。
   翻到后面几批时 display_no 可能是 11、12……照写即可。
9. 比例类字段给的都是小数(0.042 就是 4.2%)。写成百分比时**保留一位小数**,
   不要写成 4.2105%。换算单位和四舍五入不算计算,允许。

## 输出格式(必须严格遵守)

第一行:**一句话结论**,不超过 40 字,直接说"该怎么选"。
空一行,然后 3~4 条要点,每条以 "- " 开头、不超过 40 字。

**每一套房都必须被提到,一套都不能漏。** 用户看着 5 张卡片,
说明里只谈其中 3 套,剩下两套就成了没人评价的孤儿 —— 他会以为系统没看它们。
条数不够就**合并同类**,不要为了凑数硬写:

  - 第 1、3 套各项居中,没有突出优点也没有明显短板

平庸的房源合并成一句就够了,把篇幅留给真正需要说的那几套。

就这些。不要标题、不要编号、不要收尾总结。

**绝对不要逐套复述卡片上已经有的数字。** 售价、房型、毛回报、各项距离、
安静度分数、风险叠加层 —— 这些用户在房源卡上一眼就能看见,再抄一遍
只会把真正的判断埋掉。用户抱怨过这段说明是"信息地狱",就是这么来的。

同理,**假设口径和模型误差不用在这里重复**:界面上每个依赖假设的数字旁边
都标了假设、每个估值旁边都标了误差区间。你只在**做判断时**需要点明,
例如"第 4 套估值高出售价 16.9%,超出典型误差,但这只是模型意见"。

你要写的是卡片上**没有**的东西:
  - 几套之间该怎么取舍(谁适合什么样的人)
  - 哪一项差异是真的重要,哪一项其实几乎没差别
  - 有没有需要提醒但不显眼的事

**风险和估值差只在它影响取舍时才提。** 卡片上已经有"估值高于售价 16.9%"、
"须做环境审计"这样的标签了,把标签念一遍不是提醒,是噪音 ——
用户问的是安静,你回一句"第 4 套估值高出售价 16.9%",他会觉得莫名其妙。
要提就得连着结论一起提:「最便宜的第 3 套估值反而高出售价 16.9%,买前先看房况」
—— 这才叫提醒,因为它改变了"选最便宜那套"这个决定。

一个好例子:

  前三套安静度几乎一样,按价格和通勤取舍就行。

  - 第 3 套 $400,000 最便宜,距墨大 3.8 km,是通勤与价格的平衡点
  - 但第 3 套估值高出售价 16.9%,若冲着便宜去,买前要先看房况
  - 第 5 套贵一倍且回报最低,只有"更近市区"这一个理由
  - 第 1、2 套各项居中,没有突出优点也没有明显短板

注意最后一条:第 1、2 套没什么可说的,但**必须交代一句**,不能当它们不存在。

回答里每个价格、收益率、估值,都必须能追溯到我给你的这份数据。"""


def _no_result_answer(params: dict, en: bool = False) -> str:
    """没搜到结果时的确定性回答 —— 这条路径不经过 LLM,从根上杜绝编造。

    正因为不过 LLM,英文版也必须**在这里**写死,不能指望模型顺手翻一下 ——
    一旦交给模型,这条路径就重新有了编造的空间,而它存在的全部理由就是没有。
    """
    said = []
    if params.get("suburb"):
        said.append(f"suburb “{params['suburb']}”" if en else f"区域「{params['suburb']}」")
    if params.get("max_price"):
        said.append(f"max ${params['max_price']:,}" if en else f"价格上限 ${params['max_price']:,}")
    if params.get("min_price"):
        said.append(f"min ${params['min_price']:,}" if en else f"价格下限 ${params['min_price']:,}")
    if params.get("bedrooms"):
        said.append(f"{params['bedrooms']} bed" if en else f"{params['bedrooms']} 房")
    if params.get("bathrooms"):
        said.append(f"{params['bathrooms']} bath" if en else f"{params['bathrooms']} 卫")
    if params.get("property_type"):
        said.append(f"type {params['property_type']}" if en else f"类型 {params['property_type']}")
    if params.get("max_distance_cbd_km"):
        said.append(f"within {params['max_distance_cbd_km']:g} km of the CBD" if en
                    else f"距 CBD {params['max_distance_cbd_km']:g} 公里内")

    if en:
        detail = ", ".join(said) if said else "the current filters"
        lines = [f"No properties match ({detail})."]
    else:
        detail = "、".join(said) if said else "当前条件"
        lines = [f"没有找到符合条件的房源({detail})。"]

    # 地名被改过、以及有要求根本没纳入筛选 —— 这两件事在"没结果"时**更要说**:
    # 用户正在琢磨"为什么搜不到",而答案很可能就是这两条里的一条。
    typed = params.get("suburb_typed_as")
    if typed and params.get("suburb"):
        lines.append(
            f"Note: you typed “{typed}” and the system searched “{params['suburb']}”. "
            f"If you meant a different suburb, change it and try again." if en else
            f"注意:你输入的是「{typed}」,系统按「{params['suburb']}」搜的。"
            "如果本来就想找别的区,改一下再试。")
    if params.get("unsupported_asks"):
        if en:
            joined = ", ".join(_unsupported_en(a) for a in params["unsupported_asks"])
            lines.append("Also, there is no data for these, so they **never entered the filtering "
                         "at all**: " + joined + ".")
        else:
            lines.append("另外这几项本系统没有数据,**从一开始就没参与筛选**:"
                         + "、".join(params["unsupported_asks"]) + "。")

    lines.append("This dataset covers Melbourne only. Try relaxing a filter or another suburb."
                 if en else "本系统的数据集是墨尔本房源,不含其他城市。请放宽条件或换个区再试。")
    return "\n".join(lines)


_EXPLAIN_LANG_EN = """

## LANGUAGE OVERRIDE — supersedes any instruction above about writing in Chinese

Write the entire answer in **English**. Every other rule above still applies
unchanged; only the output language differs, plus these three wordings:

- Refer to a property as **"Property N"**, where N is that property's
  `display_no` field — e.g. "Property 1", "Properties 2 and 3", "Properties 2-4".
  Use exactly this form. The interface turns it into a clickable link to the
  matching card, and any other wording will not be recognised.
- Where the rules above say to write 「数据不足,暂无法计算」, write
  "not enough data to calculate".
- Keep the same shape: one conclusion line of at most ~25 words, a blank line,
  then 3-4 bullets each starting with "- " and at most ~25 words.
"""

_CONCEPT_LANG_EN = """

## LANGUAGE OVERRIDE — supersedes any instruction above about writing in Chinese

Answer in **English**, in 3-5 sentences. Every other constraint above still applies.
"""

_CONCEPT_SYSTEM = """你是房产投资助手。用户问的是一个**概念/名词/公式**,不是具体房源。

用中文简短解释(3~5 句),可以给出公式。

三条硬约束:
1. **绝对不要提到任何具体房源的价格、回报率、估值。** 你手上没有房源数据,
   编一个出来就是这个系统最不能容忍的错误。举例说明时用"假设某房 100 万、
   年租金 4 万"这样**明显是举例**的整数,并明说这是举例。
2. **不要给出任何市场统计数字**(如"墨尔本平均回报率是 4%")。你不知道,
   本系统也没有这个数据。要谈典型区间就说"通常在几个百分点之间"这种定性表述。
3. 回答开头必须写一句:"以下是通用金融常识,不是来自本系统的数据。"

如果用户问的其实和房源有关(比如"这几套哪个好"),就说请他明确一下,
不要凭空回答。"""


def _assumption_lines(state, metrics) -> list[str]:
    """交给 LLM 的「本次测算所依据的假设」必须是这批指标**当时用的**那一份(每套指标自带的 assumptions,
    没有就用本次请求的快照),不是此刻的进程级假设 —— analyze 之后 /api/assumptions 可能已经把它改了,
    追问上一轮结果(about_results)时更是如此。一致就用原来的 describe();不一致就直接按那份快照写,并注明。"""
    used = next((m["assumptions"] for m in metrics if m.get("assumptions")), None) or (state.get("assumption_snap") or {}).get("display")
    before = assumptions.snapshot()
    lines = assumptions.describe()
    if used is None or (before == used and assumptions.snapshot() == used):
        return lines
    opex, fees = used.get("opex_rate"), used.get("other_acquisition_costs")
    if opex is None or fees is None:
        return [_t(state, "这批指标计算时的假设与当前进程级假设不同,不要引用具体的运营支出比例或购置开销数值。",
                   "The assumptions used for these metrics differ from the current global ones; do not quote a specific operating-expense "
                   "ratio or acquisition-cost figure.")]
    return [_t(state, f"运营支出按年租金的 {opex:.1%} 计(这批指标计算时用的假设;进程级假设之后已被改动,以此为准)",
               f"Operating expenses at {opex:.1%} of annual rent (the assumption used for these metrics; the global assumption has since changed — use this one)"),
            _t(state, f"印花税之外的购置开销(过户/律师费、验房费等)按 ${fees:,.0f} 计(同上;印花税另按法定税率算)",
               f"Other acquisition costs excluding stamp duty (conveyancing, inspections etc.) of ${fees:,.0f} (same; stamp duty is calculated separately at statutory rates)")]


_EXPLAIN_HIDDEN = ("car_spaces", "latitude", "longitude", "id")


def _explain_fact(m: dict) -> dict:
    fact = {k: v for k, v in m.items() if k not in _EXPLAIN_HIDDEN}
    for key in ("land_size", "building_area"):
        if not (isinstance(fact.get(key), (int, float)) and fact[key] > 0):
            fact[key] = None
    return fact


def explain(state: State) -> dict:
    """LLM 把已算好的数字说成人话。它只解释,不产数字。

    V3 起要应对四种意图,其中两种根本不看房源数据:
      new_search / refine  -> 解释这一轮检索到的房源
      about_results        -> 解释**上一轮**的房源(状态还在,不用重新检索)
      concept              -> 纯概念解释,单独一套提示词,严禁出现房源数字
    """
    intent = state.get("intent") or "new_search"
    parking_kind = _parking_kind(state.get("user_query"))
    parking_notice = _parking_notice(state, parking_kind)

    if state.get("turn_notice"):
        answer = state["turn_notice"]
        return {"answer": answer, "history": [{"role": "助手", "text": answer}]}

    if intent == "concept":
        try:
            system = _CONCEPT_SYSTEM + (_CONCEPT_LANG_EN if _en(state) else "")
            return {"answer": _ask_streaming(system, state["user_query"], temperature=0.3),
                    "history": [{"role": "助手", "text": "(解释了一个概念)"}]}
        except Exception as exc:
            return {"answer": _t(state, f"(解释生成失败:{exc})",
                                 f"(Could not generate the explanation: {exc})"),
                    "history": [{"role": "助手", "text": "(概念解释失败)"}]}

    metrics = state.get("metrics") or []
    if not metrics:
        if intent == "about_results":
            answer = _t(state, "还没有搜索结果可供追问。请先告诉我你想找什么样的房子。",
                        "There are no results to ask about yet. Tell me what kind of home you are "
                        "looking for first.")
        else:
            answer = _no_result_answer(state.get("params") or {}, _en(state))
            if state.get("ranking"):
                answer += "\n" + state["ranking"].replace(";", "\n")
        if parking_notice:
            answer = parking_notice + "\n" + answer
        return {"answer": answer, "history": [{"role": "助手", "text": answer[:80]}]}

    # 给每套贴上**用户在界面上看到的编号**。翻到第三批时卡片是 11–15,
    # 模型如果按自己看到的顺序叫"第 1 套",就和卡片、地图全对不上。
    offset = int(state.get("batch_offset") or 0)
    # 解释使用独立副本;原 metrics / 估值输入保持不变。只给模型**页面上看得到**的事实
    # (外部测试第 8 项:模型说「第 2 套土地略大」,而土地面积页面上根本没有,用户无从核对)。
    # 车位不作为可展示事实;坐标和内部编号不是给用户看的。土地/建筑面积现在详情里有显示;
    # 记录为 0 的是数据集没记(公寓尤其多),当作缺失,免得模型说「没有土地」。
    numbered = [{"display_no": offset + i + 1, **_explain_fact(m)} for i, m in enumerate(metrics)]
    facts = json.dumps(numbered, ensure_ascii=False, indent=2, default=str)
    assumption_lines = "\n".join(f"  - {line}" for line in _assumption_lines(state, metrics))
    context = [f"用户的问题:{state['user_query']}"]
    if intent == "about_results":
        context.append("这是一个**针对上一轮结果的追问**,下面的房源就是上一轮给出的那几套,"
                       "没有重新检索。回答时不要说「为你找到」,要直接回答他问的那一点。")
    else:
        context.append(f"本次结果的排序口径:{state.get('ranking') or '按语义相关度排序'}")
        goals = (state.get("params") or {}).get("relative_preferences") or []
        if goals:
            comparisons = [{"attribute": goal["field"], "direction": goal["direction"],
                            "degree": goal["degree"], "previous_displayed_median": goal["baseline"],
                            "current_displayed_median": refinement.baseline_for(metrics, goal["field"])}
                           for goal in goals]
            context.append("本轮是【相对调整】,不是寻找该属性的最高分或最低价。必须以这条解释口径为准:\n"
                "1. 开头先说明保留哪些原要求,并在上一轮基础上做小幅/适度调整。\n"
                "2. 以下比较数值由程序从实际展示结果计算。引用 previous_displayed_median/current_displayed_median 时必须明确写【这批房源的评分中位数】,不能仅说整体分数或每套提高。分数是系统相对评价,不是实测噪声、全库排名或市场统计。\n"
                "3. 安静等旧条件仍是用户要求,不能说满足它的房源与本轮诉求相反。用户没有改口追求最热闹。\n"
                "4. 结果是符合原条件的局部调整候选,不能说只能在这几套里选、其他地方找不到更热闹的,也不能按分数绝对高低否定这次相对提升。\n"
                "5. 对照实际房源说明取舍,不宣称新列表每套都比旧列表每套更好。\n"
                "仍生效的条件:" + json.dumps(state.get("params") or {}, ensure_ascii=False) +
                "\n程序计算的本轮比较:" + json.dumps(comparisons, ensure_ascii=False))

    if parking_kind:
        context.append("房源自带车位无法核验,不得说任何房源有或没有车位,也不得据此推荐或声称按车位筛选。"
                       "附近公共停车设施、规划 Parking Overlay 和地点名称与房源自带车位不同。"
                       "系统会另给用户核验提示;其余问题照常回答。")

    lookup = state.get("place_lookup")
    if lookup and lookup.get("error"):
        context.append(f"⚠️ {lookup['error']} —— 必须如实告诉用户没找到这个地点,"
                       "不要假装算过到它的距离。")

    context.append(f"本次测算所依据的假设(提到 NOI / Cap Rate / ROI 时必须点明):\n{assumption_lines}")
    context.append(f"已算好的房源数据:\n{facts}")

    try:
        system = _EXPLAIN_SYSTEM + (_EXPLAIN_LANG_EN if _en(state) else "")
        answer = _ask_streaming(system, "\n\n".join(context), temperature=0.2)
    except Exception as exc:
        # LLM 挂了不该让整个回答消失 —— 房源和指标已经算出来了,照常展示,
        # 只是少一段人话说明。
        answer = _t(state,
            f"(说明生成失败:{exc};上方房源与指标均为系统计算结果,不受影响)",
            f"(Could not generate the summary: {exc}. The properties and metrics above are "
            f"computed by the system and are unaffected.)")
    if parking_notice:
        answer = parking_notice + "\n" + answer
    return {"answer": answer, "history": [{"role": "助手", "text": answer[:80]}]}


# ---------------------------------------------------------------- 组装


def _route(state: State) -> str:
    """parse_intent 之后往哪走。这是整张图里唯一一处条件路由。

    第一版任务书写的是"先直,再弯"—— 四个节点一条直线,不做条件路由。
    现在弯了,而且弯得有理由:追问上一轮的结果、问一个名词的意思,
    **都不需要碰数据库**。硬走一遍检索,既慢又会把上一轮的结果冲掉。
    """
    return "search" if state.get("intent") in ("new_search", "refine") else "explain"


def build_graph(checkpointer=None):
    builder = StateGraph(State)
    builder.add_node("parse_intent", parse_intent)
    builder.add_node("search", search)
    builder.add_node("analyze", analyze)
    builder.add_node("enrich", enrich)
    builder.add_node("rank", rank)
    builder.add_node("present", present)
    builder.add_node("explain", explain)

    builder.set_entry_point("parse_intent")
    builder.add_conditional_edges("parse_intent", _route,
                                  {"search": "search", "explain": "explain"})
    builder.add_edge("search", "analyze")
    builder.add_edge("analyze", "enrich")
    builder.add_edge("enrich", "rank")
    builder.add_edge("rank", "present")
    builder.add_edge("present", "explain")
    builder.add_edge("explain", END)

    return builder.compile(checkpointer=checkpointer)


# 会话记忆。MemorySaver 把每个 thread_id 的状态存在进程内存里 —— 重启就没了,
# 对命令行和第三版的 Streamlit 都够用。要跨重启保留,换成 SqliteSaver 即可,
# 图本身一行不用改。
MEMORY = MemorySaver()


def new_session(thread_id: str) -> dict:
    """开一个新会话。返回 invoke 要用的 config。

    同一个 thread_id 的多次 invoke 会**接着上一次的状态**跑,这就是多轮的
    实现方式:上一轮的 params 和 metrics 还在状态里,parse_intent 能看到,
    about_results 分支能直接拿来回答。
    """
    return {"configurable": {"thread_id": thread_id}}


# 模块级单例。任务书验收里写的 app.invoke(...) 在这里叫 GRAPH.invoke(...) ——
# 本项目的包就叫 app,再起一个同名变量会互相遮蔽,读代码的人会晕。
GRAPH = build_graph(checkpointer=MEMORY)
