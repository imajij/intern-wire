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
from collections.abc import Sequence
from urllib.parse import urlparse

from ddgs import DDGS

# Search indexes return fuzzy matches, so plenty of "I completed my
# internship!" story posts come back alongside actual openings. A post is
# kept only if it offers a vacancy, points to an application/contact route,
# and doesn't read like a personal story. Lists are lowercase substrings,
# overridable per-deployment via config.json.
HIRING_TERMS = (
    "hiring", "we are looking", "we're looking", "looking for intern",
    "vacanc", "opening", "recruit", "join our", "join us",
)
APPLICATION_TERMS = (
    "apply", "application", "apply here", "apply now", "dm me",
    "send your resume", "send your cv", "share your resume",
    "drop your resume", "email your resume", "comment interested",
)
EXCLUDE_TERMS = (
    "my internship", "internship experience", "my experience", "my journey",
    "completed my", "i completed", "i joined", "i applied", "i got selected",
    "i received", "selected as an intern", "excited to share that i",
    "thrilled to share that i", "happy to share that i", "grateful",
    "thankful", "my time at", "wrapped up my", "what i learned",
    "congratulations",
)

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


def is_internship_opening(
    text: str,
    hiring_terms: Sequence[str] = HIRING_TERMS,
    application_terms: Sequence[str] = APPLICATION_TERMS,
    exclude_terms: Sequence[str] = EXCLUDE_TERMS,
) -> bool:
    """Whether indexed post text contains concrete internship vacancy evidence."""
    text = text.casefold()
    return (
        "intern" in text
        and not any(term in text for term in exclude_terms)
        and any(term in text for term in hiring_terms)
        and any(term in text for term in application_terms)
    )


def scrape(
    queries: list[str],
    timeframe: str = "w",  # freshness: d=day, w=week, m=month
    region: str = "in-en",
    max_per_query: int = 25,
    hiring_terms: list[str] | None = None,
    application_terms: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> list[dict]:
    hiring_terms = (
        HIRING_TERMS if hiring_terms is None else [t.casefold() for t in hiring_terms]
    )
    application_terms = (
        APPLICATION_TERMS
        if application_terms is None
        else [t.casefold() for t in application_terms]
    )
    exclude_terms = (
        EXCLUDE_TERMS if exclude_terms is None else [t.casefold() for t in exclude_terms]
    )
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
            kept = stories = no_evidence = 0
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
                text = f"{title} {snippet}".casefold()
                if any(t in text for t in exclude_terms):
                    stories += 1
                    continue  # someone's internship story, not an opening
                if not is_internship_opening(
                    text, hiring_terms, application_terms, exclude_terms
                ):
                    no_evidence += 1
                    continue  # not enough evidence of a real opening
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
            print(
                f"  [li-posts] {query!r}: {len(hits)} results, {kept} kept"
                f" ({stories} stories, {no_evidence} without vacancy evidence)"
            )
            time.sleep(2 + random.random())
    return results
