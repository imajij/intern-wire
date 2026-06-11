/* The Intern Wire — dashboard logic.
 *
 * Two modes, detected at boot:
 *  - server: the FastAPI backend is present → filters via /api, live RE-SCRAPE
 *  - static: served from GitHub Pages → load data.json, filter client-side
 */

const state = { q: "", source: "", days: 0 };
const RENDER_CAP = 300;

let mode = "server";
let staticData = null; // {items, total, by_source, last_scraped} in static mode

const $ = (sel) => document.querySelector(sel);
const listingsEl = $("#listings");
const emptyEl = $("#empty");
const tallyEl = $("#tally");
const datelineEl = $("#dateline");
const statusEl = $("#status-line");
const lastScrapedEl = $("#last-scraped");
const refreshBtn = $("#refresh");

datelineEl.textContent = new Date()
  .toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })
  .toUpperCase();

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function parseDate(iso) {
  if (!iso) return null;
  const d = new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
  return isNaN(d.getTime()) ? null : d;
}

function relativeDate(iso) {
  const then = parseDate(iso);
  if (!then) return "DATE UNKNOWN";
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return "TODAY";
  if (days === 1) return "1 DAY AGO";
  if (days < 30) return `${days} DAYS AGO`;
  const months = Math.floor(days / 30);
  return months === 1 ? "1 MONTH AGO" : `${months} MONTHS AGO`;
}

function renderItem(item, i) {
  const isTweet = item.source === "twitter";
  const isPost = item.source === "linkedin-post";
  const isPick = item.source === "manual";
  const no = String(i + 1).padStart(3, "0");
  const title = isTweet || isPost
    ? `<span class="tweet-quote">“${esc(item.title)}”</span>`
    : esc(item.title);
  const company = item.company
    ? `<span class="co">${esc(item.company)}</span>` : "";
  const location = item.location ? `<span>${esc(item.location)}</span>` : "";
  const stamp = isTweet
    ? `<span class="stamp twitter">VIA X</span>`
    : isPost
      ? `<span class="stamp lipost">LI POST</span>`
      : isPick
        ? `<span class="stamp pick">EDITOR’S PICK</span>`
        : `<span class="stamp linkedin">LINKEDIN</span>`;
  const applyLabel = isTweet || isPost ? "VIEW POST ↗" : "APPLY ↗";
  const note = isPick && item.snippet
    ? `<p class="listing-note">${esc(item.snippet)}</p>` : "";
  const delay = Math.min(i, 18) * 0.04;

  return `<li class="listing" style="animation-delay:${delay}s">
    <span class="listing-no">№ ${no}</span>
    <h2 class="listing-title">
      <a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${title}</a>
    </h2>
    <a class="apply" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${applyLabel}</a>
    ${note}
    <div class="listing-meta">
      ${stamp}${company}${location}<span>POSTED ${relativeDate(item.posted_at || item.scraped_at)}</span>
    </div>
  </li>`;
}

function renderList(items) {
  listingsEl.innerHTML = items.slice(0, RENDER_CAP).map(renderItem).join("");
  emptyEl.hidden = items.length > 0;
  tallyEl.textContent = `${items.length} LISTING${items.length === 1 ? "" : "S"} ON FILE`;
}

/* ── static mode: client-side filtering over data.json ── */

function filterStatic() {
  const q = state.q.toLowerCase();
  const cutoff = state.days ? Date.now() - state.days * 86400000 : null;
  return staticData.items.filter((item) => {
    if (state.source && item.source !== state.source) return false;
    if (q) {
      const haystack = [item.title, item.company, item.location, item.snippet]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    if (cutoff) {
      const d = parseDate(item.posted_at || item.scraped_at);
      if (!d || d.getTime() < cutoff) return false;
    }
    return true;
  });
}

/* ── data fetching, dispatched by mode ── */

async function fetchListings() {
  if (mode === "static") {
    renderList(filterStatic());
    return;
  }
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.source) params.set("source", state.source);
  if (state.days) params.set("days", state.days);
  const res = await fetch(`/api/internships?${params}`);
  const data = await res.json();
  renderList(data.items);
}

async function fetchStats() {
  if (mode === "static") {
    lastScrapedEl.textContent = staticData.last_scraped
      ? `LAST SCRAPE ${relativeDate(staticData.last_scraped)}`
      : "NEVER SCRAPED";
    return { scraping: false };
  }
  const res = await fetch("/api/stats");
  const s = await res.json();
  lastScrapedEl.textContent = s.last_scraped
    ? `LAST SCRAPE ${relativeDate(s.last_scraped)}`
    : "NEVER SCRAPED";
  return s;
}

/* ── filters ── */

let debounceTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    state.q = e.target.value.trim();
    fetchListings();
  }, 300);
});

$("#source-chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  document.querySelectorAll(".chip").forEach((c) => c.classList.remove("is-active"));
  chip.classList.add("is-active");
  state.source = chip.dataset.source;
  fetchListings();
});

$("#days").addEventListener("change", (e) => {
  state.days = Number(e.target.value);
  fetchListings();
});

/* ── re-scrape (server mode only) ── */

function setBusy(busy) {
  refreshBtn.disabled = busy;
  refreshBtn.classList.toggle("is-busy", busy);
  statusEl.hidden = !busy;
  if (busy) statusEl.textContent = "● SCRAPING THE WIRE — new listings will appear shortly…";
}

async function pollUntilDone(timeoutMs = 180000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 4000));
    const s = await fetchStats().catch(() => null);
    await fetchListings().catch(() => {});
    if (s && !s.scraping) return;
  }
}

refreshBtn.addEventListener("click", async () => {
  const res = await fetch("/api/refresh", { method: "POST" });
  if (res.status === 409) return; // already running
  setBusy(true);
  await pollUntilDone();
  setBusy(false);
});

/* ── boot ── */

async function detectMode() {
  try {
    const res = await fetch("/api/stats");
    const type = res.headers.get("content-type") || "";
    if (res.ok && type.includes("json")) return "server";
  } catch { /* no backend */ }
  return "static";
}

(async function boot() {
  mode = await detectMode();
  if (mode === "static") {
    refreshBtn.hidden = true; // no backend to trigger; GitHub Actions re-scrapes
    const res = await fetch("data.json");
    staticData = await res.json();
    if (!staticData.by_source?.manual) {
      // no picks in this build — the chip would only show a dead-end empty
      // state (remove, not hide, so the X chip becomes :last-child again)
      document.querySelector('.chip[data-source="manual"]')?.remove();
    }
  }
  await fetchListings();
  const s = await fetchStats();
  if (s.scraping) {
    setBusy(true);
    pollUntilDone().then(() => setBusy(false));
  }
})();
