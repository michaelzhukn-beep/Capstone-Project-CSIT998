# AI-Driven Real Estate Assistant — Data & Search (Member B)

> **Working on this repo (human or AI agent)? Start with [`AGENTS.md`](./AGENTS.md)**
> and [`docs/PROJECT_STATE.md`](./docs/PROJECT_STATE.md). This repo is worked on by
> more than one AI agent, and those files — not any chat history — are the shared
> project memory.
>
> Note: the sections below describe Member B's original data/search track. The
> assistant itself now lives in `app/`; see `docs/ARCHITECTURE.md`.

This repo is Member B's track of a 3-person AI capstone project (see the team's shared `contracts.md` for the full interface contract across all tracks — not included in this repo, ask the team for the current copy). Member B owns three things:

1. The property dataset — sourced, cleaned, and enriched with real rental data
2. The `properties` table in Postgres + pgvector
3. `search_properties()` — hybrid SQL-filter + vector-similarity search

For the full story behind every decision (dataset choice, how missing `annual_rent`/`description` fields were handled, the embedding model comparison, the row-drop decision) see **[`Member B's tasks.md`](./Member%20B's%20tasks.md)**. This README is the "how do I run it" reference; that file is the "why did we do it this way" one.

## Project layout

```
data/         raw + processed CSVs/XLSX (mostly gitignored — see "Getting the data" below)
db/           docker-compose.yml (Postgres + pgvector) and schema.sql
pipeline/     one-off scripts that build the dataset (run once, in order — see below)
search.py         the actual deliverable — search_properties()
test_search.py    its test suite
requirements.txt
```

## Setup

Prerequisites: Python 3.13, Docker Desktop.

```bash
pip install -r requirements.txt
```

### 1. Start the database

```bash
cd db
docker compose up -d
docker exec -i capstone_postgres psql -U capstone -d capstone < schema.sql
cd ..
```

(If you have a local `psql` client installed, `psql postgresql://capstone:capstone@localhost:15432/capstone -f schema.sql` works too — the `docker exec` version above doesn't require anything installed beyond Docker itself.)

This starts Postgres 16 + pgvector in a container (`capstone_postgres`, host port 15432 -> container 5432, credentials `capstone`/`capstone`/`capstone` — local dev only) and creates the `properties` table with a 768-dim vector column and HNSW cosine index.

### 2. Getting the data

Most of `data/` is gitignored (large, and fully reproducible from the pipeline scripts) except `moving_annual_rent_by_suburb.xlsx`, which is committed since it's a small, dated government snapshot report you'd otherwise need to re-source correctly. You'll need to separately download:

- **Melbourne Housing Market** dataset from Kaggle — [anthonypino/melbourne-housing-market](https://www.kaggle.com/datasets/anthonypino/melbourne-housing-market). Download `Melbourne_housing_FULL.csv` and place it in `data/` — this is the one the pipeline actually builds on. `MELBOURNE_HOUSE_PRICES_LESS.csv` is only needed if you also want to run the EDA script's FULL-vs-LESS comparison (optional, see step 3) — grab it from the same Kaggle page if so.

### 3. Build the dataset

Run in order from the project root:

```bash
python3 pipeline/eda_melbourne_housing.py          # optional — sanity checks only, doesn't produce pipeline output
python3 pipeline/match_suburb_precinct.py          # suburb -> DFFH rent precinct/region mapping
python3 pipeline/aggregate_rent_benchmarks.py      # builds the rent lookup table
python3 pipeline/join_annual_rent.py               # adds annual_rent to every property
python3 pipeline/build_description.py              # adds description, drops rows that can't meet the contract's required fields
python3 pipeline/load_properties.py                # embeds every description and loads everything into Postgres
```

`load_properties.py` downloads the `nomic-embed-text-v1.5` embedding model (~500MB, first run only, then cached locally) and auto-uses your GPU if available (Apple Silicon MPS or CUDA, falls back to CPU otherwise).

### 4. Verify

```bash
python3 test_search.py
```

Should print `All tests passed.` — checks the returned record shape matches the contract exactly, hard filters are never violated, impossible constraints return `[]` rather than erroring, and that semantically different queries actually produce different rankings (i.e. the vector search is doing something, not just returning the same top results regardless of query).

## Using `search_properties()`

```python
from search import search_properties

results = search_properties(
    semantic_query="quiet apartment close to the city",
    max_price=800_000,
    bedrooms=2,
    property_type="apartment",
    limit=10,
)
```

Returns a list of dicts shaped exactly per the shared contract (`id`, `suburb`, `address`, `property_type`, `price`, `bedrooms`, `bathrooms`, `car_spaces`, `land_size`, `building_area`, `distance_cbd`, `latitude`, `longitude`, `annual_rent`, `description` — never `embedding`). Hard constraints (`max_price`, `min_price`, `bedrooms`, `bathrooms`, `property_type`, `suburb`) are enforced as exact SQL filters — a property violating any of them never appears, even ranked low. `semantic_query` is the only thing ranked by meaning (vector cosine similarity), never matched as literal text.

## Web interface

Double-click `start-web.bat` in the project root, or:

```bash
pip install -r requirements.txt
python serve.py            # http://localhost:8000, opens the browser when ready
python serve.py --lan      # also reachable from a phone on the same Wi-Fi
```

To let someone outside your network try it, double-click `share-web.bat`, or:

```bash
python share.py            # starts the server if needed, opens a Cloudflare
                           # Quick Tunnel, prints and copies the public URL
python share.py --attach   # server already running; just open the tunnel
```

The tunnel has **no password**, dies when you close the window, and gets a new
random address every time. It needs `cloudflared` on PATH
(`winget install --id Cloudflare.cloudflared`); the script never downloads it
for you, it only tells you the command.

`start-web.bat` must stay pure ASCII with CRLF line endings -- cmd.exe reads
.bat files in the OEM code page and will try to execute mis-decoded UTF-8
comment fragments as commands. The reason is documented inside the file.

No npm, no build step -- the frontend is three static files under `app/web/`
served by FastAPI. The command-line version (`python run.py`) still works and
shares the same graph. See `NOTES_FOR_SUPERVISOR.md` for the design rationale.

## Known limitations

- **20,800 of the original 34,857 rows** made it into the final dataset. ~8,225 rows were missing `bedrooms`/`bathrooms` together (a distinct incomplete-listing batch) and ~5,831 more were missing `price` — both required fields with no honest fallback, so those rows were dropped rather than estimated. See `Member B's tasks.md` for the full reasoning.
- `description` text is generated from structured fields only (bedrooms, size, location, era) — it cannot express subjective/lifestyle qualities like "quiet" or "family-friendly" since no data supports those claims. Semantic search will do well on physical/locational queries and poorly on lifestyle-flavored ones. This is a deliberate tradeoff, not a bug — see the description-generation discussion in the tasks notes.
- `annual_rent` is sourced from real DFFH (Victorian Government) rental data for ~100% of rows via suburb/region matching; a documented gross-yield fallback exists for edge cases but was never actually triggered on this dataset.
