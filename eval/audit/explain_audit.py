"""解释文字审计(TEST_PLAN.md L2)。跑完整图(含 LLM),检查售价落在 80% 区间内的房源
有没有被说成低估/高估/便宜/捡漏。

    python -m eval.audit.explain_audit
"""

import json
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langgraph.checkpoint.memory import MemorySaver     # noqa: E402

from app.orchestration.graph import build_graph, new_session  # noqa: E402

QUERIES = ["Richmond 附近被低估的房子", "找估值高于售价的两房,100万以内", "Brunswick 的房子,估值和售价比怎么样",
           "Footscray 100万以内的房子", "80万以内最便宜的房子"]
RUNS = 2
# 「最便宜」「更便宜」是五套之间比价格,不是估值判断,不计
CLAIM = re.compile(r"低估|高估|(?<![最更较])便宜|捡漏|偏贵|卖贵|划算|underval|overval|bargain")
OUT = Path(__file__).resolve().parent / "results"
GRAPH = build_graph(MemorySaver())

# 和 server.py 启动时一样先预热。不预热就并发跑会撞上 valuation._load 的竞态(见 BUGS.md)。
from app.api.server import warm_up as _server_warm_up  # noqa: E402
_server_warm_up()


def one(q):
    tid = str(uuid.uuid4())
    config = new_session(tid)
    out = GRAPH.invoke({"user_query": q, "lang": "zh"}, config)
    return out


def segments(answer, metrics):
    """回答用「第 N 套」指代房源,也可能直接写地址。按行切,一行只归给它点名的那几套。
    一行点名了多套时,只有**全部**都在区间内才归责(否则分不清那个词说的是谁)。"""
    segs = []
    for line in answer.splitlines():
        idx = {int(n) for grp in re.findall(r"第\s*([1-5](?:\s*[、,和与/]\s*[1-5])*)\s*套", line)
               for n in re.findall(r"[1-5]", grp)}
        idx |= {i + 1 for i, m in enumerate(metrics) if m.get("address") and m["address"] in line}
        named = [metrics[i - 1] for i in sorted(idx) if i <= len(metrics)]
        if named:
            segs.append((named, line))
    return segs


def main():
    jobs = [q for q in QUERIES for _ in range(RUNS)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        outs = list(ex.map(one, jobs))
    rows, bad = [], 0
    for q, out in zip(jobs, outs):
        answer = out.get("answer") or ""
        for named, seg in segments(answer, out.get("metrics") or []):
            hits = CLAIM.findall(seg)
            # 「并非低估」「不能算便宜」这类否定句是正确的,不算违规
            neg = re.findall(r"(不|非|并非|不能算|不算|谈不上|没有|别)[^,。;，；]{0,8}(低估|高估|便宜|捡漏|偏贵|划算)", seg)
            within = all(m.get("valuation_position") == "within" for m in named)
            viol = within and len(hits) > len(neg)
            # 方向:below = 售价低于区间 = 估值高于售价;above 反之。只点名一套时才判,多套一行分不清在说谁
            if len(named) == 1:
                pos = named[0].get("valuation_position")
                says_up = re.search(r"估值[^,。;，；]{0,6}高于(售价|成交价)", seg)
                says_down = re.search(r"估值[^,。;，；]{0,6}低于(售价|成交价)", seg)
                if (pos == "below" and says_down) or (pos == "above" and says_up):
                    viol = True
                    hits = hits + ["方向写反"]
            bad += viol
            rows.append({"q": q, "ids": [m["id"] for m in named], "positions": [m.get("valuation_position") for m in named],
                         "claims": hits, "negated": len(neg), "violation": viol, "text": seg[:400]})
            print(f"[{'FAIL' if viol else 'PASS'}] «{q}» {rows[-1]['ids']} {rows[-1]['positions']} 用词={hits} 否定={len(neg)}")
            if viol:
                print("       " + seg[:300])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "explain_audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n违规 {bad}/{len(rows)} 段")


if __name__ == "__main__":
    main()
