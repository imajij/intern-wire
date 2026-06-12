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

-- remembers when each URL was first scraped, surviving purges, so a stale
-- dateless post that search engines keep returning can't re-enter as "new"
CREATE TABLE IF NOT EXISTS seen_urls (
  url        TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL
);

-- visit counters: one row per distinct browser, identified by a random id
-- the client keeps in localStorage (no IPs, no fingerprints)
CREATE TABLE IF NOT EXISTS visitors (
  id         TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL,
  last_seen  TEXT NOT NULL,
  visits     INTEGER NOT NULL DEFAULT 1
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, rows, max_age_days: int = 0) -> int:
    """Insert rows, skipping URLs already on file. Returns number of new rows.

    With max_age_days set, dateless rows whose URL was first seen more than
    max_age_days ago are skipped — they were purged once already and must not
    re-enter looking fresh just because a search index still returns them.
    """
    new = 0
    for row in rows:
        conn.execute(
            """INSERT INTO seen_urls (url, first_seen) VALUES (:url, :scraped_at)
               ON CONFLICT(url) DO NOTHING""",
            row,
        )
        if max_age_days > 0 and not row["posted_at"]:
            too_old = conn.execute(
                """SELECT 1 FROM seen_urls
                   WHERE url = ? AND datetime(first_seen) < datetime('now', ?)""",
                (row["url"], f"-{max_age_days} day"),
            ).fetchone()
            if too_old:
                continue
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


def put_manual(conn: sqlite3.Connection, row: dict) -> dict:
    """Insert a hand-picked row, promoting any scraped row at the same URL.
    Returns the stored row."""
    stored = conn.execute(
        """INSERT INTO internships
             (source, title, company, location, url, posted_at, scraped_at, snippet)
           VALUES
             ('manual', :title, :company, :location, :url, :posted_at, :scraped_at, :snippet)
           ON CONFLICT(url) DO UPDATE SET
             source     = 'manual',
             title      = excluded.title,
             company    = excluded.company,
             location   = excluded.location,
             posted_at  = excluded.posted_at,
             scraped_at = excluded.scraped_at,
             snippet    = excluded.snippet
           RETURNING *""",
        row,
    ).fetchone()
    conn.commit()
    return dict(stored)


def record_visit(conn: sqlite3.Connection, visitor_id: str, now: str) -> None:
    conn.execute(
        """INSERT INTO visitors (id, first_seen, last_seen) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             visits = visits + 1, last_seen = excluded.last_seen""",
        (visitor_id, now, now),
    )
    conn.commit()


def visit_stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute(
        "SELECT COALESCE(SUM(visits), 0) AS c FROM visitors"
    ).fetchone()["c"]
    monthly = conn.execute(
        "SELECT COUNT(*) AS c FROM visitors WHERE last_seen >= datetime('now', '-30 day')"
    ).fetchone()["c"]
    return {"total_visits": total, "monthly_active": monthly}


def purge_stale(conn: sqlite3.Connection, max_age_days: int) -> int:
    """Delete scraped rows older than max_age_days. Returns number deleted.

    Rows without a parseable posted_at (e.g. LinkedIn feed posts) age by when
    they were first scraped. Manually curated rows are never purged — the
    admin removes those by hand.
    """
    if max_age_days <= 0:
        return 0
    # remember every URL we're about to forget, so re-discovery can't reset
    # its age (WHERE true disambiguates SELECT + upsert for SQLite's parser)
    conn.execute(
        """INSERT INTO seen_urls (url, first_seen)
           SELECT url, scraped_at FROM internships WHERE true
           ON CONFLICT(url) DO NOTHING"""
    )
    # COALESCE: unparseable posted_at (date() -> NULL) falls back to scraped_at age
    cur = conn.execute(
        """DELETE FROM internships
           WHERE source != 'manual'
             AND COALESCE(
                   date(posted_at) < date('now', ?),
                   datetime(scraped_at) < datetime('now', ?)
                 )""",
        (f"-{max_age_days} day",) * 2,
    )
    conn.commit()
    return cur.rowcount
