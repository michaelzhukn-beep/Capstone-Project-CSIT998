"""地理测量引擎。V5(原 V3 版本按注册表重写)。

数据来自 data/osm_points.csv(由 pipeline/fetch_osm.py 一次性抓取,
© OpenStreetMap contributors,ODbL)。**查询时不联网。**

职责划分:
    nearby.py   —— **测量**:算距离、数半径内的数量、按名字找地点
    context.py  —— **打分**:把测量值折算成"安静""通勤方便"这类属性

有哪些数据源、哪些对用户可见,全部由 registry.SOURCES 决定,这里不再硬编码。

为什么不用 PostGIS / KD 树:点总共 17 万个,候选房源最多几百套,
numpy 向量化暴力算是毫秒级。多一个扩展、多一个依赖,不值。
"""

import csv
import math
from pathlib import Path

import numpy as np
from sklearn.neighbors import BallTree

from app.amenities.registry import SOURCES, USER_FACING_KINDS

_CSV = Path(__file__).resolve().parents[2] / "data" / "osm_points.csv"

_EARTH_RADIUS_M = 6_371_000.0

# 用户能直接问到的类别(如"最近的火车站在哪")。主干道、铁路线这类只作为
# 抽象属性的证据,不在这里 —— 用户不会问"最近的主干道在哪"。
KIND_ZH = {k: SOURCES[k]["zh"] for k in USER_FACING_KINDS}
KINDS = USER_FACING_KINDS

_data: dict | None = None


def _load() -> dict:
    """把 CSV 读成按类别分组的 numpy 数组。只在第一次调用时做。"""
    global _data
    if _data is not None:
        return _data
    if not _CSV.exists():
        raise RuntimeError(
            f"地理数据缺失({_CSV.name})。请先运行:python pipeline/fetch_osm.py")

    buckets: dict[str, list] = {}
    named = []
    # 面要素(公园、海滩、墓地)的边界采样点,按 osm_id 归组。按名字找到一个公园后,
    # 量距离要量到它的边界,而不是量到中心点 —— 中心点离得远的大公园,边可能就在门口。
    edges: dict[str, list] = {}
    with _CSV.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            lat, lon = float(row["latitude"]), float(row["longitude"])
            buckets.setdefault(row["kind"], []).append((lat, lon, row["name"]))
            if row.get("role") == "edge":
                # 边界点只进最近距离的树,不进具名索引:一个公园一圈几十上百个点,
                # 全塞进按名字线性扫描的索引会把查地名拖慢一个量级
                if row.get("osm_id"):
                    edges.setdefault(row["osm_id"], []).append((lat, lon))
                continue
            if row["name"]:
                # 具名查找用"正式名 + 别名"合起来的词集合 —— 墨尔本机场正式名
                # 叫 Melbourne Airport,用户会说 Tullamarine,不认别名就查不到。
                named.append((row["name"],
                              _tokens(row["name"] + " " + (row.get("alt_names") or "")),
                              row["kind"], lat, lon, row.get("osm_id") or ""))

    # 每类建一棵 BallTree(haversine 度量,直接吃弧度经纬度)。
    #
    # 为什么不再用暴力遍历:候选池从 120 套放大到几千套之后,
    # "每套房 × 每类数据源的全部点"就变成了上亿次距离计算。实测 4,370 套房
    # 暴力算要 7 秒,BallTree 只要 0.74 秒 —— 9 倍。而这 9 倍换来的是
    # **能在全部符合条件的房源里排序,而不是只在 120 套语义候选里排**。
    #
    # sklearn 本来就装了(线性回归 baseline 用它),不引入新依赖。
    _data = {
        "by_kind": {
            kind: {
                "tree": BallTree(np.radians(np.array([[p[0], p[1]] for p in pts])),
                                 metric="haversine"),
                "lat": np.radians(np.array([p[0] for p in pts], dtype=np.float64)),
                "lon": np.radians(np.array([p[1] for p in pts], dtype=np.float64)),
                "name": [p[2] for p in pts],
            }
            for kind, pts in buckets.items() if pts
        },
        "named": named,
        "edges": edges,
        "total": sum(len(v) for v in buckets.values()),
    }
    return _data


def _radians_pairs(lats, lons) -> np.ndarray:
    return np.radians(np.column_stack([np.asarray(lats, dtype=float),
                                       np.asarray(lons, dtype=float)]))


def warm_up() -> dict:
    """启动时载入一次,让"数据文件缺失"在启动时暴露而不是用户提问时。"""
    data = _load()
    return {"total": data["total"],
            "by_kind": {k: len(v["name"]) for k, v in data["by_kind"].items()},
            "user_facing": {k: len(data["by_kind"].get(k, {}).get("name", []))
                            for k in KINDS}}


def _haversine_m(lat_deg, lon_deg, group) -> np.ndarray:
    """一个点到一组点的球面距离(米)。向量化。

    用 haversine 而不是平面勾股:墨尔本跨约 100 公里、纬度 −38°,
    直接拿经纬度差当平面坐标算,东西方向会偏 21%(cos38° ≈ 0.79)。
    """
    lat1, lon1 = math.radians(lat_deg), math.radians(lon_deg)
    dlat = group["lat"] - lat1
    dlon = group["lon"] - lon1
    a = np.sin(dlat / 2) ** 2 + math.cos(lat1) * np.cos(group["lat"]) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def nearest_batch(lats, lons, kind: str):
    """一批坐标各自到某类设施的最近距离。返回 (距离数组米, 名字列表)。

    批量是这一层存在的意义:一次树查询处理几千套房,比逐套调 nearest() 快
    一个数量级。全量排序全靠它才跑得动。
    """
    group = _load()["by_kind"].get(kind)
    if not group:
        return None, None
    distances, indices = group["tree"].query(_radians_pairs(lats, lons), k=1)
    metres = distances[:, 0] * _EARTH_RADIUS_M
    names = [group["name"][int(i)] or "(未命名)" for i in indices[:, 0]]
    return metres, names


def count_within_batch(lats, lons, kind: str, radius_m: int):
    """一批坐标各自在半径内有几个该类设施。"""
    group = _load()["by_kind"].get(kind)
    if not group:
        return None
    return group["tree"].query_radius(_radians_pairs(lats, lons),
                                      r=radius_m / _EARTH_RADIUS_M, count_only=True)


def nearest(lat, lon, kind: str) -> dict | None:
    """到某一类设施最近的那一个(名字 + 距离米)。算不出来返回 None,不编。"""
    if lat is None or lon is None:
        return None
    metres, names = nearest_batch([lat], [lon], kind)
    if metres is None:
        return None
    return {"name": names[0], "distance_m": int(round(float(metres[0])))}


def count_within(lat, lon, kind: str, radius_m: int) -> int | None:
    """半径内有几个。用于"周边商业密度"这类密度指标。"""
    if lat is None or lon is None:
        return None
    counts = count_within_batch([lat], [lon], kind, radius_m)
    return None if counts is None else int(counts[0])


def nearest_by_kind_batch(lats, lons, kinds=None) -> list[dict]:
    """一批坐标 × 多类设施。每类只做一次树查询,而不是每套房做一次。

    候选池放大到几千套之后,逐套调 nearest_by_kind() 会做几万次树查询;
    批量版是 len(kinds) 次。
    """
    n = len(list(lats))
    out: list[dict] = [{} for _ in range(n)]
    usable = [i for i in range(n) if lats[i] is not None and lons[i] is not None]
    if not usable:
        return out
    sub_lats = [lats[i] for i in usable]
    sub_lons = [lons[i] for i in usable]
    for kind in (kinds or KINDS):
        metres, names = nearest_batch(sub_lats, sub_lons, kind)
        if metres is None:
            continue
        for k, i in enumerate(usable):
            out[i][kind] = {"name": names[k],
                            "distance_m": int(round(float(metres[k])))}
    return out


def nearest_by_kind(lat, lon, kinds=None) -> dict:
    """一次算多类。返回 {kind: {"name": ..., "distance_m": ...}},
    算不出来的类别**直接不出现** —— 不放一个 None 进去假装有值。"""
    out = {}
    for kind in (kinds or KINDS):
        hit = nearest(lat, lon, kind)
        if hit:
            out[kind] = hit
    return out


# ---------------------------------------------------------------- 具名查找

# 匹配时忽略的词。前一组是英语虚词,后一组是"通用类别词" —— 它们区分不出
# 是哪一家,但去掉太早又会误伤(见 find_place 的两轮降级)。
_STOPWORDS = frozenset({"the", "of", "and", "at", "in", "a"})
_GENERIC = frozenset({
    "university", "uni", "college", "campus", "station", "hospital",
    "school", "centre", "center", "institute", "airport", "bank", "police",
})


def _tokens(text: str) -> set[str]:
    return {
        word for word in "".join(c if c.isalnum() else " " for c in text.lower()).split()
        if word and word not in _STOPWORDS
    }


def find_place(query: str, kind: str | None = None, limit: int = 40) -> list[dict]:
    """按名字找具名地点。返回**所有**匹配的点(同一机构的多个校区/网点)。

    为什么返回全部而不是最像的那一个:用户说"离 Monash 近",指的是"离任意一个
    Monash 校区近"。OSM 里 Monash University 有 5 个点(Clayton、Caulfield、
    Peninsula、City……),取其中最近的才对。

    匹配用**按词全含**而不是子串包含,因为子串太松:
      "Monash University" 按子串会命中 "John Monash Science School"(一所以
      John Monash 命名的中学)—— 和 Monash 大学无关,却会把距离算错。
      按词要求 {monash, university} **全部**出现,就被正确排除了。
    按词还顺带解决词序:"Melbourne University" 能命中 "The University of Melbourne"。
    """
    if not query or not query.strip():
        return []
    wanted = _tokens(query)
    if not wanted:
        return []
    rows = _load()["named"]

    def search(tokens: set[str], restrict: str | None) -> list[dict]:
        return [{"name": name, "kind": row_kind, "latitude": lat, "longitude": lon, "osm_id": osm_id}
                for name, name_tokens, row_kind, lat, lon, osm_id in rows
                if (not restrict or row_kind == restrict) and tokens <= name_tokens]

    # 两轮降级,一旦有结果就停:
    # ① 全部词 —— 最准
    # ② 去掉通用类别词后重试 —— 治 "Flinders Street Station" 这种情况:
    #    OSM 里这个站就叫 "Flinders Street",带上 station 反而匹配不到
    #
    # **注意这里没有"放开类别限制"那一档。** 曾经有,结果是:用户问
    # "Tullamarine 机场",系统找不到就退而求其次返回了 "Tullamarine Primary
    # School" —— 要机场给小学。宁可返回空、让系统如实说"找不到这个地点",
    # 也不能给一个类别都不对的东西。这和"没搜到就说没搜到"是同一条规矩。
    specific = wanted - _GENERIC or wanted
    for tokens, restrict in ((wanted, kind), (specific, kind)):
        hits = search(tokens, restrict)
        if hits:
            # "就是这个"优先于"名字里含这个":存在以查询词开头的条目就只取那批
            head = next(iter(sorted(specific))) if specific else ""
            prefixed = [h for h in hits if h["name"].lower().startswith(head)]
            return (prefixed or hits)[:limit]
    return []


def distance_to_place(lat, lon, places: list[dict]) -> dict | None:
    """一套房到某个具名地点的距离 —— 取到所有同名点里最近的那个。"""
    if lat is None or lon is None or not places:
        return None
    # 面要素把整圈边界点展开进来,量到最近的边;点要素就是它自己
    edges = _load()["edges"]
    pts = []
    for p in places:
        pts.append((p["latitude"], p["longitude"], p["name"]))
        pts.extend((a, b, p["name"]) for a, b in edges.get(p.get("osm_id") or "", ()))
    group = {"lat": np.radians(np.array([p[0] for p in pts], dtype=np.float64)),
             "lon": np.radians(np.array([p[1] for p in pts], dtype=np.float64))}
    distances = _haversine_m(lat, lon, group)
    index = int(np.argmin(distances))
    return {"name": pts[index][2],
            "distance_m": int(round(float(distances[index])))}


def walk_minutes(distance_m: int | None) -> int | None:
    """把距离折成步行分钟数,按 5 km/h。

    这是**换算不是估计** —— 但给的是直线距离折算,实际走路要绕路,所以偏乐观。
    展示时要说清是"直线距离",不能说成"步行 X 分钟到"。
    """
    if distance_m is None:
        return None
    return max(1, int(round(distance_m / 1000 / 5 * 60)))


# 墨尔本 CBD 的参照点:Melbourne GPO(Bourke St 与 Elizabeth St 路口)。
CBD_POINT = (-37.8136, 144.9631)


def distance_to_cbd_km(lat, lon, fallback=None) -> float | None:
    """房源到 CBD 的直线距离(公里,一位小数)。有坐标就按坐标算,没有才用数据集自带的值。

    **为什么不直接用数据集的 Distance 列。** 它是按区给的一个数,而且有 106 个区系统性写错:
    Werribee 全区写 14.7 km,按坐标实为约 28 km;Point Cook 14.7 vs 21.9(审计 BUG-05)。
    **不改数据集** —— 展示和打分改用坐标算;估值模型仍用原列,因为它就是拿原列训练的,
    临时换输入会让模型拿到训练时没见过的分布。
    """
    if lat is not None and lon is not None:
        return round(distance_between(lat, lon, *CBD_POINT) / 1000, 1)
    # NaN / inf 不是距离:原样返回会让 SSE 里出现裸 NaN(不是合法 JSON,浏览器 JSON.parse 会整条报错)
    return round(float(fallback), 1) if isinstance(fallback, (int, float)) and math.isfinite(fallback) else None


def distance_between(lat1, lon1, lat2, lon2) -> int | None:
    """两点之间的球面直线距离(米)。

    界面上的「距离测算」用它。**刻意不做路网距离** —— 这个项目里没有路网数据,
    算不出步行或驾车路程(registry.UNSUPPORTED 里明确写着这一条)。
    好在测算工具的画面本身就说清了这件事:地图上是一根**直的**线,
    连着两个图钉。看图的人不会以为那是走路要绕的路。
    """
    if None in (lat1, lon1, lat2, lon2):
        return None
    group = {"lat": np.radians(np.array([lat2], dtype=np.float64)),
             "lon": np.radians(np.array([lon2], dtype=np.float64))}
    return int(round(float(_haversine_m(lat1, lon1, group)[0])))


# 自由输入的地名怎么挑。这一段的每一条都是被实测打回来之后才定下来的。
#
# ① **必须按类别逐个试,不能只搜一次不限类别的。**
#    不限类别搜 "The University of Melbourne",89,817 个具名点里命中 9 个,
#    全是 bus_stop / park / kindergarten,一个 university 都没有。原因在
#    find_place 的两轮降级:第①轮(全部词)已经匹上那几个公交站就停了,
#    永远走不到第②轮(去掉 "university" 这个通用词再试),而真正的校区
#    恰恰要靠第②轮才找得到。所以每一类都要有自己的降级机会。
#
# ② **但也不能按类别优先级"先到先得"。** 那样做的话,一个名字匹配很差的
#    高优先类别会压掉名字匹配很好的低优先类别:实测「Chadstone」会得到
#    "Holmesglen Institute Chadstone Campus"(一所学院)而不是 Chadstone
#    购物中心,「Flinders Street Station」会得到 "Torrens University
#    Flinders Street Campus" 而不是火车站。
#    所以:**先比名字匹配得多好,再比类别**。
_KIND_PRIORITY = {
    # 一眼就知道是目的地的大地方
    "train_station": 1, "airport": 1, "hospital": 1, "university": 1, "mall": 1,
    "library": 2, "park": 2, "beach": 2, "sports_centre": 2, "police": 2,
    "secondary_school": 3, "primary_school": 3, "kindergarten": 3,
    "supermarket": 4, "pharmacy": 4, "bank": 4, "gym": 4,
    # 站点名字里常带目的地(「Chadstone Shopping Centre (Bay 8)」),
    # 能用但不该压过那个目的地本身
    "tram_stop": 5, "bus_stop": 5,
}
_MEASURE_KINDS = tuple(_KIND_PRIORITY)


def place_point(query: str, near: tuple | None = None, kind: str | None = None) -> dict | None:
    """按名字解析出**一个**地点,带坐标。找不到返回 None。

    排序口径(依次比较):
      1. 名字是不是就等于用户输入的
      2. 一头包着另一头(输入「Flinders Street Station」,点名叫「Flinders Street」)
      3. 类别优先级(见 _KIND_PRIORITY 上方的注释)
      4. 名字里多出来几个词 —— 多得越少越贴
      5. 离 near 多远 —— 同名的多个点(大学的几个校区、连锁网点)取最近的那个,
         和 distance_to_place() 的取法一致,免得同一个问题在两个入口得到两个答案
    """
    q = (query or "").strip()
    if not q:
        return None
    ql = q.lower()
    qt = _tokens(q)

    seen, cands = set(), []
    for k in ((kind,) if kind else _MEASURE_KINDS):
        for h in find_place(q, kind=k):
            key = (h["name"], h["kind"], round(h["latitude"], 6), round(h["longitude"], 6))
            if key not in seen:
                seen.add(key)
                cands.append(h)
    if not cands and not kind:
        # 兜底:不限类别。会命中路名、汽车经销商之类的东西,所以放在最后 ——
        # 但保留它:宁可给一个类别不太对的点并把类别显示出来,也比"查不到"有用,
        # 因为用户看得见图钉插在哪儿,自己能判断对不对。
        cands = find_place(q)
    if not cands:
        return None

    def rank(h):
        nl = h["name"].lower()
        return (
            0 if nl == ql else 1,
            0 if (nl.startswith(ql) or ql.startswith(nl)) else 1,
            _KIND_PRIORITY.get(h["kind"], 9),
            len(_tokens(h["name"]) - qt),
        )

    best_key = min(rank(h) for h in cands)
    tied = [h for h in cands if rank(h) == best_key]
    best = tied[0]
    if near and len(tied) > 1:
        lat, lon = near
        group = {"lat": np.radians(np.array([h["latitude"] for h in tied], dtype=np.float64)),
                 "lon": np.radians(np.array([h["longitude"] for h in tied], dtype=np.float64))}
        best = tied[int(np.argmin(_haversine_m(lat, lon, group)))]
    return {"name": best["name"], "kind": best["kind"],
            "latitude": float(best["latitude"]), "longitude": float(best["longitude"]),
            "matches": len(cands)}
