"""估值。V2 第 3 项 —— 已从 stub 换成训练好的 XGBoost 模型。

**函数签名与第一版完全一致**:`predict_value(features: dict) -> dict`。
这正是第一版把它定成「收特征字典、不收房源 ID」的目的(PROJECT.md 5.5):
编排层一行都不用改,就从占位值切到了真模型。

三个当初写在第一版里的理由,现在兑现了:
  ① 能用手写字典做单元测试,不依赖数据库 —— 见 tests/test_valuation.py
  ② 表结构改动不波及模型 —— 模型只认特征名,不认表
  ③ 结果异常时能立刻区分是取数错还是算错

模型怎么训练的、为什么是这几个特征,见 train_valuation.py。
重新训练:python -m app.analytics.train_valuation
"""

import json
import math
import re
from pathlib import Path

import pandas as pd
import xgboost as xgb

_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
_MODEL_PATH = _MODEL_DIR / "valuation_xgb.ubj"
_META_PATH = _MODEL_DIR / "valuation_meta.json"

# 库内房源的离折估值(见 crossfit_valuation.py)。缺这个文件时退回定稿模型,不报错 ——
# 但那样库内 80% 房源拿到的是训练集内的拟合值,测试会盯着这一点。
OOF_PATH = _MODEL_DIR / "valuation_oof.csv"
_OOF_FIELDS = ("address", "suburb", "price", "property_type", "bedrooms", "bathrooms", "car_spaces",
               "land_size", "building_area", "distance_cbd", "latitude", "longitude")

_model: xgb.XGBRegressor | None = None
_meta: dict | None = None
_oof: dict | None = None


def _norm(value) -> str:
    """键里的一个字段。数值统一成 10 位有效数字,空值和 NaN 都记成空串 ——
    数据库读出来是 int/float/None,pandas 读出来是 float/NaN,两边必须写成同一个字符串。"""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return "" if math.isnan(float(value)) else format(float(value), ".10g")
    text = str(value).strip().lower()
    return "" if text in ("nan", "none") else text


def oof_key(row: dict) -> str:
    """一套库内房源的离折估值查找键:地址、区、成交价 + 全部模型特征。
    任何一个字段变了(队友重新下载数据、改了一列),键就对不上,退回定稿模型 —— 不给过期的估值。"""
    return "|".join(_norm(row.get(f)) for f in _OOF_FIELDS)


def _load_oof() -> dict:
    global _oof
    if _oof is None:
        table = {}
        if OOF_PATH.exists():
            import csv
            with OOF_PATH.open(encoding="utf-8") as handle:
                for rec in csv.DictReader(handle):
                    table[rec["key"]] = float(rec["log_pred"])
        _oof = table
    return _oof


def _load():
    """懒加载模型。缺文件就明确报错,**绝不悄悄退回占位值** ——
    悄悄给一个假数字,正是本项目最不能容忍的事。"""
    global _model, _meta
    if _model is None:
        if not _MODEL_PATH.exists() or not _META_PATH.exists():
            raise RuntimeError(
                f"估值模型文件缺失({_MODEL_PATH.name} / {_META_PATH.name})。"
                "请先运行:python -m app.analytics.train_valuation"
            )
        # 先在局部变量里加载完,再一次性赋给全局。反过来写的话,并发的第二个调用会看到
        # `_model` 已经不是 None、却还没 load_model,直接抛 NotFittedError(审计 BUG-10)。
        meta = json.loads(_META_PATH.read_text(encoding="utf-8"))
        model = xgb.XGBRegressor(enable_categorical=True)
        model.load_model(_MODEL_PATH)
        _meta, _model = meta, model
    return _model, _meta


def warm_up() -> dict:
    """启动时主动加载一次,让「模型文件缺失」在启动时暴露而不是在用户提问时。
    返回模型元信息,供 CLI 打印。"""
    _, meta = _load()
    return meta


# 「1/28 Seves St」「3A/5 Yarra Rd」「303/18 Tanner St」这类带单元号的地址。
# 训练和推理**必须用同一份实现** —— 各写一遍的话,哪天两边不一致,
# 预测会安静地错掉:模型按一个定义学的,线上按另一个定义喂。
_UNIT_ADDRESS_RE = re.compile(r"^\s*(?:[A-Za-z]?\d+[A-Za-z]?)\s*/")


def is_unit_address(address) -> int:
    """地址是不是带单元号。

    为什么值得单独当一个特征:数据集的 `Type='h'` 按官方口径包含
    house / cottage / villa / semi / terrace —— 后三类常常写成「1/28 X St」。
    实测在 48 个样本充足的区里,带单元号的 h 中位价只有典型独栋的 **0.66**,
    和联排的 0.67 几乎一样,离公寓的 0.46 很远。也就是说 house 这一类里
    混着两个价格人群,而模型此前只能靠地块面积等间接特征去猜。
    加上这一个 0/1 特征后:MAE 152,741 -> 149,393,R² 0.8356 -> 0.8444,
    中位误差 9.18% -> 8.95%(测试集固定不变)。
    """
    return int(bool(_UNIT_ADDRESS_RE.match(str(address or ""))))


def _to_frame(rows: list[dict], meta: dict) -> pd.DataFrame:
    """把若干特征字典整理成模型认得的表。

    两件必须做对的事:
    1. 列的顺序和训练时一致;
    2. suburb / property_type 必须还原成**训练时那一套类别**。若直接
       astype("category"),类别是按当前这批数据现算的,编码会和训练时对不上,
       预测结果会安静地错掉 —— 不报错,只是错。
    """
    # 调用方传的是原始房源字段,派生特征在这里补齐 —— 让编排层不必知道
    # 模型内部用了哪些派生量。缺了它会变成 NaN,模型**不报错、只是变差**。
    rows = [dict(r) for r in rows]
    if "is_unit_address" in meta["feature_order"]:
        for r in rows:
            if r.get("is_unit_address") is None:
                r["is_unit_address"] = is_unit_address(r.get("address"))

    df = pd.DataFrame(
        {name: [r.get(name) for r in rows] for name in meta["feature_order"]}
    )
    for col in meta["feature_order"]:
        if col in meta["categorical"]:
            df[col] = pd.Categorical(df[col], categories=meta["categories"][col])
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _error_for(property_type, meta: dict) -> float:
    """取这一类房型的典型误差。

    为什么不能所有房型都用同一个数:整体中位误差 9.1% 是被别墅(占测试集 93%)
    撑起来的,公寓实测是 12.8%。拿 9.1% 去标注一套公寓的估值区间,就是对
    系统最主推的那类房源**低报不确定性** —— 而低报不确定性和虚报精度是一回事。
    """
    by_type = meta.get("error_by_type") or {}
    info = by_type.get(str(property_type))
    if info and info.get("mdape"):
        return float(info["mdape"])
    return float(meta["metrics"]["mdape"])


def _interval_for(property_type, meta: dict) -> dict | None:
    """取这一类房型的保形区间参数(calibrate_valuation.py 算出并写进 meta)。

    meta 里没有 conformal 段时返回 None —— **不退回任何估计值**。区间的全部意义在于
    "说 80% 就是 80%",没校准过的区间宁可不给。
    """
    conf = meta.get("conformal")
    if not conf:
        return None
    level = conf["display_level"]
    table = conf["levels"][str(level)]
    info = table.get(str(property_type)) or table["__all__"]
    return {"level": level, "q": info["q"], "coverage": info["coverage_mean"]}


def _wrap(pred: float, err: float, interval: dict | None, meta: dict) -> dict:
    out = {
        "predicted_price": int(round(pred)),
        "is_stub": False,
        "model": meta["algorithm"],
        "typical_error_pct": err,
        "range_low": int(round(pred * (1 - err))),
        "range_high": int(round(pred * (1 + err))),
        "interval_level": None, "interval_low": None, "interval_high": None, "interval_coverage": None,
    }
    if interval:
        out.update({
            "interval_level": interval["level"],
            # 对数误差上的对称区间,换回价格后下窄上宽(-17% / +21% 这种),这是房价右偏的正常形态
            "interval_low": int(round(pred * math.exp(-interval["q"]))),
            "interval_high": int(round(pred * math.exp(interval["q"]))),
            "interval_coverage": interval["coverage"],
        })
    return out


def predict_value(features: dict) -> dict:
    """预测一套房的市场价值。**签名与第一版 stub 完全一致。**

    返回:
        predicted_price   预测价(澳元,整数)
        is_stub           False —— 这是真模型的输出,不再是占位值
        model             算法名
        typical_error_pct 中位绝对百分比误差(测试集实测),用来给误差区间
        range_low/high    predicted_price × (1 ∓ typical_error_pct)。
                          实测约一半的房子落在这个区间内 —— 这是它的确切含义,
                          **不是「95% 置信区间」**,别在文档里写成那个。
        interval_level    保形区间的标称把握(0.8)。meta 未校准时为 None
        interval_low/high 分房型的分割保形区间:在模型没见过的成交上校准,
                          真实价格落入的比例经验证约为 interval_level
        interval_coverage 实测覆盖率(留出集随机对半 500 次的平均值)
    """
    return predict_values([features])[0]


def predict_values(rows: list[dict]) -> list[dict]:
    """批量版。返回值和 predict_value 逐条一致。

    为什么要有这个:编排层为了按指标排序,一次要算 120 套。逐条调
    predict_value 的话,每套都要新建一个 DataFrame 再调一次模型,实测 2.7 秒;
    批量一次搞定只要几十毫秒。开销全在「每次调用的固定成本」上,不在模型本身。
    """
    if not rows:
        return []
    import numpy as np

    model, meta = _load()
    # 训练目标是 log(price),所以预测出来要指数还原。
    log_preds = model.predict(_to_frame(rows, meta))
    # 库内房源换成离折估值:来自没见过这套房的模型。调用方要把 address 和 price 一起传进来才查得到;
    # 查不到(库外输入、数据被改过)就用定稿模型,并在 cross_fitted 里如实标出来。
    oof = _load_oof()
    out = []
    for lp, r in zip(log_preds, rows):
        hit = oof.get(oof_key(r)) if oof and r.get("price") else None
        item = _wrap(float(np.exp(hit if hit is not None else lp)), _error_for(r.get("property_type"), meta),
                     _interval_for(r.get("property_type"), meta), meta)
        item["cross_fitted"] = hit is not None
        out.append(item)
    return out
