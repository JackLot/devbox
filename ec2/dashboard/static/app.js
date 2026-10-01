// Page-level glue: the tab title and favicon, live counters, render and polling.

// Tab title and favicon lead with whatever needs you, so a background tab
// is readable at a glance: "1 needs input · devbox", "2 working · devbox".
const FAVICON_DOT = { waiting: "#fab219", busy: "#3987e5" };
let tabState = "";
function updateTab(host, sessions) {
  const waiting = sessions.filter(s => s.status === "waiting").length;
  const busy = sessions.filter(s => s.status === "busy").length;
  const lead = waiting ? `${waiting} needs input` : busy ? `${busy} working` : "";
  const dot = waiting ? "waiting" : busy ? "busy" : "";
  const state = lead + "|" + host + "|" + dot;
  if (state === tabState) return;  // don't churn the favicon every poll
  tabState = state;
  document.title = lead ? `${lead} · ${host}` : host;
  $("favicon").href = favicon(FAVICON_DOT[dot]);
}
function favicon(dot) {
  // Dark tile with three rising bars (a small activity chart); a status dot
  // in the corner when a session is working or needs input.
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
    <rect width="32" height="32" rx="7" fill="#1a1a19"/>
    <rect x="7" y="17" width="4" height="8" rx="1.5" fill="#86b6ef"/>
    <rect x="14" y="12" width="4" height="13" rx="1.5" fill="#86b6ef"/>
    <rect x="21" y="7" width="4" height="18" rx="1.5" fill="#86b6ef"/>
    ${dot ? `<circle cx="25" cy="25" r="6.5" fill="${dot}" stroke="#1a1a19" stroke-width="2.5"/>` : ""}
  </svg>`;
  return "data:image/svg+xml," + encodeURIComponent(svg);
}

function tickLive() {
  const idle = last && last.idle, now = Date.now() / 1000;
  const r = last && last.runner;
  if (r) {
    // The schedule is its own span so phones can hide it and show just the countdown
    $("runnerNext").innerHTML = r.next_run ? `next run in ${durSec(r.next_run - now)}<span class="sched"> · ${esc(r.schedule)}</span>`
      : esc(r.schedule ? r.schedule : r.crontab ? "no cron entry" : "cron entry unknown: re-run agent-runner/install.sh");
    const run = r.current ? durSec(now - r.current.started) : "";
    document.querySelectorAll(".liveRun").forEach(el => el.textContent = run);
    if ($("runnerElapsed")) $("runnerElapsed").textContent = run;
  }
  if (!idle) return;
  const next = idle.next_check ? "idle check in " + durSec(idle.next_check - now) : "idle check pending";
  document.querySelectorAll(".liveNext").forEach(el => el.textContent = next);
  if ($("liveBeat")) $("liveBeat").textContent = idle.heartbeat ? durSec(now - idle.heartbeat) + " ago" : "never";
}

function render(d) {
  if (!d || !d.host) return;
  last = d;
  const h = d.host, inst = h.instance || {};
  $("host").textContent = inst.name || h.hostname;
  updateTab(inst.name || h.hostname.split(".")[0], d.claude || []);
  const age = Date.now() / 1000 - d.time;
  // One quiet line; the instance id and architecture are in its tooltip.
  const about = [inst.instance_type, inst.region, "up " + dur(h.uptime - (h.slept || 0))].filter(Boolean).join(" · ");
  const more = [inst.instance_id, `${h.nproc} vCPU`, h.arch].filter(Boolean).join(" · ");
  $("meta").innerHTML = [
    `<span title="${esc(more)}">${esc(about)}</span>`,
    age > 20 ? `<span class="stale">data ${dur(age)} old</span>` : "",
    d.error ? `<span class="stale">sampler error: ${esc(d.error)}</span>` : "",
  ].filter(Boolean).join("");

  renderIdle(d);
  renderClaude(d);
  renderRunner(d);
  renderSystem(d);
}

async function poll() {
  try {
    const r = await fetch("api/stats", { cache: "no-store" });
    render(await r.json());
    lastFetch = Date.now();
  } catch (e) {
    $("meta").innerHTML = '<span class="stale">Can\'t reach the dashboard server (hibernated?)</span>';
  }
}

// Poll only while the tab is visible; tick relative times every second.
let timers = [];
let hibernating = false;  // after "Hibernate now": stay quiet, even on tab refocus
function startPolling() {
  if (hibernating) return;
  stopPolling(); poll().then(pollLog);
  timers = [setInterval(poll, 3000), setInterval(pollLog, 15000), setInterval(tickLive, 1000)];
}
function stopPolling() { timers.forEach(clearInterval); timers = []; }
document.addEventListener("visibilitychange", () => document.hidden ? stopPolling() : startPolling());
startPolling();
