# %% [markdown]
# ## Setup

# %%
import json

from search import search_properties

# %% [markdown]
# ## Test 1 — record shape matches contracts.md §2 exactly

# %%
results = search_properties("modern apartment close to the city", limit=3)
print(f"Got {len(results)} results")

EXPECTED_KEYS = {
    "id", "suburb", "address", "property_type", "price", "bedrooms", "bathrooms",
    "car_spaces", "land_size", "building_area", "distance_cbd", "annual_rent",
    "description", "latitude", "longitude",
}
for r in results:
    assert set(r.keys()) == EXPECTED_KEYS, f"Key mismatch: {set(r.keys()) ^ EXPECTED_KEYS}"
    assert "embedding" not in r
    assert isinstance(r["price"], int)
    assert isinstance(r["annual_rent"], int)
    assert isinstance(r["distance_cbd"], float)
print("Shape check passed.")
print(json.dumps(results[0], indent=2, default=str))

# %% [markdown]
# ## Test 2 — hard filters are strictly enforced (not just ranked low)

# %%
results = search_properties(
    "quiet family home",
    max_price=800_000,
    bedrooms=3,
    property_type="house",
    limit=20,
)
print(f"Got {len(results)} results")
for r in results:
    assert r["price"] <= 800_000, r
    assert r["bedrooms"] == 3, r
    assert r["property_type"] == "house", r
print("Hard filter check passed — no violations.")

# %% [markdown]
# ## Test 3 — impossible constraints return an empty list, not an error

# %%
results = search_properties("anything", max_price=1, bedrooms=50, limit=10)
assert results == []
print("Empty-result check passed.")

# %% [markdown]
# ## Test 4 — does the query text actually change the ranking?
#
# If two very different queries return the same top result, the embedding
# isn't actually influencing anything and something's wrong.

# %%
suburb = "Richmond"
r1 = search_properties("spacious house with a large garden", suburb=suburb, limit=5)
r2 = search_properties("compact modern apartment", suburb=suburb, limit=5)

print(f"'spacious house with a large garden' in {suburb}:")
for r in r1:
    print(" -", r["description"][:80])

print(f"\n'compact modern apartment' in {suburb}:")
for r in r2:
    print(" -", r["description"][:80])

top_ids_1 = [r["id"] for r in r1]
top_ids_2 = [r["id"] for r in r2]
assert top_ids_1 != top_ids_2, "Both queries returned identical top-5 — ranking isn't responding to query text"
print("\nRanking differs between semantically different queries — passed.")

# %% [markdown]
# ## Test 5 — suburb filter is case-insensitive, matches contract's naming rule

# %%
r_lower = search_properties("house", suburb="richmond", limit=5)
r_proper = search_properties("house", suburb="Richmond", limit=5)
assert [r["id"] for r in r_lower] == [r["id"] for r in r_proper]
print("Case-insensitive suburb match check passed.")

print("\nAll tests passed.")
