// Agent runner: the run's outcome as the agent reported it ("done" means a PR
// was opened or updated, unless it made no commits; see the issue comment).
const RUN_STATUS = {
  running: ["busy", "Running"], done: ["good", "Done"], needs_human: ["waiting", "Needs you"],
  failed: ["stopped", "Failed"], interrupted: ["stopped", "Interrupted"],
};
function runChip(status) {
  const [dot, label] = RUN_STATUS[status] || ["idle", status || "–"];
  return `<span class="chip"><span class="dot ${dot}" aria-hidden="true"></span>${esc(label)}</span>`;
}
const issueLink = x => {
  const label = `${x.repo}#${x.issue}`;
  return x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(label)}</a>` : esc(label);
};

const BRANCH_ICON = '<svg width="12" height="12" viewBox="0 0 12 12" aria-label="branch" fill="none" stroke="currentColor" stroke-width="1.3"><circle cx="3" cy="2.5" r="1.5"/><circle cx="3" cy="9.5" r="1.5"/><circle cx="9" cy="3.5" r="1.5"/><path d="M3 4v4M9 5c0 2.5-6 1.5-6 3"/></svg>';
const COPY_ICON = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="3.5" y="3.5" width="7" height="7" rx="1.2"/><path d="M8.5 2.2V2a1 1 0 0 0-1-1H2a1 1 0 0 0-1 1v5.5a1 1 0 0 0 1 1h.2"/></svg>';
const logName = p => p ? p.split("/").pop() : "";

// Where an issue is in the runner's label lifecycle (see agent-runner/README.md)
const ISSUE_STATE = {
  wip: ["busy", "Working"], queued: ["queued", "Queued"], needs_human: ["waiting", "Needs you"],
  failed: ["stopped", "Failed"], pr: ["good", "PR to review"], closed: ["idle", "Closed"],
};
// What queued an issue when it wasn't the label on the issue itself
const QUEUED_BY = { label: "Queued by PR label", review: "Queued by code review" };
const stateLabel = x => (x.state === "queued" && QUEUED_BY[x.queued_by]) || (ISSUE_STATE[x.state] || [0, "No agent label"])[1];
function issueChip(x) {
  const dot = (ISSUE_STATE[x.state] || ["idle"])[0], label = stateLabel(x);
  return `<span class="chip"><span class="dot ${dot}" aria-hidden="true"></span>${esc(label)}</span>`;
}
const tag = l => {
  const color = /^[0-9a-f]{6}$/i.test(l.color || "") ? "#" + l.color : "var(--muted)";
  return `<span class="tag"><i style="background:${color}"></i>${esc(l.name)}</span>`;
};

// The PR the runner opened for an issue, as a link: "PR#17", plus "draft" if it is one.
const prLink = (pr, text) => `<a href="${esc(pr.url)}" target="_blank" rel="noopener">${esc(text || "PR#" + pr.number)}</a>` +
  (pr.isDraft ? ' <span class="dim">draft</span>' : "");
const issuePr = x => {
  const r = last && last.runner;
  const i = r && r.issues.find(i => i.repo === x.repo && i.issue === x.issue);
  return i && i.pr;
};

function issueState(x) {
  // "PR#17 to review" in place of the chip's label when the PR is the state
  if (x.state === "pr" && x.pr) {
    return `<span class="chip"><span class="dot good" aria-hidden="true"></span><span>${prLink(x.pr)} to review</span></span>`;
  }
  return issueChip(x) + (x.pr ? " " + prLink(x.pr) : "");
}

// The dashboard's sandbox keeps home read-only, so it can't start a run itself;
// while something is queued, offer the command to start one from a shell instead.
function renderStart(r) {
  const queued = r.issues.filter(x => x.state === "queued").map(x => x.repo + "#" + x.issue);
  const show = queued.length && !r.running;
  $("runnerStart").hidden = !show;
  // Only re-render on change, so a poll doesn't cut the "Copied" flash short
  const html = show ? `<span class="dim">run now with</span> <button type="button" class="copy" data-copy="agent-runner"
    title="${esc("Click to copy, then run it in a shell to start now instead of waiting for the next cron tick\nQueued: " + queued.join(", "))}">agent-runner<span class="cp" aria-hidden="true">${COPY_ICON}</span></button>` : "";
  if ($("runnerStart").dataset.html !== html) { $("runnerStart").dataset.html = html; $("runnerStart").innerHTML = html; }
}

function renderIssues(r, now) {
  const gh = r.github, rows = r.issues;
  $("runnerIssuesNote").hidden = !(gh && gh.error);
  $("runnerIssuesNote").textContent = gh && gh.error ? "Couldn't refresh from GitHub: " + gh.error : "";
  const open = rows.filter(x => x.state !== "closed").length;
  $("runnerCounts").textContent = open ? open + " open" : "";
  // One line per issue: state, title, PR and when it last ran. A row opens the
  // issue modal, which has the rest (labels, worktree, branch, links, last run).
  $("runnerIssues").innerHTML = rows.length ? `<div class="rows">${rows.map(x => {
      const dot = (ISSUE_STATE[x.state] || ["idle"])[0], label = stateLabel(x);
      const state = x.state === "pr" && x.pr ? `${prLink(x.pr)} to review` : esc(label) + (x.pr ? " · " + prLink(x.pr) : "");
      const run = x.last_run;
      return `<div class="irow" data-issue="${esc(issueKey(x))}" role="button" tabindex="0" aria-haspopup="dialog" title="${esc(x.title || "")}">
        <span class="dot ${dot}" aria-hidden="true"></span>
        <div class="body"><div class="ttl"><span class="ref">${esc(issueKey(x))}</span> ${esc(x.title || "")}</div></div>
        <span class="side"><span>${state}</span>${run ? `<span class="dim" title="Last run: ${esc((RUN_STATUS[run.status] || [0, run.status])[1])}">${dur(now - run.started)} ago</span>` : ""}</span></div>`;
    }).join("")}</div>`
    : `<div class="note">${gh ? "No open issues with an agent label. Add <b>agent</b> to an issue to queue it." : "Loading issues from GitHub…"}</div>`;
  renderIssueModal(now);
}

// The repos the runner watches, each a link to file a new issue on GitHub
function renderRepos(r) {
  const repos = r.repos || [];
  $("runnerRepos").hidden = $("newIssueBtn").hidden = !repos.length;
  const html = repos.length ? '<span class="dim">New issue in</span>' + repos.map(x =>
    `<a class="btn small" href="https://github.com/${esc(x.slug)}/issues/new" target="_blank" rel="noopener" title="${esc("Create an issue in " + x.slug)}">${esc(x.name)} ${EXT_ICON}</a>`).join("") : "";
  if ($("runnerRepos").dataset.html !== html) { $("runnerRepos").dataset.html = html; $("runnerRepos").innerHTML = html; }
}

// Issue details: click an issue's title (or its row on phones).
const issueKey = x => `${x.repo}#${x.issue}`;
const issueModal = $("issueModal");
let issueOpen = null;  // key of the issue shown in the modal
function openIssue(key) {
  issueOpen = key;
  renderIssueModal(Date.now() / 1000);
  if (issueOpen && !issueModal.open) issueModal.showModal();
}
// Re-rendered on every poll while open, so state and last run stay current.
function renderIssueModal(now) {
  if (!issueOpen) return;
  const r = last && last.runner;
  const x = r && r.issues.find(x => issueKey(x) === issueOpen);
  if (!x) { if (issueModal.open) issueModal.close(); return; }
  const wt = x.worktree, run = x.last_run;
  $("issueKicker").textContent = issueKey(x);
  // The title links out to the issue on GitHub
  const title = esc(x.title || issueKey(x));
  const head = x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener" title="Open the issue on GitHub">${title} ${EXT_ICON}</a>` : title;
  if ($("issueModalTitle").dataset.html !== head) { $("issueModalTitle").dataset.html = head; $("issueModalTitle").innerHTML = head; }
  // Body, top to bottom: where the issue stands, when it last moved, where
  // its code is, and a prompt for picking it up by hand.
  const state = `<div class="state-row">${issueState(x)}${x.labels && x.labels.length ? `<div class="tags wrap">${x.labels.map(tag).join("")}</div>` : ""}</div>`;
  const facts = `<dl class="stats">${stats([
    ["Last run", null, run ? `${runChip(run.status)} <span class="dim">${dur(now - run.started)} ago</span>` : '<span class="dim">Not run yet</span>'],
    wt && wt.activity && ["Last commit", dur(now - wt.activity) + " ago"],
    x.updated && ["Issue updated", clock(Date.parse(x.updated) / 1000)],
  ])}</dl>`;
  const where = wt ? `<div><h3>Worktree</h3>${codeRow("cd " + wt.path, esc(home(wt.path)), "Copy: cd " + wt.path)}` +
    (wt.branch ? `<div class="branch">${BRANCH_ICON}<span>${esc(wt.branch)}</span></div>` : "") + "</div>" : "";
  const prompt = handoffPrompt(x);
  // The Copy button sits over the prompt's bottom right corner
  const handoff = `<div><h3>Handoff prompt</h3><div class="copybox"><div class="prose plain box">${esc(prompt)}</div>
    <button type="button" class="btn small" data-copy="${esc(prompt)}" title="Copy the prompt, then paste it into a Claude Code session">Copy</button></div></div>`;
  const html = state + facts + where + handoff;
  // The actions sit in the foot: the run's details, then out to GitHub.
  const foot = [
    run ? `<button type="button" class="btn" data-log="${esc(logName(run.log))}">Last run details</button>` : "",
    x.url ? `<a class="btn" href="${esc(x.url)}" target="_blank" rel="noopener">Issue ${EXT_ICON}</a>` : "",
    x.pr ? `<a class="btn primary" href="${esc(x.pr.url)}" target="_blank" rel="noopener">PR#${x.pr.number}${x.pr.isDraft ? " (draft)" : ""} ${EXT_ICON}</a>` : "",
  ].join("");
  // Only re-render on change, so a poll doesn't drop a text selection or cut the "Copied" flash short
  if ($("issueBody").dataset.html !== html) { $("issueBody").dataset.html = html; $("issueBody").innerHTML = html; }
  if ($("issueFoot").dataset.html !== foot) { $("issueFoot").dataset.html = foot; $("issueFoot").innerHTML = foot; }
  $("issueFoot").hidden = !foot;
}
// For picking an issue up by hand in Claude Code after the runner's first pass.
function handoffPrompt(x) {
  const wt = x.worktree;
  const about = [
    `We're working on issue ${issueKey(x)}${x.title ? ` ("${x.title}")` : ""}${x.url ? ": " + x.url : ""}`,
    wt && `Its worktree is ${home(wt.path)}${wt.branch ? `, on branch ${wt.branch}` : ""}; cd there if you aren't already in it.`,
    x.pr && `The agent runner already opened PR #${x.pr.number} for it: ${x.pr.url}`,
  ].filter(Boolean).join("\n");
  return about + "\n\nGet oriented first: read the issue and all of its comments, " +
    (x.pr ? "the PR's description and review comments, " : "any linked PRs, ") +
    "and the commits on this branch (git log / git diff against main), plus RUNNER-AGENTS.md and CLAUDE.md if present. " +
    "Use gh for GitHub. Don't change anything yet: give me a short summary of where things stand, " +
    "then we'll work together on further changes for this issue.";
}
bindModal(issueModal, () => { issueOpen = null; });
issueModal.addEventListener("click", e => {
  const b = e.target.closest("[data-log]");
  if (b) openRun(b.dataset.log);
});
$("runnerIssues").addEventListener("click", e => {
  const el = e.target.closest("[data-issue]");
  if (el && !e.target.closest("a, button")) openIssue(el.dataset.issue);
});
$("runnerIssues").addEventListener("keydown", e => {
  const el = e.target.closest("[data-issue]");
  if (el && e.target === el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openIssue(el.dataset.issue); }
});

// Run details: click a recent run (or an issue's last run).
const runModal = $("runModal");
let runReq = 0;
async function openRun(name) {
  const r = last && last.runner;
  const x = r && r.runs.find(x => logName(x.log) === name);
  if (!x) return;
  const req = ++runReq;
  // Head: the outcome and which issue, over the issue's title.
  $("runKicker").innerHTML = `${runChip(x.status)}<span>Run for ${issueLink(x)}</span>`;
  $("runModalTitle").textContent = x.title || `${x.repo}#${x.issue}`;
  $("runBody").innerHTML = '<div class="note">Loading…</div>';
  $("runFoot").hidden = true;
  if (!runModal.open) runModal.showModal();
  let d;
  try {
    const res = await fetch("api/runner/run?log=" + encodeURIComponent(name), { cache: "no-store", headers: { "X-Dashboard": "1" } });
    d = await res.json();
    if (!res.ok) throw new Error(d.message || "HTTP " + res.status);
  } catch (err) {
    if (req === runReq) $("runBody").innerHTML = `<div class="note">Couldn't load the run: ${esc(err.message)}</div>`;
    return;
  }
  if (req !== runReq) return;
  const wt = `${r.home}/worktrees/${x.repo}-${x.issue}`;
  const s = x.session, pr = issuePr(x);
  const resume = d.session_id && `cd ${home(wt)} && claude --resume ${d.session_id}`;
  const facts = [
    ["Started", clock(x.started)],
    ["Took", x.ended ? dur(x.ended - x.started) : x.status === "running" ? durSec(Date.now() / 1000 - x.started) + " so far" : "–"],
    x.cost != null && ["Cost", null, "$" + x.cost.toFixed(2) + (x.turns ? ` <span class="dim">${x.turns} turns</span>` : "")],
    d.models.length && ["Model", d.models.join(", ")],
    s && ["Now", `${STATUS[s.status] || s.status}${sessionDetail(s) ? " · " + sessionDetail(s) : ""}`],
  ];
  const section = (title, html) => `<div><h3>${esc(title)}</h3>${html}</div>`;
  let raw = d.raw;
  try { raw = JSON.stringify(JSON.parse(raw), null, 2); } catch (e) {}
  // Body, top to bottom: the numbers, what the agent needs or did (its question
  // first, when it has one), how to resume it, and the logs folded away.
  $("runBody").innerHTML =
    `<dl class="stats">${stats(facts)}</dl>` +
    (!d.size ? '<div class="note">The log is written when the run ends.</div>' : "") +
    (d.question ? `<div class="callout"><h3>Question for you</h3><div class="prose">${md(d.question)}</div></div>` : "") +
    (d.summary ? section("Summary", `<div class="prose">${md(d.summary)}</div>`) : "") +
    (d.decisions.length ? section("Decisions", `<div class="prose"><ul>${d.decisions.map(t => `<li>${mdInline(t)}</li>`).join("")}</ul></div>`) : "") +
    (d.result ? section("Result", `<div class="prose">${md(d.result)}</div>`) : "") +
    (d.denials.length ? section(`Permission denials (${d.denials.length})`, `<div class="prose"><ul>${d.denials.map(p => `<li><b>${esc(p.tool)}</b> ${esc(p.detail)}</li>`).join("")}</ul></div>`) : "") +
    (resume ? section("Resume this session", codeRow(resume, esc(resume), "Copy the resume command")) : "") +
    (d.cron.length ? foldSection("cron.log", `<pre class="log">${d.cron.map(esc).join("\n")}</pre>`) : "") +
    (d.size ? foldSection("Raw log" + (d.truncated ? " (first " + bytes(d.raw.length) + ")" : ""),
      `<pre class="log">${esc(raw)}</pre><div class="note">${esc(home(d.log))} · ${bytes(d.size)}</div>`) : "");
  const foot = [
    x.url ? `<a class="btn" href="${esc(x.url)}" target="_blank" rel="noopener">Issue ${EXT_ICON}</a>` : "",
    pr ? `<a class="btn primary" href="${esc(pr.url)}" target="_blank" rel="noopener">PR#${pr.number}${pr.isDraft ? " (draft)" : ""} ${EXT_ICON}</a>` : "",
  ].join("");
  $("runFoot").innerHTML = foot;
  $("runFoot").hidden = !foot;
}
document.addEventListener("click", e => {
  const row = e.target.closest("#runnerCard [data-log]");
  if (!row || e.target.closest("a, button")) return;
  openRun(row.dataset.log);
});
document.addEventListener("keydown", e => {
  const row = e.target.closest && e.target.closest("#runnerCard [data-log]");
  if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openRun(row.dataset.log); }
});
$("runnerLogFold").ontoggle = () => { if ($("runnerLogFold").open) $("runnerLog").scrollTop = $("runnerLog").scrollHeight; };
bindModal(runModal);

function renderRunner(d) {
  const r = d.runner;
  $("runnerCard").hidden = !r;
  if (!r) return;
  const now = Date.now() / 1000, cur = r.current;

  // The "now" strip only shows while a run is going; idle is the quiet default.
  $("runnerNow").hidden = !(cur || r.running);
  if (cur) {
    const s = cur.session;
    const detail = s ? `${STATUS[s.status] || s.status}${sessionDetail(s) ? " · " + sessionDetail(s) : ""}` : "";
    $("runnerNow").innerHTML = `${runChip("running")}<span class="sep">•</span>${issueLink(cur)}
      <span class="ttl" title="${esc(cur.title || "")}">${esc(cur.title || "")}</span>
      <span class="d" title="${esc(detail)}">${detail ? "· " + esc(detail) : ""}</span>
      <span class="dim" id="runnerElapsed"></span>`;
  } else if (r.running) {
    $("runnerNow").innerHTML = `${runChip("running")}<span class="d">checking for issues labeled <b>agent</b></span>`;
  }

  renderIssues(r, now);
  renderStart(r);
  renderRepos(r);

  // Widths sit on the header cells, not a <colgroup>, so the "wide" columns
  // can be hidden on narrow screens without shifting the others.
  $("runnerRuns").innerHTML = r.runs.length ? `<table class="tbl runs">
    <thead><tr><th style="width:112px">Outcome</th><th>Issue</th><th class="wide" style="width:128px">Started</th><th class="num wide" style="width:72px">Took</th><th class="num wide" style="width:64px">Cost</th></tr></thead><tbody>` +
    r.runs.map(x => `<tr tabindex="0" data-log="${esc(logName(x.log))}" title="${esc(x.summary || "Show run details")}">
      <td>${runChip(x.status)}</td>
      <td>${issueLink(x)} ${esc(x.title || "")}</td>
      <td class="wide">${clock(x.started)}</td>
      <td class="num wide">${x.ended ? dur(x.ended - x.started) : x.status === "running" ? '<span class="liveRun"></span>' : "–"}</td>
      <td class="num wide">${x.cost != null ? "$" + x.cost.toFixed(2) : "–"}</td></tr>`).join("") +
    "</tbody></table>" : '<div class="note">No runs yet</div>';

  const el = $("runnerLog");
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  el.innerHTML = r.log.lines.map(l => {
    const m = /^\[(\d{4}-\d\d-\d\d) (\d\d:\d\d):\d\d\] (.*)$/.exec(l);
    if (!m) return `<span class="t">${esc(l)}</span>`;
    const cls = /^(Picking up|PR:|Failed|Needs human|No commits|Error|Replied)/.test(m[3]) ? ' class="hi"' : "";
    return `<span class="t">${m[1].slice(5)} ${m[2]}</span>  <span${cls}>${esc(m[3])}</span>`;
  }).join("\n");
  $("runnerLogNote").textContent = r.log.available ? r.log.path + " · newest last" : r.log.path + " not found yet";
  if (atBottom) el.scrollTop = el.scrollHeight;
  tickLive();
}
