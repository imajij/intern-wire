"""FastAPI server: JSON API + the static dashboard + periodic re-scraping.

    .venv/bin/uvicorn app.server:app --port 8000

Env vars:
    SCRAPE_INTERVAL_HOURS  re-scrape cadence (default 8; 0 disables)
    DB_PATH                where the SQLite file lives (default: project dir)
"""

import contextlib
import os
import pathlib
import threading
import time

from fastapi import BackgroundTasks, FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .scrape import run as run_scrape

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "static"
SCRAPE_INTERVAL_HOURS = float(os.environ.get("SCRAPE_INTERVAL_HOURS", "8"))

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
    conn = db.connect()
    try:
        empty = conn.execute("SELECT COUNT(*) AS c FROM internships").fetchone()["c"] == 0
    finally:
        conn.close()
    if empty:
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
    sql = "SELECT * FROM internships WHERE 1=1"
    params: list = []
    if q:
        sql += (
            " AND (title LIKE ? OR company LIKE ?"
            " OR location LIKE ? OR snippet LIKE ?)"
        )
        params += [f"%{q}%"] * 4
    if source in ("linkedin", "twitter"):
        sql += " AND source = ?"
        params.append(source)
    if days:
        sql += (
            " AND (posted_at >= date('now', ?)"
            " OR (posted_at IS NULL AND scraped_at >= datetime('now', ?)))"
        )
        params += [f"-{days} day"] * 2
    sql += " ORDER BY COALESCE(posted_at, scraped_at) DESC, id DESC LIMIT ?"
    params.append(limit)

    conn = db.connect()
    try:
        items = [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
    return {"count": len(items), "items": items}


@app.get("/api/stats")
def stats():
    conn = db.connect()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM internships").fetchone()["c"]
        by_source = {
            r["source"]: r["c"]
            for r in conn.execute(
                "SELECT source, COUNT(*) AS c FROM internships GROUP BY source"
            )
        }
        last = conn.execute(
            "SELECT MAX(scraped_at) AS m FROM internships"
        ).fetchone()["m"]
    finally:
        conn.close()
    return {
        "total": total,
        "by_source": by_source,
        "last_scraped": last,
        "scraping": _scrape_lock.locked(),
    }


@app.post("/api/refresh")
def refresh(background_tasks: BackgroundTasks):
    if _scrape_lock.locked():
        return JSONResponse({"status": "already-running"}, status_code=409)
    background_tasks.add_task(_locked_scrape, "manual refresh")
    return {"status": "started"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
