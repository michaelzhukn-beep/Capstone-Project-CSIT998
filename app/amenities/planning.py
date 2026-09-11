"""规划分区与叠加层归属。V7。

数据来自 data/planning.jsonl.gz(由 pipeline/fetch_planning.py 一次性抓取,
Vicmap Planning / Victorian Open Data Platform,**CC BY 4.0**)。查询时不联网。

文件是**每行一个 Feature** 的 JSONL,不是整块 GeoJSON。原始数据 345 MB,
`json.load()` 一次读进来光 Python 对象开销就要 2.4 GB(实测),而几何本身
只占 0.39 GB。下面逐行解析、转成几何后立刻丢掉字典,峰值内存降一个数量级。

## 它和系统里其它模块的区别

    周边设施(nearby)    离最近的车站**多远**       -> 评分
    学区(zones)         落在**谁的**招生边界内     -> 事实
    分区(这里)          这块地**法律上能盖什么**   -> 事实

和学区一样,这里产出的是**事实**,不是分数。事实要么是要么不是,不需要权重,
也不需要分位数基准。所以它和 zones.py 一样在注册表(registry.SOURCES)之外。

## 为什么它能回答"未来",而 AI 读 Council 公告不能

分区是《维州规划纲要》里的法条,规定每块地能盖什么、能盖多高。点落在哪个
多边形里是确定的 —— 算错了能被查出来。此前评估过的"AI 监测开发申请(DA)"
是让模型从 PDF 里提取意图,错了不会报警、也无法核对,和本项目"每个数字都要
可追溯"的主张冲突。同一个需求,这里只做可核对的那一半。

## 三个必须一直挂着的限制

1. **"周边"是方形范围,不是圆。** 下面用 ±R 米的经纬度方框做空间查询。
   在这个尺度上方框和圆的差别对"邻居能盖什么"这个结论没有影响,
   但**不能**把它说成"半径 R 米内" —— 那是两个不同的东西。
2. **分区是当前的,房源成交是 2016–2018 年的。** 回答"现在买下会怎样"是对的;
   **不能**用来回溯解释 2017 年的成交价。
3. **分区说的是"法律上可以",不是"一定会"。** 旁边是 RGZ 只意味着开发商
   *可以* 申请盖高楼,不代表明天就动工;旁边是 NRZ 则是法律上*不能*。
   这个不对称很重要:**否定结论(不会变高)比肯定结论(会变高)强得多。**
"""

import gzip
import json
from collections import Counter
from pathlib import Path

import numpy as np
from shapely import (
    STRtree, box as shapely_box, from_wkb, points as shapely_points, to_wkb,
)
from shapely.geometry import shape

_JSONL = Path(__file__).resolve().parents[2] / "data" / "planning.jsonl.gz"
# 从 JSONL 派生出来的二进制缓存。**可以随时删,会自动重建** ——
# 所以它不进版本库,和 data/planning.jsonl.gz 那份"数据本体"是两回事。
_CACHE = _JSONL.with_name("planning.cache.npz")

# 默认"周边"半边长。350 米约等于步行 4 分钟,也是采光/视线会被影响的量级。
DEFAULT_RADIUS_M = 350

# ---------------------------------------------------------------- 分区分类
#
# 代码取自《维州规划纲要》(Victoria Planning Provisions)。分类依据是
# **该分区允许的开发强度**,不是我们的主观判断。
#
# density 的取值决定了系统敢下什么结论:
#   low    法律上限制密集开发 -> 可以说"旁边不会变高楼"
#   high   法律上明确允许加密 -> 只能说"旁边**可以**盖",不能说"一定会"
#   open   公园/保育          -> 永远不会变成建筑,这是最强的正面信号
_ZONE_FAMILIES = (
    # (代码前缀, 中文名, density) —— 匹配时按前缀长度降序,长的优先
    ("NRZ",  "邻里住宅区(限制加密)",         "low"),
    ("GRZ",  "一般住宅区",                     "medium"),
    ("RGZ",  "住宅增长区(鼓励加密)",         "high"),
    ("HCTZ", "住房选择与交通区(近车站,强制加密)", "high"),
    ("LDRZ", "低密度住宅区",                   "low"),
    ("RLZ",  "农村生活区",                     "low"),
    ("TZ",   "镇区",                           "medium"),
    ("MUZ",  "混合用途区",                     "high"),
    ("ACZ",  "活动中心区(规划的高密度核心)", "high"),
    ("CDZ",  "综合开发区",                     "high"),
    ("PRZ",  "特定片区(重大再开发)",         "high"),
    ("CCZ",  "首府城市区(CBD)",              "high"),
    ("DZ",   "码头区(Docklands)",            "high"),
    ("UGZ",  "城市增长区(规划中的新城)",     "high"),
    ("PDZ",  "优先开发区",                     "high"),
    ("C1Z",  "商业一区(商住混合)",           "high"),
    ("C2Z",  "商业二区",                       "high"),
    # 下面是**旧代码**。数据里仍有相当数量的地块没换代码,但 description
    # 已经是新名字了(R1Z 的 description 就是 GENERAL RESIDENTIAL ZONE)。
    # 只按新代码匹配会让 6% 的房源归到"未分类"。
    ("R1Z",  "一般住宅区(旧代码 R1Z)",       "medium"),
    ("R2Z",  "住宅区(旧代码 R2Z)",           "medium"),
    ("R3Z",  "住宅区(旧代码 R3Z)",           "medium"),
    ("B1Z",  "商业一区(旧代码 B1Z)",         "high"),
    ("B2Z",  "商业二区(旧代码 B2Z)",         "high"),
    ("B3Z",  "商业区(旧代码 B3Z)",           "high"),
    ("B4Z",  "商业区(旧代码 B4Z)",           "high"),
    ("B5Z",  "商业区(旧代码 B5Z)",           "high"),
    ("IN1Z", "工业一区",                       "industrial"),
    ("IN2Z", "工业二区",                       "industrial"),
    ("IN3Z", "工业三区",                       "industrial"),
    ("INZ",  "工业区",                         "industrial"),
    ("PPRZ", "公园与游憩用地",                 "open"),
    ("PCRZ", "公共保育与资源用地",             "open"),
    ("RDZ",  "道路用地",                       "infra"),
    ("TRZ",  "交通用地(主干道/铁路)",       "infra"),
    ("PUZ",  "公共用地(学校/政府/水电)",   "public"),
    ("FZ",   "农业区",                         "rural"),
    ("RAZ",  "农业用地区",                     "rural"),
    ("RCZ",  "乡村保育区",                     "rural"),
    ("GWAZ", "绿楔农业区",                     "rural"),
    ("GWZ",  "绿楔区",                         "rural"),
    ("UFZ",  "城市农业区",                     "rural"),
    ("SUZ",  "特别用途区",                     "other"),
    ("PZ",   "港口区",                         "industrial"),
)
_ZONE_BY_LEN = sorted(_ZONE_FAMILIES, key=lambda item: -len(item[0]))

# ---------------------------------------------------------------- 叠加层分类
#
# effect 决定这条叠加层对买家意味着什么:
#   build   限制你**自己**改建/重建(买之前必须知道)
#   risk    这块地本身有已登记的风险或政府计划
#   cost    开发时要额外掏钱
_OVERLAY_FAMILIES = {
    "HO":   ("历史建筑保护",             "build"),
    "DDO":  ("设计与开发控制(限高等)", "build"),
    "BFO":  ("建筑形态控制",             "build"),
    "NCO":  ("邻里特征保护",             "build"),
    "SCO":  ("特定控制",                 "build"),
    "SLO":  ("重要景观保护",             "build"),
    "VPO":  ("植被保护",                 "build"),
    "ESO":  ("环境重要性保护",           "build"),
    "DPO":  ("须先报开发总体规划",       "build"),
    "IPO":  ("须符合已并入的片区规划",   "build"),
    "RO":   ("重建区",                   "build"),
    "PO":   ("停车控制",                 "build"),
    "RXO":  ("道路封闭",                 "build"),
    "CLPO": ("City Link 工程叠加",       "build"),
    "PSB":  ("受保护聚落边界",           "build"),
    "PAO":  ("政府已划定将来征收",       "risk"),
    "SBO":  ("特殊建筑(排水/内涝)",    "risk"),
    "LSIO": ("洪泛淹没区",               "risk"),
    "FO":   ("洪道区",                   "risk"),
    "BMO":  ("山火管理",                 "risk"),
    "EAO":  ("须做环境审计(土壤污染)", "risk"),
    "EMO":  ("侵蚀管理",                 "risk"),
    "SMO":  ("盐渍化管理",               "risk"),
    "AEO":  ("机场环境(噪声)",         "risk"),
    "MAEO": ("墨尔本机场环境(噪声)",   "risk"),
    "RFO":  ("乡村洪道区",               "risk"),
    "DCPO": ("开发须缴基建费",           "cost"),
    "ICO":  ("基础设施贡献",             "cost"),
}
_OVERLAY_BY_LEN = sorted(_OVERLAY_FAMILIES, key=len, reverse=True)

_data: dict | None = None


def _family(code):
    """把 GRZ3 归到 GRZ,C1Z 归到 C1Z。

    按前缀长度降序匹配 —— 否则 IN1Z 会先撞上更短的前缀。认不出来的原样返回、
    标成 unknown,**不猜**:新代码应该以"未分类"的面貌暴露出来,
    而不是被硬塞进某个已知类别里。
    """
    if not code:
        return None, "未知分区", "unknown"
    upper = str(code).upper()
    for prefix, label, density in _ZONE_BY_LEN:
        if upper.startswith(prefix):
            return prefix, label, density
    return upper, upper + "(未分类)", "unknown"


def _overlay_family(code):
    """同上,用于叠加层代码(HO315 -> HO)。"""
    if not code:
        return None, "未知叠加层", "other"
    upper = str(code).upper()
    for prefix in _OVERLAY_BY_LEN:
        if upper.startswith(prefix):
            label, effect = _OVERLAY_FAMILIES[prefix]
            return prefix, label, effect
    return upper, upper + "(未分类)", "other"


def _stamp() -> str:
    """源文件的指纹。源换了就重建缓存,不能拿旧缓存配新数据。"""
    stat = _JSONL.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def _read_jsonl() -> dict:
    """逐行解析 JSONL,建出几何。

    整块 json.load() 会把峰值内存推到 2.4 GB —— 几何本身只要 0.39 GB,
    差的全是 Python 字典和 float 对象的开销。所以这里一行一行来,
    转成几何后立刻丢掉那一行的字典。
    """
    buckets: dict[str, dict] = {}
    with gzip.open(_JSONL, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            feature = json.loads(line)
            properties = feature["properties"]
            bucket = buckets.setdefault(properties["kind"],
                                        {"geoms": [], "code": [], "desc": [], "lga": []})
            bucket["geoms"].append(shape(feature["geometry"]))
            bucket["code"].append(properties["code"])
            bucket["desc"].append(properties["description"])
            bucket["lga"].append(properties["lga"])
    return buckets


def _write_cache(buckets: dict) -> None:
    """把几何存成 WKB(二进制),下次直接读。

    存法:所有 WKB 首尾相接成一条 uint8,再配一条 offsets 记录每个几何的边界。
    属性(代码、描述、LGA)另存成一段 UTF-8 的 JSON,也当 uint8 存。

    **全程不用 pickle。** np.savez 存 object 数组要开 allow_pickle,
    那等于让读取端执行文件里的任意代码 —— 一份自动生成、随手可删的缓存
    不值得引入这种东西。
    """
    payload = {}
    for kind, bucket in buckets.items():
        chunks = to_wkb(np.asarray(bucket["geoms"], dtype=object))
        offsets = np.zeros(len(chunks) + 1, dtype=np.int64)
        np.cumsum([len(c) for c in chunks], out=offsets[1:])
        payload[f"{kind}__wkb"] = np.frombuffer(b"".join(chunks), dtype=np.uint8)
        payload[f"{kind}__offsets"] = offsets
        attrs = json.dumps({k: bucket[k] for k in ("code", "desc", "lga")},
                           ensure_ascii=False, separators=(",", ":"))
        payload[f"{kind}__attrs"] = np.frombuffer(attrs.encode("utf-8"), dtype=np.uint8)
    payload["__stamp__"] = np.frombuffer(_stamp().encode("utf-8"), dtype=np.uint8)
    # 先写临时文件再改名:写到一半被打断时,留下的是没有缓存,
    # 而不是一份读得出来但内容不全的缓存。
    # 注意要传**文件句柄**:给 np.savez 一个路径,它会自作主张补上 .npz,
    # 于是改名的时候找不到文件(踩过)。
    tmp = _CACHE.with_name(_CACHE.name + ".tmp")
    with tmp.open("wb") as handle:
        np.savez(handle, **payload)
    tmp.replace(_CACHE)


def _read_cache() -> dict | None:
    if not _CACHE.exists():
        return None
    try:
        with np.load(_CACHE, allow_pickle=False) as store:
            if bytes(store["__stamp__"]).decode("utf-8") != _stamp():
                return None            # 源数据换过了,这份缓存作废
            buckets = {}
            for key in store.files:
                if not key.endswith("__wkb"):
                    continue
                kind = key[: -len("__wkb")]
                blob = store[key].tobytes()
                offsets = store[f"{kind}__offsets"]
                geoms = from_wkb([blob[a:b] for a, b in zip(offsets[:-1], offsets[1:])])
                attrs = json.loads(bytes(store[f"{kind}__attrs"]).decode("utf-8"))
                buckets[kind] = {"geoms": list(geoms), **attrs}
            return buckets or None
    except Exception:                  # noqa: BLE001
        # 缓存坏了不该让程序挂掉 —— 它是派生数据,重新从 JSONL 建就是了。
        return None


def _load() -> dict:
    """读进多边形,分区和叠加层各建一棵 STRtree。

    12 万个多边形 x 几千套候选房,不建空间索引是算不完的。STRtree 先用外接框
    粗筛,再做精确的几何判断。

    第一次跑要从 JSONL 解析(约 10 秒),之后走 WKB 缓存(约 2 秒)。
    CLI 每次启动都要加载,10 秒和 2 秒的差别用户是直接感觉得到的。
    """
    global _data
    if _data is not None:
        return _data
    if not _JSONL.exists():
        raise RuntimeError(
            "规划分区数据缺失(" + _JSONL.name + ")。"
            "请先运行:python pipeline/fetch_planning.py")

    buckets = _read_cache()
    if buckets is None:
        buckets = _read_jsonl()
        try:
            _write_cache(buckets)
        except Exception:              # noqa: BLE001
            pass                       # 缓存写不成(比如只读目录)不影响使用

    _data = {kind: dict(bucket, tree=STRtree(bucket["geoms"]))
             for kind, bucket in buckets.items()}
    return _data


def warm_up() -> dict:
    return {kind: len(bucket["code"]) for kind, bucket in _load().items()}


def _boxes(lats, lons, radius_m):
    """给每个坐标做一个 ±radius_m 的经纬度方框。

    纬度 1 度约 111,320 米;经度 1 度约 111,320 x cos(纬度) 米 —— 在墨尔本
    (约 -37.8 度)约 88,000 米。不做这个 cos 修正,东西方向的范围会比
    要求的大 26%。
    """
    lat_arr = np.asarray(lats, dtype=float)
    lon_arr = np.asarray(lons, dtype=float)
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * np.cos(np.radians(lat_arr)))
    return [shapely_box(lon - dx, lat - dlat, lon + dx, lat + dlat)
            for lat, lon, dx in zip(lat_arr, lon_arr, dlon)]


def for_batch(lats, lons, radius_m: int = DEFAULT_RADIUS_M) -> list[dict]:
    """一批坐标的分区归属 + 压在头上的叠加层 + 周边分区构成。

    落不进任何分区就返回 {} —— **不放 None 进去假装查过**。
    """
    lats = list(lats)
    lons = list(lons)
    out: list[dict] = [{} for _ in lats]
    usable = [i for i in range(len(lats)) if lats[i] is not None and lons[i] is not None]
    if not usable:
        return out

    data = _load()
    use_lats = [lats[i] for i in usable]
    use_lons = [lons[i] for i in usable]
    pts = shapely_points(np.array(use_lons, dtype=float), np.array(use_lats, dtype=float))

    # ---- 1. 自己这块地的分区 ----
    zone_bucket = data.get("zone")
    if zone_bucket is not None:
        pairs = zone_bucket["tree"].query(pts, predicate="within")
        for point_idx, poly_idx in zip(pairs[0], pairs[1]):
            slot = out[usable[int(point_idx)]]
            if "zone" in slot:              # 分区互不重叠,正常只会命中一个
                continue
            code = zone_bucket["code"][int(poly_idx)]
            _, label, density = _family(code)
            slot["zone"] = code
            slot["zone_desc"] = zone_bucket["desc"][int(poly_idx)]
            slot["zone_label"] = label
            slot["density"] = density
            slot["lga"] = zone_bucket["lga"][int(poly_idx)]

    # ---- 2. 压在自己头上的叠加层(可以有多个)----
    overlay_bucket = data.get("overlay")
    if overlay_bucket is not None:
        pairs = overlay_bucket["tree"].query(pts, predicate="within")
        for point_idx, poly_idx in zip(pairs[0], pairs[1]):
            slot = out[usable[int(point_idx)]]
            code = overlay_bucket["code"][int(poly_idx)]
            prefix, label, effect = _overlay_family(code)
            slot.setdefault("overlays", [])
            if not any(o["code"] == code for o in slot["overlays"]):
                slot["overlays"].append({"code": code, "family": prefix,
                                         "label": label, "effect": effect})

    # ---- 3. 周边的分区构成 ----
    if zone_bucket is not None:
        boxes = _boxes(use_lats, use_lons, radius_m)
        pairs = zone_bucket["tree"].query(boxes, predicate="intersects")
        near: dict[int, Counter] = {}
        for box_idx, poly_idx in zip(pairs[0], pairs[1]):
            _, _, density = _family(zone_bucket["code"][int(poly_idx)])
            near.setdefault(int(box_idx), Counter())[density] += 1
        for box_idx, counter in near.items():
            slot = out[usable[box_idx]]
            slot["nearby"] = dict(counter)
            slot["nearby_total"] = sum(counter.values())
            slot["nearby_high"] = counter.get("high", 0)
            slot["nearby_low"] = counter.get("low", 0)
            slot["nearby_open"] = counter.get("open", 0)
            slot["nearby_industrial"] = counter.get("industrial", 0)
            slot["radius_m"] = radius_m

    return out


def for_one(lat, lon, radius_m: int = DEFAULT_RADIUS_M) -> dict:
    if lat is None or lon is None:
        return {}
    return for_batch([lat], [lon], radius_m)[0]


def can_redevelop(info: dict):
    """翻建/改建是不是受额外限制。

    True  = 没有限制性叠加层
    False = 有(历史保护、限高、须报总体规划……)
    None  = 没查到分区数据

    **None 不等于 True** —— 查不到就是不知道,不能当成"可以"。
    """
    if not info or "zone" not in info:
        return None
    return not any(o["effect"] == "build" for o in info.get("overlays", []))


def risks(info: dict) -> list[dict]:
    """这块地上已登记的风险类叠加层(征收、洪泛、山火、土壤污染……)。"""
    if not info:
        return []
    return [o for o in info.get("overlays", []) if o["effect"] == "risk"]


def describe(info: dict) -> str:
    """写成人话。查不到就说查不到,不猜。"""
    if not info or "zone" not in info:
        return "该坐标无规划分区数据"

    parts = ["分区 " + str(info["zone"]) + "(" + info["zone_label"] + ")"]

    overlays = info.get("overlays") or []
    if overlays:
        shown = "、".join(o["code"] + " " + o["label"] for o in overlays[:4])
        if len(overlays) > 4:
            shown += " 等 " + str(len(overlays)) + " 项"
        parts.append("叠加层:" + shown)
    else:
        parts.append("无叠加层限制")

    total = info.get("nearby_total") or 0
    if total:
        radius = info.get("radius_m", DEFAULT_RADIUS_M)
        bits = ["周边 ±" + str(radius) + " 米方形范围内 " + str(total) + " 块地"]
        if info.get("nearby_low"):
            bits.append(str(info["nearby_low"]) + " 块法律上限制加密")
        if info.get("nearby_high"):
            bits.append(str(info["nearby_high"]) + " 块允许高密度开发")
        if info.get("nearby_open"):
            bits.append(str(info["nearby_open"]) + " 块是公园绿地(不会变成建筑)")
        if info.get("nearby_industrial"):
            bits.append(str(info["nearby_industrial"]) + " 块是工业用地")
        parts.append(",".join(bits))
    return " · ".join(parts)
