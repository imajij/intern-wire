"""LinkedIn scraper using the public jobs-guest endpoint (no login required).

LinkedIn serves paginated HTML job cards to logged-out visitors at
/jobs-guest/jobs/api/seeMoreJobPostings/search. We request internship-type
jobs (f_JT=I) for each keyword/location pair and parse the cards.
"""

import datetime
import random
import re
import time

import requests
from bs4 import BeautifulSoup

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
)
PAGE_SIZE = 25


def canonical_url(href: str) -> str:
    """Strip tracking params; keep the stable /jobs/view/<id> form when possible."""
    match = re.search(r"/jobs/view/[^?#]*?(\d{8,})", href)
    if match:
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}"
    return href.split("?")[0]


def _fetch_page(session: requests.Session, params: dict, retries: int = 3) -> str | None:
    for attempt in range(retries):
        resp = session.get(GUEST_SEARCH, params=params, timeout=20)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code in (400, 404):
            return None  # past the end of results
        if resp.status_code in (429, 503):
            time.sleep(4 * (attempt + 1) + random.random() * 2)
            continue
        resp.raise_for_status()
    return None


def _parse_cards(html: str, scraped_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for card in soup.select("div.base-search-card, div.base-card"):
        link_el = card.select_one("a.base-card__full-link") or card.select_one("a[href]")
        title_el = card.select_one("h3.base-search-card__title")
        if not link_el or not title_el:
            continue
        company_el = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one("span.job-search-card__location")
        time_el = card.select_one("time[datetime]")
        rows.append(
            {
                "source": "linkedin",
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else None,
                "location": location_el.get_text(strip=True) if location_el else None,
                "url": canonical_url(link_el["href"]),
                "posted_at": time_el["datetime"] if time_el else None,
                "scraped_at": scraped_at,
                "snippet": None,
            }
        )
    return rows


def _normalize_locations(locations: list) -> list[dict]:
    """Accept plain strings or {"location": ..., "remote": true} objects."""
    normalized = []
    for loc in locations:
        if isinstance(loc, str):
            normalized.append({"location": loc, "remote": False})
        else:
            normalized.append(
                {
                    "location": loc.get("location", "Worldwide"),
                    "remote": bool(loc.get("remote")),
                }
            )
    return normalized


def scrape(
    keywords: list[str],
    locations: list,
    pages_per_query: int = 2,
    delay_seconds: float = 2.0,
) -> list[dict]:
    session = requests.Session()
    session.headers.update(
        {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    )
    scraped_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    results: list[dict] = []
    seen: set[str] = set()

    for keyword in keywords:
        for entry in _normalize_locations(locations):
            location = entry["location"]
            loc_label = location + (" · remote" if entry["remote"] else "")
            for page in range(pages_per_query):
                params = {
                    "keywords": keyword,
                    "location": location,
                    "f_JT": "I",  # job type: internship
                    "start": page * PAGE_SIZE,
                }
                if entry["remote"]:
                    params["f_WT"] = "2"  # workplace type: remote
                try:
                    html = _fetch_page(session, params)
                except requests.RequestException as exc:
                    print(f"  [linkedin] {keyword!r} @ {loc_label!r} p{page}: {exc}")
                    break
                if not html:
                    break
                cards = _parse_cards(html, scraped_at)
                if not cards:
                    break  # no more results for this query
                fresh = [c for c in cards if c["url"] not in seen]
                seen.update(c["url"] for c in fresh)
                results.extend(fresh)
                print(
                    f"  [linkedin] {keyword!r} @ {loc_label!r} p{page}: "
                    f"{len(cards)} cards ({len(fresh)} new)"
                )
                time.sleep(delay_seconds + random.random())
    return results
