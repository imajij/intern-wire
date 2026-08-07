import unittest

from app import mongo


class Result:
    def __init__(self, deleted_count=0):
        self.deleted_count = deleted_count


class MemoryCollection:
    def __init__(self, documents):
        self.documents = documents

    def update_one(self, selector, update, upsert=False):
        for document in self.documents:
            if document["url"] == selector["url"]:
                document.update(update["$set"])
                return Result()
        self.documents.append(dict(update["$set"]))
        return Result()

    def delete_many(self, selector):
        before = len(self.documents)
        kept = []
        for document in self.documents:
            should_delete = (
                document.get("source") == "manual"
                and document.get("curated_from_file") is True
                and document["url"] not in selector["url"]["$nin"]
            )
            if not should_delete:
                kept.append(document)
        self.documents = kept
        return Result(before - len(kept))


class MongoFilePickTests(unittest.TestCase):
    def test_sync_replaces_only_file_curated_manual_listings(self):
        collection = MemoryCollection([
            {
                "url": "https://old.example",
                "source": "manual",
                "curated_from_file": True,
            },
            {
                "url": "https://admin.example",
                "source": "manual",
                "title": "Admin pick",
            },
        ])

        result = mongo.sync_file_picks([
            {
                "url": "https://new.example",
                "title": "Curated internship",
                "company": None,
                "location": None,
                "snippet": None,
                "posted_at": "2026-08-07",
                "scraped_at": "2026-08-07T00:00:00+00:00",
            }
        ], coll=collection)

        by_url = {document["url"]: document for document in collection.documents}
        self.assertEqual(result, {"picks": 1, "removed": 1})
        self.assertNotIn("https://old.example", by_url)
        self.assertTrue(by_url["https://new.example"]["curated_from_file"])
        self.assertIn("https://admin.example", by_url)


if __name__ == "__main__":
    unittest.main()
