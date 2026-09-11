"""投资公式的验收(V1_TASKS.md 第 4 步 + V2 支出假设)。纯函数,不需要数据库、不需要模型。

    python tests/test_formulas.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics.formulas import cap_rate, gross_yield, noi, roi, stamp_duty_vic

# --- 任务书里逐字列出的四条 ---
assert gross_yield(32760, 780000) == 0.042
assert gross_yield(None, 780000) is None
assert gross_yield(32760, 0) is None
assert noi(32760, None) is None

# --- 铁律 1:任一输入 None -> None ---
assert gross_yield(32760, None) is None
assert noi(None, 8000) is None
assert cap_rate(None, 780000) is None
assert roi(None, 100000) is None

# --- 铁律 2:分母 0 或 None -> None,不抛 ZeroDivisionError ---
assert cap_rate(24760, 0) is None
assert cap_rate(24760, None) is None
assert roi(5000, 0) is None
assert roi(5000, None) is None

# --- 铁律 3:比例是小数,不是百分数 ---
assert gross_yield(50000, 1000000) == 0.05
assert cap_rate(40000, 1000000) == 0.04
assert roi(20000, 100000) == 0.2

# --- 能算的就得算对 ---
assert noi(32760, 8000) == 24760
assert cap_rate(noi(32760, 8000), 780000) == 24760 / 780000

# --- 第一版现实:缺 operating_expenses,链条一路 None ---
oe = None
assert noi(32760, oe) is None
assert cap_rate(noi(32760, oe), 780000) is None

# --- V2:支出假设进来之后,这三个从「恒为 None」变成「算得出来」 ---
# 公式本身一个字没改 —— 变的只是调用方传了什么进来。这正是第一版
# 「函数照写,先返回 None」的价值:第二版补上假设,调用方零改动。
rent, price, opex_rate = 32760, 780000, 0.28
opex = round(rent * opex_rate)
assert opex == 9173
assert noi(rent, opex) == 23587
assert abs(cap_rate(noi(rent, opex), price) - 23587 / 780000) < 1e-12

# --- 维州印花税:法定分档税率,不是假设 ---
# 出处:SRO Victoria,非自住(投资房)税率,适用 2008-05-06 ~ 2021-06-30 合同,
# 覆盖本数据集的成交期(2016-01 ~ 2018-03)。
assert stamp_duty_vic(25_000) == 350                    # 1.4%
assert stamp_duty_vic(130_000) == 2_870                 # 350 + 2.4% × 105,000
assert stamp_duty_vic(240_000) == 9_470                 # 2,870 + 6% × 110,000
assert stamp_duty_vic(960_000) == 52_670
assert stamp_duty_vic(1_300_000) == 71_500              # 最高档:全额 5.5%
assert stamp_duty_vic(0) == 0
assert stamp_duty_vic(None) is None
assert stamp_duty_vic(-5) is None

# 分档必须连续,不能在档位边界跳变(最高一档除外 —— 法定表本身有个小台阶)
for boundary in (25_000, 130_000):
    assert stamp_duty_vic(boundary) == stamp_duty_vic(boundary + 1)

# 累进的意义:便宜房子的实际税率必须明显低于最高档的 5.5%
assert stamp_duty_vic(240_000) / 240_000 < 0.04
assert abs(stamp_duty_vic(1_300_000) / 1_300_000 - 0.055) < 1e-9
# 这正是不能用固定 5.5% 的原因:24 万的房会被高估近三成购置税
assert round(240_000 * 0.055) - stamp_duty_vic(240_000) > 3_000

# --- ROI 的分母必须是总投入,不能是房价,否则它和 Cap Rate 是同一个数 ---
total_cost = price + stamp_duty_vic(price) + 2_000
assert roi(noi(rent, opex), total_cost) < cap_rate(noi(rent, opex), price)

print("formulas 全部通过。")
