"""One-command database setup for a fresh clone.

    docker compose -f db/docker-compose.yml up -d
    python db/setup_db.py

What it does (safe to re-run; it never deletes anything):
  1. waits until Postgres at DB_DSN (from .env) accepts connections;
  2. enables the pgvector extension;
  3. if the `properties` table is missing or empty, restores the 20,800 listings
     (with their 768-dim embeddings) from db/seed/properties.dump, using the
     pg_restore that ships inside the Postgres container -- nothing to install;
  4. runs db/schema.sql for the remaining tables (users / sessions / favorites).

The seed contains the `properties` table only -- no accounts, no favorites.

Options:
  --container NAME   Docker container running Postgres (default: capstone_postgres)
  --force            restore even if `properties` already has rows (rows are replaced)

Regenerating the seed (maintainers only, after re-running the data pipeline):
  docker exec capstone_postgres pg_dump -U capstone -d capstone -Fc -Z 9 -t properties -f /tmp/properties.dump
  docker cp capstone_postgres:/tmp/properties.dump db/seed/properties.dump
"""
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2                                  # noqa: E402

from app.core.config import DB_DSN               # noqa: E402

SEED = ROOT / "db" / "seed" / "properties.dump"
SCHEMA = ROOT / "db" / "schema.sql"


def _arg(name: str, default: str) -> str:
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def _connect(timeout_s: int = 60):
    deadline = time.time() + timeout_s
    while True:
        try:
            conn = psycopg2.connect(DB_DSN)
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as exc:
            if time.time() > deadline:
                sys.exit(f"Cannot connect to {DB_DSN.split('@')[-1]}: {exc}\n"
                         "Is the database container running?  docker compose -f db/docker-compose.yml up -d")
            time.sleep(2)


def _properties_rows(cur) -> int | None:
    cur.execute("SELECT to_regclass('public.properties')")
    if cur.fetchone()[0] is None:
        return None
    cur.execute("SELECT count(*) FROM properties")
    return cur.fetchone()[0]


def _restore(container: str, user: str, db: str, data_only: bool) -> None:
    cmd = ["docker", "exec", "-i", container, "pg_restore", "-U", user, "-d", db,
           "--no-owner", "--no-privileges"]
    if data_only:
        cmd.append("--data-only")
    print(f"Restoring {SEED.name} ({SEED.stat().st_size / 1e6:.0f} MB) into container '{container}' ...")
    with SEED.open("rb") as fh:
        result = subprocess.run(cmd, stdin=fh, capture_output=True)
    if result.returncode != 0:
        sys.exit("pg_restore failed:\n" + result.stderr.decode("utf-8", "replace"))


def main() -> None:
    if not SEED.exists():
        sys.exit(f"Seed file not found: {SEED}")
    container = _arg("--container", "capstone_postgres")
    dsn = urlparse(DB_DSN)
    user, db = dsn.username or "capstone", (dsn.path or "/capstone").lstrip("/")

    conn = _connect()
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

    rows = _properties_rows(cur)
    if rows and "--force" not in sys.argv:
        print(f"`properties` already has {rows:,} rows -- skipping restore (use --force to reload).")
    else:
        if rows:
            cur.execute("TRUNCATE properties")
        _restore(container, user, db, data_only=rows is not None)
        cur.execute("SELECT setval(pg_get_serial_sequence('properties', 'id'), (SELECT max(id) FROM properties))")
        print(f"Loaded {_properties_rows(cur):,} properties.")

    cur.execute(SCHEMA.read_text(encoding="utf-8"))     # IF NOT EXISTS everywhere: only adds what is missing
    conn.close()
    print("Database ready.")


if __name__ == "__main__":
    main()
