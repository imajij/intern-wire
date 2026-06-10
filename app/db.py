"""SQLite storage. One table, deduped on the original post URL."""

import os
import pathlib
import sqlite3

DB_PATH = pathlib.Path(
    os.environ.get(
        "DB_PATH",
        pathlib.Path(__file__).resolve().parent.parent / "internships.db",
    )
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS internships (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  source     TEXT NOT NULL,
  title      TEXT NOT NULL,
  company    TEXT,
  location   TEXT,
  url        TEXT NOT NULL UNIQUE,
  posted_at  TEXT,
  scraped_at TEXT NOT NULL,
  snippet    TEXT
);
CREATE INDEX IF NOT EXISTS idx_internships_source ON internships(source);
CREATE INDEX IF NOT EXISTS idx_internships_posted ON internships(posted_at);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, rows) -> int:
    """Insert rows, skipping URLs already on file. Returns number of new rows."""
    new = 0
    for row in rows:
        cur = conn.execute(
            """INSERT INTO internships
                 (source, title, company, location, url, posted_at, scraped_at, snippet)
               VALUES
                 (:source, :title, :company, :location, :url, :posted_at, :scraped_at, :snippet)
               ON CONFLICT(url) DO NOTHING""",
            row,
        )
        new += cur.rowcount
    conn.commit()
    return new
