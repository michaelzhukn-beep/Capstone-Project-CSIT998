"""投资测算用到的假设,以及它们的出处标签。V2 第 4 项。

第一版里 NOI / Cap Rate / ROI 恒为 None,因为数据集不含运营支出。第二版引入
假设把它们算出来 —— 但**假设和数据必须能被分辨**,否则这个项目「每个数字可
追溯」的主张就垮了。

所以这个模块干三件事:
1. 持有当前假设值(启动时从 .env / 默认值来,运行中可被用户覆盖);
2. 给每个假设配一句人话说明,输出层和 LLM 都用它来标注;
3. 让每一条计算结果都能带上「我是基于哪几个假设算出来的」。

判断标准很简单:看到一个数字,能不能立刻说出它是**量出来的**、**查得到出处的**,
还是**假设出来的**。

⚠️ 印花税**不在这个模块里**。它是维州法定分档税率,有明确出处(SRO Victoria),
可以精确算,属于第二类不属于第三类 —— 见 formulas.py 的 stamp_duty_vic()。
把有出处的东西降格成「假设」,和把假设伪装成数据一样,都是把界线搞模糊。
"""

from app.core.config import OPEX_RATE, OTHER_ACQUISITION_COSTS

# 当前生效的假设。故意用可变字典而不是常量 —— 用户要能当场改(任务书 §5)。
_current = {
    "opex_rate": OPEX_RATE,
    "other_acquisition_costs": OTHER_ACQUISITION_COSTS,
}

# 每项的:人话模板、取值上下限、是比例还是金额
_SPEC = {
    "opex_rate": {
        "label": "运营支出 = 年租金的 {pct},行业惯例 25%~30%,数据集不含实际支出",
        "kind": "rate",
        "bounds": (0.0, 1.0),
    },
    "other_acquisition_costs": {
        "label": "印花税之外的购置开销 {money}(过户、验房等),粗略值,可按实际报价改",
        "kind": "money",
        "bounds": (0, 200_000),
    },
}


def opex_rate() -> float:
    return _current["opex_rate"]


def other_acquisition_costs() -> int:
    return _current["other_acquisition_costs"]


def bounds(name: str) -> tuple[float, float]:
    """某个假设的取值区间。**闸门只有一处**:CLI 的 :opex、/api/assumptions、
    详情窗里的就地试算,三条路都读这里 —— 各写一份的话,总有一条会松。"""
    if name not in _SPEC:
        raise KeyError(f"未知假设 {name!r},可用:{', '.join(_SPEC)}")
    return _SPEC[name]["bounds"]


def set_rate(name: str, value: float) -> None:
    """运行时覆盖一个假设。CLI 的 :opex / :fees 命令走这里。"""
    if name not in _SPEC:
        raise KeyError(f"未知假设 {name!r},可用:{', '.join(_SPEC)}")
    low, high = _SPEC[name]["bounds"]
    if not low <= value < high:
        raise ValueError(f"{name} 必须在 [{low}, {high}) 之间,当前是 {value}")
    _current[name] = value if _SPEC[name]["kind"] == "rate" else int(value)


def snapshot() -> dict:
    """当前假设的快照。会被塞进每一条 metrics 里,让数字和它依赖的假设绑在一起 ——
    用户改了假设之后再回头看旧结果,不会张冠李戴。"""
    return dict(_current)


def describe() -> list[str]:
    """人话版说明,给 CLI 打印、给 LLM 当事实。"""
    out = []
    for key, value in _current.items():
        spec = _SPEC[key]
        out.append(spec["label"].format(
            pct=f"{value * 100:.1f}%" if spec["kind"] == "rate" else "",
            money=f"${value:,}" if spec["kind"] == "money" else "",
        ))
    return out
