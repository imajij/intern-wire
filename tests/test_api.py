import pathlib
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, picks, server, store

from .test_sqlite_store import _row


@unittest.skipIf(store.USING_MONGO, "API tests run against the SQLite backend")
class ApiTests(unittest.TestCase):
    """Exercise the HTTP layer against a throwaway SQLite file.

    TestClient is used without a `with` block, so the lifespan hook (and its
    scrape scheduler) never starts.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        for target, value in (
            (db, ("DB_PATH", root / "test.db")),
            (picks, ("PICKS_PATH", root / "picks.json")),
            (server, ("ADMIN_TOKEN", "test-token")),
        ):
            p = patch.object(target, *value)
            p.start()
            self.addCleanup(p.stop)
        store.upsert(
            [
                _row("https://x/backend", posted_days_ago=1),
                {**_row("https://x/design", posted_days_ago=2), "title": "Design Intern",
                 "source": "twitter"},
            ]
        )
        self.client = TestClient(server.app)

    def test_lists_newest_first_and_filters(self):
        body = self.client.get("/api/internships").json()
        self.assertEqual(body["count"], 2)
        self.assertEqual([i["url"] for i in body["items"]], ["https://x/backend", "https://x/design"])

        body = self.client.get("/api/internships", params={"q": "design"}).json()
        self.assertEqual([i["url"] for i in body["items"]], ["https://x/design"])

        body = self.client.get("/api/internships", params={"source": "twitter"}).json()
        self.assertEqual([i["source"] for i in body["items"]], ["twitter"])

    def test_rejects_out_of_range_query_params(self):
        self.assertEqual(self.client.get("/api/internships?limit=0").status_code, 422)
        self.assertEqual(self.client.get("/api/internships?days=999").status_code, 422)

    def test_stats_counts_by_source(self):
        body = self.client.get("/api/stats").json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["by_source"], {"linkedin": 1, "twitter": 1})
        self.assertFalse(body["scraping"])

    def test_visit_beacon_requires_a_uuid(self):
        self.assertEqual(self.client.post("/api/visit", json={"vid": "nope"}).status_code, 422)
        vid = "123e4567-e89b-12d3-a456-426614174000"
        self.client.post("/api/visit", json={"vid": vid})
        body = self.client.post("/api/visit", json={"vid": vid}).json()
        self.assertEqual(body["total_visits"], 2)
        self.assertEqual(body["monthly_active"], 1)

    def test_admin_endpoints_require_the_token(self):
        listing = {"url": "https://x/pick", "title": "Picked Intern"}
        self.assertEqual(
            self.client.post("/api/admin/internships", json=listing).status_code, 401
        )
        headers = {"X-Admin-Token": "test-token"}
        created = self.client.post("/api/admin/internships", json=listing, headers=headers)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["source"], "manual")
        dup = self.client.post("/api/admin/internships", json=listing, headers=headers)
        self.assertEqual(dup.status_code, 409)

        listing_id = created.json()["id"]
        deleted = self.client.delete(f"/api/admin/internships/{listing_id}", headers=headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(picks.load(), [])


if __name__ == "__main__":
    unittest.main()
