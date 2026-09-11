# %% [markdown]
# ## Setup

# %%
import math

import pandas as pd
import psycopg2
import torch
from sentence_transformers import SentenceTransformer

INPUT_CSV = "data/property_with_description.csv"
# 端口与 db/docker-compose.yml 一致(宿主 15432 -> 容器 5432)。
# 此处仍是硬编码,app/ 已改为从 app.core.config 读取;见 TODO。
DB_DSN = "postgresql://capstone:capstone@localhost:15432/capstone"
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
BATCH_SIZE = 256


def _pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

TYPE_LABEL = {"h": "house", "u": "apartment", "t": "townhouse"}

# %% [markdown]
# ## Load data

# %%
df = pd.read_csv(INPUT_CSV)
print("Rows:", len(df))

# %% [markdown]
# ## Drop rows that can't satisfy the contract's required fields
#
# `price`, `bedrooms`, `bathrooms` are all required (contracts.md §1) with
# no honest fallback available for any of them. `Bedroom2` is filled from
# `Rooms` first where possible (0% missing, matches Bedroom2 96.4% of the
# time when both are present — real observed data from the same listing,
# not a statistical guess). Everything still missing price/bedrooms/
# bathrooms after that gets dropped rather than imputed — same
# grounded-or-excluded principle used for annual_rent/description.
# Decision + numbers discussed with the team before running this.

# %%
df["Bedroom2"] = df["Bedroom2"].fillna(df["Rooms"])

before = len(df)
df = df.dropna(subset=["Price", "Bedroom2", "Bathroom"]).reset_index(drop=True)
print(f"Dropped {before - len(df)} rows missing price/bedrooms/bathrooms")
print(f"Remaining: {len(df)} rows ({len(df) / before:.1%})")

# %% [markdown]
# ## Generate embeddings
#
# Nomic requires a task-instruction prefix on every input — "search_document: "
# for the things being indexed. (The matching "search_query: " prefix belongs
# in search_properties() at query time, not here — different prefix, same
# model, so the two embedding spaces stay compatible.)

# %%
model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device=_pick_device())

prefixed = ["search_document: " + text for text in df["description"]]
embeddings = model.encode(prefixed, batch_size=BATCH_SIZE, show_progress_bar=True, normalize_embeddings=True)

print("Embedding shape:", embeddings.shape)

# %% [markdown]
# ## Map dataframe columns -> contracts.md schema
#
# `car_spaces` missing -> 0, per contracts.md's own documented default (not
# something we invented — the schema explicitly says "Default 0 when
# unknown" for this one column, unlike annual_rent/description which
# required a grounded fallback instead of a default).

# %%
def to_pynone(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def row_to_record(row):
    return {
        "suburb": row.Suburb,
        "address": to_pynone(row.Address),
        "property_type": TYPE_LABEL.get(row.Type, row.Type),
        "price": int(row.Price) if pd.notna(row.Price) else None,
        "bedrooms": int(row.Bedroom2),
        "bathrooms": int(row.Bathroom),
        "car_spaces": int(row.Car) if pd.notna(row.Car) else 0,
        "land_size": to_pynone(row.Landsize),
        "building_area": to_pynone(row.BuildingArea),
        "year_built": int(row.YearBuilt) if pd.notna(row.YearBuilt) and 1840 <= row.YearBuilt <= 2020 else None,
        "distance_cbd": float(row.Distance),
        "latitude": to_pynone(row.Lattitude),
        "longitude": to_pynone(row.Longtitude),
        "annual_rent": int(row.annual_rent),
        "description": row.description,
        "sale_date": pd.to_datetime(row.Date, dayfirst=True).date(),
        "rent_source": to_pynone(row.rent_source),
    }

# %% [markdown]
# ## Load into Postgres
#
# Every remaining row already satisfies the required-field contract (see
# the drop step above), so this is a straight insert.

# %%
conn = psycopg2.connect(DB_DSN)
cur = conn.cursor()

insert_sql = """
    INSERT INTO properties (
        suburb, address, property_type, price, bedrooms, bathrooms,
        car_spaces, land_size, building_area, year_built, distance_cbd,
        latitude, longitude, annual_rent, description, embedding,
        sale_date, rent_source
    ) VALUES (
        %(suburb)s, %(address)s, %(property_type)s, %(price)s, %(bedrooms)s, %(bathrooms)s,
        %(car_spaces)s, %(land_size)s, %(building_area)s, %(year_built)s, %(distance_cbd)s,
        %(latitude)s, %(longitude)s, %(annual_rent)s, %(description)s, %(embedding)s,
        %(sale_date)s, %(rent_source)s
    )
"""

inserted = 0
for row, embedding in zip(df.itertuples(), embeddings):
    record = row_to_record(row)
    record["embedding"] = embedding.tolist()
    cur.execute(insert_sql, record)
    inserted += 1

conn.commit()
print(f"Inserted: {inserted}")

cur.close()
conn.close()
