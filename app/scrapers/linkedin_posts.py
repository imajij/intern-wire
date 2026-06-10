"""LinkedIn feed-post scraper via web search (no login required).

The informal "Hiring: ..." posts people write on LinkedIn live behind the
authwall — logged-out visitors can't browse or search the feed. But public
posts are indexed by search engines under linkedin.com/posts/. The ddgs
library queries those indexes (rotating across search backends, no API key)
and we link straight to the original post URL.
"""

import datetime
import random
import re
import time
from urllib.parse import urlparse

from ddgs import DDGS

# titles look like: 'Author Name on LinkedIn: Hiring interns! … | 26 comments'
_TITLE_RE = re.compile(r"^(?P<author>.{2,80}?) on LinkedIn:\s*(?P<rest>.+)$", re.S)
_SUFFIX_RE = re.compile(
    r"\s*[|\-–]\s*(\d+\s+comments?|Link(?:edIn|ed|…)?\.{0,3})\s*$", re.I
)
_WHITESPACE = re.compile(r"\s+")


def _truncate(text: str, limit: int = 140) -> str:
    text = _WHITESPACE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _canonical(href: str) -> str | None:
    parsed = urlparse(href)
    if "linkedin.com" not in parsed.netloc or "/posts/" not in parsed.path:
        return None
    return f"https://www.linkedin.com{parsed.path}"


def scrape(
    queries: list[str],
    timeframe: str = "w",  # freshness: d=day, w=week, m=month
    region: str = "in-en",
    max_per_query: int = 25,
) -> list[dict]:
    scraped_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    results: list[dict] = []
    seen: set[str] = set()

    with DDGS() as ddgs:
        for query in queries:
            try:
                hits = list(
                    ddgs.text(
                        query,
                        region=region,
                        timelimit=timeframe,
                        max_results=max_per_query,
                    )
                )
            except Exception as exc:  # backend rate limits etc. — skip query
                print(f"  [li-posts] {query!r}: failed ({exc})")
                continue
            kept = 0
            for hit in hits:
                url = _canonical(hit.get("href", ""))
                if not url or url in seen:
                    continue
                title = _SUFFIX_RE.sub("", hit.get("title", ""))
                snippet = _WHITESPACE.sub(" ", hit.get("body", "")).strip()
                author = None
                match = _TITLE_RE.match(title)
                if match:
                    author = match.group("author").strip()
                    title = match.group("rest")
                if "intern" not in f"{title} {snippet}".lower():
                    continue  # stay internship-focused
                seen.add(url)
                kept += 1
                results.append(
                    {
                        "source": "linkedin-post",
                        "title": _truncate(title),
                        "company": author,
                        "location": None,
                        "url": url,
                        "posted_at": None,  # search indexes don't expose post dates
                        "scraped_at": scraped_at,
                        "snippet": snippet or None,
                    }
                )
            print(f"  [li-posts] {query!r}: {len(hits)} results, {kept} kept")
            time.sleep(2 + random.random())
    return results
