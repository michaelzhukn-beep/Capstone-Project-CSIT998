# %% [markdown]
# ## Setup
#
# Matches each property-dataset `Suburb` to a rent-report precinct label.
# Strategy: exact match -> hyphen-part exact match -> substring containment ->
# everything left over gets fuzzy candidates printed for manual review (no
# auto-assignment on the fuzzy tier).

# %%
import re

import openpyxl
import pandas as pd
from rapidfuzz import fuzz, process

PROPERTY_CSV = "data/Melbourne_housing_FULL.csv"
RENT_XLSX = "data/moving_annual_rent_by_suburb.xlsx"
RENT_SHEET = "3 bedroom house"  # precinct/region labels are the same across all sheets
OUTPUT_CSV = "data/suburb_precinct_mapping.csv"

FUZZY_CANDIDATES = 3
FUZZY_MIN_SCORE = 60  # below this, don't even bother showing it as a candidate


def normalize(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9\s]", " ", name)  # drop punctuation/hyphens
    name = re.sub(r"\s+", " ", name).strip()
    return name

# %% [markdown]
# ## Load property suburbs

# %%
df_prop = pd.read_csv(PROPERTY_CSV)

# %% [markdown]
# ## Manual overrides for known data-quality issues
#
# Found while building this mapping — carry these into the real cleaning
# pipeline too, this is just applying them locally so the matching below is
# correct.
#
# - "Fawkner Lot" is not a suburb: a single malformed row (1/3 Brian St, every
#   other field null). The real suburb is "Fawkner" (211 clean rows already
#   matched fine) -> rename.
# - "viewbank" (lowercase, 1 row) is a casing duplicate of "Viewbank"
#   (100 rows, already matched) -> rename.
# - "MacLeod" and "Olinda" have zero rows with lat/long in this dataset ->
#   backfill with manually looked-up suburb coordinates.

# %%
df_prop["Suburb"] = df_prop["Suburb"].replace({"Fawkner Lot": "Fawkner", "viewbank": "Viewbank"})

MANUAL_COORDS = {
    "MacLeod": (-37.7243102, 145.0590133),
    "Olinda": (-37.8557452, 145.1798592),
}
for suburb, (lat, lon) in MANUAL_COORDS.items():
    mask = df_prop["Suburb"] == suburb
    df_prop.loc[mask, "Lattitude"] = df_prop.loc[mask, "Lattitude"].fillna(lat)
    df_prop.loc[mask, "Longtitude"] = df_prop.loc[mask, "Longtitude"].fillna(lon)

property_suburbs = sorted(df_prop["Suburb"].dropna().unique())
print("Distinct property suburbs:", len(property_suburbs))

# %% [markdown]
# ## Load rent precincts (+ region column) from the workbook

# %%
wb = openpyxl.load_workbook(RENT_XLSX, read_only=True, data_only=True)
ws = wb[RENT_SHEET]

precincts = []          # [(region, precinct_label), ...]
current_region = None
for row in ws.iter_rows(min_row=4, values_only=True):
    region, precinct = row[0], row[1]
    if region:
        current_region = region
    if precinct:
        precincts.append((current_region, precinct))

print("Rent precinct rows:", len(precincts))
print(precincts[:5])

# %% [markdown]
# ## Tier 1 — exact match
#
# Normalized property suburb == normalized precinct label.

# %%
precinct_by_norm = {normalize(label): (region, label) for region, label in precincts}

results = []
unresolved = []

for suburb in property_suburbs:
    norm_suburb = normalize(suburb)
    if norm_suburb in precinct_by_norm:
        region, label = precinct_by_norm[norm_suburb]
        results.append({
            "property_suburb": suburb,
            "matched_precinct": label,
            "region": region,
            "match_method": "exact",
        })
    else:
        unresolved.append(suburb)

print(f"Tier 1 exact matches: {len(results)} / {len(property_suburbs)}")
print(f"Remaining after tier 1: {len(unresolved)}")

# %% [markdown]
# ## Tier 2 — hyphen-part exact match
#
# Precinct labels are hyphen-joined suburb groups, e.g.
# "Albert Park-Middle Park-West St Kilda". Split on "-" and check each part
# for an exact normalized match against the suburb.

# %%
precinct_parts = []  # [(region, label, [normalized_part, ...]), ...]
for region, label in precincts:
    parts = [normalize(p) for p in label.split("-")]
    precinct_parts.append((region, label, parts))

still_unresolved = []
for suburb in unresolved:
    norm_suburb = normalize(suburb)
    match = next(
        ((region, label) for region, label, parts in precinct_parts if norm_suburb in parts),
        None,
    )
    if match:
        region, label = match
        results.append({
            "property_suburb": suburb,
            "matched_precinct": label,
            "region": region,
            "match_method": "hyphen_part",
        })
    else:
        still_unresolved.append(suburb)

unresolved = still_unresolved
print(f"Tier 2 hyphen-part matches: {len(results) - len([r for r in results if r['match_method'] == 'exact'])}")
print(f"Remaining after tier 2: {len(unresolved)}")

# %% [markdown]
# ## Tier 3 — substring containment
#
# Catches partial overlaps that aren't a clean hyphen-split part, e.g. a
# suburb name embedded inside a longer precinct label or vice versa.

# %%
still_unresolved = []
for suburb in unresolved:
    norm_suburb = normalize(suburb)
    candidates = [
        (region, label) for region, label in precincts
        if norm_suburb in normalize(label) or normalize(label) in norm_suburb
    ]
    if len(candidates) == 1:
        region, label = candidates[0]
        results.append({
            "property_suburb": suburb,
            "matched_precinct": label,
            "region": region,
            "match_method": "substring",
        })
    elif len(candidates) > 1:
        # ambiguous substring match — don't guess, send to fuzzy/manual review
        still_unresolved.append(suburb)
    else:
        still_unresolved.append(suburb)

unresolved = still_unresolved
print(f"Remaining after tier 3: {len(unresolved)}")

# %% [markdown]
# ## Tier 4 — geographic nearest-REGION fallback (not precinct)
#
# Some suburbs are genuinely independent — never grouped into any precinct
# by DFFH at all (e.g. Aberfeldie sits next to the Essendon precinct but
# isn't part of it). Guessing a precinct for these fabricates a membership
# that doesn't exist. But DFFH's 13 regions are large enough that "which
# region is this suburb in" is basically unambiguous by geography, unlike
# "which precinct". So: compute each region's centroid from its resolved
# precincts, assign each unresolved suburb to its nearest region, and use
# a region-wide aggregate rent figure for it — honestly coarser-grained,
# fully automatic, zero manual lookup required.

# %%
import math

def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


suburb_centroid = df_prop.groupby("Suburb")[["Lattitude", "Longtitude"]].mean()

resolved_suburb_to_precinct = {r["property_suburb"]: r["matched_precinct"] for r in results}
label_to_region = {label: region for region, label in precincts}

# precinct centroid = mean of its resolved member suburbs' centroids
precinct_centroids = {}
for suburb, precinct_label in resolved_suburb_to_precinct.items():
    if suburb not in suburb_centroid.index:
        continue
    lat, lon = suburb_centroid.loc[suburb, ["Lattitude", "Longtitude"]]
    if pd.isna(lat) or pd.isna(lon):
        continue
    precinct_centroids.setdefault(precinct_label, []).append((lat, lon))

precinct_centroid_point = {
    label: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    for label, pts in precinct_centroids.items()
}

# region centroid = mean of its resolved precincts' centroids
region_precinct_points = {}
for label, point in precinct_centroid_point.items():
    region = label_to_region.get(label)
    if region:
        region_precinct_points.setdefault(region, []).append(point)

region_centroid_point = {
    region: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    for region, pts in region_precinct_points.items()
}

print(f"Regions with a computable centroid: {len(region_centroid_point)}")

# %% [markdown]
# ## Assign each unresolved suburb to its nearest region
#
# Also report the gap to the 2nd-nearest region — a small gap means the
# suburb sits near a region boundary and the assignment is less certain,
# worth a note in the report even though it's not worth manual review.

# %%
region_fallback_rows = []
no_geo = []

for suburb in unresolved:
    if suburb not in suburb_centroid.index:
        no_geo.append(suburb)
        continue
    lat, lon = suburb_centroid.loc[suburb, ["Lattitude", "Longtitude"]]
    if pd.isna(lat) or pd.isna(lon):
        no_geo.append(suburb)
        continue

    ranked = sorted(
        ((haversine_km(lat, lon, rlat, rlon), region) for region, (rlat, rlon) in region_centroid_point.items()),
        key=lambda x: x[0],
    )
    nearest_km, nearest_region = ranked[0]
    second_km, second_region = ranked[1]

    row = {
        "property_suburb": suburb,
        "matched_precinct": None,
        "region": nearest_region,
        "match_method": "region_geo_fallback",
        "region_km": round(nearest_km, 1),
        "second_nearest_region": second_region,
        "second_region_km": round(second_km, 1),
        "boundary_flag": (second_km - nearest_km) < 5,  # under 5km gap -> flag for a quick look
    }
    region_fallback_rows.append(row)
    results.append(row)

for suburb in no_geo:
    row = {"property_suburb": suburb, "matched_precinct": None, "region": None,
           "match_method": "no_geo_data"}
    results.append(row)

print(f"Assigned to nearest region automatically: {len(region_fallback_rows)}")
boundary_flags = sum(r["boundary_flag"] for r in region_fallback_rows)
print(f"Of those, near a region boundary (<5km gap to 2nd-nearest) — worth a quick look: {boundary_flags}")
print(f"No coordinates available at all (manual lookup only): {len(no_geo)} -> {no_geo}")

# %% [markdown]
# ## Summary + save

# %%
mapping_df = pd.DataFrame(results)
method_counts = mapping_df["match_method"].value_counts()
print(method_counts)
print(f"\nTotal: {len(mapping_df)} / {len(property_suburbs)} property suburbs")

mapping_df.to_csv(OUTPUT_CSV, index=False)
print(f"\nSaved to {OUTPUT_CSV}")

print("\nSuburbs near a region boundary (quick sanity check, not required):")
print(mapping_df[mapping_df.get("boundary_flag") == True].to_string(index=False))

print("\nSuburbs with no coordinates at all (genuinely need a manual/gross-yield fallback):")
print(mapping_df[mapping_df["match_method"] == "no_geo_data"].to_string(index=False))
