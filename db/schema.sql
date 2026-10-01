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
    car_spaces     INTEGER,                      -- NULL = 数据集缺失(未知);0 = 记录里确有 0 个车位
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

-- 账号(可选登录)。已有数据库不会重跑本文件,服务启动时 app/auth/store.py 会幂等建同样的表。
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    username       TEXT NOT NULL,
    username_key   TEXT NOT NULL UNIQUE,      -- 小写:Alice 与 alice 视为同一账号
    email          TEXT,
    email_key      TEXT UNIQUE,
    password_hash  TEXT NOT NULL,             -- scrypt$n$r$p$salt$hash,不存明文
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,             -- 会话令牌的 sha256,不存令牌本身
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

-- 收藏(需登录)。不对 properties 建外键:数据集会被整体重新下载,外键会挡住重新导入;
-- snapshot 存收藏时的房源事实字段(服务端从 properties 取),房源表重建后仍可显示。
CREATE TABLE IF NOT EXISTS favorites (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    property_id  INTEGER NOT NULL,
    snapshot     JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, property_id)
);
