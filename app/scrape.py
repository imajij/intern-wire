"""Run the scrapers and store results.

    python -m app.scrape                 # both sources
    python -m app.scrape --source linkedin
    python -m app.scrape --source twitter
"""

import argparse
import datetime
import json
import pathlib

from . import store
from .scrapers import linkedin, linkedin_posts, twitter

CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_MAX_AGE_DAYS = 30


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


ALL_SOURCES = ("linkedin", "posts", "twitter")


def drop_stale(rows: list[dict], max_age_days: int, label: str) -> list[dict]:
    """Keep rows posted within the window (dateless rows pass — they were
    just scraped, and purge_stale ages them out by scraped_at later)."""
    if max_age_days <= 0:
        return rows
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=max_age_days)
    ).date().isoformat()
    fresh = [r for r in rows if not r["posted_at"] or r["posted_at"][:10] >= cutoff]
    if len(fresh) < len(rows):
        print(f"  [{label}] dropped {len(rows) - len(fresh)} stale (older than {max_age_days}d)")
    return fresh


def run(sources: tuple[str, ...] = ALL_SOURCES) -> dict:
    config = load_config()
    max_age_days = int(config.get("max_age_days", DEFAULT_MAX_AGE_DAYS))
    counts = {}
    purged = store.purge_stale(max_age_days)
    if purged:
        print(f"[scrape] purged {purged} stale listings (older than {max_age_days}d)")
    synced = store.sync_picks()
    if synced:
        print(f"[scrape] picks.json: {synced['picks']} picks ({synced['removed']} removed)")
    if "linkedin" in sources:
        print("[scrape] linkedin…")
        li = config["linkedin"]
        rows = linkedin.scrape(
            keywords=li["keywords"],
            locations=li["locations"],
            pages_per_query=li.get("pages_per_query", 2),
            delay_seconds=li.get("delay_seconds", 2.0),
        )
        rows = drop_stale(rows, max_age_days, "linkedin")
        counts["linkedin"] = {"found": len(rows), "new": store.upsert(rows, max_age_days)}
    if "posts" in sources and "linkedin_posts" in config:
        print("[scrape] linkedin posts…")
        lp = config["linkedin_posts"]
        rows = linkedin_posts.scrape(
            queries=lp["queries"],
            timeframe=lp.get("timeframe", "w"),
            region=lp.get("region", "in-en"),
            max_per_query=lp.get("max_per_query", 25),
            hiring_terms=lp.get("hiring_terms"),
            exclude_terms=lp.get("exclude_terms"),
        )
        rows = drop_stale(rows, max_age_days, "li-posts")
        counts["linkedin_posts"] = {"found": len(rows), "new": store.upsert(rows, max_age_days)}
    if "twitter" in sources:
        print("[scrape] twitter/x…")
        tw = config["twitter"]
        rows = twitter.scrape(
            accounts=tw["accounts"],
            keywords=tw.get("keywords", ["intern"]),
            max_per_account=tw.get("max_per_account", 20),
        )
        rows = drop_stale(rows, max_age_days, "twitter")
        counts["twitter"] = {"found": len(rows), "new": store.upsert(rows, max_age_days)}
    print(f"[scrape] done: {counts}")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape internship posts.")
    parser.add_argument(
        "--source",
        choices=["linkedin", "posts", "twitter", "all"],
        default="all",
    )
    args = parser.parse_args()
    sources = ALL_SOURCES if args.source == "all" else (args.source,)
    run(sources)


if __name__ == "__main__":
    main()
