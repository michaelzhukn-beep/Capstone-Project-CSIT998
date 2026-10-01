"""网页服务:把 LangGraph 编排包成几个 HTTP 接口。V8。

    python serve.py            # 然后打开 http://localhost:8000

## 为什么不是 Streamlit

Streamlit 是"表单 + 整页重跑"的模型:手机端很差,做不了条件卡的点选切换、
底部抽屉、逐字流式输出。要的是"简约、轻量、适配手机",所以这里是
**FastAPI + 一个单页 HTML/JS**,不用 npm、不用构建,前端三个文件在 app/web/。

## 接口只有四个

    GET  /api/meta          属性、设施、证据项的中文名和当前假设 —— 前端不硬编码这些
    POST /api/chat          {thread_id, message}  -> SSE 事件流
    POST /api/refine        {thread_id, params}   -> SSE 事件流(条件卡改过之后)
    POST /api/assumptions   {opex_rate?, other_acquisition_costs?}

## 事件流

一次问答约 9 秒,前端不能干等。图跑到哪一步就推一个事件出来:

    node      到了哪个节点(给进度用)
    params    parse_intent 抽出的条件 -> 条件卡在 1 秒内就出现
    ranking   rank 用了什么口径
    results   present 之后的 5 套完整数据 -> 卡片在 3 秒左右出现
    token     explain 里 LLM 逐字吐的说明
    answer    完整说明(以它为准,token 只是预览)
    done      本轮结束,附会话状态摘要
    error

## 条件卡改动怎么进图

不重新让 LLM 解析。`GRAPH.update_state(..., as_node="parse_intent")` 把改好的
params 当作 parse_intent 的输出写进会话状态,再 stream(None) 从 search 继续。
参数先过一遍图里的 `_sanitize` —— 它本来就是给不可信的 LLM 输出准备的闸,
拿来挡不可信的浏览器输入正好。

## 一个必须说明的局限

假设(opex_rate 等)是**进程级**的,不是按会话的 —— 一个人改了所有人都变。
单人演示没问题;多人同时用要把 assumptions 挪进会话状态,那是另一次改动。
"""

import asyncio
import json
import math
import sys
import threading
from copy import deepcopy
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langgraph.types import Overwrite

from app.amenities import context, nearby, planning, registry, suburb_stats, zones
from app.analytics import assumptions
from app.analytics.valuation import warm_up as valuation_warm_up
from app import i18n
from app.analytics.formulas import investment_metrics
from app.orchestration import graph as g
from app.auth import favorites as auth_favorites, routes as auth_routes, store as auth_store
from app.orchestration.graph import GRAPH, new_session
from app.search.search import _get_model

WEB = Path(__file__).resolve().parents[1] / "web"

# ⚠️ 数据集的 Type='h' 官方口径是 house / cottage / villa / semi / terrace ——
# 它**不等于**「独栋」。实测在 48 个样本充足的区里,h 里地址带单元号的那 426 套
# 中位价只有典型独栋的 0.66,和联排的 0.67 几乎一样。把整类叫「独栋」,
# 就是拿一个更贵的词去标一群更便宜的房 —— 前端会再按地址细分一次,见 app.js。
PROPERTY_TYPE_ZH = {"house": "独立屋", "apartment": "公寓", "townhouse": "联排"}

# 每个会话一把锁:同一个 thread_id 不能并发跑两次,MemorySaver 的状态会串。
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_meta_cache: dict | None = None


def _lock_for(thread_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(thread_id, threading.Lock())


def warm_up() -> dict:
    """和 run.py 的启动预热一样 —— 否则第一个问题要多等二十秒。"""
    _get_model()
    meta = valuation_warm_up()
    context.warm_up()
    nearby.warm_up()
    zones.warm_up()
    suburb_stats.warm_up()
    planning.warm_up()
    return meta


def _say(text: str) -> None:
    """启动提示。GBK 控制台(中文 Windows 的 cmd、Agent 的 Bash 子进程)编码不了「R²」之类的字符,
    直接 print 会抛 UnicodeEncodeError 打死 lifespan —— 提示是给人看的,不能拿服务陪葬。
    serve.py 已把 stdout 改成 UTF-8;这里兜的是 uvicorn 直起、TestClient 等其他入口。"""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, errors="replace").decode(enc), flush=True)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _say("正在加载模型与地理数据(约 20 秒)……")
    await asyncio.to_thread(auth_store.ensure_schema)      # 账号表:已有数据库不会重跑 db/schema.sql,这里幂等建一次
    meta = await asyncio.to_thread(warm_up)
    m = meta["metrics"]
    # 这里不印网址 —— 端口是 serve.py 决定的(可以 --port= 改),
    # 在这里硬编码 8000 会在换端口时给出一个错的地址。
    _say(f"就绪:估值模型 R² {m['r2']:.3f} · 可以开始提问")
    yield


class _RevalidatingStatic(StaticFiles):
    """强制浏览器每次都校验前端资源是否过期。

    StaticFiles 只发 ETag / Last-Modified,不发 Cache-Control。缺了它,浏览器会用
    **启发式缓存**自己决定留多久,并且在同一个标签页里可能直接吃内存缓存、连校验
    请求都不发 —— 结果是改完 app.js 刷新页面还是旧的。踩过一次,以为改动没生效。

    no-cache 的意思是"每次都来问一句",不是"不许缓存"。ETag 还在,没变就回 304,
    不传正文,代价几乎为零。演示当天别让人看到上一版。
    """

    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"
        return r


app = FastAPI(title="筑明AI", lifespan=_lifespan)
app.include_router(auth_routes.router)                     # /api/auth/*:注册、登录、登出、当前用户(登录可选)
app.include_router(auth_favorites.router)                  # /api/favorites:收藏(需登录)
app.mount("/static", _RevalidatingStatic(directory=str(WEB)), name="static")


@app.get("/")
async def index():
    # index.html 同理 —— 它缓存住了,里面引用的新资源根本没机会被发现
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- meta


def _build_meta() -> dict:
    """前端要用的所有中文名和口径,全部从注册表/模块生成 —— 前端不硬编码。"""
    global _meta_cache
    if _meta_cache is None:
        vmeta = valuation_warm_up()
        _meta_cache = {
            "attributes": dict(context.ATTRIBUTE_ZH),
            "attribute_parts": {k: list(v["parts"]) for k, v in context.ATTRIBUTES.items()},
            "attribute_notes": {k: v.get("note", "") for k, v in context.ATTRIBUTES.items()},
            "evidence_labels": {k: list(registry.evidence_label(k))
                                for k in registry.all_evidence_keys()},
            "kinds": dict(nearby.KIND_ZH),
            "sort_labels": dict(g._SORT_LABEL),
            "planning_needs": {k: v[0] for k, v in g._PLANNING_NEEDS.items()},
            "property_types": PROPERTY_TYPE_ZH,
            "valuation_error_by_type": vmeta.get("error_by_type") or {},
            "unsupported": dict(registry.UNSUPPORTED),
            "crime_year": suburb_stats.warm_up().get("year"),
        }
    return {**_meta_cache,
            "assumptions": {"describe": assumptions.describe(),
                            "snapshot": assumptions.snapshot()}}


@app.get("/api/meta")
async def meta(lang: str = "zh"):
    """lang 不传就是中文 —— 老的调用方(以及 tests/test_api.py)一个字都不用改。
    英文不是另一份 meta,是同一份 meta 过一遍翻译:结构完全一致,只有值变了,
    前端因此不需要知道自己拿的是哪种语言。"""
    built = _build_meta()
    return i18n.translate_meta(built) if lang == "en" else built


# ---------------------------------------------------------------- 事件流


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


# ---- done 事件里的「本轮假设」---------------------------------------------------------------
# 假设是进程级的,/api/assumptions 可以在一轮进行中把它改掉。done 事件必须描述**这一轮的数字实际用的那份**,
# 不是 done 发出那一刻的进程级值 —— 否则 done 说 40%、同一轮的卡片和详情却是按 28.4% 算的。
# 本轮的快照来源(按序取第一个可用的):
#   1. state["assumption_snap"]["display"]  —— search 节点读一次后写进会话状态的那份(本轮预排序/analyze/展示共用);
#   2. 状态里第一套房 metrics["assumptions"] —— 没有 assumption_snap 的旧状态(快照机制出现之前写下的会话)仍带着每套房自己的假设;
#   3. 兼容行为:两者都没有(没有结果的概念题/澄清、或旧状态),退回**此刻的进程级假设**,与改动前完全一致 —— 此时没有「本轮数字」可对应。
def _snapshot_ok(snap) -> bool:
    return (isinstance(snap, dict) and all(
        isinstance(snap.get(k), (int, float)) and not isinstance(snap.get(k), bool) and math.isfinite(snap[k]) for k in ('opex_rate', 'other_acquisition_costs')))


def _round_assumption_snapshot(state):
    sources = [(state.get("assumption_snap") or {}).get("display") if isinstance(state.get("assumption_snap"), dict) else None]
    sources += [m.get("assumptions") for m in (state.get("metrics") or [])[:1] if isinstance(m, dict)]
    return next((s for s in sources if _snapshot_ok(s)), None)


def _describe_snapshot_zh(snap) -> list[str]:
    """通过假设模块的公共格式器描述快照,不重复读取其私有文案注册表。"""
    return assumptions.describe(snap)


def _done_assumptions(state, lang: str) -> list[str]:
    snap = _round_assumption_snapshot(state)
    if snap is None:                                   # 兼容:没有本轮快照,按改动前的行为描述当前进程级假设
        snap_now = assumptions.snapshot()
        return i18n.assumptions_describe_en(snap_now) if lang == "en" else assumptions.describe(snap_now)
    return i18n.assumptions_describe_en(snap) if lang == "en" else _describe_snapshot_zh(snap)


async def _run(thread_id: str, inputs, config, lang: str = "zh", refinement=None):
    """在工作线程里跑图,事件通过队列送回异步端。图是同步的、里面有 LLM 调用,
    直接在事件循环里跑会把整个服务卡住。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def put(item):
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def producer():
        lock = _lock_for(thread_id)
        if not lock.acquire(blocking=False):
            put(("error", {"message": "One request is still running — give it a moment"
                                      if lang == "en" else "上一条还在处理,稍等一下再发"}))
            put(None)
            return
        previous = None
        try:
            previous = deepcopy(GRAPH.get_state(config).values or {})
            if refinement is not None:
                # 读旧条件、更新参数和执行检索必须在同一把锁内,失败可恢复整轮结果。
                clean = g.prepare_refinement(refinement.params, previous.get("params") or {},
                                             refinement.removed_attributes)
                change = "(通过条件卡修改,以这些条件为准,未列出的旧偏好不再使用): " + json.dumps(clean, ensure_ascii=False)
                GRAPH.update_state(config,
                    {"user_query": change, "intent": "refine", "params": clean,
                     "refinement_base": g.refinement.snapshot(previous), "turn_notice": None,
                     "history": [{"role": "用户", "text": change}], "lang": lang},
                    as_node="parse_intent")
            for mode, chunk in GRAPH.stream(inputs, config=config, stream_mode=["updates", "custom"]):
                if mode == "custom":
                    if isinstance(chunk, dict) and "token" in chunk:
                        put(("token", {"t": chunk["token"]}))
                    continue
                for node, out in chunk.items():
                    out = out or {}
                    put(("node", {"node": node}))
                    if node == "parse_intent":
                        put(("params", {"intent": out.get("intent"), "params": out.get("params")}))
                    elif node == "rank":
                        put(("ranking", {"ranking": out.get("ranking"),
                                         "count": len(out.get("metrics") or [])}))
                        # 排序后紧随其后的几套,给"换一批"翻页用。已经算好了,
                        # 一起发过去就行 —— 换一批不需要再跑一次图。
                        if out.get("more") is not None:
                            put(("more", {"metrics": i18n.apply(out.get("more"), lang)}))
                        if not out.get("metrics"):
                            put(("results", {"metrics": []}))
                    elif node == "present" and out.get("metrics") is not None:
                        # 规划分区那几项的值是中文的,跟着房源一起走 ——
                        # meta 翻了但这里不翻的话,英文界面上会冒出「一般住宅区」。
                        put(("results", {"metrics": i18n.apply(out.get("metrics"), lang)}))
                    elif node == "explain":
                        put(("answer", {"answer": out.get("answer")}))
            state = GRAPH.get_state(config).values or {}
            put(("done", {"intent": state.get("intent"), "params": state.get("params"),
                          "notice": state.get("turn_notice"), "batch_offset": state.get("batch_offset") or 0,
                          "ranking": state.get("ranking"),
                          "count": len(state.get("metrics") or []),
                          "assumptions": _done_assumptions(state, lang)}))
        except Exception as exc:                       # noqa: BLE001
            if previous is not None:
                restore = {key: previous.get(key) for key in g.State.__annotations__}
                restore["history"] = Overwrite(previous.get("history") or [])
                try:
                    GRAPH.update_state(config, restore, as_node="explain")
                except Exception as restore_error:
                    put(("error", {"message": f"{type(exc).__name__}: {exc}; restore: {restore_error}",
                                   "rollback_failed": True}))
                    return
            put(("error", {"message": f"{type(exc).__name__}: {exc}"}))
        finally:
            lock.release()
            put(None)

    loop.run_in_executor(None, producer)
    while True:
        item = await queue.get()
        if item is None:
            break
        yield _sse(*item)


class ChatIn(BaseModel):
    thread_id: str
    message: str
    lang: str = "zh"     # 影响 LLM 用哪种语言写说明,以及房源里中文值要不要翻


class RefineIn(BaseModel):
    thread_id: str
    params: dict
    lang: str = "zh"
    removed_attributes: list[str] = []


class AssumeIn(BaseModel):
    opex_rate: float | None = None
    other_acquisition_costs: float | None = None


@app.post("/api/chat")
async def chat(body: ChatIn):
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "空消息")
    config = new_session(body.thread_id)
    return StreamingResponse(_run(body.thread_id, {"user_query": message, "lang": body.lang},
                                  config, body.lang),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/refine")
async def refine(body: RefineIn):
    """条件卡改过之后:参数直接写进会话状态,从 search 继续跑,不经过 LLM 解析。"""
    config = new_session(body.thread_id)
    return StreamingResponse(_run(body.thread_id, None, config, body.lang, refinement=body),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class RebatchIn(BaseModel):
    thread_id: str
    offset: int = 0
    lang: str = "zh"


@app.post("/api/rebatch")
async def rebatch(body: RebatchIn):
    """换一批:把候选池里的下一段当作当前展示的房源,**只重跑 explain**。

    不重新检索、不重算指标 —— 排序早就在整个候选池上做完了,第 6 名之后一直存在
    `more` 里。但**说明必须重写**:它讲的是"第几套怎么样",换了房源还挂着旧说明,
    用户读到的是对不上号的描述,比没有说明更糟。

    走的是和 /api/refine 同一条路子:`update_state(as_node="present")` 把新的
    metrics 当作 present 的输出写进会话状态,再 stream(None) 从 explain 继续。
    """
    config = new_session(body.thread_id)
    prev = (GRAPH.get_state(config).values or {})
    pool = prev.get("more") or prev.get("metrics") or []
    if not pool:
        raise HTTPException(status_code=400, detail="这一轮还没有可翻的候选")

    limit = g.RESULT_LIMIT
    offset = max(0, int(body.offset))
    if offset >= len(pool):
        offset = 0                      # 翻到头就回到第一批
    batch = pool[offset:offset + limit]
    if not batch:
        raise HTTPException(status_code=400, detail="没有更多候选了")

    GRAPH.update_state(
        config,
        {"metrics": batch,
         "batch_offset": offset,
         "user_query": prev.get("user_query") or "找房",
         "intent": "new_search",
         "turn_notice": None, "refinement_base": None,
         "history": [{"role": "用户",
                      "text": f"(换了一批,看第 {offset + 1}–{offset + len(batch)} 套)"}],
         "lang": body.lang},
        as_node="present",
    )
    return StreamingResponse(_run(body.thread_id, None, config, body.lang),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class MeasurePoint(BaseModel):
    """测距的一头。要么直接给坐标(比如"这套房自己"),要么给个名字让服务端去解析。"""
    q: str | None = None
    lat: float | None = None
    lon: float | None = None
    label: str | None = None


class MeasureIn(BaseModel):
    origin: MeasurePoint
    target: MeasurePoint


def _resolve_point(pt: MeasurePoint, near: tuple | None, side: str) -> dict:
    if pt.lat is not None and pt.lon is not None:
        return {"name": pt.label or f"{pt.lat:.4f}, {pt.lon:.4f}", "kind": None,
                "latitude": float(pt.lat), "longitude": float(pt.lon), "matches": 1}
    if not (pt.q or "").strip():
        raise HTTPException(400, f"{side}没填")
    found = nearby.place_point(pt.q, near=near)
    if not found:
        # 找不到就说找不到,**不给一个类别不对的点凑数** —— 和 find_place 里
        # "要机场不能给小学"是同一条规矩。
        raise HTTPException(404, f"找不到「{pt.q}」。数据来自 OpenStreetMap,只认英文名,"
                                 f"换一个更完整的写法试试。")
    return found


@app.post("/api/measure")
async def measure(body: MeasureIn):
    """两点之间的直线距离,顺带把两头解析成坐标给地图插图钉。

    **为什么只有直线距离。** 这个项目没有路网数据,算不出步行或驾车路程
    (registry.UNSUPPORTED 里明确列着这一条)。好在这个功能的画面本身就说清了
    这件事:地图上是一根**直的**线连着两个图钉 —— 看图的人不会以为那是走路要绕的路。
    与其在文案里反复声明"这不是步行距离",不如让画面自己讲。

    先解析有坐标的那一头,再拿它当锚点去解析另一头:同名的点有好几个时
    (大学的几个校区),取离锚点最近的那个才是用户要问的。
    """
    o, t = body.origin, body.target
    anchor_o = (o.lat, o.lon) if o.lat is not None and o.lon is not None else None
    anchor_t = (t.lat, t.lon) if t.lat is not None and t.lon is not None else None
    origin = _resolve_point(o, anchor_t, "起点")
    target = _resolve_point(t, (origin["latitude"], origin["longitude"]), "终点")
    dist = nearby.distance_between(origin["latitude"], origin["longitude"],
                                   target["latitude"], target["longitude"])
    return {"origin": origin, "target": target, "distance_m": dist}


class RecalcIn(BaseModel):
    """详情窗里就地试算一套房。**不改全局假设,也不碰会话状态。**"""
    price: float | None = None
    annual_rent: float | None = None
    opex_rate: float
    other_acquisition_costs: float


@app.get("/api/property/{property_id}")
async def property_detail(property_id: int, lang: str = "zh"):
    """一套房的完整详情数据,与搜索结果同一口径(收藏夹里不在当前结果中的房源用)。

    按编号现算 —— 等于一次没有偏好条件的检索,只跑 analyze → enrich → present,不调用 LLM。
    不读收藏时存下的快照:估值、回报率都随模型和假设变化,旧值不能当成现在的值展示。
    房源表被整体重建后编号可能不在了,如实返回 404,由前端说明。
    """
    lang = "en" if lang == "en" else "zh"
    metrics = await asyncio.to_thread(g.detail_metrics, [property_id], lang)
    if not metrics:
        raise HTTPException(404, "property not found")
    return {"metric": i18n.apply(metrics, lang)[0]}


@app.post("/api/recalc")
async def recalc(body: RecalcIn):
    """改一个假设,立刻看到总成本和回报率跟着变。

    **为什么不让前端自己用 JS 算。** 这几个公式(分档累进的印花税、NOI、
    ROI 的分母口径)在 formulas.py 里都带着"为什么是这样"的理由,而且被
    tests/test_formulas.py 逐条盯着。前端再实现一遍,等于把这些理由复制到一个
    没有测试的地方 —— 哪天两边不一致,页面上的数字会**安静地**和后端对不上。
    所以走一趟服务端:没有 LLM、不查库,就是几次算术,几毫秒。

    **为什么不复用 /api/assumptions。** 那个改的是**进程级**的假设,一个人改了
    所有人都变,而且要重跑整张图(含一次 LLM 调用)才能看到结果。详情窗里的
    改动是"这套房如果按 3000 块杂费算会怎样"——一次一套房的试算,不该有那么大
    的副作用,也等不起二十秒。要改成全局默认,窗口里另有一个按钮。
    """
    rate = float(body.opex_rate)
    fees = float(body.other_acquisition_costs)
    # 闸门和 /api/assumptions 用同一套边界:前端能填的东西,后端一律不当真。
    lo, hi = assumptions.bounds("opex_rate")
    if not (lo <= rate <= hi):
        raise HTTPException(400, f"运营支出比例要在 {lo:.0%} ~ {hi:.0%} 之间")
    lo, hi = assumptions.bounds("other_acquisition_costs")
    if not (lo <= fees <= hi):
        raise HTTPException(400, f"购置杂费要在 {lo:,.0f} ~ {hi:,.0f} 之间")
    return investment_metrics(body.price, body.annual_rent, rate, fees)


@app.post("/api/assumptions")
async def set_assumptions(body: AssumeIn):
    try:
        if body.opex_rate is not None:
            assumptions.set_rate("opex_rate", float(body.opex_rate))
        if body.other_acquisition_costs is not None:
            assumptions.set_rate("other_acquisition_costs", float(body.other_acquisition_costs))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"describe": assumptions.describe(), "snapshot": assumptions.snapshot()}
