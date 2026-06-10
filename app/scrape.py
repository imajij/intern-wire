"""Run the scrapers and store results.

    python -m app.scrape                 # both sources
    python -m app.scrape --source linkedin
    python -m app.scrape --source twitter
"""

import argparse
import json
import pathlib

from . import db
from .scrapers import linkedin, linkedin_posts, twitter

CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


ALL_SOURCES = ("linkedin", "posts", "twitter")


def run(sources: tuple[str, ...] = ALL_SOURCES) -> dict:
    config = load_config()
    counts = {}
    conn = db.connect()
    try:
        if "linkedin" in sources:
            print("[scrape] linkedin…")
            li = config["linkedin"]
            rows = linkedin.scrape(
                keywords=li["keywords"],
                locations=li["locations"],
                pages_per_query=li.get("pages_per_query", 2),
                delay_seconds=li.get("delay_seconds", 2.0),
            )
            counts["linkedin"] = {"found": len(rows), "new": db.upsert(conn, rows)}
        if "posts" in sources and "linkedin_posts" in config:
            print("[scrape] linkedin posts…")
            lp = config["linkedin_posts"]
            rows = linkedin_posts.scrape(
                queries=lp["queries"],
                timeframe=lp.get("timeframe", "w"),
                region=lp.get("region", "in-en"),
                max_per_query=lp.get("max_per_query", 25),
            )
            counts["linkedin_posts"] = {"found": len(rows), "new": db.upsert(conn, rows)}
        if "twitter" in sources:
            print("[scrape] twitter/x…")
            tw = config["twitter"]
            rows = twitter.scrape(
                accounts=tw["accounts"],
                keywords=tw.get("keywords", ["intern"]),
                max_per_account=tw.get("max_per_account", 20),
            )
            counts["twitter"] = {"found": len(rows), "new": db.upsert(conn, rows)}
    finally:
        conn.close()
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
