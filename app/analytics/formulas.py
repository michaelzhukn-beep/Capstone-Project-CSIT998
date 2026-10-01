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
      $960,000 的房子 -> $52,670,实际税率 5.5%(超过 $960,000 才整体按 5.5% 计)
    之前用固定 5.5% 会**高估便宜房子的购置成本、从而低估它们的 ROI**,
    而系统主推的高回报房恰恰都是便宜房 —— 偏差正好打在最关键的地方。
    """
    # 价格为 0 不是"免税",是价格不可用 —— 和其他公式一样返回 None,不拿 0 冒充
    if price is None or price <= 0:
        return None
    # 取整按《Duties Act 2000》(Vic) 第 28(1) 条:取最近的整元,**恰好是若干元加 50 分时
    # 取较低的整元**(半数向下)。只改取整,税率表仍是上面的历史表。
    # 不能用 round():Python 是银行家舍入,整数部分为奇数时多算 1 元($130,125 -> $2,877.50,
    # 法定 $2,877,round 给 $2,878)。也不能靠浮点:本该恰好 .50 的金额可能算成 .4999…/.5000…。
    # 税率都是千分之整数,所以以「千分之一元」为单位整数精确计算。
    # 不用模块级 import —— ROI 离线测试会把本函数单独抽出来执行。
    for cap, base, rate, threshold in _VIC_DUTY_BRACKETS:
        if cap is None or price <= cap:
            if float(price).is_integer():
                milli = base * 1000 + round(rate * 1000) * (int(price) - threshold)
                dollars, rest = divmod(milli, 1000)
            else:       # 非整数价格(库里是整数列,不该出现):浮点兜底,同一取整规则
                exact = base + rate * (price - threshold)
                dollars, rest = int(exact), (exact - int(exact)) * 1000
            return dollars + (1 if rest > 500 else 0)
    return None


def _duty_unrounded(price: float) -> float:
    """印花税,不取整(只供 ROI 预排序用;对外数字一律用 stamp_duty_vic)。price 必须 > 0。"""
    for cap, base, rate, threshold in _VIC_DUTY_BRACKETS:
        if cap is None or price <= cap:
            return base + rate * (price - threshold)
    raise AssertionError("unreachable: last bracket has no cap")


def roi_unrounded(price, annual_rent, opex_rate: float, other_costs: float) -> float | None:
    """ROI 不取整版:annual_rent × (1 − opex) ÷ (price + 未取整印花税 + 杂费)。与 roi_order_sql 同一个式子。
    价格 ≤ 0 或缺租金 -> None(和 investment_metrics 一致)。"""
    if price is None or annual_rent is None or price <= 0:
        return None
    total = price + _duty_unrounded(price) + other_costs
    return annual_rent * (1 - opex_rate) / total if total > 0 else None


def roi_order_sql(rent_col: str = "annual_rent", price_col: str = "price",
                  opex_param: str = "%(opex_rate)s::float8", fees_param: str = "%(other_costs)s::float8") -> str:
    """ROI(不取整)的 SQL 表达式,供检索层 ORDER BY 取候选池;**税档直接由 _VIC_DUTY_BRACKETS 生成**,不另抄税率表。

    为什么只做「预排序」而不宣称精确:investment_metrics 把运营支出和印花税各取整到元,SQL 这一版不取整,
    两者对极接近的房源可能反序。所以最终排序仍用 Python 的 ROI,并用 roi_certified_prefix 证明**哪几名**不可能被
    候选池外的房源超过;证明不了的,调用方必须如实披露。价格 ≤ 0 或缺租金 -> NULL(排最后)。
    """
    p = price_col
    whens, tail = [], None
    for cap, base, rate, threshold in _VIC_DUTY_BRACKETS:
        term = f"{base} + {rate} * ({p} - {threshold})"
        if cap is None:
            tail = term
        else:
            whens.append(f"WHEN {p} <= {cap} THEN {term}")
    duty = f"CASE WHEN {p} <= 0 THEN NULL {' '.join(whens)} ELSE {tail} END"
    return f"(({rent_col} * (1 - {opex_param})) * 1.0 / NULLIF({p} + ({duty}) + {fees_param}, 0))"


def roi_certified_prefix(rois_desc: list, cutoff: float | None, other_costs: float) -> int:
    """候选池内、按 ROI 降序排好的结果里,**前几名**可以证明不会被池外房源超过(返回个数)。

    证明:池外任何一套的「不取整 ROI」≤ cutoff(池里最后一套的不取整 ROI,SQL 按它排序截断)。
    Python 取整后的 ROI 与不取整版相差至多 δ = (0.5 + 1.5·ROI) / (杂费 − 0.5):
      分子(年租金 − 取整的运营支出)至多差 0.5;分母(房价 + 取整的印花税 + 杂费,再 int())至多差 1.5,
      且分母不小于杂费 − 0.5(房价 ≥ 1)。所以池外任何一套的取整 ROI < cutoff + δ(cutoff)。
      池内某名的 Python ROI 严格大于这个上界,它就不可能被池外的超过 —— 与数据库怎么处理并列、
      浮点、取整的细节无关(1e-9 留给 SQL 浮点与 Python 浮点的差)。
    cutoff 为 None:池没被截断,或截断处已是 NULL-ROI,所有有 ROI 的房源都在池里 -> 全部成立。
    杂费 ≤ 0.5 时分母没有下界,证明不了,返回 0。
    """
    if cutoff is None:
        return len(rois_desc)
    denom = float(other_costs) - 0.5
    if denom <= 0:
        return 0
    threshold = cutoff + (0.5 + 1.5 * cutoff) / denom + 1e-9
    n = 0
    for r in rois_desc:
        if r is None or not r > threshold:
            break
        n += 1
    return n


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
