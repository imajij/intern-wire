"""FastAPI server: JSON API + the static dashboard + periodic re-scraping.

    .venv/bin/uvicorn app.server:app --port 8000

Env vars:
    SCRAPE_INTERVAL_HOURS  re-scrape cadence (default 8; 0 disables)
    DB_PATH                where the SQLite file lives (default: project dir)
    MONGODB_URI            store data in MongoDB instead of SQLite (see store.py)
    ADMIN_TOKEN            enables /admin.html + the admin API (unset = disabled)
"""

import collections
import contextlib
import datetime
import os
import pathlib
import secrets
import threading
import time

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from .scrape import run as run_scrape

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"
SCRAPE_INTERVAL_HOURS = float(os.environ.get("SCRAPE_INTERVAL_HOURS", "8"))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
SOURCES = ("linkedin", "linkedin-post", "twitter", "manual")

_scrape_lock = threading.Lock()


def _locked_scrape(reason: str) -> bool:
    """Run a scrape unless one is already running. Returns False if skipped."""
    if not _scrape_lock.acquire(blocking=False):
        return False
    try:
        print(f"[scheduler] scraping ({reason})…")
        run_scrape()
    except Exception as exc:  # never kill the scheduler thread
        print(f"[scheduler] scrape failed: {exc}")
    finally:
        _scrape_lock.release()
    return True


def _scheduler() -> None:
    # fresh deploy: populate immediately instead of waiting a full interval
    if store.count() == 0:
        _locked_scrape("first run, empty database")
    while True:
        time.sleep(SCRAPE_INTERVAL_HOURS * 3600)
        _locked_scrape(f"periodic, every {SCRAPE_INTERVAL_HOURS:g}h")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    if SCRAPE_INTERVAL_HOURS > 0:
        threading.Thread(target=_scheduler, daemon=True, name="scrape-scheduler").start()
        print(f"[scheduler] started: every {SCRAPE_INTERVAL_HOURS:g}h")
    yield


app = FastAPI(title="Intern Wire", lifespan=lifespan)


@app.get("/api/internships")
def list_internships(
    q: str = "",
    source: str = "",
    days: int = Query(0, ge=0, le=365),
    limit: int = Query(200, ge=1, le=1000),
):
    items = store.list_internships(
        q=q,
        source=source if source in SOURCES else "",
        days=days,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@app.get("/api/stats")
def stats():
    return {**store.stats(), "scraping": _scrape_lock.locked()}


@app.post("/api/refresh")
def refresh(background_tasks: BackgroundTasks):
    if _scrape_lock.locked():
        return JSONResponse({"status": "already-running"}, status_code=409)
    background_tasks.add_task(_locked_scrape, "manual refresh")
    return {"status": "started"}


# ── admin: hand-picked listings (requires ADMIN_TOKEN) ──────────────────────

AUTH_WINDOW_SECONDS = 60.0
AUTH_MAX_FAILURES = 10
_auth_failures: collections.deque = collections.deque()


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Admin is disabled — set the ADMIN_TOKEN environment variable.",
        )
    now = time.monotonic()
    while _auth_failures and now - _auth_failures[0] > AUTH_WINDOW_SECONDS:
        _auth_failures.popleft()
    if len(_auth_failures) >= AUTH_MAX_FAILURES:
        raise HTTPException(
            status_code=429, detail="Too many wrong tokens — try again in a minute."
        )
    # bytes, not str: compare_digest raises on non-ASCII str, and header
    # values can carry latin-1 bytes from any unauthenticated client
    if not secrets.compare_digest(
        x_admin_token.encode("utf-8"), ADMIN_TOKEN.encode("utf-8")
    ):
        _auth_failures.append(now)
        raise HTTPException(status_code=401, detail="Wrong admin token.")


class ManualListing(BaseModel):
    url: str
    title: str
    company: str | None = None
    location: str | None = None
    snippet: str | None = None


@app.get("/api/admin/check", dependencies=[Depends(require_admin)])
def admin_check():
    return {"status": "ok"}


@app.post(
    "/api/admin/internships",
    dependencies=[Depends(require_admin)],
    status_code=201,
)
def add_internship(listing: ManualListing):
    url = listing.url.strip()
    title = listing.title.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="URL must start with http(s)://")
    if not title:
        raise HTTPException(status_code=422, detail="Title is required.")
    now = datetime.datetime.now(datetime.timezone.utc)
    row = {
        "title": title,
        "company": (listing.company or "").strip() or None,
        "location": (listing.location or "").strip() or None,
        "url": url,
        "posted_at": now.date().isoformat(),
        "scraped_at": now.isoformat(timespec="seconds"),
        "snippet": (listing.snippet or "").strip() or None,
    }
    # promotes the row if a scraper already found the same URL
    item = store.add_manual(row)
    if item is None:
        raise HTTPException(status_code=409, detail="Already picked that URL.")
    return item


# listing_id is a str: SQLite ids are ints, Mongo ids are ObjectId hex strings
@app.delete("/api/admin/internships/{listing_id}", dependencies=[Depends(require_admin)])
def delete_internship(listing_id: str):
    if not store.delete(listing_id):
        raise HTTPException(status_code=404, detail="No such listing.")
    return {"status": "deleted", "id": listing_id}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
