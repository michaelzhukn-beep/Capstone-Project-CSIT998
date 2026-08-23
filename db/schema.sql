-- properties table per contracts.md section 1
-- embedding dimension = 768 (nomic-embed-text-v1.5)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS properties (
    id             SERIAL PRIMARY KEY,
    suburb         TEXT NOT NULL,
    address        TEXT,
    property_type  TEXT NOT NULL CHECK (property_type IN ('house', 'apartment', 'townhouse')),
    price          INTEGER NOT NULL,
    bedrooms       INTEGER NOT NULL,
    bathrooms      INTEGER NOT NULL,
    car_spaces     INTEGER NOT NULL DEFAULT 0,
    land_size      REAL,
    building_area  REAL,
    year_built     INTEGER,
    distance_cbd   REAL NOT NULL,
    latitude       REAL,
    longitude      REAL,
    annual_rent    INTEGER NOT NULL,
    description    TEXT NOT NULL,
    embedding      vector(768) NOT NULL,
    sale_date      DATE,

    -- extra columns, kept for our own methodology/traceability (contracts.md
    -- allows extra columns; not part of the shared record other tracks rely on)
    rent_source    TEXT
);

CREATE INDEX IF NOT EXISTS properties_embedding_idx
    ON properties USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS properties_price_idx ON properties (price);
CREATE INDEX IF NOT EXISTS properties_suburb_idx ON properties (suburb);
CREATE INDEX IF NOT EXISTS properties_bedrooms_idx ON properties (bedrooms);
