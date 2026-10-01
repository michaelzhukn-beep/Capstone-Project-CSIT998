"""估值的 K 折交叉拟合:库里每一套房的估值,都来自**没见过它**的那一折模型。

    python -m app.analytics.crossfit_valuation      # 重算并写出 models/valuation_oof.csv

为什么要这个
------------
保存的估值模型用前 80% 的成交训练。库里 20,800 套房有 16,640 套在训练集里,模型对它们给的
是**拟合值**,不是预测值:中位误差 7.0%,没见过的只有 8.94%;更糟的是异常成交会被直接记住 ——
Caulfield 一栋 4 房 155 ㎡ 独栋登记成交价 $131,000(同区其他独栋都在百万以上),模型估 $286,690,
80% 区间把 $131,000 包在里面,界面于是说「估值与售价基本相符」,等于替一条脏数据背书(审计 BUG-03)。

做法
----
1. 按「地址 + 区」分组(同一套房多次成交必须落在同一折,否则模型会从它的另一次成交里认出它);
2. 分成 K 折,每折用其余 K−1 折训练一个模型(与定稿模型同一套特征、参数和早停流程),
   预测这一折;
3. 每套房的离折对数估值写进 models/valuation_oof.csv,键是地址、区、成交价和全部特征的组合 ——
   数据库里任何一个字段变了,键就对不上,线上会退回定稿模型而不是给出过期的估值。

线上:库内房源用离折估值,库外输入(比如以后接入新房源)用定稿模型。
"""

import csv
import math
import re
import sys
from pathlib import Path

import numpy as np

from app.analytics.train_valuation import FINAL_FEATURES, SEED, TARGET, fit_xgb, load_frame
from app.analytics.valuation import OOF_PATH, oof_key
from app.core.db import close_pool

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

K = 5


def folds_by_group(df, k: int = K) -> np.ndarray:
    """每行分到哪一折。按地址+区分组后随机打散,同组必同折。"""
    groups = (df["address"].astype(str).str.strip().str.lower() + "|"
              + df["suburb"].astype(str).str.strip().str.lower())
    uniq = groups.unique()
    rng = np.random.default_rng(SEED)
    fold_of = dict(zip(uniq[rng.permutation(len(uniq))], np.arange(len(uniq)) % k))
    return groups.map(fold_of).to_numpy()


def main() -> None:
    df = load_frame().reset_index(drop=True)
    fold = folds_by_group(df)
    log_pred = np.full(len(df), np.nan)
    for f in range(K):
        train, test = df[fold != f], df[fold == f]
        model, report = fit_xgb(train, test, FINAL_FEATURES, log_target=True)
        log_pred[fold == f] = model.predict(test[FINAL_FEATURES])
        print(f"  第 {f + 1}/{K} 折:训练 {len(train):,} · 预测 {len(test):,} · "
              f"中位误差 {report['mdape'] * 100:.2f}% · {report['n_estimators']} 棵树")

    rows = df.to_dict("records")
    keys = [oof_key(r) for r in rows]
    dup = len(keys) - len(set(keys))
    with OOF_PATH.open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["key", "log_pred", "fold"])
        for key, lp, fo in zip(keys, log_pred, fold):
            w.writerow([key, f"{lp:.6f}", int(fo)])

    # 写完回读一遍,逐行确认键对得上。实测本机(Python 3.14 + numpy 2.4)出现过一次写出的键里
    # 纬度变成 "-nan" —— 同一个值 isnan() 判断为假,格式化出来却是 nan,是内存被写坏的症状。
    # 这种错不会报错,只会让那套房安静地退回训练集内的拟合值,所以必须在这里拦住。
    reread = {}
    with OOF_PATH.open(encoding="utf-8") as handle:
        for rec in csv.DictReader(handle):
            reread[rec["key"]] = float(rec["log_pred"])
    fresh = [oof_key(r) for r in load_frame().to_dict("records")]
    lost = [k for k in fresh if k not in reread]
    if lost or any(re.search(r"(?:^|\|)-?nan(?:\||$)", k) for k in reread):
        OOF_PATH.unlink()
        raise SystemExit(f"离折估值文件自检失败({len(lost)} 个键对不上,例:{lost[:2]}),已删除,请重跑。")

    err = np.abs(np.exp(log_pred) - df[TARGET]) / df[TARGET]
    print(f"\n已写入 {OOF_PATH.name}:{len(df):,} 行(键重复 {dup} 个 —— 重复行特征与售价完全相同,估值也相同)")
    print(f"离折估值中位误差(全库,每套都没被自己的模型见过):{np.median(err) * 100:.2f}%")
    for t, g in df.assign(_e=err).groupby("property_type", observed=True):
        print(f"  {str(t):<10}{np.median(g['_e']) * 100:>6.2f}%  n={len(g):,}")
    assert not math.isnan(float(log_pred.sum())), "有行没被任何一折预测到"


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
