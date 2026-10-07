import datetime
import sqlite3
import unittest

from app import db, scrape


def _iso(days_ago: int) -> str:
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return when.isoformat(timespec="seconds")


def _row(url, posted_days_ago=None, scraped_days_ago=0, source="linkedin"):
    return {
        "source": source,
        "title": "Backend Intern",
        "company": "Acme",
        "location": "Remote",
        "url": url,
        "posted_at": (
            None if posted_days_ago is None else _iso(posted_days_ago)[:10]
        ),
        "scraped_at": _iso(scraped_days_ago),
        "snippet": None,
    }


class SqliteStoreTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(db.SCHEMA)

    def tearDown(self):
        self.conn.close()

    def urls(self):
        return {r["url"] for r in self.conn.execute("SELECT url FROM internships")}

    def test_upsert_dedupes_on_url(self):
        first = db.upsert(self.conn, [_row("https://x/1"), _row("https://x/2")])
        again = db.upsert(self.conn, [_row("https://x/1"), _row("https://x/3")])
        self.assertEqual(first, 2)
        self.assertEqual(again, 1)
        self.assertEqual(self.urls(), {"https://x/1", "https://x/2", "https://x/3"})

    def test_purge_drops_old_scraped_rows_but_keeps_fresh_and_manual(self):
        db.upsert(
            self.conn,
            [
                _row("https://x/old-dated", posted_days_ago=40),
                _row("https://x/new-dated", posted_days_ago=2),
                _row("https://x/old-dateless", scraped_days_ago=40),
                _row("https://x/new-dateless", scraped_days_ago=1),
            ],
        )
        db.put_manual(self.conn, _row("https://x/pick", posted_days_ago=90))

        purged = db.purge_stale(self.conn, 30)

        self.assertEqual(purged, 2)
        self.assertEqual(
            self.urls(), {"https://x/new-dated", "https://x/new-dateless", "https://x/pick"}
        )

    def test_purge_is_disabled_when_max_age_is_zero(self):
        db.upsert(self.conn, [_row("https://x/ancient", posted_days_ago=999)])
        self.assertEqual(db.purge_stale(self.conn, 0), 0)
        self.assertEqual(self.urls(), {"https://x/ancient"})

    def test_purged_dateless_url_cannot_reenter_as_new(self):
        db.upsert(self.conn, [_row("https://x/zombie", scraped_days_ago=40)])
        db.purge_stale(self.conn, 30)
        # the search index returns it again today, still without a date
        new = db.upsert(self.conn, [_row("https://x/zombie")], max_age_days=30)
        self.assertEqual(new, 0)
        self.assertEqual(self.urls(), set())

    def test_put_manual_promotes_an_already_scraped_url(self):
        db.upsert(self.conn, [_row("https://x/1")])
        stored = db.put_manual(self.conn, {**_row("https://x/1"), "title": "Picked"})
        self.assertEqual(stored["source"], "manual")
        self.assertEqual(stored["title"], "Picked")
        count = self.conn.execute("SELECT COUNT(*) FROM internships").fetchone()[0]
        self.assertEqual(count, 1)


class DropStaleTests(unittest.TestCase):
    def test_drops_only_rows_with_an_old_posted_date(self):
        rows = [
            _row("https://x/old", posted_days_ago=45),
            _row("https://x/new", posted_days_ago=3),
            _row("https://x/dateless"),
        ]
        kept = scrape.drop_stale(rows, 30, "test")
        self.assertEqual([r["url"] for r in kept], ["https://x/new", "https://x/dateless"])


if __name__ == "__main__":
    unittest.main()
