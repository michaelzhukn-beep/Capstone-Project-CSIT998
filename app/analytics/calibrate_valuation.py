"""给估值加上**有明确把握、而且验证过**的价格区间(分房型的分割保形预测)。

    python -m app.analytics.calibrate_valuation --measure   # 只测量、打印报告,不写文件
    python -m app.analytics.calibrate_valuation             # 测量 + 把区间参数写进 valuation_meta.json

为什么要这个
------------
原来的区间是 `估值 × (1 ± 该房型中位误差)`。中位误差的定义就是「一半房子错得比它少」,
所以真实成交价**只有约一半的机会**落在区间里 —— 可界面上的「72 万 – 88 万」会被读成
「真实价格八九不离十就在这中间」。数字本身没错,给人的把握却比它实际的大。

做法:分割保形预测(split conformal prediction)
----------------------------------------------
1. 校准集是**全库的离折估值**(crossfit_valuation.py):每套房的估值都来自没见过它的那一折模型,
   也就是界面上实际显示的那个数;
2. 算每套的对数误差 |log(成交价) − log(离折估值)|;
3. 取这批误差的 ⌈(n+1)·level⌉ 小的那个值 q;
4. 区间 = [估值 · e^(−q), 估值 · e^(+q)]。

只要"新房子"和校准集是同一类样本,这个区间覆盖真实价格的概率**至少是 level**,
不依赖模型对不对、误差是不是正态 —— 这是这个方法的保证,也是选它的原因。
分房型各算一个 q(Mondrian 保形):公寓的误差比独栋大,共用一个 q 会让公寓的区间名不副实。

怎么证明「说 80% 就是 80%」
----------------------------
校准集随机对半分 500 次:一半算 q,另一半数真实价格落进区间的比例。报告里给出
平均覆盖率和 5%–95% 的波动范围 —— 这就是界面上「实测覆盖率」的出处。

必须如实交代的一个口径
----------------------
离折用的是随机分组:模型见过同一时期的其他成交,比真正"用过去估未来"乐观。所以每个房型的 q
还要和定稿模型在时间留出集(2018 年那批)上的 q 比一下,取更宽的那个;公寓在 2018 年只剩几十套,
样本不够时不参与比较。

以前的做法是只拿时间留出集校准,而界面对训练集内的 80% 房源显示的是拟合值 —— 校准的对象和展示的
对象不是同一批数,异常成交价还会被模型原样记住(审计 BUG-03)。
"""

import json
import math
import sys

import numpy as np

from app.analytics import valuation
from app.analytics.train_valuation import FINAL_FEATURES, META_PATH, SEED, TARGET, load_frame, split
from app.core.db import close_pool

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LEVELS = (0.8, 0.9)
# 界面上展示的那一档。90% 的区间在独栋上要放到 −22%/+29%,宽到几乎没有参考价值;
# 80% 是 −17%/+21%,实测覆盖率 500 次重复都落在 78%–82%,既有用又站得住。
DISPLAY_LEVEL = 0.8
REPEATS = 500
MIN_GROUP = 100              # 某房型在时间留出集里少于这个数时,不拿时间留出集的 q 去放宽(样本太少不稳)


def conformal_q(residuals: np.ndarray, level: float) -> float:
    """分割保形的分位数:第 ⌈(n+1)·level⌉ 小的残差。样本不够时返回 inf(区间无界 —— 如实表示"不知道")。"""
    n = len(residuals)
    k = math.ceil((n + 1) * level)
    if n == 0 or k > n:
        return math.inf
    return float(np.sort(residuals)[k - 1])


def half_width_pct(q: float) -> tuple[float, float]:
    """对数区间换成相对估值的上下幅度:下限 −(1−e^−q),上限 +(e^q−1)。"""
    return 1 - math.exp(-q), math.exp(q) - 1


def predict_log(df) -> np.ndarray:
    model, meta = valuation._load()
    rows = df[FINAL_FEATURES + ["address"]].to_dict("records")
    return model.predict(valuation._to_frame(rows, meta))


def main(write: bool) -> None:
    df = load_frame()
    train, hold = split(df, "time")
    _, meta = valuation._load()

    log_true = np.log(df[TARGET].to_numpy(dtype=float))
    log_pred = predict_log(df)
    df = df.assign(_res=np.abs(log_true - log_pred), _pred=np.exp(log_pred))
    hold = df.loc[hold.index]

    # ---- 0. 先确认:保存的模型真的只见过训练那 80% ----
    def mdape(frame, col="_pred"):
        return float(np.median(np.abs(frame[TARGET] - frame[col]) / frame[TARGET]))
    print(f"定稿模型留出集(2018 年那批,{len(hold):,} 套)中位误差 {mdape(hold)*100:.2f}%"
          f"(meta 记录 {meta['metrics']['mdape']*100:.2f}%)")
    if abs(mdape(hold) - meta["metrics"]["mdape"]) > 0.002:
        raise SystemExit("留出集误差与训练时记录的不一致:数据库或模型已变,不能沿用这个划分做校准。")

    # ---- 1. 离折估值:库里每套房都由没见过它的那一折模型估出(crossfit_valuation.py)----
    # 界面上显示的就是这个数,所以区间也按它的误差来校准 —— 校准的对象和展示的对象必须是同一个。
    oof = valuation._load_oof()
    keys = [valuation.oof_key(r) for r in df.to_dict("records")]
    missing = sum(k not in oof for k in keys)
    if missing:
        raise SystemExit(f"{missing} 套房源查不到离折估值:先跑 python -m app.analytics.crossfit_valuation")
    log_oof = np.array([oof[k] for k in keys])
    df = df.assign(_res_oof=np.abs(log_true - log_oof), _pred_oof=np.exp(log_oof))
    hold = df.loc[hold.index]
    print(f"离折估值中位误差:全库 {mdape(df, '_pred_oof')*100:.2f}% · 其中 2018 年那批 {mdape(hold, '_pred_oof')*100:.2f}%\n")

    rng = np.random.default_rng(SEED)
    types = sorted(df["property_type"].astype(str).unique())
    result = {"levels": {}, "repeats": REPEATS, "n_calibration": int(len(df)),
              "calibration": "K-fold out-of-fold residuals on all rows; q = max(OOF, time-split holdout) per type"}

    for level in LEVELS:
        print(f"==== 标称把握 {level:.0%} ====")
        print(f"  {'房型':<10}{'校准n':>7}{'区间(下/上)':>18}{'实测覆盖(均值)':>14}{'5%–95%':>16}{'2018批覆盖':>11}")
        per_type = {}
        for t in types + ["__all__"]:
            g = df if t == "__all__" else df[df["property_type"].astype(str) == t]
            h = hold if t == "__all__" else hold[hold["property_type"].astype(str) == t]
            r = g["_res_oof"].to_numpy()
            # 离折用的是随机分组,模型见过同时期的成交,比"用过去估未来"乐观。时间留出集样本够时,
            # 两者取更宽的那个 —— 两个诚实的估计不一致时,给用户看更保守的。
            # 公寓在 2018 年那批只剩几十套,q 不稳定,这时只用离折的。
            q_time = conformal_q(h["_res"].to_numpy(), level) if len(h) >= MIN_GROUP else 0.0
            covs = []
            for _ in range(REPEATS):
                idx = rng.permutation(len(r))
                cal, ev = r[idx[: len(r) // 2]], r[idx[len(r) // 2:]]
                # 验证的是**实际上线的那条规则**(含按时间留出集放宽),不然报出的覆盖率和界面上的区间对不上
                covs.append(float(np.mean(ev <= max(conformal_q(cal, level), q_time))))
            q_oof = conformal_q(r, level)
            widened = q_time > q_oof
            q_full = max(q_oof, q_time)
            cov_hold = float(np.mean(h["_res_oof"].to_numpy() <= q_full)) if len(h) else float("nan")
            lo, hi = half_width_pct(q_full)
            covs = np.array(covs)
            print(f"  {t:<10}{len(r):>7}{f'-{lo:.1%} / +{hi:.1%}':>18}{covs.mean():>14.1%}"
                  f"{f'{np.percentile(covs,5):.1%}–{np.percentile(covs,95):.1%}':>16}{cov_hold:>11.1%}"
                  + ("   (按时间留出集放宽)" if widened else ""))
            per_type[t] = {"q": q_full, "n": int(len(r)), "down_pct": lo, "up_pct": hi,
                           "coverage_mean": float(covs.mean()), "coverage_p5": float(np.percentile(covs, 5)),
                           "coverage_p95": float(np.percentile(covs, 95)), "coverage_2018_rows": cov_hold,
                           "widened_by_time_split": bool(widened)}
        result["levels"][str(level)] = per_type
        print()

    # ---- 用区间判断"低于估值"会怎样 ----
    lv = result["levels"][str(DISPLAY_LEVEL)]
    q = df["property_type"].astype(str).map(lambda t: lv.get(t, lv["__all__"])["q"])
    below_oof = float(np.mean(df[TARGET] < df["_pred_oof"] * np.exp(-q)))
    below_fit = float(np.mean(df.loc[train.index, TARGET] < df.loc[train.index, "_pred"] * np.exp(-q[train.index])))
    print(f"售价低于 {DISPLAY_LEVEL:.0%} 区间下限的比例:离折估值 {below_oof:.1%}"
          f"(按定义约 {(1-DISPLAY_LEVEL)/2:.0%})· 旧做法训练集内拟合值 {below_fit:.1%}")

    if write:
        meta_json = json.loads(META_PATH.read_text(encoding="utf-8"))
        meta_json["conformal"] = {**result, "display_level": DISPLAY_LEVEL,
                                  "note": "区间 = 估值·e^(∓q),q 为分房型分割保形分位数;"
                                          "coverage_* 为全库离折残差随机对半 500 次的实测覆盖率(含按时间留出集放宽的规则)"}
        META_PATH.write_text(json.dumps(meta_json, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {META_PATH.name} 的 conformal 段")


if __name__ == "__main__":
    try:
        main(write="--measure" not in sys.argv)
    finally:
        close_pool()
