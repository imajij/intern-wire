# The Intern Wire

Scrapes internships from **LinkedIn job listings**, **LinkedIn feed posts**
(the informal "Hiring: …" posts), and **X/Twitter** — no login or signup
anywhere — and shows them in a dashboard where every listing links straight
to the original post. Currently tuned for **India + remote**
internships. The server re-scrapes itself every 8 hours, so once deployed it
stays fresh with zero extra setup.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.scrape                      # optional manual scrape
.venv/bin/uvicorn app.server:app --port 8000        # http://127.0.0.1:8000
```

Or with Docker:

```bash
docker compose up -d --build                        # http://localhost:8000
```

On first boot with an empty database the server scrapes immediately, then
every `SCRAPE_INTERVAL_HOURS` (default 8) after that. The **RE-SCRAPE ⟳**
button on the dashboard triggers one on demand.

## Configuration (`config.json`)

```jsonc
{
  "linkedin": {
    "keywords":  ["software engineer intern", "..."],
    "locations": [
      "India",                                      // plain location search
      { "location": "India", "remote": true },      // remote-only filter
      { "location": "Worldwide", "remote": true }   // global remote
    ],
    "pages_per_query": 2,       // 25 results per page
    "delay_seconds": 2.0        // politeness delay between requests
  },
  "linkedin_posts": {
    "queries": ["site:linkedin.com/posts \"hiring interns\"", "..."],
    "timeframe": "w",           // search freshness: d / w / m
    "region": "in-en",
    "max_per_query": 25
  },
  "twitter": {
    "accounts": ["Internshala", "GitHubEducation"],  // timelines to follow
    "keywords": ["intern"],     // keep tweets containing any of these
    "max_per_account": 20
  }
}
```

`python -m app.scrape` takes `--source linkedin|posts|twitter|all`.

Environment variables (all optional):

| Var | Default | Meaning |
|---|---|---|
| `SCRAPE_INTERVAL_HOURS` | `8` | re-scrape cadence; `0` disables the scheduler |
| `DB_PATH` | `./internships.db` | SQLite location (containers use `/data/internships.db`) |
| `PORT` | `8000` | listen port (set automatically by most PaaS hosts) |

## How each source works

- **LinkedIn** — the public *jobs-guest* endpoint served to logged-out
  visitors, filtered to internship job type (`f_JT=I`) and, where configured,
  remote workplace type (`f_WT=2`). Low volume + delays + backoff on 429.
- **LinkedIn feed posts** — the feed itself is behind LinkedIn's authwall,
  but public posts are indexed by search engines under `linkedin.com/posts/`.
  The `ddgs` library queries those indexes (rotating across search backends,
  no API key) for fresh internship-hiring posts. Noisier than the jobs feed
  and post dates aren't available, but it catches the informal "DM me to
  apply" openings that never become job listings. Tune the search queries in
  `config.json` (`linkedin_posts.queries`, freshness `timeframe`: d/w/m).
- **X/Twitter** — X removed logged-out search in 2024 and the public Nitter
  mirrors are bot-walled, so keyword search without an account isn't
  possible. Instead the scraper follows accounts via X's public syndication
  API (the engine behind embedded timelines) and keeps tweets matching the
  keyword filter. Retweets resolve to the original post. Add any accounts
  that post internships you care about — Internshala is the big one for
  India.

## Deploying so others can use it

### GitHub Pages + Actions (recommended — 100% free)

No server at all: a GitHub Actions workflow
(`.github/workflows/scrape.yml`) scrapes every 8 hours, commits the updated
database, and publishes the dashboard to GitHub Pages. The dashboard
detects there's no backend and switches to client-side filtering over
`static/data.json` (the RE-SCRAPE button hides itself; GitHub's cron does
that job).

1. Push this folder to a **public** GitHub repo (public = free unlimited
   Actions minutes + free Pages).
2. Repo **Settings → Pages → Source: GitHub Actions**.
3. Done. The push itself triggers the first run; the site appears at
   `https://<user>.github.io/<repo>/` and refreshes every 8 hours.

Notes: GitHub disables cron workflows after ~60 days without repo activity
(one click re-enables, and the workflow's own data commits usually count as
activity). If LinkedIn ever blocks GitHub's runner IPs, run
`python -m app.scrape && python -m app.export` locally and push.

The options below run the actual server (live RE-SCRAPE button, API), which
needs a host with a persistent disk. The built-in scheduler handles the
8-hourly scans; no external cron needed.

### Railway (simplest paid PaaS, ~$5/mo)

1. Push this folder to a GitHub repo.
2. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
   (it auto-detects the Dockerfile).
3. In the service: **Settings → Volumes → Add volume**, mount path `/data`.
4. **Settings → Networking → Generate Domain** — that URL is what you share.

Hobby plan is ~$5/mo including usage. Nothing else to configure.

### Fly.io (cheapest, CLI-based)

```bash
fly launch --no-deploy          # accept defaults, it reads the Dockerfile
fly volumes create wire_data --size 1
# add to fly.toml:  [mounts]  source = "wire_data"  destination = "/data"
fly deploy
```

### Any VPS (Hetzner/DigitalOcean/Oracle free tier — most control)

```bash
git clone <your repo> && cd internship_finder
docker compose up -d --build
```

Then put Caddy or nginx in front for HTTPS, or just share `http://<ip>:8000`.

### Why not Vercel/Netlify?

Serverless platforms are a poor fit for this app: no persistent disk for
SQLite, free-tier cron is once-per-day, function time limits clip the
scraper, and LinkedIn rate-limits shared serverless egress IPs aggressively.
A container host with a volume is simpler and cheaper.

### Heads-up: scraping from datacenter IPs

LinkedIn is stricter with cloud-provider IPs than with home connections. The
volume here is tiny (~16 requests per scan, 3 scans/day) and the scraper
backs off on 429s, so it generally works — but if a host's IP range is
blocked, raise `delay_seconds`, lower `pages_per_query`, or run
`python -m app.scrape` from a home machine against the same volume.

## API

| Endpoint | Description |
|---|---|
| `GET /api/internships?q=&source=&days=&limit=` | filtered listings, newest first |
| `GET /api/stats` | totals per source, last scrape time, scrape-in-progress flag |
| `POST /api/refresh` | run scrapers in the background (409 if already running) |

## Notes

- Data lives in SQLite (`internships.db` locally, `/data/internships.db` in
  containers), deduped by original post URL. Delete the file to start fresh.
- Both platforms' terms restrict automated collection; this only touches
  public, logged-out pages at low volume. Run it politely and at your own
  discretion.
