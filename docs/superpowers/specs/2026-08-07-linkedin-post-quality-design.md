# LinkedIn post quality and curated examples

## Goal

Keep genuine LinkedIn internship openings in the dashboard while excluding
personal internship experiences, general discussions, and other non-vacancy
posts. Preserve the three user-supplied LinkedIn posts as curated listings,
independent of search-engine indexing.

## Scope

- Add the supplied `lnkd.in` URLs as durable curated picks.
- Make LinkedIn feed-post acceptance require concrete vacancy evidence rather
  than only a broad hiring keyword.
- Keep the existing LinkedIn Jobs and X/Twitter sources unchanged.
- Publish the resulting static data through the existing GitHub Pages
  workflow and synchronize the app to the existing `imajij/internwire`
  Hugging Face Space.

## Data model and flow

Curated posts will live in the existing version-controlled `picks.json`
format. They are promoted into both storage backends on each scrape/export
run and therefore survive search-index changes and normal stale-listing
cleanup. In MongoDB, file-synced picks carry a dedicated marker, so updates or
removals affect only those entries and never an admin-created manual listing.
The supplied short links remain the destination URLs because the current
environment cannot resolve their redirects (the service responds with HTTP
403).

The LinkedIn feed-post scraper will classify search result text in two stages:

1. Reject a result if it includes personal-experience or general-discussion
   signals.
2. Accept the result only if it has internship context plus at least two
   independent vacancy signals. Signals include a role or role pattern, an
   employer/recruiter signal, and an application or contact route. A result
   with an explicit `hiring`/`open roles` message and a role may satisfy the
   same rule where the search snippet omits a URL.

This deliberately rejects ambiguous date-only snippets instead of presenting
them as opportunities. The source remains configurable via `config.json` for
search queries and term lists; concrete classification logic stays in the
scraper so automated tests describe the public behavior.

## Error handling

- A failed search backend continues to skip only that query, as today.
- Bad or duplicate links in curated picks are handled by the existing picks
  validation and URL de-duplication.
- MongoDB sync deletes only entries previously marked as file-synced; it does
  not delete manual entries created through the live admin page.
- The manual links are not fetched during scraping, so an unavailable
  LinkedIn shortener cannot break a scrape.

## Tests

Tests will exercise the pure post-classification behavior before integrating
it with DDGS. They will cover:

- each supplied curated pick being exported as a manual listing;
- file-synced picks being inserted in MongoDB without deleting an unmarked
  admin-created manual listing;
- valid job posts with role and application evidence being accepted;
- personal experience announcements and internship commentary being rejected;
- ambiguous "internship" search results without vacancy evidence being
  rejected; and
- existing URL canonicalization and duplicate handling remaining intact.

## Deployment and acceptance

After the change, a fresh export must contain the three curated links and no
known non-vacancy fixtures. The change will be pushed to `main`, which triggers
the existing GitHub Pages deployment at
`https://imajij.github.io/intern-wire/`. The Hugging Face sync workflow will
be run or checked, targeting `imajij/internwire`; its deployed Space will be
verified after the build completes.
