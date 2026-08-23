# Member B's tasks — progress notes

Member B owns: the dataset, the `properties` database table, and the `search_properties()` function (see `contracts.md`). This note covers what's been done so far on the data side.

## Project layout

```
data/         raw + processed CSVs/XLSX (mostly gitignored — see note below)
db/           docker-compose.yml (Postgres+pgvector) and schema.sql
pipeline/     one-off scripts that build the dataset, run in this order:
              eda_melbourne_housing.py  →  match_suburb_precinct.py  →
              aggregate_rent_benchmarks.py  →  join_annual_rent.py  →
              build_description.py  →  load_properties.py
search.py         the actual contract deliverable — search_properties()
test_search.py    its test suite
```

All scripts assume they're run from the project root, e.g. `python3 pipeline/eda_melbourne_housing.py`, `python3 search.py`. Database commands run from `db/`: `cd db && docker compose up -d`.

## Dataset

We're using the **Melbourne Housing Market** dataset from Kaggle:
https://www.kaggle.com/datasets/anthonypino/melbourne-housing-market?resource=download&select=MELBOURNE_HOUSE_PRICES_LESS.csv

Chosen because our project is scoped to the Australian market (AUD prices, ABS/DFFH-style rent sources, "distance to CBD" concept — all Australia-specific), and this dataset matches our required schema (`contracts.md`) better than the alternatives we checked (Perth, Sydney, etc.) — mainly because it already has a proper `property_type` column (house/unit/townhouse), which most others don't.

The download has two files:

- **FULL**: more columns (bedrooms, bathrooms, land size, building area, year built, lat/long), fewer rows (~34,857), more missing values per column
- **LESS**: fewer columns, more rows (~63,000), but missing several columns our schema needs (bedrooms, bathrooms, etc.)

We're using **FULL** — it's the one that actually covers the required schema fields, even though it has more gaps to clean up.

![](./Pasted%20image%2020260822180012.png)

## Data quality check (EDA)

Ran a full exploratory pass on the dataset — missing values, duplicates, suburb naming consistency, sanity checks on distance/price/land size/lat-long. Found and need to fix: two suburb name casing bugs (`viewbank`/`Viewbank`, and one malformed row `"Fawkner Lot"` that should just be `"Fawkner"`).

Script: `pipeline/eda_melbourne_housing.py` (also available as a Jupyter notebook)

## The two missing required fields: `annual_rent` and `description`

Our schema requires both, but this dataset has neither. Contract rules: never fabricate a "real-looking" number — either ground it in a real source, or leave it as `None`.

### `annual_rent` — done ✅

Rather than assume a rent value, we sourced real rent data from the Victorian Government and joined it to every property:

- Source: DFFH (Homes Victoria) "Moving Annual Rents by Suburb" report — real quarterly rent data, publicly published:
  https://discover.data.vic.gov.au/dataset/rental-report-quarterly-moving-annual-rents-by-suburb

- Problem: this rent report groups suburbs into ~150 broader "precincts" (e.g. "Albert Park-Middle Park-West St Kilda") that don't match our dataset's individual suburb names. Matched them automatically using suburb name matching first, then geographic distance for anything left over (nearest precinct, and if a suburb turned out to be independent — not part of any precinct — nearest region instead). Ended with **100% of suburbs matched**, no manual lookup needed for the vast majority.

- Result: every property now has a real `annual_rent` value sourced from actual government rent data for the right suburb/property type/bedroom count/time period. A small backup ("gross yield assumption") method exists for edge cases but wasn't actually needed — real data covered everything.

Scripts: `pipeline/match_suburb_precinct.py` (suburb matching) → `pipeline/aggregate_rent_benchmarks.py` (builds the rent lookup table) → `pipeline/join_annual_rent.py` (adds `annual_rent` to every property)

Output: `data/property_with_annual_rent.csv`

### `description` — done ✅

Skipped the LLM-paraphrase idea in the end — decided a plain template (facts only, no invented adjectives like "quiet"/"family-friendly") was the safer and equally effective choice, since embedding models don't need natural prose to work well and the LLM step only adds hallucination risk and cost for no proven benefit. Added 3 rotating phrasing variants (same facts, different wording, picked by a stable hash per row) so near-identical properties don't get byte-identical description text.

Also found and dropped 1 row during this step: the "Fawkner Lot" row was missing `bedrooms`, `bathrooms`, AND `distance_cbd` (all required by the contract) — no honest fallback could fill those in, so it's excluded rather than patched.

Script: `pipeline/build_description.py`
Output: `data/property_with_description.csv` (34,856 rows — down from 34,857 after the drop)

## Embedding model — decided ✅

Going with **`nomic-ai/nomic-embed-text-v1.5`** — 768 dimensions, free, runs locally (no API key/cost), Apache 2.0.

Why: compared against `bge-base-en-v1.5`, OpenAI's `text-embedding-3-small`, and a couple of others on retrieval quality, cost, and popularity — Nomic came out ahead or roughly tied on all of them, and it's the most-downloaded of the realistic options (16.5M downloads/month on Hugging Face vs 11.9M for BGE). Cost was a non-issue either way — even the paid OpenAI option would only run about 4 cents to embed our whole dataset.

**Important implementation detail**: Nomic requires a task-instruction prefix on every input — `"search_document: "` when embedding property descriptions, `"search_query: "` when embedding a user's search phrase at query time. Getting this backwards silently degrades results (no error, just worse rankings), so don't skip it.

This resolves the `vector(N)` pending item — **N = 768**. (Not touching `contracts.md` directly per Binh's call — this note is the source of truth for now, can get folded into `contracts.md` properly when it's next updated with the team.)

## Database — done ✅

Postgres + pgvector running locally via Docker (`db/docker-compose.yml` — `cd db && docker compose up -d`). Table schema in `db/schema.sql`, matches contracts.md §1 exactly (`embedding vector(768)`), plus an HNSW cosine index for the actual similarity search and a `rent_source` extra column for our own traceability.

**Important data decision made here — flagging for the team**: `bedrooms` and `bathrooms` (both required fields) turned out to be missing together in ~8,225 rows (a distinct "incomplete listing" batch — same rows also lack car spaces/land size/lat-long), and `price` was separately missing in ~5,831 more. No honest fallback exists for these the way there was for `annual_rent`, so — discussed and decided together — we **dropped** every row missing any of price/bedrooms/bathrooms rather than estimate them. Final dataset: **20,800 rows (59.7% of the original 34,857)**. Every field in the database is now either directly observed or grounded in a real source — nothing estimated or guessed, same principle used for `annual_rent`. Worth flagging to Member C since it also affects how much data is available for the valuation model.

Script: `pipeline/load_properties.py` — embeds every description (with Nomic's required `"search_document: "` prefix) and loads everything into Postgres in one pass.

Verified working: 20,800 rows loaded, 0 null embeddings, and a real vector similarity query returns sensible results (nearby Abbotsford houses cluster together).

## Next steps

- [x] Fix the two suburb casing bugs found in EDA — renames applied in `pipeline/match_suburb_precinct.py` / `pipeline/join_annual_rent.py` (Fawkner Lot → Fawkner, viewbank → Viewbank), carried through the rest of the pipeline from there
- [x] Build `description` field
- [x] Pick embedding model
- [x] Set up PostgreSQL + pgvector, create the `properties` table
- [x] Generate embeddings, load everything into the database
- [x] Build `search_properties()` — implemented + tested in `search.py` / `test_search.py`. All of Member B's contract deliverables (dataset, `properties` table, `search_properties()`) are now done.
