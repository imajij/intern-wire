"""MongoDB storage backend — used when MONGODB_URI is set (see store.py).

Documents mirror the SQLite rows exactly (ISO-8601 strings for posted_at /
scraped_at, deduped by a unique index on url), so the JSON API and the
frontend don't change. All date comparisons are lexicographic, which is
correct because every writer in this codebase emits the same ISO format.

The API exposes the ObjectId hex string as `id`. picks.json is not used in
this mode: Mongo is durable and no scraper bot rewrites it, so manual rows
simply live in the collection.
"""

import datetime
import os
import re
import threading

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient, ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

FIELDS = ("source", "title", "company", "location", "url", "posted_at", "scraped_at", "snippet")

_lock = threading.Lock()
_db = None


def _database():
    global _db
    with _lock:
        if _db is None:
            client = MongoClient(
                os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10_000
            )
            _db = client.get_default_database("internwire")
            _db.internships.create_index("url", unique=True)
            _db.internships.create_index("source")
            _db.internships.create_index("posted_at")
        return _db


def _item(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


def _cutoffs(days: int) -> tuple[str, str]:
    """(date, datetime) ISO cutoff strings `days` ago, matching the stored formats."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return cutoff.date().isoformat(), cutoff.isoformat(timespec="seconds")


def list_internships(q: str = "", source: str = "", days: int = 0, limit: int = 200) -> list[dict]:
    clauses = []
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        clauses.append({"$or": [{f: rx} for f in ("title", "company", "location", "snippet")]})
    if source:
        clauses.append({"source": source})
    if days:
        date_cutoff, dt_cutoff = _cutoffs(days)
        clauses.append({"$or": [
            {"posted_at": {"$gte": date_cutoff}},
            {"posted_at": None, "scraped_at": {"$gte": dt_cutoff}},
        ]})
    pipeline = [
        {"$match": {"$and": clauses} if clauses else {}},
        # same ordering as the SQLite query: COALESCE(posted_at, scraped_at) DESC
        {"$addFields": {"_k": {"$ifNull": ["$posted_at", "$scraped_at"]}}},
        {"$sort": {"_k": -1, "_id": -1}},
        {"$limit": limit},
        {"$unset": "_k"},
    ]
    return [_item(d) for d in _database().internships.aggregate(pipeline)]


def stats() -> dict:
    coll = _database().internships
    by_source = {
        d["_id"]: d["c"]
        for d in coll.aggregate([{"$group": {"_id": "$source", "c": {"$sum": 1}}}])
    }
    last = coll.find_one(sort=[("scraped_at", -1)], projection={"scraped_at": True})
    return {
        "total": coll.count_documents({}),
        "by_source": by_source,
        "last_scraped": last["scraped_at"] if last else None,
    }


def count() -> int:
    return _database().internships.count_documents({})


def upsert(rows, max_age_days: int = 0) -> int:
    db = _database()
    new = 0
    for row in rows:
        db.seen_urls.update_one(
            {"_id": row["url"]},
            {"$setOnInsert": {"first_seen": row["scraped_at"]}},
            upsert=True,
        )
        if max_age_days > 0 and not row["posted_at"]:
            _, dt_cutoff = _cutoffs(max_age_days)
            seen = db.seen_urls.find_one({"_id": row["url"]})
            if seen and seen["first_seen"] < dt_cutoff:
                continue
        try:
            db.internships.insert_one({f: row[f] for f in FIELDS})
            new += 1
        except DuplicateKeyError:
            pass
    return new


def add_manual(row: dict) -> dict | None:
    """Store a hand-picked row, promoting any scraped row at the same URL.
    Returns None if that URL is already a manual pick."""
    coll = _database().internships
    if coll.find_one({"url": row["url"], "source": "manual"}):
        return None
    doc = coll.find_one_and_update(
        {"url": row["url"]},
        {"$set": {"source": "manual", **{f: row[f] for f in FIELDS if f != "source"}}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return _item(doc)


def delete(listing_id: str) -> bool:
    try:
        oid = ObjectId(listing_id)
    except InvalidId:
        return False
    return _database().internships.delete_one({"_id": oid}).deleted_count > 0


def purge_stale(max_age_days: int) -> int:
    if max_age_days <= 0:
        return 0
    db = _database()
    # remember every URL we're about to forget, so re-discovery can't reset its age
    ops = [
        UpdateOne({"_id": d["url"]}, {"$setOnInsert": {"first_seen": d["scraped_at"]}}, upsert=True)
        for d in db.internships.find({}, {"url": True, "scraped_at": True})
    ]
    if ops:
        db.seen_urls.bulk_write(ops)
    date_cutoff, dt_cutoff = _cutoffs(max_age_days)
    res = db.internships.delete_many({
        "source": {"$ne": "manual"},
        "$or": [
            {"posted_at": {"$type": "string", "$lt": date_cutoff}},
            {"posted_at": None, "scraped_at": {"$lt": dt_cutoff}},
        ],
    })
    return res.deleted_count
