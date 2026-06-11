"""Storage facade: SQLite by default, MongoDB when MONGODB_URI is set.

The server, scraper, and exporter only call these functions, so either
backend can sit behind them:

- SQLite (default) keeps the picks.json workflow — required by the GitHub
  Actions + Pages deployment, where a bot rewrites the binary database and
  hand-picks must live in a mergeable text file.
- MongoDB (e.g. a free Atlas cluster) needs no disk at all, which lets the
  server run on free hosts like Render and lets the Editor's Desk write
  from the live site. picks.json is skipped: Mongo is the source of truth.
"""

import os

USING_MONGO = bool(os.environ.get("MONGODB_URI"))

if USING_MONGO:
    from .mongo import (  # noqa: F401
        add_manual,
        count,
        delete,
        list_internships,
        purge_stale,
        stats,
        upsert,
    )

    def sync_picks() -> dict | None:
        """picks.json is a SQLite-mode concept; manual rows live in Mongo."""
        return None

else:
    from . import db, picks

    def list_internships(q: str = "", source: str = "", days: int = 0, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM internships WHERE 1=1"
        params: list = []
        if q:
            sql += (
                " AND (title LIKE ? OR company LIKE ?"
                " OR location LIKE ? OR snippet LIKE ?)"
            )
            params += [f"%{q}%"] * 4
        if source:
            sql += " AND source = ?"
            params.append(source)
        if days:
            sql += (
                " AND (posted_at >= date('now', ?)"
                " OR (posted_at IS NULL AND scraped_at >= datetime('now', ?)))"
            )
            params += [f"-{days} day"] * 2
        sql += " ORDER BY COALESCE(posted_at, scraped_at) DESC, id DESC LIMIT ?"
        params.append(limit)
        conn = db.connect()
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def stats() -> dict:
        conn = db.connect()
        try:
            total = conn.execute("SELECT COUNT(*) AS c FROM internships").fetchone()["c"]
            by_source = {
                r["source"]: r["c"]
                for r in conn.execute(
                    "SELECT source, COUNT(*) AS c FROM internships GROUP BY source"
                )
            }
            last = conn.execute(
                "SELECT MAX(scraped_at) AS m FROM internships"
            ).fetchone()["m"]
        finally:
            conn.close()
        return {"total": total, "by_source": by_source, "last_scraped": last}

    def count() -> int:
        conn = db.connect()
        try:
            return conn.execute("SELECT COUNT(*) AS c FROM internships").fetchone()["c"]
        finally:
            conn.close()

    def upsert(rows, max_age_days: int = 0) -> int:
        conn = db.connect()
        try:
            return db.upsert(conn, rows, max_age_days)
        finally:
            conn.close()

    def add_manual(row: dict) -> dict | None:
        """Store a hand-picked row (in picks.json AND the database).
        Returns None if that URL is already picked."""
        if not picks.add(row):
            return None
        conn = db.connect()
        try:
            return db.put_manual(conn, row)
        finally:
            conn.close()

    def delete(listing_id: str) -> bool:
        try:
            rowid = int(listing_id)
        except ValueError:
            return False
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT url FROM internships WHERE id = ?", (rowid,)
            ).fetchone()
            if not row:
                return False
            picks.remove(row["url"])
            conn.execute("DELETE FROM internships WHERE id = ?", (rowid,))
            conn.commit()
        finally:
            conn.close()
        return True

    def purge_stale(max_age_days: int) -> int:
        conn = db.connect()
        try:
            return db.purge_stale(conn, max_age_days)
        finally:
            conn.close()

    def sync_picks() -> dict | None:
        conn = db.connect()
        try:
            return picks.sync_db(conn)
        finally:
            conn.close()
