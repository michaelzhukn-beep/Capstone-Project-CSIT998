"""注册表自洽性检查。V5。

不需要数据库、不需要 LLM、不联网。

    python tests/test_registry.py

**这套测试是"可持续扩展"的保险。** 注册表变成唯一真相源之后,风险从"忘了改
五个地方"变成了"注册表里写错一处,系统安静地失效"。所以这里逐条遍历注册表,
把所有"写错了但不会报错"的情况变成会报错的情况:

  - 属性引用了不存在的证据 -> 那个属性永远算不出分,但不报错
  - 数据源没被任何属性用到 -> 白抓数据,白占体积
  - 权重加起来不是 1     -> 分数尺度会漂,和别的属性不可比
  - 同义词重复           -> 两个属性抢同一个说法,映射不确定
  - 不支持的类别和支持的属性重名 -> 系统自相矛盾
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.amenities.registry import (
    ATTRIBUTES, BY_TYPE_KEYS, CONFLICTS, PROPERTY_EVIDENCE, RESAMPLE_M, SOURCES,
    SUBURB_EVIDENCE, UNSUPPORTED, USER_FACING_KINDS, all_evidence_keys, amenity_kinds_block,
    evidence_key, evidence_label, prompt_block, unsupported_block, used_evidence_keys,
)

# ---------------------------------------------------------------- 数据源

REQUIRED = {"match", "zh", "geometry", "measure", "user_facing"}
for kind, source in SOURCES.items():
    missing = REQUIRED - set(source)
    assert not missing, f"数据源 {kind} 缺字段:{missing}"
    assert source["geometry"] in ("point", "line", "area"), kind
    assert source["measure"] in ("nearest", "count"), kind
    if source["measure"] == "count":
        assert source.get("radius_m", 0) > 0, f"{kind} 是密度类却没给半径"
    key, values = source["match"]
    assert values == "*" or (isinstance(values, tuple) and values), f"{kind} 的 match 取值有问题"

# 线/面要素必须靠重采样取点 —— 取质心毫无意义(一条 20 公里的高速,
# 质心可能在离你 10 公里的地方)
assert 20 <= RESAMPLE_M <= 100, "重采样间距不合理"

# 证据键不能撞车
keys = [evidence_key(k) for k in SOURCES]
assert len(keys) == len(set(keys)), "两个数据源产出了同一个证据键"
# 证据有三种来源:OSM 数据源、房源自身的列、按区查表。三类合起来就是全集。
assert set(all_evidence_keys()) == set(keys) | set(PROPERTY_EVIDENCE) | set(SUBURB_EVIDENCE)

# 每个证据键都要有中文标签和单位
for key in all_evidence_keys():
    label, unit = evidence_label(key)
    assert label and label != key, f"证据 {key} 没有中文标签"
    assert unit, f"证据 {key} 没有单位"

# ---------------------------------------------------------------- 属性

used = used_evidence_keys()
known = set(all_evidence_keys()) | {"bedrooms_many"}

for name, spec in ATTRIBUTES.items():
    assert spec.get("zh"), f"属性 {name} 没有中文名"
    assert spec.get("note"), f"属性 {name} 没有说明 —— 说不清依据什么的属性不该存在"
    assert spec.get("synonyms"), f"属性 {name} 没有同义词,LLM 映射不上"
    assert spec.get("parts"), f"属性 {name} 没有任何证据依据"

    total = 0.0
    for key, value in spec["parts"].items():
        assert key in known, f"属性 {name} 引用了不存在的证据 {key} —— 它会永远算不出分"
        direction, weight = value
        assert direction in ("near", "far", "many", "few"), f"{name}.{key} 方向 {direction} 非法"
        assert 0 < weight <= 1, f"{name}.{key} 权重 {weight} 不合理"
        total += weight
    # 权重和必须是 1:不然不同属性的分数尺度不一样,放在一起比就是错的
    assert abs(total - 1.0) < 1e-9, f"属性 {name} 的权重和是 {total:.3f},应为 1"

# 数量门槛只管**参与打分**的源。分位数需要足够样本才有意义,50 个以下
# 算出来的分位全是噪声。而只回答"最近的 X 在哪"的源不受这条限制 ——
# 大墨尔本本来就只有 26 个机场,这不是数据缺失,是现实如此。
for kind, source in SOURCES.items():
    count = source.get("count")
    if count is not None and evidence_key(kind) in used:
        assert count >= 50, (
            f"{kind} 只有 {count} 个却被用于打分 —— 分位数会全是噪声。"
            "要么别用它打分,要么换个数据源。")

# 按区查表的证据粒度比点级粗一个数量级,标签里必须写明,免得输出时忘了标注
for key, meta in SUBURB_EVIDENCE.items():
    assert "LGA" in meta["zh"] or "区" in meta["zh"], f"{key} 的标签没体现粒度"

# 抓了却既不打分、也不给用户看的源 = 白抓、白占体积
waste = [k for k in SOURCES
         if evidence_key(k) not in used and not SOURCES[k]["user_facing"]]
assert not waste, f"这些源既不参与打分也不对用户可见,要么用起来要么删掉:{waste}"

# 一个说法不该同时属于两个属性 —— 那样映射到哪个是不确定的
seen = {}
for name, spec in ATTRIBUTES.items():
    for word in spec["synonyms"]:
        assert word not in seen, f"同义词「{word}」同时属于 {seen[word]} 和 {name}"
        seen[word] = name

# 互斥对里的属性必须真实存在
for a, b in CONFLICTS:
    assert a in ATTRIBUTES and b in ATTRIBUTES, f"互斥对 {a}/{b} 引用了不存在的属性"

# ---------------------------------------------------------------- 不支持清单

assert len(UNSUPPORTED) >= 8, "明确列出'没有这项数据'的类别太少"
assert all(v.strip() for v in UNSUPPORTED.values()), "每一项都要写清为什么没有"
# 不支持的类别不能和支持的属性重名 —— 那会让系统自相矛盾
assert not (set(UNSUPPORTED) & {s["zh"] for s in ATTRIBUTES.values()})
# 治安必须在不支持清单里:库里有警察局位置,但警察局离得近**不等于**治安好
# (市中心警局最密集)。把它做成"安全评分"是典型的伪科学。
assert any("治安" in k for k in UNSUPPORTED)
assert "police" in SOURCES, "警察局位置本身是可以显示的事实,只是不能当治安指标"

# ---------------------------------------------------------------- 生成出来的提示词片段

attrs_block = prompt_block()
for name, spec in ATTRIBUTES.items():
    assert name in attrs_block and spec["zh"] in attrs_block, f"{name} 没出现在生成的提示词里"
    assert spec["synonyms"][0] in attrs_block

kinds_block = amenity_kinds_block()
for kind in USER_FACING_KINDS:
    assert kind in kinds_block, f"{kind} 没出现在设施清单里"
# 非 user_facing 的不该出现 —— 列出来会诱导模型误用
for kind, source in SOURCES.items():
    if not source["user_facing"]:
        assert f"{kind:<18}" not in kinds_block, f"{kind} 不该出现在给用户的设施清单里"

unsup_block = unsupported_block()
for name in UNSUPPORTED:
    assert name in unsup_block

assert set(BY_TYPE_KEYS) <= set(all_evidence_keys())

# ---------------------------------------------------------------- 英文标签的覆盖
# 加了新属性 / 新设施 / 新证据 / 新分区,却忘了在 app/i18n.py 里配英文 ——
# 这件事**不会报错**,只会让英文界面上突然冒出一句中文,而且要等演示时才被人看见。
# 所以在这里挡住:少一个键就在测试里炸。
from app import i18n as _i18n                                       # noqa: E402

_missing = _i18n.check()
assert not _missing, "英文标签缺这些键(见 app/i18n.py):\n  " + "\n  ".join(_missing)

print(f"注册表自洽 —— {len(SOURCES)} 个数据源 · {len(ATTRIBUTES)} 个属性 · "
      f"{len(UNSUPPORTED)} 类明确不支持 · 英文标签无缺口,全部通过。")
