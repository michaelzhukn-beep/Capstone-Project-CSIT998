"""「不要 / 避开 / 全部排除 X」必须是硬排除(外部测试第 7 项,2026-10-05)。离线,不调用 LLM。

    python tests/test_exclusion_offline.py

以前「不要机场噪音」只能变成「最好安静」这类评分偏好,带机场噪声叠加层的房子照样出现;
「有机场噪音叠加层的全部排除」被模型写成 remove unsupported_asks,程序静默接受、什么都没改。
这里检查:
  1. 按类别排除的规划条件只剔除那一类叠加层,不误伤其他类;没规划数据的证明不了「没有」,一并剔除;
  2. rank 真的把这些房源剔掉(用真实 rank,合成房源);
  3. 删一项不存在的条件不再静默通过,而是澄清。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import i18n                                            # noqa: E402
from app.amenities import planning                              # noqa: E402
from app.orchestration import graph as g                        # noqa: E402

checks = 0
ov = lambda *fams: {"zone": "GRZ", "overlays": [{"code": f + "1", "family": f, "effect": "risk"} for f in fams]}

# 1. 谓词:只看自己那一类
cases = {
    "no_airport_noise": (ov("MAEO"), ov("AEO"), ov("LSIO")),
    "no_flood":         (ov("LSIO"), ov("SBO"), ov("MAEO")),
    "no_bushfire":      (ov("BMO"), ov("BMO", "HO"), ov("LSIO")),
    "no_acquisition":   (ov("PAO"), ov("PAO"), ov("BMO")),
    "no_contamination": (ov("EAO"), ov("EAO"), ov("PAO")),
    "no_erosion":       (ov("EMO"), ov("SMO"), ov("EAO")),
}
for need, (hit1, hit2, other) in cases.items():
    label, pred = g._PLANNING_NEEDS[need]
    assert not pred(hit1) and not pred(hit2), (need, "该剔除的没剔除")
    assert pred(other), (need, "误伤了别的类别")
    assert pred({"zone": "GRZ", "overlays": []}), need
    assert not pred({}), (need, "没规划数据证明不了「没有」,应剔除")
    assert need in i18n.PLANNING_NEEDS_EN, (need, "缺英文标签")
    checks += 6
# 所有 risk 家族都被某一组覆盖,新增的风险叠加层不会被漏掉
risk_fams = {f for f, (_, eff) in planning._OVERLAY_FAMILIES.items() if eff == "risk"}
grouped = {f for _, fams in planning.RISK_GROUPS.values() for f in fams}
assert risk_fams == grouped, f"未归组的风险叠加层:{risk_fams - grouped}"
checks += 1

# 2. rank 真的剔除(合成房源,真实 rank)
metrics = [{"id": i, "price": 700_000 + i, "gross_yield": 0.04, "planning": p}
           for i, p in enumerate([ov("MAEO"), ov(), ov("LSIO"), ov("AEO"), {}])]
state = {"params": {**{k: None for k in g.PARAM_KEYS}, "planning_needs": ["no_airport_noise"]},
         "metrics": metrics, "lang": "zh", "user_query": "q"}
out = g.rank(state)
kept = [m["id"] for m in out.get("metrics") or []]
assert kept == [1, 2], kept                         # 1:无叠加层  2:只有洪泛,不在本次排除范围
assert "没有机场噪声叠加层" in (out.get("ranking") or ""), out.get("ranking")
checks += 2

# 3. 删一项不存在的东西 = 没改任何条件,必须澄清而不是假装生效
prev = g._sanitize({"intent": "new_search", "max_price": 1_000_000}, "q")
g._ask = lambda *_a, **_k: json.dumps({"intent": "refine", "changes": [
    {"action": "remove", "field": "unsupported_asks", "value": "机场噪音叠加层", "source": "全部排除"}]}, ensure_ascii=False)
st = g.parse_intent({"user_query": "有机场噪音叠加层的房子全部排除", "lang": "zh", "params": prev,
                     "metrics": [{"id": 1, "price": 1}]})
assert st["intent"] == "clarify", st["intent"]
checks += 1

print(f"硬排除 全部通过:{checks} 项检查(离线,不调用 LLM)")
