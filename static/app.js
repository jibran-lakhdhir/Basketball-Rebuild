const state = {
  franchiseId: null,
  franchiseState: null, // { franchise, roster, starters, bench_rotation, cap_sheet }
  draggedSlug: null,
  currentTab: "calendar",
  lastKnownPhase: null, // used to detect the in_season -> playoffs transition
  awardsShownThisTransition: false,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function showScreen(id) {
  $$(".screen").forEach((el) => el.classList.add("hidden"));
  $(`#${id}`).classList.remove("hidden");
}

function showLoading(text) {
  $("#loading-text").textContent = text;
  $("#loading-overlay").classList.remove("hidden");
}
function hideLoading() {
  $("#loading-overlay").classList.add("hidden");
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "request failed");
  return data;
}

function money(n) {
  // Round to the nearest $100K and show as millions, e.g. 3,235,127 -> "$3.2M"
  const millions = Math.round(n / 100000) / 10;
  return "$" + millions.toFixed(1) + "M";
}

// Stat averages are already rounded to 1 decimal server-side, but JS Numbers
// don't preserve a trailing ".0" (2.0 prints as "2") -- toFixed(1) keeps
// display consistent so a whole-number average doesn't look different from
// its neighbors (e.g. steals/blocks leaders showing "2" next to "1.9").
function fmt1(n) {
  return (n ?? 0).toFixed(1);
}

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

// ---------------------------------------------------------------------------
// Franchise hub
// ---------------------------------------------------------------------------

async function loadHub() {
  state.franchiseId = null;
  $("#franchise-header").classList.add("hidden");
  showScreen("screen-hub");
  const franchises = await api("/api/franchises");
  const list = $("#franchise-list");
  list.innerHTML = "";
  if (franchises.length === 0) {
    list.innerHTML = `<p class="subtitle">No franchises yet — start one below.</p>`;
  }
  for (const f of franchises) {
    const card = document.createElement("div");
    card.className = "team-card franchise-card";
    card.innerHTML = `
      <div class="team-name">${f.name}</div>
      <div class="franchise-meta">${f.user_team_abbr} &middot; ${formatDate(f.current_date)}</div>
      <div class="franchise-phase">${f.phase.replace(/_/g, " ")}</div>
    `;
    card.addEventListener("click", () => enterDashboard(f.id));
    list.appendChild(card);
  }
}

$("#btn-new-franchise").addEventListener("click", async () => {
  $("#franchise-name-input").value = "";
  $("#new-franchise-error").textContent = "";
  showScreen("screen-new-franchise");
  const teams = await api("/api/teams");
  const grid = $("#team-grid");
  grid.innerHTML = "";
  for (const t of teams) {
    const card = document.createElement("div");
    card.className = "team-card";
    card.innerHTML = `<div class="team-name">${t.full_name}</div><div class="team-roster-size">${t.roster_size} players</div>`;
    card.addEventListener("click", () => createFranchise(t.team_abbr));
    grid.appendChild(card);
  }
});

$("#btn-back-to-hub").addEventListener("click", loadHub);

async function createFranchise(teamAbbr) {
  const name = $("#franchise-name-input").value.trim();
  if (!name) {
    $("#new-franchise-error").textContent = "Give your franchise a name first.";
    return;
  }
  showLoading("Setting up your franchise (generating schedule)...");
  try {
    const result = await api("/api/franchises", {
      method: "POST",
      body: JSON.stringify({ name, team_id: teamAbbr }),
    });
    state.franchiseId = result.franchise.id;
    state.franchiseState = result;
    await enterDashboard(state.franchiseId);
  } catch (e) {
    $("#new-franchise-error").textContent = e.message;
  } finally {
    hideLoading();
  }
}

// ---------------------------------------------------------------------------
// Dashboard shell
// ---------------------------------------------------------------------------

async function enterDashboard(franchiseId) {
  showLoading("Loading franchise...");
  try {
    state.franchiseId = franchiseId;
    state.franchiseState = await api(`/api/franchises/${franchiseId}`);
    state.lastKnownPhase = state.franchiseState.franchise.phase; // baseline -- no transition on initial load
    renderHeader();
    showScreen("screen-dashboard");
    switchTab(state.currentTab || "calendar");
  } catch (e) {
    alert(e.message);
    await loadHub();
  } finally {
    hideLoading();
  }
}

async function refreshFranchiseState() {
  const previousPhase = state.lastKnownPhase;
  state.franchiseState = await api(`/api/franchises/${state.franchiseId}`);
  const newPhase = state.franchiseState.franchise.phase;
  renderHeader();
  if (previousPhase === "in_season" && newPhase === "playoffs") {
    await showAwardsModal();
  }
  state.lastKnownPhase = newPhase;
}

function renderHeader() {
  const fs = state.franchiseState;
  const cap = fs.cap_sheet;
  const el = $("#franchise-header");
  el.classList.remove("hidden");
  el.innerHTML = `
    <span><b>${fs.franchise.name}</b> (${fs.franchise.user_team_abbr})</span>
    <span>${formatDate(fs.franchise.current_date)}</span>
    <span>Cap Hit: <b>${money(cap.total_cap_hit)}</b></span>
    <span>Cap Room: <b>${money(cap.cap_room)}</b></span>
    <span class="${cap.is_over_tax_line ? "over-tax" : ""}">${cap.is_over_tax_line ? "Over Luxury Tax" : "Under Tax Line"}</span>
    ${cap.dead_cap_total ? `<span>Dead Cap: <b>${money(cap.dead_cap_total)}</b></span>` : ""}
    <span style="cursor:pointer; text-decoration:underline;" id="btn-switch-franchise">Switch Franchise</span>
  `;
  $("#btn-switch-franchise").addEventListener("click", loadHub);
}

for (const btn of $$(".tab-btn")) {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
}

function switchTab(tab) {
  state.currentTab = tab;
  for (const btn of $$(".tab-btn")) btn.classList.toggle("active", btn.dataset.tab === tab);
  for (const panel of $$(".tab-panel")) panel.classList.toggle("hidden", panel.id !== `tab-${tab}`);

  if (tab === "calendar") renderCalendarTab();
  else if (tab === "stats") renderStatsTab();
  else if (tab === "front-office") renderFrontOfficeTab();
  else if (tab === "coaching") renderCoachingTab();
}

// ---------------------------------------------------------------------------
// Player card rendering (shared by Front Office + Coaching tabs)
// ---------------------------------------------------------------------------

const GRADE_CATEGORIES = [
  ["interior_scoring", "INT SCR"],
  ["perimeter_scoring", "PER SCR"],
  ["playmaking", "PLAY"],
  ["rebounding", "REB"],
  ["interior_defense", "INT DEF"],
  ["perimeter_defense", "PER DEF"],
  ["athleticism", "ATH"],
];

function playerCard(player, { draggable = false, actions = [], badge = null } = {}) {
  const tpl = $("#player-card-template").content.cloneNode(true);
  const card = tpl.querySelector(".player-card");
  card.dataset.slug = player.slug;

  const nameEl = card.querySelector(".player-name");
  nameEl.textContent = player.name;
  if (badge) {
    const badgeEl = document.createElement("span");
    badgeEl.className = "bird-rights-badge";
    badgeEl.textContent = badge;
    nameEl.appendChild(badgeEl);
  }
  const heightStr = player.height_in ? `${Math.floor(player.height_in / 12)}'${player.height_in % 12}"` : "?";
  const contractStr = player.contract_years ? `${player.contract_years}yr` : "";
  card.querySelector(".player-meta").textContent =
    `${player.positions.join("/")} · ${heightStr} · ${player.weight_lb || "?"}lb · Age ${player.age} · ${money(player.salary)}${contractStr ? " · " + contractStr : ""}`;

  const gradesEl = card.querySelector(".player-card-grades");
  const overallChip = document.createElement("span");
  overallChip.className = "grade-chip overall-chip";
  overallChip.innerHTML = `OVR <b>${player.overall_rating}</b>`;
  gradesEl.appendChild(overallChip);
  for (const [key, label] of GRADE_CATEGORIES) {
    const chip = document.createElement("span");
    chip.className = "grade-chip";
    chip.innerHTML = `${label} <b>${player.grades[key]}</b>`;
    gradesEl.appendChild(chip);
  }

  const actionsEl = card.querySelector(".player-card-actions");
  for (const { label, onClick, cls } of actions) {
    const btn = document.createElement("button");
    btn.textContent = label;
    btn.className = cls || "secondary";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      onClick(player);
    });
    actionsEl.appendChild(btn);
  }

  if (draggable) {
    card.draggable = true;
    card.addEventListener("dragstart", () => (state.draggedSlug = player.slug));
  }

  return card;
}

function playerBySlug(slug) {
  return state.franchiseState.roster.find((p) => p.slug === slug);
}

// ---------------------------------------------------------------------------
// Calendar tab
// ---------------------------------------------------------------------------

async function renderCalendarTab() {
  const fs = state.franchiseState;
  const phase = fs.franchise.phase;
  const inPlayoffs = phase === "playoffs";
  const inOffseason = phase === "offseason" || phase === "offseason_draft" || phase === "offseason_free_agency";
  $("#calendar-date-label").textContent = `Today: ${formatDate(fs.franchise.current_date)} — ${phase.replace(/_/g, " ")}`;

  $("#regular-season-view").classList.toggle("hidden", inPlayoffs || inOffseason);
  $("#playoff-view").classList.toggle("hidden", !inPlayoffs);
  $("#offseason-view").classList.toggle("hidden", !inOffseason);

  if (inPlayoffs) {
    await renderPlayoffView();
  } else if (inOffseason) {
    await renderOffseasonView();
  } else {
    await renderRegularSeasonView();
  }
}

async function renderRegularSeasonView() {
  const fs = state.franchiseState;
  $("#calendar-error").textContent = "";
  $("#btn-sim-next-game").disabled = false;
  $("#btn-sim-next-milestone").disabled = false;

  renderLastGamePanel();

  const schedule = await api(`/api/franchises/${state.franchiseId}/schedule?team=${fs.franchise.user_team_abbr}`);
  const table = $("#schedule-table");
  const rows = schedule
    .map((g) => {
      const isHome = g.home === fs.franchise.user_team_abbr;
      const opponent = isHome ? g.away : g.home;
      let resultCell = "-";
      let resultClass = "";
      if (g.played) {
        const won = g.winner === fs.franchise.user_team_abbr;
        resultCell = won ? "W" : "L";
        resultClass = won ? "result-w" : "result-l";
      }
      return `
        <tr class="${g.played ? "played" : ""}">
          <td>${formatDate(g.date)}</td>
          <td>${isHome ? "vs" : "@"} ${opponent}</td>
          <td class="${resultClass}">${resultCell}</td>
        </tr>`;
    })
    .join("");
  table.innerHTML = `<tr><th>Date</th><th>Opponent</th><th>Result</th></tr>${rows}`;
}

function renderLastGamePanel() {
  const box = state.franchiseState.franchise.last_box_score;
  const panel = $("#last-game-panel");
  if (!box) {
    panel.innerHTML = `<div class="last-game-panel"><span class="empty-state">No games played yet — sim to your first game.</span></div>`;
    return;
  }

  const lines = Object.entries(box.lines).map(([slug, line]) => {
    const p = playerBySlug(slug);
    return { name: p ? p.name : slug, line };
  });
  lines.sort((a, b) => b.line.ppg - a.line.ppg);
  const totalPts = lines.reduce((sum, r) => sum + r.line.ppg, 0);

  const rows = lines
    .map(
      (r) => `
    <tr>
      <td>${r.name}</td><td>${fmt1(r.line.mpg)}</td><td>${fmt1(r.line.ppg)}</td><td>${fmt1(r.line.rpg)}</td>
      <td>${fmt1(r.line.apg)}</td><td>${fmt1(r.line.spg)}</td><td>${fmt1(r.line.bpg)}</td>
      <td>${(r.line.fg_pct * 100).toFixed(1)}%</td><td>${(r.line.fg3_pct * 100).toFixed(1)}%</td>
    </tr>`
    )
    .join("");

  $("#last-game-panel").innerHTML = `
    <div class="last-game-panel">
      <span class="result-badge ${box.won ? "win" : "loss"}">${box.won ? "W" : "L"}</span>
      ${formatDate(box.date)} — ${box.is_home ? "vs" : "@"} ${box.opponent} — ${Math.round(totalPts)} pts
      <table class="data-table" style="margin-top:12px;">
        <tr><th>Player</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FG%</th><th>3P%</th></tr>
        ${rows}
      </table>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Playoffs (bracket + awards modal)
// ---------------------------------------------------------------------------

const ROUND_LABELS = {
  ROUND_1: "Round 1",
  CONF_SEMIS: "Conference Semifinals",
  CONF_FINALS: "Conference Finals",
  FINALS: "NBA Finals",
};

function renderPlayoffLastGamePanel() {
  const box = state.franchiseState.franchise.last_box_score;
  const panel = $("#playoff-last-game-panel");
  if (!box || box.round === undefined) {
    panel.innerHTML = "";
    return;
  }

  const lines = Object.entries(box.lines).map(([slug, line]) => {
    const p = playerBySlug(slug);
    return { name: p ? p.name : slug, line };
  });
  lines.sort((a, b) => b.line.ppg - a.line.ppg);

  const rows = lines
    .map(
      (r) => `
    <tr>
      <td>${r.name}</td><td>${fmt1(r.line.mpg)}</td><td>${fmt1(r.line.ppg)}</td><td>${fmt1(r.line.rpg)}</td>
      <td>${fmt1(r.line.apg)}</td><td>${fmt1(r.line.spg)}</td><td>${fmt1(r.line.bpg)}</td>
      <td>${(r.line.fg_pct * 100).toFixed(1)}%</td><td>${(r.line.fg3_pct * 100).toFixed(1)}%</td>
    </tr>`
    )
    .join("");

  panel.innerHTML = `
    <div class="last-game-panel">
      <span class="result-badge ${box.won ? "win" : "loss"}">${box.won ? "Won" : "Lost"}</span>
      ${ROUND_LABELS[box.round] || box.round} vs ${box.opponent} — series ${box.series_score}
      <table class="data-table" style="margin-top:12px;">
        <tr><th>Player</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FG%</th><th>3P%</th></tr>
        ${rows}
      </table>
    </div>
  `;
}

async function renderPlayoffView() {
  const fs = state.franchiseState;
  $("#playoff-error").textContent = "";

  const champUnknown = fs.franchise.phase !== "offseason";
  $("#btn-sim-next-round").classList.toggle("hidden", !champUnknown);
  $("#btn-continue-to-offseason").classList.toggle("hidden", champUnknown);

  renderPlayoffLastGamePanel();

  const bracket = await api(`/api/franchises/${state.franchiseId}/playoffs/bracket`);
  const byRound = {};
  for (const s of bracket) {
    (byRound[s.round] = byRound[s.round] || []).push(s);
  }

  const finals = byRound.FINALS && byRound.FINALS[0];
  const championBanner = $("#champion-banner");
  if (finals && finals.completed) {
    const championName = finals.winner_abbr === finals.high_seed_abbr ? finals.high_seed_name : finals.low_seed_name;
    championBanner.classList.remove("hidden");
    championBanner.textContent = `🏆 ${championName} win the championship!`;
  } else {
    championBanner.classList.add("hidden");
  }

  const userTeam = fs.franchise.user_team_abbr;
  const container = $("#bracket-container");
  container.innerHTML = "";
  for (const round of ["ROUND_1", "CONF_SEMIS", "CONF_FINALS", "FINALS"]) {
    const seriesList = byRound[round];
    if (!seriesList) continue;
    const block = document.createElement("div");
    block.className = "bracket-round";
    let html = `<h4>${ROUND_LABELS[round]}</h4>`;
    let lastConf = null;
    for (const s of seriesList) {
      if (s.conference && s.conference !== lastConf) {
        html += `<div class="bracket-conference-label">${s.conference} Conference</div>`;
        lastConf = s.conference;
      }
      const highEliminated = s.completed && s.winner_abbr !== s.high_seed_abbr;
      const lowEliminated = s.completed && s.winner_abbr !== s.low_seed_abbr;
      const highCls = `bracket-team ${s.winner_abbr === s.high_seed_abbr ? "winner" : ""} ${highEliminated ? "eliminated" : ""} ${s.high_seed_abbr === userTeam ? "user-team" : ""}`;
      const lowCls = `bracket-team ${s.winner_abbr === s.low_seed_abbr ? "winner" : ""} ${lowEliminated ? "eliminated" : ""} ${s.low_seed_abbr === userTeam ? "user-team" : ""}`;
      html += `
        <div class="bracket-series">
          <span class="${highCls}">${s.high_seed_name}</span>
          <span class="bracket-score">${s.completed ? `${s.high_seed_wins}-${s.low_seed_wins}` : "vs"}</span>
          <span class="${lowCls}">${s.low_seed_name}</span>
        </div>`;
    }
    block.innerHTML = html;
    container.appendChild(block);
  }
}

$("#btn-sim-next-round").addEventListener("click", async () => {
  showLoading("Simulating the next playoff round...");
  try {
    await api(`/api/franchises/${state.franchiseId}/playoffs/sim_next_round`, { method: "POST" });
    await refreshFranchiseState();
    await renderPlayoffView();
  } catch (e) {
    $("#playoff-error").textContent = e.message;
  } finally {
    hideLoading();
  }
});

async function showAwardsModal() {
  const awards = await api(`/api/franchises/${state.franchiseId}/awards`);
  const offenseListHtml = (players) =>
    players
      .map(
        (p) =>
          `<div>${p.name} <span class="award-player-team">(${p.team_abbr})</span> — ${fmt1(p.ppg)}/${fmt1(p.rpg)}/${fmt1(p.apg)}</div>`
      )
      .join("");
  const defenseListHtml = (players) =>
    players
      .map(
        (p) =>
          `<div>${p.name} <span class="award-player-team">(${p.team_abbr})</span> — ${fmt1(p.spg)} SPG · ${fmt1(p.bpg)} BPG</div>`
      )
      .join("");

  const mvp = awards.mvp;
  $("#awards-content").innerHTML = `
    <div class="award-block">
      <h4>Most Valuable Player</h4>
      <div class="award-mvp">
        ${mvp.name} (${mvp.team_abbr})
        <span class="award-line-stats">${fmt1(mvp.ppg)} PPG · ${fmt1(mvp.rpg)} RPG · ${fmt1(mvp.apg)} APG</span>
      </div>
    </div>
    <div class="award-block"><h4>All-NBA First Team</h4><div class="award-team-list">${offenseListHtml(awards.all_nba_1st)}</div></div>
    <div class="award-block"><h4>All-NBA Second Team</h4><div class="award-team-list">${offenseListHtml(awards.all_nba_2nd)}</div></div>
    <div class="award-block"><h4>All-NBA Third Team</h4><div class="award-team-list">${offenseListHtml(awards.all_nba_3rd)}</div></div>
    <div class="award-block"><h4>All-Defensive First Team</h4><div class="award-team-list">${defenseListHtml(awards.all_defensive_1st)}</div></div>
    <div class="award-block"><h4>All-Defensive Second Team</h4><div class="award-team-list">${defenseListHtml(awards.all_defensive_2nd)}</div></div>
  `;
  $("#awards-modal").classList.remove("hidden");
}

$("#btn-close-awards").addEventListener("click", async () => {
  $("#awards-modal").classList.add("hidden");
  if (state.currentTab === "calendar") {
    await renderPlayoffView();
  } else {
    switchTab("calendar");
  }
});

$("#btn-view-awards-again").addEventListener("click", showAwardsModal);

$("#btn-continue-to-offseason").addEventListener("click", renderCalendarTab);

// ---------------------------------------------------------------------------
// Offseason (retirement review -> re-signing/free agency -> new season)
// ---------------------------------------------------------------------------

async function renderOffseasonView() {
  const fs = state.franchiseState;
  const phase = fs.franchise.phase;
  $("#offseason-error").textContent = "";
  $("#draft-error").textContent = "";

  $("#btn-begin-offseason").classList.toggle("hidden", phase !== "offseason");
  $("#btn-start-new-season").classList.toggle("hidden", phase !== "offseason_free_agency");
  $("#draft-board").classList.toggle("hidden", phase !== "offseason_draft");

  $("#offseason-hint").textContent =
    phase === "offseason"
      ? "Begin offseason processing to age up the league, roll retirements, and expire contracts."
      : phase === "offseason_draft"
      ? "Make your picks when you're on the clock, or sim the rest of the draft whenever you're ready to skip ahead."
      : "Head to Front Office to re-sign your own free agents (Bird rights) or sign others, then start the new season when you're ready.";

  const retireesEl = $("#offseason-retirees");
  if (phase === "offseason") {
    retireesEl.innerHTML = "";
  } else {
    const retirees = await api(`/api/franchises/${state.franchiseId}/offseason/retirees`);
    if (retirees.length === 0) {
      retireesEl.innerHTML = `<p class="subtitle">No retirements this offseason.</p>`;
    } else {
      const rows = retirees
        .map(
          (r) => `
        <tr>
          <td>${r.name}</td><td>${r.age}</td><td>${r.team_abbr || "Free Agent"}</td>
          <td>${r.can_undo ? `<button class="secondary" data-undo-slug="${r.slug}">Un-retire</button>` : "—"}</td>
        </tr>`
        )
        .join("");
      retireesEl.innerHTML = `
        <h3>Retirements</h3>
        <table class="data-table">
          <tr><th>Player</th><th>Age</th><th>Last Team</th><th></th></tr>
          ${rows}
        </table>
      `;
      for (const btn of $$("[data-undo-slug]", retireesEl)) {
        btn.addEventListener("click", () => undoRetirement(btn.dataset.undoSlug));
      }
    }
  }

  if (phase === "offseason_draft") {
    await renderDraftBoard();
  }
}

function prospectCard(prospect, { onDraft } = {}) {
  const tpl = $("#player-card-template").content.cloneNode(true);
  const card = tpl.querySelector(".player-card");
  card.dataset.slug = prospect.slug;

  card.querySelector(".player-name").textContent = prospect.name;
  const heightStr = prospect.height_in ? `${Math.floor(prospect.height_in / 12)}'${prospect.height_in % 12}"` : "?";
  card.querySelector(".player-meta").textContent =
    `${prospect.positions.join("/")} · ${heightStr} · ${prospect.weight_lb || "?"}lb · Age ${prospect.age}`;

  const gradesEl = card.querySelector(".player-card-grades");
  const overallChip = document.createElement("span");
  overallChip.className = "grade-chip overall-chip";
  overallChip.innerHTML = `OVR <b>${prospect.overall_rating}</b>`;
  gradesEl.appendChild(overallChip);
  for (const [key, label] of GRADE_CATEGORIES) {
    const chip = document.createElement("span");
    chip.className = "grade-chip";
    chip.innerHTML = `${label} <b>${prospect.grades[key]}</b>`;
    gradesEl.appendChild(chip);
  }

  const actionsEl = card.querySelector(".player-card-actions");
  if (onDraft) {
    const btn = document.createElement("button");
    btn.textContent = "Draft";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      onDraft();
    });
    actionsEl.appendChild(btn);
  }
  return card;
}

async function renderDraftBoard() {
  const board = await api(`/api/franchises/${state.franchiseId}/offseason/draft/board`);
  const userTeam = state.franchiseState.franchise.user_team_abbr;

  $("#draft-status-label").textContent =
    board.pick_index < board.total_picks
      ? `Pick ${board.pick_index + 1} of ${board.total_picks} — On the clock: ${board.on_the_clock}${board.user_turn ? " (you!)" : ""}`
      : "Draft complete";

  const listEl = $("#draft-prospect-list");
  listEl.innerHTML = "";
  if (board.user_turn) {
    for (const p of board.available_prospects) {
      listEl.appendChild(prospectCard(p, { onDraft: () => makeDraftPick(p.slug) }));
    }
  } else if (board.pick_index < board.total_picks) {
    listEl.innerHTML = `<p class="subtitle">Waiting on other teams to pick...</p>`;
  }

  const picksHeading = $("#draft-picks-made-heading");
  const picksTable = $("#draft-picks-made-table");
  if (board.picks_made.length === 0) {
    picksHeading.classList.add("hidden");
    picksTable.innerHTML = "";
  } else {
    picksHeading.classList.remove("hidden");
    const rows = [...board.picks_made]
      .reverse()
      .slice(0, 20)
      .map(
        (p) => `
      <tr class="${p.drafted_by_team_abbr === userTeam ? "user-team" : ""}">
        <td>${p.pick_number}</td><td>${p.drafted_by_team_abbr}</td><td>${p.name}</td>
        <td>${p.positions.join("/")}</td><td>OVR ${p.overall_rating}</td>
      </tr>`
      )
      .join("");
    picksTable.innerHTML = `<tr><th>Pick</th><th>Team</th><th>Player</th><th>Pos</th><th>Rating</th></tr>${rows}`;
  }
}

async function makeDraftPick(slug) {
  showLoading("Making the pick...");
  try {
    await api(`/api/franchises/${state.franchiseId}/offseason/draft/pick`, {
      method: "POST",
      body: JSON.stringify({ prospect_slug: slug }),
    });
    await refreshFranchiseState();
    await renderCalendarTab();
  } catch (e) {
    $("#draft-error").textContent = e.message;
  } finally {
    hideLoading();
  }
}

$("#btn-sim-rest-draft").addEventListener("click", async () => {
  showLoading("Simulating the rest of the draft...");
  try {
    await api(`/api/franchises/${state.franchiseId}/offseason/draft/sim_rest`, { method: "POST" });
    await refreshFranchiseState();
    await renderCalendarTab();
  } catch (e) {
    $("#draft-error").textContent = e.message;
  } finally {
    hideLoading();
  }
});

async function undoRetirement(slug) {
  showLoading("Un-retiring player...");
  try {
    await api(`/api/franchises/${state.franchiseId}/offseason/undo_retirement`, {
      method: "POST",
      body: JSON.stringify({ player_slug: slug }),
    });
    await refreshFranchiseState();
    await renderOffseasonView();
  } catch (e) {
    $("#offseason-error").textContent = e.message;
  } finally {
    hideLoading();
  }
}

$("#btn-begin-offseason").addEventListener("click", async () => {
  showLoading("Processing offseason (aging, retirement, contracts)...");
  try {
    await api(`/api/franchises/${state.franchiseId}/offseason/begin`, { method: "POST" });
    await refreshFranchiseState();
    await renderCalendarTab();
  } catch (e) {
    $("#offseason-error").textContent = e.message;
  } finally {
    hideLoading();
  }
});

$("#btn-start-new-season").addEventListener("click", async () => {
  showLoading("Starting the new season (generating schedule)...");
  try {
    await api(`/api/franchises/${state.franchiseId}/offseason/start_new_season`, { method: "POST" });
    await refreshFranchiseState();
    renderCalendarTab();
  } catch (e) {
    $("#offseason-error").textContent = e.message;
  } finally {
    hideLoading();
  }
});

$("#btn-sim-next-game").addEventListener("click", async () => {
  showLoading("Simming to your next game...");
  try {
    await api(`/api/franchises/${state.franchiseId}/sim/next_game`, { method: "POST" });
    await refreshFranchiseState();
    renderCalendarTab();
  } catch (e) {
    $("#calendar-error").textContent = e.message;
  } finally {
    hideLoading();
  }
});

$("#btn-sim-next-milestone").addEventListener("click", async () => {
  showLoading("Simming to the next milestone (this may take a moment)...");
  try {
    await api(`/api/franchises/${state.franchiseId}/sim/next_milestone`, { method: "POST" });
    await refreshFranchiseState();
    renderCalendarTab();
  } catch (e) {
    $("#calendar-error").textContent = e.message;
  } finally {
    hideLoading();
  }
});

// ---------------------------------------------------------------------------
// Stats & Records tab
// ---------------------------------------------------------------------------

const LEADER_STATS = [
  ["ppg", "Points"],
  ["rpg", "Rebounds"],
  ["apg", "Assists"],
  ["spg", "Steals"],
  ["bpg", "Blocks"],
];

function renderConferenceTable(selector, rows, userTeam) {
  const playoffCutoff = 8;
  const body = rows
    .map(
      (r, i) => `
    <tr class="${r.team_abbr === userTeam ? "user-team" : ""} ${i < playoffCutoff ? "in-playoff-spot" : ""}">
      <td>${i + 1}</td><td>${r.full_name}</td><td>${r.wins}-${r.losses}</td>
    </tr>`
    )
    .join("");
  $(selector).innerHTML = `<tr><th>#</th><th>Team</th><th>Record</th></tr>${body}`;
}

async function renderStatsTab() {
  const fs = state.franchiseState;
  const userTeam = fs.franchise.user_team_abbr;

  const standingsByConf = await api(`/api/franchises/${state.franchiseId}/standings`);
  renderConferenceTable("#standings-table-eastern", standingsByConf.Eastern, userTeam);
  renderConferenceTable("#standings-table-western", standingsByConf.Western, userTeam);

  const teamStats = await api(`/api/franchises/${state.franchiseId}/season_stats`);
  const teamTable = $("#team-season-stats-table");
  if (teamStats.length === 0) {
    teamTable.innerHTML = `<tr><td>No games played yet — sim forward to see season averages.</td></tr>`;
  } else {
    const teamRows = teamStats
      .map(
        (s) => `
      <tr>
        <td>${s.name}</td><td>${s.games_played}</td><td>${fmt1(s.mpg)}</td>
        <td>${fmt1(s.ppg)}</td><td>${fmt1(s.rpg)}</td><td>${fmt1(s.apg)}</td>
        <td>${fmt1(s.spg)}</td><td>${fmt1(s.bpg)}</td>
        <td>${(s.fg_pct * 100).toFixed(1)}%</td><td>${(s.fg3_pct * 100).toFixed(1)}%</td>
      </tr>`
      )
      .join("");
    teamTable.innerHTML = `<tr><th>Player</th><th>GP</th><th>MPG</th><th>PPG</th><th>RPG</th><th>APG</th><th>SPG</th><th>BPG</th><th>FG%</th><th>3P%</th></tr>${teamRows}`;
  }

  const leadersGrid = $("#league-leaders-grid");
  const leaderLists = await Promise.all(
    LEADER_STATS.map(([statKey]) => api(`/api/franchises/${state.franchiseId}/league_leaders?stat=${statKey}&limit=5`))
  );
  leadersGrid.innerHTML = "";
  LEADER_STATS.forEach(([statKey, label], i) => {
    const leaders = leaderLists[i];
    const items = leaders
      .map(
        (p) =>
          `<li class="${p.team_abbr === userTeam ? "is-user-team" : ""}">${p.name} (${p.team_abbr}) — <b>${fmt1(p[statKey])}</b></li>`
      )
      .join("");
    const card = document.createElement("div");
    card.className = "leaders-card";
    card.innerHTML = `<h4>${label} Per Game</h4><ol>${items || "<li>No data yet</li>"}</ol>`;
    leadersGrid.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Front Office tab (free agency)
// ---------------------------------------------------------------------------

async function renderFrontOfficeTab() {
  $("#fa-error").textContent = "";
  const rosterList = $("#fa-roster-list");
  rosterList.innerHTML = "";
  for (const p of state.franchiseState.roster) {
    rosterList.appendChild(
      playerCard(p, {
        actions: [{ label: "Waive", cls: "secondary", onClick: (pl) => waivePlayer(pl.slug) }],
      })
    );
  }

  const pool = await api(`/api/franchises/${state.franchiseId}/free_agents`);
  const userTeam = state.franchiseState.franchise.user_team_abbr;
  const poolList = $("#fa-pool-list");
  poolList.innerHTML = "";
  for (const p of pool) {
    const isBirdRights = p.previous_team_abbr === userTeam;
    poolList.appendChild(
      playerCard(p, {
        badge: isBirdRights ? "Bird Rights" : null,
        actions: [{ label: `Sign (${money(p.salary)})`, onClick: (pl) => signFreeAgent(pl.slug) }],
      })
    );
  }
}

async function waivePlayer(slug) {
  showLoading("Waiving player...");
  try {
    await api(`/api/franchises/${state.franchiseId}/waive`, {
      method: "POST",
      body: JSON.stringify({ player_id: slug }),
    });
    await refreshFranchiseState();
    await renderFrontOfficeTab();
  } catch (e) {
    $("#fa-error").textContent = e.message;
  } finally {
    hideLoading();
  }
}

async function signFreeAgent(slug) {
  showLoading("Signing free agent...");
  try {
    await api(`/api/franchises/${state.franchiseId}/sign`, {
      method: "POST",
      body: JSON.stringify({ free_agent_id: slug }),
    });
    await refreshFranchiseState();
    await renderFrontOfficeTab();
  } catch (e) {
    $("#fa-error").textContent = e.message;
  } finally {
    hideLoading();
  }
}

// ---------------------------------------------------------------------------
// Coaching tab (lineup)
// ---------------------------------------------------------------------------

function renderCoachingTab() {
  const fs = state.franchiseState;
  $("#lineup-error").textContent = "";

  const startersList = $("#starters-list");
  const benchList = $("#bench-list");
  const rosterList = $("#roster-list");
  startersList.innerHTML = "";
  benchList.innerHTML = "";
  rosterList.innerHTML = "";

  for (const slug of fs.starters) {
    startersList.appendChild(playerCard(playerBySlug(slug), { draggable: true }));
  }
  for (const slug of fs.bench_rotation) {
    benchList.appendChild(playerCard(playerBySlug(slug), { draggable: true }));
  }
  const assigned = new Set([...fs.starters, ...fs.bench_rotation]);
  for (const p of fs.roster) {
    if (!assigned.has(p.slug)) rosterList.appendChild(playerCard(p, { draggable: true }));
  }

  setupDropzones();
}

function setupDropzones() {
  for (const zoneEl of $$(".dropzone")) {
    zoneEl.addEventListener("dragover", (e) => {
      e.preventDefault();
      zoneEl.classList.add("drag-over");
    });
    zoneEl.addEventListener("dragleave", () => zoneEl.classList.remove("drag-over"));
    zoneEl.addEventListener("drop", (e) => {
      e.preventDefault();
      zoneEl.classList.remove("drag-over");
      const zone = zoneEl.dataset.zone;
      moveToZone(state.draggedSlug, zone);
    });
  }
}

function moveToZone(slug, zone) {
  const fs = state.franchiseState;
  fs.starters = fs.starters.filter((s) => s !== slug);
  fs.bench_rotation = fs.bench_rotation.filter((s) => s !== slug);
  if (zone === "starters") {
    if (fs.starters.length >= 5) {
      $("#lineup-error").textContent = "Starters already has 5 players — swap one out first.";
      renderCoachingTab();
      return;
    }
    fs.starters.push(slug);
  } else if (zone === "bench") {
    fs.bench_rotation.push(slug);
  }
  renderCoachingTab();
}

$("#btn-save-lineup").addEventListener("click", async () => {
  const fs = state.franchiseState;
  showLoading("Saving lineup...");
  try {
    await api(`/api/franchises/${state.franchiseId}/lineup`, {
      method: "POST",
      body: JSON.stringify({ starter_ids: fs.starters, bench_order: fs.bench_rotation }),
    });
    await refreshFranchiseState();
    renderCoachingTab();
  } catch (e) {
    $("#lineup-error").textContent = e.message;
    await refreshFranchiseState();
    renderCoachingTab();
  } finally {
    hideLoading();
  }
});

loadHub();
