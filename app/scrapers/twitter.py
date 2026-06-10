"""Twitter/X scraper via the public syndication API (no login required).

X removed logged-out search in 2024 and the Nitter mirror network is behind
bot-walls, so keyword search isn't possible without an account. What still
works logged-out is the syndication endpoint that powers embedded timelines:

    https://syndication.twitter.com/srv/timeline-profile/screen-name/<user>

So this scraper follows a configurable list of accounts that post internship
openings, pulls their recent tweets, and keeps the ones matching the keyword
filter. Retweets are resolved to the original tweet so the dashboard links
to the real post.
"""

import datetime
import json
import re

import requests

TIMELINE_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{account}"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
)

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_WHITESPACE = re.compile(r"\s+")


def _tweet_title(text: str, limit: int = 140) -> str:
    text = _WHITESPACE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _parse_created_at(raw: str) -> str | None:
    # e.g. "Tue Jun 02 17:51:38 +0000 2026"
    try:
        return (
            datetime.datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
            .date()
            .isoformat()
        )
    except (ValueError, TypeError):
        return None


def _fetch_timeline(session: requests.Session, account: str) -> list[dict]:
    resp = session.get(TIMELINE_URL.format(account=account), timeout=20)
    resp.raise_for_status()
    match = _NEXT_DATA.search(resp.text)
    if not match:
        return []
    data = json.loads(match.group(1))
    entries = data["props"]["pageProps"]["timeline"]["entries"]
    return [
        e["content"]["tweet"]
        for e in entries
        if e.get("content", {}).get("tweet")
    ]


def scrape(
    accounts: list[str],
    keywords: list[str] | None = None,
    max_per_account: int = 20,
) -> list[dict]:
    keywords = [k.lower() for k in (keywords or ["intern"])]
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    scraped_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    results: list[dict] = []
    seen: set[str] = set()

    for account in accounts:
        try:
            tweets = _fetch_timeline(session, account.lstrip("@"))
        except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
            print(f"  [twitter] @{account}: failed ({exc})")
            continue
        kept = 0
        for tweet in tweets[:max_per_account]:
            # link retweets to the original post, not the RT wrapper
            original = tweet.get("retweeted_status") or tweet
            text = original.get("full_text") or original.get("text") or ""
            if not any(k in text.lower() for k in keywords):
                continue
            tweet_id = original.get("id_str")
            user = original.get("user", {}).get("screen_name")
            if not tweet_id or not user:
                continue
            url = f"https://x.com/{user}/status/{tweet_id}"
            if url in seen:
                continue
            seen.add(url)
            kept += 1
            clean = _WHITESPACE.sub(" ", text).strip()
            results.append(
                {
                    "source": "twitter",
                    "title": _tweet_title(clean),
                    "company": f"@{user}",
                    "location": None,
                    "url": url,
                    "posted_at": _parse_created_at(original.get("created_at")),
                    "scraped_at": scraped_at,
                    "snippet": clean,
                }
            )
        print(f"  [twitter] @{account}: {len(tweets)} tweets, {kept} kept")
    return results
