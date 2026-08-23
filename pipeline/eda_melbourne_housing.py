# %% [markdown]
# ## Setup

# %%
import pandas as pd
import matplotlib.pyplot as plt

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 160)

DATA_DIR = "data"
FULL_PATH = f"{DATA_DIR}/Melbourne_housing_FULL.csv"
LESS_PATH = f"{DATA_DIR}/MELBOURNE_HOUSE_PRICES_LESS.csv"

# %% [markdown]
# ## Load both files and compare shape / columns

# %%
df_full = pd.read_csv(FULL_PATH)
df_less = pd.read_csv(LESS_PATH)

print("FULL:", df_full.shape)
print("LESS:", df_less.shape)

print("\nColumns only in FULL:", set(df_full.columns) - set(df_less.columns))
print("Columns only in LESS:", set(df_less.columns) - set(df_full.columns))
print("Columns in both:     ", set(df_full.columns) & set(df_less.columns))

# %% [markdown]
# ## Missingness in FULL

# %%
missing_full = (
    df_full.isna().mean().mul(100).round(1).sort_values(ascending=False)
)
print("Missing % per column — FULL")
print(missing_full)

# %% [markdown]
# ## Missingness in LESS

# %%
missing_less = (
    df_less.isna().mean().mul(100).round(1).sort_values(ascending=False)
)
print("Missing % per column — LESS")
print(missing_less)

# %% [markdown]
# ## Row-key overlap between FULL and LESS
#
# Join key: `Suburb` + `Address` + `Date` should uniquely identify a sale in both files.

# %%
key_cols = ["Suburb", "Address", "Date"]

full_keys = set(map(tuple, df_full[key_cols].values))
less_keys = set(map(tuple, df_less[key_cols].values))

print("Unique keys in FULL:", len(full_keys))
print("Unique keys in LESS:", len(less_keys))
print("Keys in both:        ", len(full_keys & less_keys))
print("Keys only in FULL:    ", len(full_keys - less_keys))
print("Keys only in LESS:    ", len(less_keys - full_keys))

# %% [markdown]
# ## Price coverage and distribution
#
# Does LESS actually have `Price` for every row? (It doesn't — check the numbers.)

# %%
print("FULL — rows with non-null Price:", df_full["Price"].notna().sum(), "/", len(df_full))
print("LESS — rows with non-null Price:", df_less["Price"].notna().sum(), "/", len(df_less))

print("\nFULL Price describe:\n", df_full["Price"].describe())
print("\nLESS Price describe:\n", df_less["Price"].describe())

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
df_full["Price"].dropna().plot(kind="hist", bins=60, ax=axes[0], title="FULL — Price")
df_less["Price"].dropna().plot(kind="hist", bins=60, ax=axes[1], title="LESS — Price")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## `Type` column → contracts.md `property_type` mapping
#
# The contract requires `property_type` in `{"house", "apartment", "townhouse"}`.

# %%
print("FULL Type value counts:\n", df_full["Type"].value_counts())
print("\nLESS Type value counts:\n", df_less["Type"].value_counts())

TYPE_MAP = {"h": "house", "u": "apartment", "t": "townhouse"}
unmapped_full = set(df_full["Type"].dropna().unique()) - set(TYPE_MAP.keys())
unmapped_less = set(df_less["Type"].dropna().unique()) - set(TYPE_MAP.keys())
print("\nUnmapped Type codes in FULL:", unmapped_full)
print("Unmapped Type codes in LESS:", unmapped_less)

# %% [markdown]
# ## Suburb naming consistency
#
# The contract requires standardised casing, no abbreviations. Flag any suburb name
# that appears in more than one casing/whitespace variant.

# %%
def casing_variants(df):
    normalized = df["Suburb"].str.strip().str.lower()
    grouped = df["Suburb"].groupby(normalized).unique()
    return {k: list(v) for k, v in grouped.items() if len(v) > 1}

print("Distinct suburbs — FULL:", df_full["Suburb"].nunique())
print("Distinct suburbs — LESS:", df_less["Suburb"].nunique())
print("\nSuburb casing variants — FULL:", casing_variants(df_full))
print("Suburb casing variants — LESS:", casing_variants(df_less))

# %% [markdown]
# ## Distance to CBD sanity check
#
# Rows with 0 or implausibly large distance are worth a manual look.

# %%
print("FULL Distance describe:\n", df_full["Distance"].describe())
print("\nLESS Distance describe:\n", df_less["Distance"].describe())

print("\nFULL rows with Distance == 0:", (df_full["Distance"] == 0).sum())
print("FULL rows with Distance > 50:", (df_full["Distance"] > 50).sum())

# %% [markdown]
# ## Bedrooms / bathrooms / car spaces sanity checks
#
# FULL only — LESS lacks these columns.

# %%
for col in ["Bedroom2", "Bathroom", "Car"]:
    print(f"\n{col} value counts (top 10):")
    print(df_full[col].value_counts(dropna=False).sort_index().head(10))

print("\nRows with Bathroom == 0:", (df_full["Bathroom"] == 0).sum())
print("Rows with Bedroom2 == 0:", (df_full["Bedroom2"] == 0).sum())

# %% [markdown]
# ## Block 10 — Land size / building area: sparsity and outliers
#
# FULL only.

# %%
for col in ["Landsize", "BuildingArea"]:
    s = df_full[col]
    print(f"\n{col} — missing: {s.isna().mean():.1%}, zeros: {(s == 0).mean():.1%}")
    print(s.describe())

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
df_full["Landsize"].clip(upper=df_full["Landsize"].quantile(0.99)).plot(
    kind="hist", bins=60, ax=axes[0], title="Landsize (clipped at p99)"
)
df_full["BuildingArea"].clip(upper=df_full["BuildingArea"].quantile(0.99)).plot(
    kind="hist", bins=60, ax=axes[1], title="BuildingArea (clipped at p99)"
)
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Block 11 — Lat/long sanity check
#
# FULL only. Checks missingness and a rough bounding box for greater Melbourne.

# %%
print("Missing lat/long:", df_full[["Lattitude", "Longtitude"]].isna().mean())

lat_ok = df_full["Lattitude"].between(-38.5, -37.0)
lon_ok = df_full["Longtitude"].between(144.4, 145.6)
out_of_bounds = df_full[["Lattitude", "Longtitude"]].dropna().shape[0] - (lat_ok & lon_ok).sum()
print("Rows with lat/long outside expected Melbourne bounding box:", out_of_bounds)

# %% [markdown]
# ## Block 12 — Duplicate rows

# %%
print("Exact duplicate rows — FULL:", df_full.duplicated().sum())
print("Exact duplicate rows — LESS:", df_less.duplicated().sum())

print("Duplicate (Suburb, Address, Date) — FULL:", df_full.duplicated(subset=key_cols).sum())
print("Duplicate (Suburb, Address, Date) — LESS:", df_less.duplicated(subset=key_cols).sum())

# %% [markdown]
# ## Block 13 — Contract-column coverage summary
#
# Maps contracts.md's required `properties` columns to what each file actually offers,
# so the dataset choice (FULL vs LESS vs a merge) is a documented decision, not a guess.

# %%
CONTRACT_COLUMNS = {
    "suburb": "Suburb",
    "address": "Address",
    "property_type": "Type",
    "price": "Price",
    "bedrooms": "Bedroom2",       # FULL only; LESS has "Rooms" instead
    "bathrooms": "Bathroom",      # FULL only
    "car_spaces": "Car",          # FULL only
    "land_size": "Landsize",      # FULL only
    "building_area": "BuildingArea",  # FULL only
    "year_built": "YearBuilt",    # FULL only
    "distance_cbd": "Distance",
    "latitude": "Lattitude",      # FULL only
    "longitude": "Longtitude",    # FULL only
    "sale_date": "Date",
    "annual_rent": None,          # not present in either file
    "description": None,          # not present in either file
}

rows = []
for contract_col, source_col in CONTRACT_COLUMNS.items():
    in_full = source_col in df_full.columns if source_col else False
    in_less = source_col in df_less.columns if source_col else False
    rows.append({"contract_column": contract_col, "source_column": source_col,
                 "in_FULL": in_full, "in_LESS": in_less})

summary = pd.DataFrame(rows)
print(summary.to_string(index=False))
