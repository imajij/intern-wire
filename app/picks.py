"""Hand-picked listings live in picks.json, not just the database.

The GitHub Actions bot rewrites internships.db on every scheduled scrape, so
a human committing that binary file too means unmergeable conflicts. Instead
the Editor's Desk writes picks to this small text file (trivially diffable
and mergeable) and every scrape run syncs it into the database: entries are
upserted as source='manual' rows and manual rows missing from the file are
removed. Commit picks.json to publish picks on a static (GitHub Pages)
deployment; the database stays the bot's file.
"""

import datetime
import json
import os
import pathlib
import threading

from . import db

PICKS_PATH = pathlib.Path(
    os.environ.get(
        "PICKS_PATH",
        pathlib.Path(__file__).resolve().parent.parent / "picks.json",
    )
)

_lock = threading.Lock()

FIELDS = ("url", "title", "company", "location", "snippet", "posted_at", "scraped_at")


def load() -> list[dict]:
    """Picks on file, oldest first. Missing file = no picks."""
    try:
        raw = json.loads(PICKS_PATH.read_text())
    except FileNotFoundError:
        return []
    return [{f: entry.get(f) for f in FIELDS} for entry in raw if entry.get("url")]


def _save(picks: list[dict]) -> None:
    PICKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PICKS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(picks, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(PICKS_PATH)


def add(entry: dict) -> bool:
    """Append a pick. Returns False if the URL is already picked."""
    with _lock:
        picks = load()
        if any(p["url"] == entry["url"] for p in picks):
            return False
        picks.append({f: entry.get(f) for f in FIELDS})
        _save(picks)
    return True


def remove(url: str) -> bool:
    """Drop a pick by URL. Returns False if it wasn't on file."""
    with _lock:
        picks = load()
        kept = [p for p in picks if p["url"] != url]
        if len(kept) == len(picks):
            return False
        _save(kept)
    return True


def sync_db(conn) -> dict | None:
    """Make the database's manual rows mirror picks.json.

    No-op (returns None) when the file doesn't exist, so deployments that
    never use the desk — or a database moved without its picks file — keep
    whatever manual rows they have.
    """
    if not PICKS_PATH.exists():
        return None
    with _lock:
        picks = load()
    urls = [p["url"] for p in picks]
    placeholders = ",".join("?" * len(urls)) or "''"
    cur = conn.execute(
        f"DELETE FROM internships WHERE source = 'manual' AND url NOT IN ({placeholders})",
        urls,
    )
    removed = cur.rowcount
    synced = 0
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    for p in picks:
        if not (p.get("title") or "").strip():
            print(f"  [picks] skipping {p['url']}: no title")
            continue
        row = dict(p)
        row["posted_at"] = row.get("posted_at") or today
        row["scraped_at"] = row.get("scraped_at") or row["posted_at"]
        db.put_manual(conn, row)
        synced += 1
    return {"picks": synced, "removed": removed}
