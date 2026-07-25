const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

const TEAM_IDS = {
  1: "Atlanta Hawks", 2: "Boston Celtics", 17: "Brooklyn Nets", 30: "Charlotte Hornets",
  4: "Chicago Bulls", 5: "Cleveland Cavaliers", 6: "Dallas Mavericks", 7: "Denver Nuggets",
  8: "Detroit Pistons", 9: "Golden State Warriors", 10: "Houston Rockets", 11: "Indiana Pacers",
  12: "LA Clippers", 13: "Los Angeles Lakers", 29: "Memphis Grizzlies", 14: "Miami Heat",
  15: "Milwaukee Bucks", 16: "Minnesota Timberwolves", 3: "New Orleans Pelicans", 18: "New York Knicks",
  25: "Oklahoma City Thunder", 19: "Orlando Magic", 20: "Philadelphia 76ers", 21: "Phoenix Suns",
  22: "Portland Trail Blazers", 23: "Sacramento Kings", 24: "San Antonio Spurs", 28: "Toronto Raptors",
  26: "Utah Jazz", 27: "Washington Wizards"
};

const CACHE_KEY = "nbaPlayersCache";
const CACHE_MAX_AGE_MS = 12 * 60 * 60 * 1000; // 12 hours

let players = [];
let byMonthDay = new Map();
let dataFetchedAt = null;

const monthSelect = document.getElementById("monthSelect");
const daySelect = document.getElementById("daySelect");
const datePicker = document.getElementById("datePicker");
const searchInput = document.getElementById("searchInput");
const todayTab = document.getElementById("todayTab");
const upcomingTab = document.getElementById("upcomingTab");
const browseTab = document.getElementById("browseTab");
const resultsTitle = document.getElementById("resultsTitle");
const resultsEl = document.getElementById("results");

function populateMonthSelect() {
  MONTH_NAMES.forEach((name, i) => {
    const opt = document.createElement("option");
    opt.value = i + 1;
    opt.textContent = name;
    monthSelect.appendChild(opt);
  });
}

function populateDaySelect(month) {
  const daysInMonth = new Date(2024, month, 0).getDate(); // 2024 is a leap year, safe for Feb 29
  const prevValue = daySelect.value;
  daySelect.innerHTML = "";
  for (let d = 1; d <= daysInMonth; d++) {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d;
    daySelect.appendChild(opt);
  }
  if (prevValue && prevValue <= daysInMonth) {
    daySelect.value = prevValue;
  }
}

function keyFor(month, day) {
  return `${month}-${day}`;
}

// NBA scheduling is anchored to US Eastern Time regardless of where a game is
// played, so "today" for birthday-matching purposes must be Eastern's calendar
// date, not the visitor's local date (which can already be tomorrow, or still
// yesterday, in the US).
const US_TIME_ZONE = "America/New_York";

function getUSToday() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: US_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const map = {};
  for (const p of parts) map[p.type] = p.value;
  return { year: Number(map.year), month: Number(map.month), day: Number(map.day) };
}

// Pure calendar-date arithmetic (no timezone re-interpretation): add `offset`
// days to a {year,month,day} and return the resulting {year,month,day}.
function addDays({ year, month, day }, offset) {
  const d = new Date(Date.UTC(year, month - 1, day));
  d.setUTCDate(d.getUTCDate() + offset);
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

function buildIndex() {
  byMonthDay = new Map();
  for (const p of players) {
    const key = keyFor(p.month, p.day);
    if (!byMonthDay.has(key)) byMonthDay.set(key, []);
    byMonthDay.get(key).push(p);
  }
}

async function fetchTeamRoster(id, teamName) {
  const res = await fetch(`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/${id}/roster`);
  if (!res.ok) throw new Error(`ESPN roster fetch failed for team ${id}: HTTP ${res.status}`);
  const data = await res.json();
  return (data.athletes || [])
    .filter((a) => a.dateOfBirth)
    .map((a) => {
      const dob = a.dateOfBirth.slice(0, 10);
      const [y, m, d] = dob.split("-").map(Number);
      return {
        id: a.id,
        name: a.fullName || a.displayName,
        dob,
        month: m,
        day: d,
        year: y,
        teams: [teamName],
        position: (a.position || {}).abbreviation || "",
        jersey: a.jersey || "",
        headshot: (a.headshot || {}).href || "",
      };
    });
}

async function fetchLiveRosters() {
  const entries = Object.entries(TEAM_IDS);
  const results = await Promise.all(
    entries.map(([id, name]) =>
      fetchTeamRoster(id, name).catch((err) => {
        console.warn(err);
        return null; // signals a failed team so we don't cache a partial roster as truth
      })
    )
  );
  if (results.some((r) => r === null)) {
    throw new Error("One or more team rosters failed to load");
  }
  return results.flat();
}

function loadCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.players) || !parsed.fetchedAt) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveCache(playerList) {
  const fetchedAt = Date.now();
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ players: playerList, fetchedAt }));
  } catch {
    // localStorage full/unavailable — fine, just skip caching
  }
  return fetchedAt;
}

function formatAgo(ms) {
  const mins = Math.round(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function updateFreshnessLabel() {
  const el = document.getElementById("freshness");
  if (!el) return;
  if (!dataFetchedAt) {
    el.textContent = "";
    return;
  }
  el.textContent = `Updated ${formatAgo(Date.now() - dataFetchedAt)}`;
}

function ageFromDob(dob, today) {
  const [by, bm, bd] = dob.split("-").map(Number);
  let age = today.year - by;
  if (today.month < bm || (today.month === bm && today.day < bd)) age--;
  return age;
}

function setActiveTab(tab) {
  [todayTab, upcomingTab, browseTab].forEach((btn) => btn.classList.remove("active"));
  tab.classList.add("active");
  datePicker.hidden = tab !== browseTab;
}

function playerCard(p, extra, today) {
  const dobDate = new Date(p.dob);
  const dobFormatted = `${MONTH_NAMES[dobDate.getUTCMonth()]} ${dobDate.getUTCDate()}, ${dobDate.getUTCFullYear()}`;
  const age = ageFromDob(p.dob, today);
  const team = p.teams[0] || "Free agent";
  const posJersey = [p.position, p.jersey ? `#${p.jersey}` : ""].filter(Boolean).join(" · ");

  const card = document.createElement("div");
  card.className = "player-card";
  card.innerHTML = `
    ${p.headshot ? `<img class="headshot" src="${p.headshot}" alt="${p.name}" loading="lazy">` : `<div class="headshot placeholder"></div>`}
    <div class="info">
      <div class="name">${p.name}</div>
      <div class="team">${team}${posJersey ? ` · ${posJersey}` : ""}</div>
      <div class="dob">${dobFormatted} · turns ${age}${extra ? ` <span class="badge">${extra}</span>` : ""}</div>
    </div>
  `;
  return card;
}

function renderPlayers(list, title, extraFn) {
  resultsTitle.textContent = title;
  resultsEl.innerHTML = "";

  if (list.length === 0) {
    resultsEl.innerHTML = `<p class="empty-state">No players found.</p>`;
    return;
  }

  const today = getUSToday();
  const frag = document.createDocumentFragment();
  for (const p of list) {
    frag.appendChild(playerCard(p, extraFn ? extraFn(p) : null, today));
  }
  resultsEl.appendChild(frag);
}

function showBirthdaysFor(month, day, { silent } = {}) {
  if (!silent) {
    monthSelect.value = month;
    populateDaySelect(month);
    daySelect.value = day;
  }
  const key = keyFor(month, day);
  return (byMonthDay.get(key) || []).slice().sort((a, b) => a.name.localeCompare(b.name));
}

function showToday() {
  setActiveTab(todayTab);
  const today = getUSToday();
  const list = showBirthdaysFor(today.month, today.day, { silent: true });
  renderPlayers(list, `Birthdays Today (US ET) — ${MONTH_NAMES[today.month - 1]} ${today.day}`);
}

function showUpcoming() {
  setActiveTab(upcomingTab);
  const today = getUSToday();
  const days = 14;
  const matches = [];

  for (let i = 0; i < days; i++) {
    const { month, day } = addDays(today, i);
    const list = showBirthdaysFor(month, day, { silent: true });
    for (const p of list) {
      matches.push({ player: p, daysOut: i, month, day });
    }
  }

  matches.sort((a, b) => a.daysOut - b.daysOut || a.player.name.localeCompare(b.player.name));

  const list = matches.map((m) => m.player);
  const labelFor = (p) => {
    const m = matches.find((x) => x.player === p);
    if (m.daysOut === 0) return "today";
    if (m.daysOut === 1) return "tomorrow";
    return `in ${m.daysOut} days`;
  };

  renderPlayers(list, `Upcoming Birthdays — Next ${days} Days`, labelFor);
}

function showBrowse() {
  setActiveTab(browseTab);
  const month = Number(monthSelect.value);
  const day = Number(daySelect.value);
  const list = showBirthdaysFor(month, day);
  renderPlayers(list, `Birthdays on ${MONTH_NAMES[month - 1]} ${day}`);
}

function doSearch(query) {
  const q = query.trim().toLowerCase();
  if (!q) {
    showToday();
    return;
  }
  const list = players
    .filter((p) => p.name.toLowerCase().includes(q))
    .sort((a, b) => a.name.localeCompare(b.name));
  renderPlayers(list, `Search results for "${query}"`);
}

todayTab.addEventListener("click", () => {
  searchInput.value = "";
  showToday();
});

upcomingTab.addEventListener("click", () => {
  searchInput.value = "";
  showUpcoming();
});

browseTab.addEventListener("click", () => {
  searchInput.value = "";
  showBrowse();
});

monthSelect.addEventListener("change", () => {
  populateDaySelect(Number(monthSelect.value));
  showBrowse();
});

daySelect.addEventListener("change", showBrowse);

searchInput.addEventListener("input", () => {
  doSearch(searchInput.value);
});

function applyPlayers(list, fetchedAt) {
  players = list;
  dataFetchedAt = fetchedAt;
  buildIndex();
  document.getElementById("subtitle").textContent =
    `${players.length.toLocaleString()} active NBA players — current rosters only`;
  updateFreshnessLabel();
}

function currentView() {
  if (browseTab.classList.contains("active")) return showBrowse;
  if (upcomingTab.classList.contains("active")) return showUpcoming;
  return showToday;
}

async function refreshFromEspn({ background } = {}) {
  const refreshBtn = document.getElementById("refreshBtn");
  if (refreshBtn) refreshBtn.disabled = true;
  try {
    const live = await fetchLiveRosters();
    const fetchedAt = saveCache(live);
    applyPlayers(live, fetchedAt);
    if (!background) currentView()();
    else if (!searchInput.value) currentView()(); // silently update the visible list
  } catch (err) {
    console.warn("Live ESPN refresh failed:", err);
    if (!background) throw err;
  } finally {
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

async function init() {
  populateMonthSelect();
  const today = getUSToday();
  monthSelect.value = today.month;
  populateDaySelect(today.month);
  daySelect.value = today.day;

  document.getElementById("refreshBtn").addEventListener("click", () => {
    resultsTitle.textContent = "Refreshing from ESPN…";
    refreshFromEspn({ background: false }).catch((err) => {
      resultsEl.innerHTML = `<p class="empty-state">Refresh failed (${err.message}). Still showing the last known data.</p>`;
    });
  });

  const cached = loadCache();
  if (cached) {
    applyPlayers(cached.players, cached.fetchedAt);
    showToday();
  }

  const isStale = !cached || Date.now() - cached.fetchedAt > CACHE_MAX_AGE_MS;

  if (!cached) {
    resultsTitle.textContent = "Loading current rosters from ESPN…";
  }

  try {
    if (!cached || isStale) {
      await refreshFromEspn({ background: !!cached });
    }
  } catch (err) {
    if (cached) {
      // We already showed cached data above; just note the failed background refresh.
      console.warn("Background refresh failed, keeping cached data:", err);
    } else {
      // No cache and live fetch failed — fall back to the bundled snapshot.
      try {
        const res = await fetch("data/players.json");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const bundled = await res.json();
        applyPlayers(bundled, null);
        document.getElementById("freshness").textContent = "Using bundled snapshot (live ESPN fetch failed)";
        showToday();
      } catch (fallbackErr) {
        resultsTitle.textContent = "Failed to load player data";
        resultsEl.innerHTML = `<p class="empty-state">Live ESPN fetch failed (${err.message}) and the bundled fallback also failed (${fallbackErr.message}).<br>
          If you opened this file directly in the browser, that's the problem — browsers block local file fetches.<br>
          Run a local server instead, e.g. <code>python3 -m http.server 8000</code>, then visit <code>http://localhost:8000</code>.</p>`;
      }
    }
  }
}

init();
