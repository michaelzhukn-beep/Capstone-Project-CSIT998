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
# 特别地,_SEARCH_SQL 和 search_properties() 的签名一个字都没动 ——
# 那是跨线契约,改了就毁了 B 的交付。

# %%
import torch
from sentence_transformers import SentenceTransformer

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
_SEARCH_SQL = """
    SELECT id, suburb, address, property_type, price, bedrooms, bathrooms,
           car_spaces, land_size, building_area, distance_cbd,
           latitude, longitude, annual_rent, description
    FROM properties
    WHERE (%(max_price)s IS NULL OR price <= %(max_price)s)
      AND (%(min_price)s IS NULL OR price >= %(min_price)s)
      AND (%(bedrooms)s IS NULL OR bedrooms = %(bedrooms)s)
      AND (%(bathrooms)s IS NULL OR bathrooms = %(bathrooms)s)
      AND (%(property_type)s IS NULL OR property_type = %(property_type)s)
      AND (%(suburb)s IS NULL OR lower(suburb) = lower(%(suburb)s))
    ORDER BY embedding <=> %(query_vector)s
    LIMIT %(limit)s
"""


def search_properties(
    semantic_query: str,
    max_price: int | None = None,
    min_price: int | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    property_type: str | None = None,
    suburb: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return up to `limit` property records matching the constraints,
    ranked by semantic similarity to `semantic_query`."""
    query_vector = _get_model().encode("search_query: " + semantic_query, normalize_embeddings=True)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_SEARCH_SQL, {
            "max_price": max_price,
            "min_price": min_price,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "property_type": property_type,
            "suburb": suburb,
            "query_vector": query_vector,
            "limit": limit,
        })
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
