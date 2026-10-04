"""Apply db/migrations/*.sql in filename order to the configured database.

Works against any Postgres, including Neon (no psql / Docker required).

- Tracks applied files in a schema_migrations table so runs are idempotent.
- Warns (but does not re-run) when an already-applied file's content changed.

Usage:
    python -m services.api.scripts.migrate
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import psycopg2
from services.api.app.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"


def get_dsn() -> str:
    """Sync DSN for psycopg2 (strip the SQLAlchemy async driver prefix)."""
    return settings.database_url_sync.replace("postgresql+asyncpg://", "postgresql://")


def migrate() -> int:
    """Apply pending migration files. Returns process exit code."""
    conn = psycopg2.connect(get_dsn())
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename text primary key,
            checksum text not null,
            applied_at timestamptz not null default now()
        )
        """
    )
    conn.commit()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"No migration files found in {MIGRATIONS_DIR}")
        return 1

    failures = 0
    for path in files:
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

        cur.execute("SELECT checksum FROM schema_migrations WHERE filename = %s", (path.name,))
        row = cur.fetchone()
        if row:
            if row[0] != checksum:
                print(f"WARNING {path.name}: content changed since it was applied (not re-running)")
            else:
                print(f"skip    {path.name} (already applied)")
            continue

        try:
            cur.execute(sql)  # multi-statement file; no params
            cur.execute(
                "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                (path.name, checksum),
            )
            conn.commit()
            print(f"applied {path.name}")
        except Exception as exc:
            conn.rollback()
            print(f"FAILED  {path.name}: {exc}")
            failures += 1

    cur.close()
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(migrate())
