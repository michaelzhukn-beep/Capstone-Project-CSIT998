"""同义说法必须得到同一个条件(外部测试第 6 项,2026-10-05)。离线,不调用 LLM。

    python tests/test_paraphrase_offline.py

「离小学近一点」「最好小学近一点」「小学近点」意思相同,模型却会写成三种操作:
set amenity_needs、把字段名写成 "primary_school"、或对 primary_school 做 relative/prioritize。
后两种以前不在白名单里,整轮被拒。这里用模型实际给出过的原始输出(固定在下面)喂给
真实的 parse_intent,只把 LLM 调用换成返回这段文本,检查程序把它们统一成同一个条件;
另外检查「第一句就是 refine」不再被拒,而是当作新搜索。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.orchestration import graph as g, refinement as r      # noqa: E402

prev = g._sanitize({"intent": "new_search", "max_price": 1_000_000, "bedrooms": 3, "property_type": "house"}, "q")
rows = [{"id": i, "price": 800_000 + i, "bedrooms": 3, "suburb": "Box Hill",
         "context_scores": {"school_access": 50 + i}} for i in range(5)]


def run(query, raw, follow_up=True):
    g._ask = lambda *_a, **_k: json.dumps(raw, ensure_ascii=False)
    return g.parse_intent({"user_query": query, "lang": "zh", "params": prev if follow_up else None,
                           "metrics": rows if follow_up else []})


def amen(st):
    return [(n["kind"], n["max_distance_m"]) for n in (st.get("params") or {}).get("amenity_needs") or []]


checks = 0
# 模型实际出过的几种写法(2026-10-05 用 deepseek-chat 采到)
variants = {
    "最好离小学近一点": [{"action": "set", "field": "amenity_needs", "value": {"kind": "primary_school", "max_distance_m": 1500}, "source": "离小学近一点"}],
    "最好小学近一点(字段写成设施名)": [{"action": "set", "field": "primary_school", "value": {"kind": "primary_school", "max_distance_m": 1500}, "source": "小学近一点"}],
    "小学近一点(对设施做 relative)": [{"action": "relative", "field": "primary_school", "direction": "increase", "degree": "slight", "source": "近一点"}],
}
queries = {"最好离小学近一点": "最好离小学近一点", "最好小学近一点(字段写成设施名)": "最好小学近一点", "小学近一点(对设施做 relative)": "小学近一点"}
for label, changes in variants.items():
    for follow_up in (True, False):
        st = run(queries[label], {"intent": "refine", "changes": changes, "clarification": None}, follow_up)
        want_intent = "refine" if follow_up else "new_search"
        assert st["intent"] == want_intent, (label, follow_up, st["intent"], st.get("turn_notice"))
        assert amen(st) == [("primary_school", 1500)], (label, follow_up, amen(st))
        if follow_up:
            assert st["params"]["max_price"] == 1_000_000, "追加条件不能丢掉原有预算"
        checks += 2

# prioritize 某类设施:设门槛 + 按距离从近到远
st = run("离小学越近越好", {"intent": "refine", "changes": [{"action": "prioritize", "field": "primary_school", "source": "离小学越近越好"}]})
assert amen(st) == [("primary_school", 1500)] and st["params"]["sort_by"] == "nearest:primary_school", (amen(st), st["params"]["sort_by"])
checks += 1

# 已有门槛时「再近一点」收紧到约 2/3,不重置成默认值
prev = {**prev, "amenity_needs": [{"kind": "primary_school", "max_distance_m": 1500}]}
st = run("小学再近一点", {"intent": "refine", "changes": [{"action": "relative", "field": "primary_school", "direction": "increase", "degree": "slight", "source": "再近一点"}]})
assert amen(st) == [("primary_school", 1000)], amen(st)
checks += 1
# 用户给了数字就用用户的
st = run("小学 800 米内", {"intent": "refine", "changes": [{"action": "set", "field": "primary_school", "value": {"max_distance_m": 800}, "source": "小学 800 米内"}]})
assert amen(st) == [("primary_school", 800)], amen(st)
checks += 1
# 删除
st = run("不用离小学近了", {"intent": "refine", "changes": [{"action": "remove", "field": "primary_school", "source": "不用离小学近了"}]})
assert amen(st) == [], amen(st)
checks += 1

# 相对调整仍要有依据:第一句说「再便宜点」没有基准,照旧澄清,不能凭空编
prev = g._sanitize({"intent": "new_search", "max_price": 1_000_000}, "q")
st = run("再便宜点", {"intent": "refine", "changes": [{"action": "relative", "field": "price", "direction": "decrease", "degree": "slight", "source": "再便宜点"}]}, follow_up=False)
assert st["intent"] == "clarify", st["intent"]
checks += 1

# 非设施字段原样不动
assert r.normalize_amenity_changes([{"action": "set", "field": "max_price", "value": 1, "source": "x"}], {}) == \
    [{"action": "set", "field": "max_price", "value": 1, "source": "x"}]
checks += 1

print(f"同义说法统一 全部通过:{checks} 项检查(离线,不调用 LLM)")
