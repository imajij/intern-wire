# LinkedIn Post Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the three supplied LinkedIn posts as durable curated opportunities, reject vague and personal LinkedIn feed posts, and publish the result to the existing GitHub Pages site and Hugging Face Space.

**Architecture:** A pure classifier in the LinkedIn post scraper will require both a vacancy signal and an application/contact signal after rejecting known story and discussion language. The curated `picks.json` file is synchronized by both storage adapters; MongoDB marks file-synced records so it never deletes a live-admin pick. The established Actions workflows then export and publish the static site and deploy the Docker snapshot.

**Tech Stack:** Python 3.12+, standard-library `unittest`, DDGS, SQLite, PyMongo, GitHub Actions, GitHub Pages, Hugging Face Spaces.

## Global Constraints

- Use `unittest`; do not add a test dependency to `requirements.txt`.
- Keep all three supplied `https://lnkd.in/p/...` URLs exactly as given. The shortener currently returns HTTP 403 from this environment, so do not invent canonical destination URLs.
- A scraped feed post must have internship context, no exclusion marker, one vacancy signal, and one application/contact signal.
- Preserve the `hiring_terms` configuration override as the vacancy-signal override; add only `application_terms` as a new optional override.
- MongoDB deletion may affect only documents with `curated_from_file: true`; admin-created manual records must remain untouched.
- Do not commit local test databases or mutate the production MongoDB manually. The existing workflows own production data publication.

---

## File Structure

- `tests/test_linkedin_posts.py` — regression and integration tests for post classification plus SQLite curated-pick synchronization.
- `tests/test_mongo_picks.py` — unit test for Mongo file-pick synchronization using an in-memory collection double with the real collection interface used by production code.
- `app/scrapers/linkedin_posts.py` — pure feed-post classifier and its use in the DDGS result loop.
- `app/scrape.py` — forwards the optional application-signal configuration to the post scraper.
- `app/mongo.py` — synchronizes `picks.json` entries to Mongo while preserving admin-created manual entries.
- `app/store.py` — routes `sync_picks()` to the correct SQLite or Mongo implementation.
- `picks.json` — three user-supplied curated LinkedIn opportunities.
- `README.md` — documents the precise post acceptance rule and the Mongo-backed curated-pick behavior.

### Task 1: Introduce a testable high-precision LinkedIn post classifier

**Files:**

- Create: `tests/__init__.py`
- Create: `tests/test_linkedin_posts.py`
- Modify: `app/scrapers/linkedin_posts.py:15-130`
- Modify: `app/scrape.py:64-72`

**Interfaces:**

- Produces: `is_internship_opening(text: str, hiring_terms: Sequence[str], application_terms: Sequence[str], exclude_terms: Sequence[str]) -> bool` in `app.scrapers.linkedin_posts`.
- Consumes: DDGS hits with `title`, `body`, and `href` fields, as already returned by `DDGS.text()`.
- Produces: `scrape(..., application_terms: list[str] | None = None) -> list[dict]`; callers that omit the new argument continue to use built-in defaults.

- [ ] **Step 1: Write the failing classifier and scraper-integration tests**

```python
# tests/test_linkedin_posts.py
import unittest
from unittest.mock import patch

from app.scrapers import linkedin_posts


class LinkedInPostClassifierTests(unittest.TestCase):
    def test_accepts_a_hiring_post_with_an_application_route(self):
        text = (
            "Acme is hiring a Backend Engineering Intern. "
            "Apply by sending your resume to careers@acme.example."
        )
        self.assertTrue(linkedin_posts.is_internship_opening(text))

    def test_rejects_a_personal_internship_announcement_even_when_it_mentions_apply(self):
        text = (
            "Excited to share that I got selected as a summer intern. "
            "Apply these lessons to your next internship search."
        )
        self.assertFalse(linkedin_posts.is_internship_opening(text))

    def test_rejects_general_internship_discussion_without_an_application_route(self):
        text = "How to create compliant internships: a legal guide for employers hiring interns."
        self.assertFalse(linkedin_posts.is_internship_opening(text))

    @patch("app.scrapers.linkedin_posts.time.sleep")
    @patch("app.scrapers.linkedin_posts.DDGS")
    def test_scrape_keeps_only_the_qualifying_search_hit(self, ddgs_class, _sleep):
        ddgs = ddgs_class.return_value.__enter__.return_value
        ddgs.text.return_value = [
            {
                "href": "https://www.linkedin.com/posts/acme_hiring-intern-activity-1",
                "title": "Acme on LinkedIn: Hiring a Data Intern",
                "body": "Apply with your resume at careers@acme.example.",
            },
            {
                "href": "https://www.linkedin.com/posts/person_my-internship-activity-2",
                "title": "Person on LinkedIn: My internship experience",
                "body": "I am grateful for everything I learned.",
            },
        ]

        rows = linkedin_posts.scrape(["test query"], max_per_query=2)

        self.assertEqual([row["company"] for row in rows], ["Acme"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test module and verify the expected red state**

Run: `python -m unittest tests.test_linkedin_posts -v`

Expected: FAIL with `AttributeError` because `is_internship_opening` does not exist yet. If another failure occurs, correct the test setup rather than changing production code.

- [ ] **Step 3: Add the smallest classifier that satisfies the tests**

Split the current mixed `HIRING_TERMS` constant into three lower-case term tuples. Keep vacancy terms and application terms separate so a story that says only “apply” cannot qualify.

```python
from collections.abc import Sequence

HIRING_TERMS = (
    "hiring", "we are looking", "we're looking", "looking for intern",
    "vacanc", "opening", "recruit", "join our", "join us",
)
APPLICATION_TERMS = (
    "apply", "application", "apply here", "apply now", "dm me",
    "send your resume", "send your cv", "share your resume",
    "drop your resume", "email your resume", "comment interested",
)


def is_internship_opening(
    text: str,
    hiring_terms: Sequence[str] = HIRING_TERMS,
    application_terms: Sequence[str] = APPLICATION_TERMS,
    exclude_terms: Sequence[str] = EXCLUDE_TERMS,
) -> bool:
    normalized = text.casefold()
    return (
        "intern" in normalized
        and not any(term in normalized for term in exclude_terms)
        and any(term in normalized for term in hiring_terms)
        and any(term in normalized for term in application_terms)
    )
```

In `scrape()`, normalize optional configuration lists with `casefold()`, build the current title-and-snippet string, and call the helper instead of separately checking an all-purpose hiring list. Track rejected `stories` and `no_evidence` counts in the existing log line.

Add the backwards-compatible argument and forwarding call:

```python
# app/scrapers/linkedin_posts.py
def scrape(..., hiring_terms=None, application_terms=None, exclude_terms=None):
    ...

# app/scrape.py
application_terms=lp.get("application_terms"),
```

- [ ] **Step 4: Run the focused tests and the complete test suite**

Run: `python -m unittest tests.test_linkedin_posts -v && python -m unittest discover -s tests -v`

Expected: all four focused tests PASS and the complete suite has zero failures.

- [ ] **Step 5: Commit the classifier change**

```bash
git add app/scrapers/linkedin_posts.py app/scrape.py tests/__init__.py tests/test_linkedin_posts.py
git commit -m "fix: require vacancy evidence in LinkedIn posts"
```

### Task 2: Add and verify the three durable curated postings in SQLite

**Files:**

- Modify: `tests/test_linkedin_posts.py`
- Create: `picks.json`

**Interfaces:**

- Consumes: `app.picks.sync_db(conn) -> dict | None` and its existing manual-listing schema.
- Produces: Three `source="manual"` entries identified by the supplied short URLs after a SQLite pick sync.

- [ ] **Step 1: Add a failing test for the committed curated picks**

Append this test class to `tests/test_linkedin_posts.py`:

```python
import sqlite3

from app import db, picks


class CuratedPickTests(unittest.TestCase):
    def test_file_picks_sync_as_manual_listings(self):
        expected_urls = {
            "https://lnkd.in/p/dMX7MJnT",
            "https://lnkd.in/p/dMXzzXz5",
            "https://lnkd.in/p/dCcT6gh3",
        }
        self.assertEqual({pick["url"] for pick in picks.load()}, expected_urls)

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA)
        picks.sync_db(conn)
        rows = conn.execute(
            "SELECT source, url, title FROM internships ORDER BY url"
        ).fetchall()

        self.assertEqual({row["url"] for row in rows}, expected_urls)
        self.assertTrue(all(row["source"] == "manual" for row in rows))
        self.assertTrue(all(row["title"].strip() for row in rows))
```

- [ ] **Step 2: Run the focused curated-pick test and verify the expected red state**

Run: `python -m unittest tests.test_linkedin_posts.CuratedPickTests -v`

Expected: FAIL because `picks.json` does not yet exist.

- [ ] **Step 3: Create the curated source file**

Create `picks.json` with precisely these three entries. The labels deliberately identify the items as curated LinkedIn opportunities because the supplied short links cannot be resolved for safe company/title extraction.

```json
[
  {
    "url": "https://lnkd.in/p/dMX7MJnT",
    "title": "Curated LinkedIn internship opportunity",
    "company": "LinkedIn post",
    "location": null,
    "snippet": "Curated internship opportunity supplied by the editor.",
    "posted_at": "2026-08-07",
    "scraped_at": "2026-08-07T00:00:00+00:00"
  },
  {
    "url": "https://lnkd.in/p/dMXzzXz5",
    "title": "Curated LinkedIn internship opportunity",
    "company": "LinkedIn post",
    "location": null,
    "snippet": "Curated internship opportunity supplied by the editor.",
    "posted_at": "2026-08-07",
    "scraped_at": "2026-08-07T00:00:00+00:00"
  },
  {
    "url": "https://lnkd.in/p/dCcT6gh3",
    "title": "Curated LinkedIn internship opportunity",
    "company": "LinkedIn post",
    "location": null,
    "snippet": "Curated internship opportunity supplied by the editor.",
    "posted_at": "2026-08-07",
    "scraped_at": "2026-08-07T00:00:00+00:00"
  }
]
```

- [ ] **Step 4: Run the focused test and the complete suite**

Run: `python -m unittest tests.test_linkedin_posts.CuratedPickTests -v && python -m unittest discover -s tests -v`

Expected: the three exact URLs are loaded and become non-empty `manual` rows; the full suite remains green.

- [ ] **Step 5: Commit the curated source file and its regression test**

```bash
git add picks.json tests/test_linkedin_posts.py
git commit -m "feat: add curated LinkedIn internship posts"
```

### Task 3: Synchronize file-curated picks to MongoDB safely

**Files:**

- Create: `tests/test_mongo_picks.py`
- Modify: `app/mongo.py:18-190`
- Modify: `app/store.py:15-30`

**Interfaces:**

- Produces: `sync_file_picks(picks: list[dict], coll=None) -> dict` in `app.mongo`.
- Consumes: the normal `picks.load()` result and a PyMongo collection with `update_one()` and `delete_many()` methods.
- Produces: `store.sync_picks()` returning `{"picks": int, "removed": int}` in Mongo mode when `picks.json` exists.

- [ ] **Step 1: Write a failing Mongo synchronization test**

Use a tiny in-memory collection double that implements only the calls made by the production helper. Seed it with one `curated_from_file: true` row that is no longer in the input and one unmarked `source: "manual"` admin row.

```python
# tests/test_mongo_picks.py
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
        keep = []
        for document in self.documents:
            delete = (
                document.get("source") == "manual"
                and document.get("curated_from_file") is True
                and document["url"] not in selector["url"]["$nin"]
            )
            if not delete:
                keep.append(document)
        self.documents = keep
        return Result(before - len(keep))


class MongoFilePickTests(unittest.TestCase):
    def test_sync_replaces_only_file_curated_manual_listings(self):
        collection = MemoryCollection([
            {"url": "https://old.example", "source": "manual", "curated_from_file": True},
            {"url": "https://admin.example", "source": "manual", "title": "Admin pick"},
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
```

- [ ] **Step 2: Run the new test and verify the expected red state**

Run: `python -m unittest tests.test_mongo_picks -v`

Expected: FAIL with `AttributeError` because `sync_file_picks` does not exist yet.

- [ ] **Step 3: Implement the Mongo file-pick helper and store routing**

Add this helper to `app/mongo.py`. It accepts a collection only for test isolation; normal callers omit it and use the real collection.

```python
def sync_file_picks(picks: list[dict], coll=None) -> dict:
    if coll is None:
        coll = _database().internships
    synced = 0
    urls = []
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for pick in picks:
        if not (pick.get("title") or "").strip():
            print(f"  [picks] skipping {pick['url']}: no title")
            continue
        row = {field: pick.get(field) for field in FIELDS if field != "source"}
        row.update(
            source="manual",
            posted_at=pick.get("posted_at") or today,
            scraped_at=pick.get("scraped_at") or now,
            curated_from_file=True,
        )
        coll.update_one({"url": row["url"]}, {"$set": row}, upsert=True)
        urls.append(row["url"])
        synced += 1
    removed = coll.delete_many({
        "source": "manual",
        "curated_from_file": True,
        "url": {"$nin": urls},
    }).deleted_count
    return {"picks": synced, "removed": removed}
```

In the Mongo branch of `app/store.py`, replace the no-op `sync_picks()` with an implementation that returns `None` when `picks.PICKS_PATH` is absent and otherwise calls `mongo.sync_file_picks(picks.load())`. Retain the existing SQLite branch unchanged.

- [ ] **Step 4: Run Mongo, curated-pick, and complete test suites**

Run: `python -m unittest tests.test_mongo_picks -v && python -m unittest tests.test_linkedin_posts -v && python -m unittest discover -s tests -v`

Expected: Mongo test proves stale marked records are removed, admin records remain, the three file entries are synchronized, and every test passes.

- [ ] **Step 5: Commit the dual-store curated-pick support**

```bash
git add app/mongo.py app/store.py tests/test_mongo_picks.py
git commit -m "fix: sync curated picks to Mongo"
```

### Task 4: Document configuration and verify the deployable artifact locally

**Files:**

- Modify: `README.md:62-72,148-164,194-240`

**Interfaces:**

- Consumes: `linkedin_posts.hiring_terms`, `linkedin_posts.application_terms`, and `linkedin_posts.exclude_terms` from `config.json` when configured.
- Produces: concise operational documentation for the static GitHub Pages build and Mongo-backed Space.

- [ ] **Step 1: Write a failing documentation-regression test**

Add a test to `tests/test_linkedin_posts.py` that reads `README.md` and asserts the three override names and `curated_from_file` are documented:

```python
def test_readme_documents_the_post_evidence_and_mongo_pick_rules(self):
    readme = pathlib.Path("README.md").read_text()
    self.assertIn("application_terms", readme)
    self.assertIn("hiring_terms", readme)
    self.assertIn("exclude_terms", readme)
    self.assertIn("curated_from_file", readme)
```

Add `import pathlib` with the other test imports.

- [ ] **Step 2: Run the focused documentation test and verify the expected red state**

Run: `python -m unittest tests.test_linkedin_posts.LinkedInPostClassifierTests.test_readme_documents_the_post_evidence_and_mongo_pick_rules -v`

Expected: FAIL because the README does not yet document `application_terms` or the Mongo marker.

- [ ] **Step 3: Update the operational documentation**

Revise the LinkedIn-post source section to say a scraped result needs both vacancy intent (`hiring_terms`) and an application/contact route (`application_terms`) and must have no `exclude_terms` marker. Revise the configuration example to show all three optional lists. In the Hugging Face section, state that tracked `picks.json` is synchronized by the GitHub scrape job to MongoDB, and that only rows marked `curated_from_file` are cleaned up by subsequent file syncs.

- [ ] **Step 4: Run all unit tests and a temporary SQLite export verification**

Run: `python -m unittest discover -s tests -v`

Expected: every test PASS.

Then run this isolated verification, which never changes the committed SQLite database or the production MongoDB instance:

```bash
verify_dir=$(mktemp -d)
DB_PATH="$verify_dir/internships.db" python -c 'from app import store; assert store.sync_picks()["picks"] == 3'
DB_PATH="$verify_dir/internships.db" python -c 'from app import export; from pathlib import Path; export.OUT_PATH = Path("/tmp/intern-wire-data.json"); export.main()'
python -c 'import json; data=json.load(open("/tmp/intern-wire-data.json")); urls={item["url"] for item in data["items"]}; assert {"https://lnkd.in/p/dMX7MJnT", "https://lnkd.in/p/dMXzzXz5", "https://lnkd.in/p/dCcT6gh3"} <= urls'
```

Expected: the JSON export contains all three supplied URLs as `manual` listings.

- [ ] **Step 5: Commit the documentation**

```bash
git add README.md tests/test_linkedin_posts.py
git commit -m "docs: explain LinkedIn post quality rules"
```

### Task 5: Publish and inspect both existing deployments

**Files:**

- No new source files; deploy the commits from Tasks 1–4.

**Interfaces:**

- Consumes: `main` in `imajij/intern-wire`, the existing `Scrape & Deploy` workflow, and the `Sync to Hugging Face Space` workflow configured with `HF_SPACE=imajij/internwire`.
- Produces: current static data at `https://imajij.github.io/intern-wire/` and a rebuilt app at `https://imajij-internwire.hf.space`.

- [ ] **Step 1: Refresh the repository before publishing**

Run: `git fetch origin main && git rebase origin/main`

Expected: local commits replay on the current remote `main`. If a conflict occurs, inspect each hunk and preserve both the newer remote change and this plan’s behavior; do not use reset or checkout commands that discard either side.

- [ ] **Step 2: Confirm the branch contains only intended changes**

Run: `git status --short && git log --oneline origin/main..HEAD && git diff --check origin/main...HEAD`

Expected: a clean worktree, the focused commits from this plan, and no whitespace errors.

- [ ] **Step 3: Push the branch to trigger both workflows**

Run: `git push origin main`

Expected: the push starts `Scrape & Deploy` and `Sync to Hugging Face Space` because both workflows run on a `main` push.

- [ ] **Step 4: Verify GitHub Pages and its published data**

Run: `gh run list --repo imajij/intern-wire --limit 10 --json workflowName,status,conclusion,url && gh run watch <scrape-run-id> --exit-status`

Expected: `Scrape & Deploy` completes successfully.

Then run: `curl -fsS https://imajij.github.io/intern-wire/data.json -o /tmp/intern-wire-pages-data.json && python -c 'import json; data=json.load(open("/tmp/intern-wire-pages-data.json")); urls={item["url"] for item in data["items"]}; assert {"https://lnkd.in/p/dMX7MJnT", "https://lnkd.in/p/dMXzzXz5", "https://lnkd.in/p/dCcT6gh3"} <= urls'`

Expected: GitHub Pages responds and its published JSON contains all three exact curated URLs.

- [ ] **Step 5: Verify the Hugging Face synchronization and running Space**

Run: `gh run list --repo imajij/intern-wire --workflow sync-to-hf.yml --limit 1 --json status,conclusion,url && gh run watch <hf-sync-run-id> --exit-status && hf spaces info imajij/internwire --format json`

Expected: the sync workflow succeeds and the Space reports the Docker app as running. Because this Space uses the repository `MONGODB_URI` secret, GitHub’s scrape workflow is the authoritative seed for the three file-curated picks; wait for that successful scrape before checking the Space’s listing API.

- [ ] **Step 6: Record the deployed URLs in the handoff**

Report both verified URLs and the workflow run links, plus the exact test commands and outcomes.
