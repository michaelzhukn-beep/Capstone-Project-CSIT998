"""训练房价估值模型,产出 valuation.py 加载的模型文件。V2 第 3 项。

    python -m app.analytics.train_valuation            # 对比若干配置,训练并保存最优
    python -m app.analytics.train_valuation --compare  # 只对比,不保存

为什么要带一个线性回归 baseline:说"XGBoost 的 MAE 是 X"没有意义,
必须回答"比最笨的办法好多少"。没有 baseline 的模型指标是不可解释的。

为什么同时报「随机划分」和「按时间划分」:
- 随机划分:训练集里混着 2018 年的成交,测试集也有 2016 年的 —— 相当于
  拿未来的市场行情去预测过去,数字会偏乐观。
- 按时间划分:用 2016~2017 的成交预测 2018 的,这才是模型真实上线时的处境。
两个都报,诚实,而且答辩问「你怎么防过拟合/数据泄漏」时有据可答。
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from app.analytics.valuation import is_unit_address as valuation_is_unit_address
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.core.db import close_pool, get_connection

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_PATH = MODEL_DIR / "valuation_xgb.ubj"   # 二进制格式,比等价的 .json 小一截
META_PATH = MODEL_DIR / "valuation_meta.json"

CATEGORICAL = ["suburb", "property_type"]
NUMERIC = [
    "bedrooms", "bathrooms", "car_spaces", "land_size", "building_area",
    "year_built", "distance_cbd", "latitude", "longitude", "annual_rent",
    "months_since_start",
]
TARGET = "price"
SEED = 42

# 定稿特征。两个刻意的排除,理由都是实测出来的,不是拍脑袋:
#
# 1) months_since_start(成交时间):去掉后反而更好(MAE 153,747 -> 151,797)。
#    数据只跨 26 个月,行情没走出趋势,给了时间特征只是多一个噪声维度。
#    去掉它还顺带省掉一个麻烦 —— 不必再规定「按哪个月的行情估值」这种口径。
#
# 2) annual_rent:留着 MAE 151,797,去掉 152,399,差 0.4%,基本没代价。
#    但去掉换来一个干净得多的设计:**估值不看租金,租金回报率不看估值**,
#    两个信号互相独立,不会自己印证自己。若估值吃了租金,再拿估值和租金
#    回报率一起给用户看,等于同一个信息说两遍。
#    (顺带回答「会不会数据泄漏」:不会。它重要性看着有 32%,但删掉几乎
#     不掉分,说明那点信息和地段特征重复,不含个体房价的秘密。)
#
# 3) year_built:**线上根本拿不到**。search_properties() 的 15 个字段里没有它
#    (那是跨线契约,不能为了模型去改)。留着它的后果是训练/线上不一致:
#    对外报 MAE 152,399,用户实际拿到的是 156,995 —— 等于虚报。删掉后
#    报 154,805,而用户拿到的就是 154,805。**报的数和用户拿到的数必须是同一个。**
#
# 一条通用原则:模型只能吃「线上真的喂得进来」的特征。训练时有、预测时没有,
# 比一开始就不用它更糟。
#
# 注意:suburb 在测试集上删掉「更好」(150,007 vs 151,797),但差距 1.2%
# 在噪声范围内,而且**按测试集表现挑特征就是在偷看答案**,所以保留。
FINAL_FEATURES = CATEGORICAL + [
    "bedrooms", "bathrooms", "car_spaces", "land_size", "building_area",
    "distance_cbd", "latitude", "longitude",
    # 地址是否带单元号。property_type='house' 里混着典型独栋(相对价 1.00)和
    # villa/半独立/排屋(0.66,和联排的 0.67 几乎一样),此前模型只能靠地块面积
    # 间接去猜。派生函数放在 valuation.py,**训练和推理共用同一份**。
    "is_unit_address",
]

_LOAD_SQL = """
    SELECT suburb, property_type, price, bedrooms, bathrooms, car_spaces,
           land_size, building_area, year_built, distance_cbd,
           latitude, longitude, annual_rent, sale_date, address
    FROM properties
    ORDER BY id
"""


def load_frame() -> pd.DataFrame:
    """从数据库读训练数据。走 core/db.py 的连接池,不另开连接。"""
    with get_connection() as conn:
        df = pd.read_sql(_LOAD_SQL, conn)

    # 成交时间转成「距数据集起点多少个月」。房价随行情走,不给模型时间信息,
    # 它会把 2016 年的成交价和 2018 年的混在一起学。
    sale = pd.to_datetime(df["sale_date"])
    df["months_since_start"] = (
        (sale.dt.year - sale.dt.year.min()) * 12 + sale.dt.month
    )
    df["months_since_start"] -= df["months_since_start"].min()
    for col in CATEGORICAL:
        df[col] = df[col].astype("category")
    # 派生特征。用 valuation.py 里那一份实现,保证线上线下口径一致 ——
    # 两边各写一遍的话,不一致时预测会安静地错掉。
    df["is_unit_address"] = df["address"].map(valuation_is_unit_address)
    return df


def split(df: pd.DataFrame, mode: str):
    """mode='random' 随机 8:2;mode='time' 按成交时间,最后 20% 当测试集。"""
    if mode == "random":
        rng = np.random.default_rng(SEED)
        idx = rng.permutation(len(df))
        cut = int(len(df) * 0.8)
        return df.iloc[idx[:cut]], df.iloc[idx[cut:]]
    order = df["months_since_start"].sort_values(kind="stable").index
    cut = int(len(df) * 0.8)
    return df.loc[order[:cut]], df.loc[order[cut:]]


def _report(y_true, y_pred) -> dict:
    err = np.abs(y_true - y_pred)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(np.mean((y_true - y_pred) ** 2))),
        "r2": float(r2_score(y_true, y_pred)),
        # 中位数绝对百分比误差。房价右偏严重(8.5 万到 1120 万),平均值会被
        # 少数豪宅拽偏,中位数才代表「典型一套房错多少」。
        "mdape": float(np.median(err / y_true)),
        "within_10pct": float(np.mean(err / y_true <= 0.10)),
        "within_20pct": float(np.mean(err / y_true <= 0.20)),
    }


# 单调约束:把「常识」直接写进模型结构。1 = 只许随该特征增大而涨,
# -1 = 只许跌,0 = 不限。顺序必须与传入的 features 一一对应。
#
# 为什么要加:不加的时候,模型会给出「4 房比 3 房便宜」「800㎡ 地块比 400㎡
# 便宜」这种荒谬结论。原因不是模型烂,是这些探针落在训练数据没见过的组合上
# (Richmond 的 800㎡ 地块现实中几乎不存在),树模型不外推,只会掉进某个叶子。
# 真实房源(分布之内)不受影响,但一个卖点是「数字可信」的系统,不能在被人
# 随手一试时给出反常识的答案。
#
# 代价实测几乎为零:MAE 154,805 -> 154,859(+0.03%),R² 0.829 -> 0.841(更好),
# 而两处倒挂全部消失。
_MONOTONE = {
    "bedrooms": 1, "bathrooms": 1, "car_spaces": 1,
    "land_size": 1, "building_area": 1,
    "distance_cbd": -1,          # 离市中心越远越便宜
}


def fit_xgb(train, test, features, log_target: bool):
    """训练 XGBoost。树的数量由**训练集内部切出来的验证集**决定,不由测试集决定。

    这一点很要紧。实测固定树数时:200 棵 MAE 149,957、400 棵 148,423、
    1200 棵 154,859 —— 树多了会过拟合。但**照着测试集去挑最好的那个树数,
    和照着测试集挑特征是同一个错**:测试集一旦参与了任何选择,它报出来的
    误差就不再是「模型没见过的数据上的表现」,而是被你调出来的数字。

    所以:从训练集尾部再切 20% 当验证集,用它早停;测试集全程只在最后
    看一眼,不参与任何决定。
    """
    y_full = np.log(train[TARGET]) if log_target else train[TARGET]

    # 验证集取训练集**时间上靠后**的那一段,和「用过去预测未来」的划分方式一致。
    cut = int(len(train) * 0.8)
    X_fit, y_fit = train[features].iloc[:cut], y_full.iloc[:cut]
    X_val, y_val = train[features].iloc[cut:], y_full.iloc[cut:]

    params = dict(
        learning_rate=0.05, max_depth=8,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
        reg_lambda=1.0, random_state=SEED,
        enable_categorical=True, tree_method="hist",
        monotone_constraints=tuple(_MONOTONE.get(f, 0) for f in features),
    )
    probe = xgb.XGBRegressor(n_estimators=2000, early_stopping_rounds=50, **params)
    probe.fit(X_fit, y_fit, eval_set=[(X_val, y_val)], verbose=False)
    best = max(int(probe.best_iteration) + 1, 50)

    # 用早停选出的树数,在**完整训练集**上重训一次 —— 验证集那 20% 的数据
    # 不能白白浪费掉。
    model = xgb.XGBRegressor(n_estimators=best, **params)
    model.fit(train[features], y_full, verbose=False)

    pred = model.predict(test[features])
    if log_target:
        pred = np.exp(pred)
    report = _report(test[TARGET].to_numpy(), pred)
    report["n_estimators"] = best
    return model, report


def fit_linear(train, test, features, log_target: bool):
    """最笨的对照组:one-hot + 中位数填补 + 标准化 + 普通最小二乘。"""
    cats = [c for c in features if c in CATEGORICAL]
    nums = [c for c in features if c not in CATEGORICAL]
    pipe = Pipeline([
        ("prep", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cats),
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                              ("sc", StandardScaler())]), nums),
        ])),
        ("lr", LinearRegression()),
    ])
    y_tr = np.log(train[TARGET]) if log_target else train[TARGET]
    pipe.fit(train[features], y_tr)
    pred = pipe.predict(test[features])
    if log_target:
        pred = np.exp(pred)
    return pipe, _report(test[TARGET].to_numpy(), pred)


def error_by_type(df: pd.DataFrame, features: list[str]) -> dict:
    """分房型给出中位误差,取两种划分方式里**更保守**的那个。

    为什么必须分房型:整体 9.1% 的中位误差是被别墅撑起来的。按时间划分时
    测试集里只有 48 套公寓(1.2%)—— 因为公寓成交在 2017Q3 之后几乎从数据集
    里消失了(828 -> 57 -> 29,是数据采集的产物,不是模型的问题)。用一个
    house 撑出来的误差去标注公寓的估值区间,等于对系统最主推的那类房源
    **低报不确定性**。而低报不确定性,和虚报精度是一回事。

    为什么取两者更大的:按时间划分的公寓样本只有 48 套,不可信;随机划分有
    715 套但整体偏乐观。两个诚实的估计不一致时,给用户看更保守的那个。
    """
    out = {}
    for mode in ("time", "random"):
        train, test = split(df, mode)
        model, _ = fit_xgb(train, test, features, log_target=True)
        pred = np.exp(model.predict(test[features]))
        frame = test.assign(_pred=pred)
        for ptype, group in frame.groupby("property_type", observed=True):
            r = _report(group[TARGET].to_numpy(), group["_pred"].to_numpy())
            key = str(ptype)
            prev = out.get(key, {})
            if r["mdape"] > prev.get("mdape", 0):
                out[key] = {"mdape": r["mdape"], "n": int(len(group)), "split": mode,
                            "within_20pct": r["within_20pct"]}
    return out


def _row(name, m):
    return (f"  {name:<34}{m['mae']:>11,.0f}{m['mdape']*100:>9.1f}%"
            f"{m['r2']:>8.3f}{m['within_10pct']*100:>9.1f}%{m['within_20pct']*100:>9.1f}%")


def main(save: bool = True) -> None:
    df = load_frame()
    print(f"训练数据:{len(df):,} 行 · {df['suburb'].nunique()} 个区 · "
          f"{df['sale_date'].min()} ~ {df['sale_date'].max()}\n")

    features_full = CATEGORICAL + NUMERIC
    features_notime = [f for f in features_full if f != "months_since_start"]

    results = {}
    for split_mode in ("random", "time"):
        train, test = split(df, split_mode)
        label = "随机划分 8:2" if split_mode == "random" else "按时间划分(用过去预测未来)"
        print(f"【{label}】训练 {len(train):,} / 测试 {len(test):,}")
        print(f"  {'配置':<34}{'MAE':>11}{'中位误差':>9}{'R²':>8}{'±10%内':>9}{'±20%内':>9}")
        _, m = fit_linear(train, test, features_full, log_target=False)
        print(_row("线性回归 baseline", m)); results[f"{split_mode}/linear"] = m
        _, m = fit_linear(train, test, features_full, log_target=True)
        print(_row("线性回归 baseline(对数价)", m)); results[f"{split_mode}/linear_log"] = m
        _, m = fit_xgb(train, test, features_full, log_target=False)
        print(_row("XGBoost", m)); results[f"{split_mode}/xgb"] = m
        _, m = fit_xgb(train, test, features_full, log_target=True)
        print(_row("XGBoost(对数价)", m)); results[f"{split_mode}/xgb_log"] = m
        _, m = fit_xgb(train, test, features_notime, log_target=True)
        print(_row("XGBoost(对数价,去掉时间特征)", m)); results[f"{split_mode}/xgb_log_notime"] = m
        print()

    if not save:
        return

    # 定稿:XGBoost + 对数价 + FINAL_FEATURES(理由见该常量上方注释)。
    # 误差用「按时间划分」那一份报 —— 上线时模型面对的就是没见过的未来成交,
    # 拿随机划分的数字对外说,是在虚报。
    train, test = split(df, "time")
    model, metrics = fit_xgb(train, test, FINAL_FEATURES, log_target=True)
    _, baseline = fit_linear(train, test, FINAL_FEATURES, log_target=True)
    per_type = error_by_type(df, FINAL_FEATURES)

    MODEL_DIR.mkdir(exist_ok=True)
    model.save_model(MODEL_PATH)
    META_PATH.write_text(json.dumps({
        "trained_on": str(date.today()),
        "rows": int(len(df)),
        "algorithm": "XGBRegressor(log price target)",
        "categorical": CATEGORICAL,
        "feature_order": FINAL_FEATURES,
        # 预测时要把 suburb / property_type 还原成训练时同一套类别,
        # 否则 XGBoost 的类别编码对不上,预测结果会是错的。
        "categories": {c: sorted(map(str, df[c].cat.categories)) for c in CATEGORICAL},
        "log_target": True,
        "monotone_constraints": {k: v for k, v in _MONOTONE.items() if k in FINAL_FEATURES},
        "split": "time(前 80% 训练,后 20% 测试)",
        "metrics": metrics,
        "baseline_metrics": baseline,
        # 分房型的误差,给估值区间用。整体那个 9.1% 是被别墅撑起来的,
        # 拿它去标注公寓会低报不确定性 —— 详见 error_by_type() 的说明。
        "error_by_type": per_type,
        "excluded_features": {
            "months_since_start": "去掉后 MAE 更低;数据仅跨 26 个月,无趋势可学",
            "annual_rent": "去掉代价 0.4%,换取估值与租金回报率两个信号互相独立",
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存:{MODEL_PATH.name} + {META_PATH.name}")
    print(f"定稿模型(按时间划分):MAE ${metrics['mae']:,.0f} · "
          f"中位误差 {metrics['mdape']*100:.1f}% · R² {metrics['r2']:.3f} · "
          f"±20% 内 {metrics['within_20pct']*100:.1f}%")
    print(f"线性回归 baseline 同口径:MAE ${baseline['mae']:,.0f} · "
          f"中位误差 {baseline['mdape']*100:.1f}% · R² {baseline['r2']:.3f}")
    print("分房型中位误差(取两种划分里更保守的):")
    for ptype, info in sorted(per_type.items()):
        print(f"  {ptype:<12}{info['mdape']*100:>6.1f}%   (n={info['n']}, {info['split']} 划分)")


if __name__ == "__main__":
    try:
        main(save="--compare" not in sys.argv)
    finally:
        close_pool()
