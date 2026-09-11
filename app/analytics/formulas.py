"""投资指标公式。V1_TASKS.md 第 4 步。

四个纯函数:零依赖、不碰数据库、不碰 LLM、不碰配置。
所以它们能用手写字典测(见 tests/test_formulas.py),这就是
PROJECT.md 5.5「计算与取数分离」的价值 —— 答辩会问。

三条铁律(PROJECT.md 5.7):
1. 任一输入是 None -> 返回 None。不用 0 兜底。
2. 分母是 0 或 None -> 返回 None。不让 ZeroDivisionError 炸到用户面前。
3. 比例返回小数(0.042 就是 4.2%)。格式化成百分号是展示层的活,
   数字在系统内部保持纯数字。

为什么算不出来宁可返回 None:代码编造数字和 LLM 编造数字危害等同,
都违反本项目"每个数字可追溯"的核心主张。
"""


def gross_yield(annual_rent: int | None, price: int | None) -> float | None:
    """毛租金回报率 = 年租金 / 房价。

    >>> gross_yield(32760, 780000)
    0.042
    """
    if annual_rent is None or not price:
        return None
    return annual_rent / price


def noi(annual_rent: int | None, operating_expenses: int | None) -> int | None:
    """净营运收入 = 年租金 − 运营支出。

    第一版数据集不含 operating_expenses,所以这个函数会一直返回 None。
    这是正确行为,不是 bug —— 函数照写,第二版补上支出假设后
    调用方一行都不用改。
    """
    if annual_rent is None or operating_expenses is None:
        return None
    return annual_rent - operating_expenses


def cap_rate(noi_value: int | None, price: int | None) -> float | None:
    """资本化率 = NOI / 房价。NOI 算不出来时它自然也算不出来。"""
    if noi_value is None or not price:
        return None
    return noi_value / price


def roi(net_gain: int | None, total_cost: int | None) -> float | None:
    """投资回报率 = 净收益 / 总成本。"""
    if net_gain is None or not total_cost:
        return None
    return net_gain / total_cost


# 维州土地转让税(印花税)—— **非自住**(投资房)税率表。
# 本项目是给投资者用的,投资房不适用自住优惠,所以用的是 non-principal
# place of residence 这一套。
#
# 出处:State Revenue Office Victoria,"Land transfer duty – non-principal
# place of residence (historical rates)",适用于 2008-05-06 至 2021-06-30
# 之间签订的合同。本数据集的成交日期是 2016-01 至 2018-03,**完全落在这个
# 区间内**,所以用这张表在时间口径上是自洽的。
#
# ⚠️ 2021-07-01 起新增了 200 万以上的高档税率($110,000 + 超出部分 6.5%),
# 现行表与此表仅此一处不同。若日后换用近期成交数据,记得改这张表。
#
# 每档是 (上限, 起征基数, 该档税率, 起算门槛);上限 None 表示最高一档。
# 最高一档的算法不同 —— 它是对**全额**征 5.5%,不是"基数 + 超出部分",
# 所以门槛写 0、基数写 0。
_VIC_DUTY_BRACKETS = (
    (25_000,    0,     0.014, 0),
    (130_000,   350,   0.024, 25_000),
    (960_000,   2_870, 0.06,  130_000),
    (None,      0,     0.055, 0),
)


def stamp_duty_vic(price: int | None) -> int | None:
    """按维州法定税率表算印花税。

    **这不是假设,是法条。** 和 NOI / Cap Rate 那几个不一样 —— 那几个建立在
    "运营支出占租金 28%" 这种行业惯例上,这个有明确出处、可以逐条核对。
    所以它在输出里不打 ~ 标记。

    税制是**分档累进**的,不是一个固定百分比。这一点很要紧:
      $240,000 的房子 -> $9,470,实际税率 3.9%
      $430,000 的房子 -> $20,870,实际税率 4.9%
      $960,000 的房子 -> $52,800,实际税率 5.5%
    之前用固定 5.5% 会**高估便宜房子的购置成本、从而低估它们的 ROI**,
    而系统主推的高回报房恰恰都是便宜房 —— 偏差正好打在最关键的地方。
    """
    if price is None or price < 0:
        return None
    for cap, base, rate, threshold in _VIC_DUTY_BRACKETS:
        if cap is None or price <= cap:
            return int(round(base + rate * (price - threshold)))
    return None


def investment_metrics(price, annual_rent, opex_rate: float, other_costs: float) -> dict:
    """房价 + 年租金 + 两个假设 -> 一整套投资指标。

    **为什么要把这几行单独抽出来。** 详情窗里那两个假设现在是可以就地改的:
    改完总成本、NOI、回报率必须立刻跟着变。最省事的做法是在前端用 JS 再算一遍
    —— 也是最容易出事的做法:两处公式哪天不一致,页面上的数字会**安静地**和
    后端对不上,不报错、不告警,只是错。所以前端改完调 /api/recalc,
    走的还是这一个函数,和 analyze 节点用的完全是同一份实现。

    每一项的口径见上面各自的函数;这里只负责把它们串起来,不引入新规则。
    """
    operating_expenses = (
        int(round(annual_rent * opex_rate)) if annual_rent is not None else None
    )
    noi_value = noi(annual_rent, operating_expenses)
    # 钱一律取整到元。管线里 annual_rent 来自数据库、本来就是整数,而
    # /api/recalc 收到的是 JSON 数字(浮点)—— 不取整的话同一套房在两条路上
    # 会返回 14939 和 14939.0,比对起来像是两个不同的值。
    if noi_value is not None:
        noi_value = int(round(noi_value))
    duty = stamp_duty_vic(price)
    total_cost = price + duty + other_costs if price and duty is not None else None
    return {
        "gross_yield": gross_yield(annual_rent, price),   # 只用真实数据,不含假设
        "operating_expenses": operating_expenses,
        "noi": noi_value,
        "cap_rate": cap_rate(noi_value, price),
        "roi": roi(noi_value, total_cost),
        "stamp_duty": duty,
        "total_cost": int(total_cost) if total_cost is not None else None,
    }
