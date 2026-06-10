"""Export the database to static/data.json for the static (GitHub Pages) build.

    python -m app.export
"""

import datetime
import json
import pathlib

from . import db

OUT_PATH = pathlib.Path(__file__).resolve().parent.parent / "static" / "data.json"
LIMIT = 2000  # newest listings; keeps the payload small forever


def main() -> None:
    conn = db.connect()
    try:
        items = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM internships"
                " ORDER BY COALESCE(posted_at, scraped_at) DESC, id DESC LIMIT ?",
                (LIMIT,),
            )
        ]
        last = conn.execute(
            "SELECT MAX(scraped_at) AS m FROM internships"
        ).fetchone()["m"]
    finally:
        conn.close()

    by_source: dict[str, int] = {}
    for item in items:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1

    OUT_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "total": len(items),
                "by_source": by_source,
                "last_scraped": last,
                "items": items,
            },
            ensure_ascii=False,
        )
    )
    print(f"[export] wrote {len(items)} listings -> {OUT_PATH}")


if __name__ == "__main__":
    main()
