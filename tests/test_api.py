"""网页服务的验收。V8。

    python tests/test_api.py

需要数据库,**不需要 LLM、不联网**:两处 LLM 调用(解析意图、写说明)都换成
固定返回。这样测的是接口本身 —— 事件流的顺序、条件卡改动能不能不经 LLM
直接续跑、参数闸门有没有把垃圾挡住 —— 而不是模型今天心情好不好。

写说明那一处换成的假函数会**真的往流里推 token**,所以逐字流式那条路也被测到了。
"""

import json
import sys
import os
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient   # noqa: E402

from app.analytics import assumptions       # noqa: E402
from app.api import server                  # noqa: E402
from app.orchestration import graph as g    # noqa: E402

# ---------------------------------------------------------------- 把 LLM 换掉

_PARSE_REPLY = json.dumps({
    "intent": "new_search", "semantic_query": "quiet three bedroom house",
    "max_price": 900000, "min_price": None, "bedrooms": 3, "bathrooms": None,
    "property_type": "house", "suburb": None, "sort_by": "quiet", "min_gross_yield": None,
    "amenity_needs": [{"kind": "train_station", "max_distance_m": 1500}], "near_place": None,
    "abstract_needs": [{"attribute": "quiet", "min_score": 60}],
    "unsupported_asks": ["采光"], "school_zone": None, "planning_needs": ["no_risk_overlay"],
})


def _fake_ask(system, user, temperature=0.0):
    return _PARSE_REPLY


def _fake_ask_streaming(system, user, temperature=0.0):
    from langgraph.config import get_stream_writer
    writer = get_stream_writer()
    for piece in ("这是", "一段", "测试说明"):
        writer({"token": piece})
    return "这是一段测试说明"


g._ask = _fake_ask
g._ask_streaming = _fake_ask_streaming


def _events(response_text: str) -> list[tuple[str, dict]]:
    out = []
    for block in response_text.split("\n\n"):
        event, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            out.append((event, json.loads(data)))
    return out


with TestClient(server.app) as client:
    # ---------------------------------------------------------------- meta
    meta = client.get("/api/meta").json()
    assert "quiet" in meta["attributes"] and meta["attributes"]["quiet"] == "安静"
    assert "gross_yield" in meta["sort_labels"] and "quiet" in meta["sort_labels"]
    assert "train_station" in meta["kinds"]
    assert "no_heritage" in meta["planning_needs"]
    assert meta["assumptions"]["snapshot"]["opex_rate"] == assumptions.opex_rate()
    assert "major_road_m" in meta["evidence_labels"]
    # 不是「独栋」:数据集 Type='h' 官方口径含 house/cottage/villa/semi/terrace,
    # 实测其中带单元号地址的中位价只有典型独栋的 0.66(≈联排)。见 server.py 注释。
    assert meta["property_types"]["house"] == "独立屋"

    # ------------------------------------------------------------ 就地试算
    # 详情窗里改一个假设,走的是这条路:不碰全局假设、不重跑图,只重算这一套。
    # 它必须和管线用同一份公式 —— 所以这里比对的是 formulas 的输出本身。
    from app.analytics.formulas import investment_metrics    # noqa: PLC0415

    before_recalc = assumptions.snapshot()
    body = {"price": 555000, "annual_rent": 20748,
            "opex_rate": 0.28, "other_acquisition_costs": 2000}
    r = client.post("/api/recalc", json=body)
    assert r.status_code == 200
    assert r.json() == investment_metrics(555000, 20748, 0.28, 2000)

    # 改了杂费,总投入要跟着动;NOI 不该动(它不含购置开销)
    r2 = client.post("/api/recalc", json={**body, "other_acquisition_costs": 5000}).json()
    assert r2["total_cost"] == r.json()["total_cost"] + 3000
    assert r2["noi"] == r.json()["noi"]
    assert r2["roi"] < r.json()["roi"]

    # 改了运营支出比例,NOI 和两个回报率都要动,总投入不动
    r3 = client.post("/api/recalc", json={**body, "opex_rate": 0.20}).json()
    assert r3["noi"] > r.json()["noi"] and r3["roi"] > r.json()["roi"]
    assert r3["total_cost"] == r.json()["total_cost"]

    # 闸门:和 /api/assumptions 共用 assumptions.bounds(),不能各松各的
    assert client.post("/api/recalc", json={**body, "opex_rate": 1.5}).status_code == 400
    assert client.post("/api/recalc", json={**body,
                                            "other_acquisition_costs": 999_999}).status_code == 400

    # 全局假设**没有**被这条路改掉 —— 这正是它和 /api/assumptions 的区别
    assert assumptions.snapshot() == before_recalc

    # ------------------------------------------------------------ 距离测算
    from app.amenities import nearby as _nb                  # noqa: PLC0415

    house = {"lat": -37.87, "lon": 144.83, "label": "Altona Meadows"}
    r = client.post("/api/measure", json={"origin": house,
                                          "target": {"q": "Flinders Street Station"}})
    assert r.status_code == 200
    j = r.json()
    # 距离要和 nearby 里那份 haversine 完全一致 —— 接口不能自己另算一份
    assert j["distance_m"] == _nb.distance_between(
        house["lat"], house["lon"], j["target"]["latitude"], j["target"]["longitude"])
    # 「Flinders Street Station」必须解析成火车站,而不是同名的警务点/药房/学院。
    # 这一条是 place_point 排序口径的验收:先比名字匹配,再比类别。
    assert j["target"]["kind"] == "train_station", j["target"]

    # 「Chadstone」必须是购物中心,不是名字里带 Chadstone 的学院或汽车行
    r = client.post("/api/measure", json={"origin": house, "target": {"q": "Chadstone"}})
    assert r.json()["target"]["kind"] == "mall", r.json()["target"]

    # 两头都给名字也要能用
    r = client.post("/api/measure", json={"origin": {"q": "Werribee"},
                                          "target": {"q": "Melbourne Airport"}})
    assert r.status_code == 200 and r.json()["distance_m"] > 20_000

    # 查不到就说查不到,**不给一个类别不对的点凑数**
    assert client.post("/api/measure", json={"origin": house,
                                             "target": {"q": "zzzz no such place"}}).status_code == 404
    assert client.post("/api/measure", json={"origin": {}, "target": {"q": "Werribee"}}).status_code == 400

    # ---------------------------------------------------------------- 假设
    original = assumptions.snapshot()
    r = client.post("/api/assumptions", json={"opex_rate": 0.30})
    assert r.status_code == 200 and any("30.0%" in s for s in r.json()["describe"])
    # 越界必须被拒,而且不能改掉现值
    r = client.post("/api/assumptions", json={"opex_rate": 1.5})
    assert r.status_code == 400 and assumptions.opex_rate() == 0.30
    assumptions.set_rate("opex_rate", original["opex_rate"])

    # ---------------------------------------------------------------- 对话事件流
    thread = "test-thread-1"
    r = client.post("/api/chat", json={"thread_id": thread, "message": "90万以内安静的三房独栋"})
    assert r.status_code == 200
    events = _events(r.text)
    names = [e for e, _ in events]
    assert "params" in names and "results" in names and "ranking" in names and "answer" in names
    assert names[-1] == "done", names[-3:]
    # 事件顺序:条件先于结果,结果先于说明 —— 前端就是靠这个顺序做"渐进出现"的
    assert names.index("params") < names.index("results") < names.index("answer")
    tokens = [d["t"] for e, d in events if e == "token"]
    assert tokens == ["这是", "一段", "测试说明"], tokens
    answer = next(d for e, d in events if e == "answer")["answer"]
    assert answer == "这是一段测试说明"

    params = next(d for e, d in events if e == "params")["params"]
    assert params["bedrooms"] == 3 and params["max_price"] == 900000 and params["sort_by"] == "quiet"
    assert params["planning_needs"] == ["no_risk_overlay"]

    metrics = next(d for e, d in events if e == "results")["metrics"]
    assert 1 <= len(metrics) <= 5
    for m in metrics:
        assert m["bedrooms"] == 3 and m["price"] <= 900000 and m["property_type"] == "house"
        # present 之后每套都要带这些事实字段,前端详情页靠它们
        for key in ("planning", "school_zones", "crime", "amenities", "context_scores", "context_evidence",
                    "stamp_duty", "predicted_price", "valuation_range", "valuation_interval",
                    "valuation_position", "assumptions", "rent_source"):
            assert key in m, f"结果里缺 {key}"
        # 审计 BUG-07:年租金是片区中位租金,匹配粒度必须随数字一起给到前端
        assert m["rent_source"] in ("precinct_exact_sheet", "precinct_all_properties",
                                    "region_exact_sheet", "region_all_properties")
        assert m["context_scores"]["quiet"] >= 60
        assert m["amenities"]["train_station"]["distance_m"] <= 1500
    done = next(d for e, d in events if e == "done")
    assert done["intent"] == "new_search" and done["count"] == len(metrics)

    # 删除安静仍保留教育:必须重新调用数据库检索,不是重排上一批 5/20 套。
    before_delete = deepcopy(params)
    before_delete["abstract_needs"].append({"attribute": "school_access", "min_score": 60})
    response = client.post("/api/refine", json={"thread_id": thread, "params": before_delete})
    base_events = _events(response.text)
    assert base_events[-1][0] == "done", base_events[-1]
    baseline = next(d for e, d in base_events if e == "done")["params"]
    removed = deepcopy(baseline)
    removed["abstract_needs"] = [n for n in removed["abstract_needs"] if n["attribute"] != "quiet"]
    # 模拟旧客户端仍携带 quiet 排序与旧描述,后端必须兜住。
    removed["semantic_query"] = "peaceful quiet three bedroom house away from traffic"
    with patch.object(g, "search_properties", wraps=g.search_properties) as queried:
        response = client.post("/api/refine", json={"thread_id": thread, "params": removed})
        assert queried.call_count == 1, "删除条件没有重新检索数据库"
        args = queried.call_args.kwargs
        assert args["limit"] == g.CANDIDATE_LIMIT and args["bedrooms"] == 3
        assert not any(word in args["semantic_query"].lower() for word in ("quiet", "peaceful", "traffic"))
    deletion_events = _events(response.text)
    assert deletion_events[-1][0] == "done", deletion_events[-1]
    deleted = next(d for e, d in deletion_events if e == "done")
    assert deleted["params"]["sort_by"] is None
    assert deleted["params"]["abstract_needs"] == [{"attribute": "school_access", "min_score": 60}]
    assert deleted["params"]["max_price"] == 900000 and deleted["params"]["property_type"] == "house"
    assert "按语义相关度排序" in deleted["ranking"] and "安静" not in deleted["ranking"]
    assert [d["node"] for e, d in deletion_events if e == "node"] == ["search", "analyze", "enrich", "rank", "present", "explain"]
    # 可选导出真实数据库响应给浏览器回归重放,不提交数据副本、不调用真实 LLM。
    if os.environ.get("REFINE_FIXTURE_PATH"):
        fixture = {"initial": {"params": baseline,
                    "metrics": next(d for e, d in base_events if e == "results")["metrics"]},
                   "removed": {"params": deleted["params"],
                    "metrics": next(d for e, d in deletion_events if e == "results")["metrics"]}}
        Path(os.environ["REFINE_FIXTURE_PATH"]).write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")

    # 删除偏好不得清掉不相关排序;显式再选择安静排序仍然允许。
    other_sort = {**removed, "sort_by": "price_asc"}
    assert g.prepare_refinement(other_sort, baseline)["sort_by"] == "price_asc"
    assert g.prepare_refinement({**deleted["params"], "sort_by": "quiet"}, deleted["params"])["sort_by"] == "quiet"
    assert g.prepare_refinement(removed, {}, ["quiet"])["sort_by"] is None, "旧页面在服务重启后删除也必须生效"

    # 搜索失败 / 已发出结果后的执行异常都恢复参数、结果及历史。
    config = g.new_session(thread)
    committed = deepcopy(server.GRAPH.get_state(config).values)
    original_stream = server.GRAPH.stream
    def stream_then_fail(*args, **kwargs):
        for event in original_stream(*args, **kwargs):
            yield event
            if event[0] == "updates" and "present" in event[1]:
                raise RuntimeError("intentional failure after results")
    for failure in (patch.object(g, "search_properties", side_effect=RuntimeError("intentional search failure")),
                    patch.object(server.GRAPH, "stream", side_effect=stream_then_fail)):
        with failure:
            response = client.post("/api/refine", json={"thread_id": thread, "params": other_sort})
        failed_events = _events(response.text)
        assert failed_events[-1][0] == "error" and not failed_events[-1][1].get("rollback_failed"), failed_events[-1]
        restored = server.GRAPH.get_state(config).values
        for key in ("params", "metrics", "more", "ranking", "history", "user_query", "batch_offset"):
            assert restored.get(key) == committed.get(key), f"失败后没有恢复 {key}"
    lock = server._lock_for(thread)
    lock.acquire()
    try:
        response = client.post("/api/refine", json={"thread_id": thread, "params": other_sort})
        assert _events(response.text)[0][0] == "error"
        assert server.GRAPH.get_state(config).values["params"] == committed["params"], "繁忙会话的条件被提前覆盖"
    finally:
        lock.release()

    # ---------------------------------------------------------------- 条件卡改动:不经 LLM 续跑
    # 实际数据库检索必须遵守新的比较符号,并把它回传给页面与后续会话。
    below = deepcopy(deleted["params"])
    below["abstract_needs"] = [{"attribute": "quiet", "min_score": 60, "operator": "lt"}]
    below["amenity_needs"] = []
    below["planning_needs"] = []
    events = _events(client.post("/api/refine", json={"thread_id": thread, "params": below}).text)
    assert events[-1][0] == "done", events[-1]
    below_metrics = next(d for e, d in events if e == "results")["metrics"]
    assert below_metrics and all(m["context_scores"]["quiet"] < 60 for m in below_metrics)
    assert events[-1][1]["params"]["abstract_needs"] == below["abstract_needs"]
    assert "评分 < 60" in events[-1][1]["ranking"]

    edited = dict(params)
    edited["bedrooms"] = 2
    edited["sort_by"] = "gross_yield"
    edited["abstract_needs"] = []
    edited["amenity_needs"] = []
    edited["planning_needs"] = []
    r = client.post("/api/refine", json={"thread_id": thread, "params": edited})
    assert r.status_code == 200
    events = _events(r.text)
    names = [e for e, _ in events]
    assert "params" not in names, "refine 不该再走 parse_intent"
    assert names[0] == "node" and events[0][1]["node"] == "search"
    metrics2 = next(d for e, d in events if e == "results")["metrics"]
    assert metrics2 and all(m["bedrooms"] == 2 for m in metrics2)
    yields = [m["gross_yield"] for m in metrics2]
    assert yields == sorted(yields, reverse=True), "没按毛回报排序"
    done2 = next(d for e, d in events if e == "done")
    assert done2["intent"] == "refine" and done2["params"]["bedrooms"] == 2

    # ---------------------------------------------------------------- 参数闸门
    junk = dict(params)
    junk.update({"sort_by": "drop table", "bedrooms": -3, "property_type": "castle",
                 "planning_needs": ["no_such_need"], "max_price": "很多"})
    r = client.post("/api/refine", json={"thread_id": thread, "params": junk})
    done3 = next(d for e, d in _events(r.text) if e == "done")
    p3 = done3["params"]
    assert p3["sort_by"] is None and p3["bedrooms"] is None and p3["property_type"] is None
    assert p3["planning_needs"] is None and p3["max_price"] is None

    # ---------------------------------------------------------------- 空消息
    assert client.post("/api/chat", json={"thread_id": thread, "message": "   "}).status_code == 400

print("网页服务 全部通过:meta · 假设 · 就地试算 · 距离测算 · 对话事件流(含逐字 token)· 条件卡续跑 · 参数闸门")
