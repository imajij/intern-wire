---
title: The Intern Wire
emoji: 📰
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 8000
pinned: false
---

# The Intern Wire

Scrapes internships from **LinkedIn job listings**, **LinkedIn feed posts**
(the informal "Hiring: …" posts), and **X/Twitter** — no login or signup
anywhere — and shows them in a dashboard where every listing links straight
to the original post. Currently tuned for **India + remote**
internships. The server re-scrapes itself every 8 hours, so once deployed it
stays fresh with zero extra setup. Listings older than `max_age_days`
(default 30) are dropped at scrape time and purged from the database on
every run, so the wire never goes stale. An **Editor's Desk** admin page
lets you hand-pick listings that appear alongside the scraped ones.

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
  "max_age_days": 30,          // drop + purge listings older than this (0 = keep forever)
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
| `MONGODB_URI` | *(unset)* | store data in MongoDB instead of SQLite — no disk needed (see [MongoDB Atlas + Hugging Face Spaces](#mongodb-atlas--hugging-face-spaces-free-live-admin-page)) |
| `PORT` | `8000` | listen port (set automatically by most PaaS hosts) |
| `ADMIN_TOKEN` | *(unset)* | enables the Editor's Desk admin page + API; unset = admin disabled |
| `PICKS_PATH` | `./picks.json` | where hand-picked listings live (SQLite mode only; containers use `/data/picks.json`) |

## The Editor's Desk (admin)

`/admin.html` is a staff-only page for hand-picking listings — paste a link,
give it a title, and it appears on the front page stamped **EDITOR'S PICK**
(source `manual`, with its own front-page filter chip). Filing a URL the
scrapers already found promotes that listing to a pick. Picks are never
auto-purged; remove them from the same page when they close.

Start the server with a secret of your choosing, then unlock the page with
that same value:

```bash
ADMIN_TOKEN=<secret> .venv/bin/uvicorn app.server:app --port 8000
```

Or keep it in a git-ignored `.env` file (`ADMIN_TOKEN=...`) — both
`uvicorn --env-file .env` and `docker compose up` read it from there:

```bash
echo "ADMIN_TOKEN=$(openssl rand -hex 24)" > .env
.venv/bin/uvicorn app.server:app --port 8000 --env-file .env
```

If `ADMIN_TOKEN` is unset, the admin API is disabled entirely. Writes are
authenticated per request via the `X-Admin-Token` header; the browser keeps
the token in localStorage until you hit **LOCK THE DESK**. Pick a long
random value (`openssl rand -hex 24`) — wrong-token attempts are
rate-limited, but a guessable token is still a guessable token. The header
travels in cleartext over plain HTTP, so if the desk is reachable from the
internet, put HTTPS in front before unlocking it there.

In **MongoDB mode** (`MONGODB_URI` set) picks simply live in the database —
nothing below applies, and admins can file picks from the deployed site
directly. In **SQLite mode** picks are stored in **`picks.json`** (at
`PICKS_PATH`), not just the database — every scrape run syncs the file into
the database, so it is the source of truth: entries added there appear as
`manual` rows, and manual rows missing from it are removed. That makes
publishing picks on the static GitHub Pages deployment a plain-text git
operation:

1. Run the server locally with `ADMIN_TOKEN` set and file your picks.
2. Commit and push `picks.json` (just the text file — leave
   `internships.db` to the Actions bot, two writers of a binary file means
   merge conflicts).
3. The next Actions run syncs your picks into the database and exports them
   to `static/data.json`.

Note for Docker: the container keeps its data on the `/data` volume
(`PICKS_PATH=/data/picks.json`), not in the repo — picks filed against a
container serve fine from that container, but to publish them via Pages
copy the file out first: `docker compose cp wire:/data/picks.json picks.json`.

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

### MongoDB Atlas + Hugging Face Spaces (free, live admin page)

The Pages deployment above is read-only — admins can't file picks through
the live site. This recipe runs the real server for free, no credit card:
storage moves to MongoDB Atlas (free M0 cluster) so no disk is needed, and
the container runs on a free Hugging Face Space (the YAML block at the top
of this README is the Space's config — `sdk: docker`, port 8000).

1. **Atlas** — create a free cluster at
   [mongodb.com/atlas](https://www.mongodb.com/atlas), add a database user,
   and under *Network Access* allow `0.0.0.0/0` (free hosts don't have fixed
   egress IPs). Copy the connection string and put a database name in the
   path, e.g. `mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/internwire`.
2. **Create the Space** — at [huggingface.co/new-space](https://huggingface.co/new-space):
   SDK **Docker** → **Blank** template, hardware **CPU basic (free)**.
3. **Secrets** — in the Space: **Settings → Variables and secrets**, add
   `MONGODB_URI` and `ADMIN_TOKEN` as *secrets* (they become env vars).
4. **Push the code** — grab a *write* token from
   [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens), then:

   ```bash
   git push --force https://<hf-user>:<hf-token>@huggingface.co/spaces/<hf-user>/<space> main
   ```

   Or let GitHub do it on every push: add the token as an Actions secret
   named `HF_TOKEN` and a repository *variable* `HF_SPACE` (e.g.
   `youruser/intern-wire`) — the `sync-to-hf.yml` workflow takes it from there.

The app lives at `https://<hf-user>-<space>.hf.space` (underscores become
dashes). **Use that direct URL, not the huggingface.co page** — the Space
page embeds the app in an iframe where browsers partition localStorage, so
the admin unlock won't stick there.

Free Spaces pause after ~48h without visitors (the next visit wakes them in
under a minute), and the in-process scheduler only runs while awake — so
also add `MONGODB_URI` as a GitHub Actions secret (**Settings → Secrets and
variables → Actions**) and the existing scrape workflow writes straight to
Atlas every 8 hours regardless. The Pages site keeps working too:
`app.export` reads Atlas and publishes the same data. Both writers dedupe
on URL, so they can't conflict.

To run Mongo mode locally:
`MONGODB_URI=... ADMIN_TOKEN=... .venv/bin/uvicorn app.server:app --port 8000`.
Prefer Render instead of a Space? A `render.yaml` blueprint is included —
**New → Blueprint** at [render.com](https://render.com) and fill in the
same two secrets (note its free tier sleeps after ~15 idle minutes).

The options below also run the actual server, with SQLite on a host with a
persistent disk instead. The built-in scheduler handles the 8-hourly scans;
no external cron needed.

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
| `GET /api/admin/check` 🔒 | validates the admin token |
| `POST /api/admin/internships` 🔒 | add a hand-picked listing (`url`, `title` required) |
| `DELETE /api/admin/internships/{id}` 🔒 | remove a listing |

🔒 = requires the `X-Admin-Token` header matching `ADMIN_TOKEN`.

## Notes

- Data lives in SQLite (`internships.db` locally, `/data/internships.db` in
  containers) or MongoDB when `MONGODB_URI` is set — same JSON API either
  way, deduped by original post URL. Delete the file / drop the database to
  start fresh.
- Both platforms' terms restrict automated collection; this only touches
  public, logged-out pages at low volume. Run it politely and at your own
  discretion.
