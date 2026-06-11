/* The Editor's Desk — admin page logic.
 *
 * Server mode only: every write goes through the admin API with the
 * X-Admin-Token header. On the static (GitHub Pages) build there is no
 * backend, so the page just explains how to open the desk on the server.
 */

const TOKEN_KEY = "wire-admin-token";

const $ = (sel) => document.querySelector(sel);
const staticNotice = $("#static-notice");
const lockPanel = $("#lock-panel");
const lockStatus = $("#lock-status");
const desk = $("#desk");
const addBtn = $("#add-btn");
const addStatus = $("#add-status");
const picksEl = $("#picks");
const picksStatusEl = $("#picks-status");
const picksEmptyEl = $("#picks-empty");
const pickTallyEl = $("#pick-tally");

$("#dateline").textContent = new Date()
  .toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })
  .toUpperCase();

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

let token = localStorage.getItem(TOKEN_KEY) || "";

function lockDesk(message) {
  token = "";
  localStorage.removeItem(TOKEN_KEY);
  desk.hidden = true;
  lockPanel.hidden = false;
  $("#token").value = "";
  if (message) showStatus(lockStatus, message, false);
  else lockStatus.hidden = true;
}

/* Returns {res, body}; res is null when the server can't be reached (or the
 * token contains characters fetch() refuses to put in a header). A 401 on any
 * admin call means the token went bad mid-session — relock immediately. */
async function adminFetch(path, options = {}) {
  let res;
  try {
    res = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": token,
        ...(options.headers || {}),
      },
    });
  } catch {
    return { res: null, body: null };
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (res.status === 401) lockDesk("TOKEN NO LONGER VALID — UNLOCK AGAIN.");
  return { res, body };
}

function showStatus(el, message, ok) {
  el.textContent = message;
  el.classList.toggle("ok", !!ok);
  el.classList.toggle("err", !ok);
  el.hidden = false;
}

/* ── lock / unlock ── */

async function tryUnlock() {
  const { res } = await adminFetch("/api/admin/check");
  if (res && res.ok) {
    localStorage.setItem(TOKEN_KEY, token);
    lockPanel.hidden = true;
    lockStatus.hidden = true;
    desk.hidden = false;
    await loadPicks();
    return true;
  }
  return false;
}

$("#unlock-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  lockStatus.hidden = true;
  token = $("#token").value.trim();
  const { res, body } = await adminFetch("/api/admin/check");
  if (res && res.ok) {
    localStorage.setItem(TOKEN_KEY, token);
    lockPanel.hidden = true;
    lockStatus.hidden = true;
    desk.hidden = false;
    await loadPicks();
    return;
  }
  token = "";
  localStorage.removeItem(TOKEN_KEY);
  if (!res) {
    showStatus(lockStatus, "COULDN'T REACH THE SERVER — IS IT RUNNING?", false);
  } else if (res.status === 401) {
    showStatus(lockStatus, "WRONG TOKEN — THE DESK STAYS LOCKED.", false);
  } else {
    // e.g. 503 when ADMIN_TOKEN isn't set, 429 when rate-limited
    showStatus(lockStatus, (body?.detail || `SERVER SAID ${res.status}`).toUpperCase(), false);
  }
});

$("#logout-btn").addEventListener("click", () => lockDesk());

/* ── picks list ── */

function renderPick(item) {
  const meta = [item.company, item.location, `FILED ${(item.posted_at || "—").toUpperCase()}`]
    .filter(Boolean)
    .map((part) => `<span>${esc(part)}</span>`)
    .join("");
  const note = item.snippet
    ? `<p class="listing-note">${esc(item.snippet)}</p>` : "";
  return `<li class="listing" data-id="${item.id}">
    <span class="listing-no">№ ${String(item.id).padStart(3, "0")}</span>
    <h2 class="listing-title">
      <a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>
    </h2>
    <button class="remove-btn" data-id="${item.id}">REMOVE ✕</button>
    ${note}
    <div class="listing-meta">
      <span class="stamp pick">EDITOR’S PICK</span>${meta}
    </div>
  </li>`;
}

async function loadPicks() {
  try {
    const res = await fetch("/api/internships?source=manual&limit=1000");
    const data = await res.json();
    picksEl.innerHTML = data.items.map(renderPick).join("");
    picksEmptyEl.hidden = data.items.length > 0;
    pickTallyEl.textContent = `${data.count} PICK${data.count === 1 ? "" : "S"}`;
  } catch {
    showStatus(picksStatusEl, "COULDN'T LOAD THE PICKS LIST — RELOAD THE PAGE.", false);
  }
}

picksEl.addEventListener("click", async (e) => {
  const btn = e.target.closest(".remove-btn");
  if (!btn) return;
  btn.disabled = true;
  picksStatusEl.hidden = true;
  const { res, body } = await adminFetch(`/api/admin/internships/${btn.dataset.id}`, {
    method: "DELETE",
  });
  if (res && (res.ok || res.status === 404)) {
    await loadPicks();
  } else {
    btn.disabled = false;
    if (res && res.status !== 401) {
      showStatus(picksStatusEl, (body?.detail || `REMOVE FAILED (${res.status})`).toUpperCase(), false);
    } else if (!res) {
      showStatus(picksStatusEl, "COULDN'T REACH THE SERVER — TRY AGAIN.", false);
    }
  }
});

/* ── filing a new pick ── */

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  addStatus.hidden = true;
  addBtn.disabled = true;
  const payload = {
    url: $("#f-url").value.trim(),
    title: $("#f-title").value.trim(),
    company: $("#f-company").value.trim() || null,
    location: $("#f-location").value.trim() || null,
    snippet: $("#f-snippet").value.trim() || null,
  };
  const { res, body } = await adminFetch("/api/admin/internships", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  addBtn.disabled = false;
  if (res && res.status === 201) {
    showStatus(addStatus, "STAMPED — IT'S ON THE FRONT PAGE.", true);
    $("#add-form").reset();
    await loadPicks();
  } else if (!res) {
    showStatus(addStatus, "COULDN'T REACH THE SERVER — TRY AGAIN.", false);
  } else if (res.status !== 401) {
    const detail = typeof body?.detail === "string"
      ? body.detail
      : `COULDN'T FILE IT (${res.status})`;
    showStatus(addStatus, detail.toUpperCase(), false);
  }
});

/* ── boot ── */

(async function boot() {
  let serverMode = false;
  try {
    const res = await fetch("/api/stats");
    serverMode = res.ok && (res.headers.get("content-type") || "").includes("json");
  } catch { /* no backend */ }

  if (!serverMode) {
    staticNotice.hidden = false;
    return;
  }
  if (!token || !(await tryUnlock())) {
    lockPanel.hidden = false;
  }
})();
