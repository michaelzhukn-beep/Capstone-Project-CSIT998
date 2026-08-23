# %% [markdown]
# ## Setup

# %%
import hashlib

import pandas as pd

INPUT_CSV = "data/property_with_annual_rent.csv"
OUTPUT_CSV = "data/property_with_description.csv"

TYPE_LABEL = {"h": "house", "u": "apartment", "t": "townhouse"}
N_VARIANTS = 3

# %% [markdown]
# ## Load

# %%
df = pd.read_csv(INPUT_CSV)
print("Rows:", len(df))

# %% [markdown]
# ## Drop rows that fail the contract's required fields
#
# One row (originally "Fawkner Lot", renamed to "Fawkner" during suburb
# cleanup) has every structured field null except Suburb/Address/Rooms/
# Type/Price/Method/SellerG/Date — including `bedrooms`, `bathrooms`, and
# `distance_cbd`, all required by contracts.md §1. No template or fallback
# can honestly fill those in; this row can't satisfy the shared record
# contract no matter what we do to annual_rent/description, so it gets
# dropped rather than patched. (Verified it's the only row this broken —
# see match_suburb_precinct.py investigation.)

# %%
core_required = ["Bedroom2", "Bathroom", "Distance"]
before = len(df)
df = df[~df[core_required].isna().all(axis=1)].reset_index(drop=True)
print(f"Dropped {before - len(df)} row(s) missing all of bedrooms/bathrooms/distance_cbd")

# %% [markdown]
# ## Phrasing variants
#
# Same facts, different wording — no LLM, fully deterministic. Each row
# gets one variant index (stable hash of Suburb+Address+Date, not Python's
# randomized str hash) applied consistently across all its clauses, so one
# property reads in one coherent "voice" rather than mixing styles
# mid-description. Re-running the script on the same data always produces
# byte-identical output.

# %%
def variant_for(row) -> int:
    key = f"{row.Suburb}|{row.Address}|{row.Date}"
    digest = hashlib.md5(key.encode()).hexdigest()
    return int(digest[:8], 16) % N_VARIANTS


def core_v0(bed, ptype, suburb, extras):
    base = f"{bed}-bedroom {ptype} in {suburb}" if bed else f"{ptype.capitalize()} in {suburb}"
    if extras:
        base += " with " + " and ".join(extras)
    return base + "."


def core_v1(bed, ptype, suburb, extras):
    if bed:
        base = f"This {ptype} in {suburb} has {bed} bedroom" + ("s" if bed != 1 else "")
    else:
        base = f"This {ptype} is located in {suburb}"
    if extras:
        base += ", plus " + " and ".join(extras)
    return base + "."


def core_v2(bed, ptype, suburb, extras):
    if bed:
        base = f"{ptype.capitalize()} located in {suburb}, featuring {bed} bedroom" + ("s" if bed != 1 else "")
    else:
        base = f"{ptype.capitalize()} located in {suburb}"
    if extras:
        base += " along with " + " and ".join(extras)
    return base + "."


CORE_VARIANTS = [core_v0, core_v1, core_v2]


def loc_v0(dist, region):
    s = f"Located {dist:.1f} km from the Melbourne CBD"
    if region:
        s += f", in the {region} region"
    return s + "."


def loc_v1(dist, region):
    s = f"Situated {dist:.1f} km from the CBD"
    if region:
        s += f", within the {region} region"
    return s + "."


def loc_v2(dist, region):
    s = f"{dist:.1f} km from Melbourne's CBD"
    if region:
        s += f", part of the {region} region"
    return s + "."


LOC_VARIANTS = [loc_v0, loc_v1, loc_v2]


def size_v0(land, area):
    bits = [b for b in [f"land size {land}" if land else None, f"building area {area}" if area else None] if b]
    if not bits:
        return None
    s = " and ".join(bits)
    return s[0].upper() + s[1:] + "."


def size_v1(land, area):
    bits = [b for b in [f"a land size of {land}" if land else None, f"a building area of {area}" if area else None] if b]
    if not bits:
        return None
    return "The property has " + " and ".join(bits) + "."


def size_v2(land, area):
    bits = [b for b in [f"Land size: {land}" if land else None, f"Building area: {area}" if area else None] if b]
    if not bits:
        return None
    return ". ".join(bits) + "."


SIZE_VARIANTS = [size_v0, size_v1, size_v2]

YEAR_VARIANTS = [
    lambda year: f"Built in {year}.",
    lambda year: f"Constructed in {year}.",
    lambda year: f"Year built: {year}.",
]

COUNCIL_VARIANTS = [
    lambda council: f"{council}.",
    lambda council: f"Council area: {council}.",
    lambda council: f"Part of {council}.",
]

# %% [markdown]
# ## Template builder
#
# Only states facts the data actually supports. Missing/zero optional
# fields are omitted entirely rather than padded with "unknown". YearBuilt
# is bounds-checked (1840-2020) since this dataset has a few garbage
# values (e.g. 1196, 2106) that would otherwise get stated as fact.

# %%
def build_description(row) -> str:
    v = variant_for(row)
    ptype = TYPE_LABEL.get(row.Type, row.Type)
    parts = []

    bed = int(row.Bedroom2) if pd.notna(row.Bedroom2) and row.Bedroom2 > 0 else None
    extras = []
    if pd.notna(row.Bathroom) and row.Bathroom > 0:
        n = int(row.Bathroom)
        extras.append(f"{n} bathroom" + ("s" if n != 1 else ""))
    if pd.notna(row.Car) and row.Car > 0:
        n = int(row.Car)
        extras.append(f"{n} car space" + ("s" if n != 1 else ""))
    parts.append(CORE_VARIANTS[v](bed, ptype, row.Suburb, extras))

    region = row.Regionname if pd.notna(row.Regionname) else None
    parts.append(LOC_VARIANTS[v](row.Distance, region))

    land = f"{row.Landsize:.0f} m²" if pd.notna(row.Landsize) and row.Landsize > 0 else None
    area = f"{row.BuildingArea:.0f} m²" if pd.notna(row.BuildingArea) and row.BuildingArea > 0 else None
    size_sentence = SIZE_VARIANTS[v](land, area)
    if size_sentence:
        parts.append(size_sentence)

    if pd.notna(row.YearBuilt) and 1840 <= row.YearBuilt <= 2020:
        parts.append(YEAR_VARIANTS[v](int(row.YearBuilt)))

    if pd.notna(row.CouncilArea):
        parts.append(COUNCIL_VARIANTS[v](row.CouncilArea))

    return " ".join(parts)

# %% [markdown]
# ## Apply + save

# %%
df["description"] = [build_description(row) for row in df.itertuples()]

df.to_csv(OUTPUT_CSV, index=False)
print(f"Saved to {OUTPUT_CSV}")

# %% [markdown]
# ## Spot check — one property shown in all 3 variants, plus a random sample

# %%
sample_row = df.iloc[0]
print("Same property, forced through each variant (sanity check the wording differs cleanly):")
for i, fn in enumerate(CORE_VARIANTS):
    print(f"  v{i}:", fn(
        int(sample_row.Bedroom2) if pd.notna(sample_row.Bedroom2) and sample_row.Bedroom2 > 0 else None,
        TYPE_LABEL.get(sample_row.Type, sample_row.Type),
        sample_row.Suburb,
        ["2 bathrooms", "1 car space"],
    ))

print("\nVariant distribution:")
print(df.apply(lambda r: variant_for(r), axis=1).value_counts().sort_index())

print("\nRandom sample of full descriptions:")
for text in df["description"].sample(6, random_state=1):
    print("-", text)
