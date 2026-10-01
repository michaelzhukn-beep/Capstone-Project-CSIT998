# %% [markdown]
# ## Setup
#
# search_properties() per contracts.md §3.1. Hard constraints are enforced
# as SQL filters (None = not specified = ignored); semantic_query is ranked
# by pgvector cosine distance. Returns records shaped exactly per §2 — only
# the documented keys, embedding never included, missing optionals are
# None (never 0/"").
#
# 搬迁自仓库根目录的 search.py(Member B 的交付)。V1_TASKS.md 第 3 步,
# 只改 4 处,其余一个字不动:
#   1. DB_DSN 硬编码      -> from app.core.config import DB_DSN(经 db.py 用)
#   2. connect + try/finally -> with get_connection()(用连接池)
#   3. register_vector(conn) -> 删掉(已移入 db.py,连接级注册归池子管)
#   4. MODEL_NAME 硬编码   -> from app.core.config import EMBED_MODEL
# 特别地,_SEARCH_SQL 和 search_properties() 的签名在迁移时一个字都没动 ——
# 那是跨线契约。
#
# **之后唯一一处经所有者同意的改动:加了可选参数 order_by**(2026-09-15,审计 BUG-04)。
# 默认值 None 时 SQL 与原来逐字相同,已有调用方不受影响。起因:硬条件命中超过候选上限
# (5,000)时,编排层只能在语义最相关的那 5,000 套里按价格/回报率排序 ——「80 万以内最便宜」
# 命中 8,246 套,系统给的前 5 漏掉了库里真正最便宜的 $131k、$145k、$160k。价格和毛回报率
# 都是库里的列,本来就能在 SQL 里排。

# %%
import torch
from sentence_transformers import SentenceTransformer

from app.analytics.formulas import roi_order_sql
from app.core.config import EMBED_MODEL
from app.core.db import get_connection

MODEL_NAME = EMBED_MODEL

_model = None


def _pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device=_pick_device())
    return _model

# %% [markdown]
# ## search_properties()

# %%
# 检索结果与「按编号取」共用同一组列:下游 analyze / enrich / present 依赖的字段必须完全一致
_COLUMNS = """id, suburb, address, property_type, price, bedrooms, bathrooms,
           car_spaces, land_size, building_area, distance_cbd,
           latitude, longitude, annual_rent, description"""

_SEARCH_SQL = """
    SELECT """ + _COLUMNS + """
    FROM properties
    WHERE (%(max_price)s IS NULL OR price <= %(max_price)s)
      AND (%(min_price)s IS NULL OR price >= %(min_price)s)
      AND (%(bedrooms)s IS NULL OR bedrooms = %(bedrooms)s)
      AND (%(bathrooms)s IS NULL OR bathrooms = %(bathrooms)s)
      AND (%(property_type)s IS NULL OR property_type = %(property_type)s)
      AND (%(suburb)s IS NULL OR lower(suburb) = lower(%(suburb)s))
    ORDER BY {order}embedding <=> %(query_vector)s, id
    LIMIT %(limit)s
"""

# order_by 白名单 -> ORDER BY 前缀。**只接受这几个固定字符串**,不拼接调用方传进来的任何文本。
# 语义距离始终作为最后一级,同价/同回报率时仍按相关度排。
_ORDER_BY = {
    None: "",
    # 价格 ≤ 0 是「价格不可用」,不是最便宜:排到最后,免得它们占掉候选池的头部位置
    "price_asc": "CASE WHEN price > 0 THEN 0 ELSE 1 END, price ASC, ",
    "price_desc": "price DESC, ",
    # 毛回报率 = 年租金 / 售价。cap_rate 与它同序(同一个运营支出比例),ROI 近似同序
    "gross_yield": "annual_rent::float / NULLIF(price, 0) DESC NULLS LAST, ",
    # ROI 的分母含分档累进印花税与杂费,和毛回报率不同序(按毛回报率截候选会漏掉真正的 ROI 最高者)。
    # 这里按**不取整**的 ROI 预排序取候选池;最终顺序与「哪几名可证明精确」由 Python 侧决定(formulas.roi_certified_prefix)。
    "roi": roi_order_sql() + " DESC NULLS LAST, ",
}


def _order_params(order_by, opex_rate, other_costs) -> dict:
    """order_by='roi' 才需要两个假设;缺了就报错,不悄悄用默认值。"""
    if order_by == "roi":
        if opex_rate is None or other_costs is None:
            raise ValueError("order_by='roi' 需要同时给 opex_rate 和 other_costs")
        return {"opex_rate": float(opex_rate), "other_costs": float(other_costs)}
    return {"opex_rate": None, "other_costs": None}


def search_properties(
    semantic_query: str,
    max_price: int | None = None,
    min_price: int | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    property_type: str | None = None,
    suburb: str | None = None,
    limit: int = 10,
    order_by: str | None = None,
    opex_rate: float | None = None,
    other_costs: float | None = None,
) -> list[dict]:
    """Return up to `limit` property records matching the constraints,
    ranked by semantic similarity to `semantic_query`.

    order_by: None(默认,纯语义相关度)| "price_asc" | "price_desc" | "gross_yield" | "roi"(需同时给 opex_rate 与 other_costs;按不取整 ROI 预排序)。
    给了就先按这一列排、语义距离兜底 —— 截到 limit 时留下的是**全库**这一列最靠前的那批。
    """
    if order_by not in _ORDER_BY:
        raise ValueError(f"order_by 只能是 {sorted(k for k in _ORDER_BY if k)} 或 None")
    order_args = _order_params(order_by, opex_rate, other_costs)
    query_vector = _get_model().encode("search_query: " + semantic_query, normalize_embeddings=True)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_SEARCH_SQL.format(order=_ORDER_BY[order_by]), {
            "max_price": max_price,
            "min_price": min_price,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "property_type": property_type,
            "suburb": suburb,
            "query_vector": query_vector,
            "limit": limit,
            **order_args,
        })
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def properties_by_ids(ids: list[int]) -> list[dict]:
    """按编号取房源,列与 search_properties 完全相同(收藏夹打开详情用)。按传入顺序返回,查不到的跳过。"""
    ids = [int(i) for i in ids]
    if not ids:
        return []
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM properties WHERE id = ANY(%s)", (ids,))
        columns = [d[0] for d in cur.description]
        rows = {r[0]: dict(zip(columns, r)) for r in cur.fetchall()}
    return [rows[i] for i in ids if i in rows]
