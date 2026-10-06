// "shell": the turn is over but a background shell command it started is still running
const STATUS = { busy: "Working", waiting: "Needs input", idle: "Idle", shell: "Idle", stopped: "Stopped" };

// Colored dot + written label, so status never relies on color alone.
function sessionChip(s, now) {
  let label = STATUS[s.status] || s.status;
  if (["idle", "shell", "stopped"].includes(s.status) && s.status_since) label += ` (${dur(now - s.status_since)})`;
  const dot = s.status === "shell" ? "idle" : s.status;
  const note = s.status === "shell" ? '<span class="note-inline">shell running</span>' : "";
  return `<span class="chip"><span class="dot ${esc(dot)}" aria-hidden="true"></span>${esc(label)}${note}</span>`;
}

const sessionTitle = s => s.title || (s.prompt ? s.prompt.slice(0, 120) : s.name || "session " + s.pid);

// PRs the session opened, as "learn-git-app PR#51": a chat's PR can be in
// another repo than the one it runs in.
const sessionPrLink = pr => `<a href="${esc(pr.url)}" target="_blank" rel="noopener" title="${esc(pr.repo)}#${pr.number}">${esc(pr.repo.split("/")[1])} PR#${pr.number}</a>`;
const sessionPrButton = pr => `<a class="btn primary" href="${esc(pr.url)}" target="_blank" rel="noopener">${esc(pr.repo.split("/")[1])} PR#${pr.number} ${EXT_ICON}</a>`;

// A session row opens its live log. Closes the opening tag's class attribute.
const logAttrs = s => s.session_id
  ? ` open-log" data-sid="${esc(s.session_id)}" role="button" tabindex="0" aria-haspopup="dialog" title="Watch this session's log"`
  : '"';

// Live log modal: follows the session's transcript, polling for what was
// appended since the last byte offset. Claude Code writes a line per finished
// block, so text arrives a block at a time, not token by token.
const slogModal = $("slogModal");
let slog = null;  // {sid, offset, timer, busy}
function openSessionLog(sid) {
  if (slog) clearInterval(slog.timer);
  slog = { sid, offset: -1, busy: false };
  $("slog").innerHTML = "";
  $("slogNote").textContent = "Loading…";
  $("slogStop").dataset.html = $("slogStop").innerHTML = "";
  $("slogPrs").dataset.html = $("slogPrs").innerHTML = "";
  slogHead();
  slogModal.showModal();
  fetchSessionLog();
  slog.timer = setInterval(fetchSessionLog, 1500);
}
// Head: status, then where the session runs, over its title.
function slogHead() {
  const s = slog && ((last && last.claude) || []).find(x => x.session_id === slog.sid);
  if (!s) return;
  $("slogTitle").textContent = sessionTitle(s);
  const where = home(s.cwd) + (s.branch ? " · " + s.branch : "");
  const html = sessionChip(s, Date.now() / 1000) + `<span class="mono" title="${esc(s.cwd || "")}">${esc(where)}</span>`;
  if ($("slogKicker").dataset.html !== html) { $("slogKicker").dataset.html = html; $("slogKicker").innerHTML = html; }
  const stop = s.status === "stopped" ? "" : stopButton(s.pid, s.start, last.host.user, "Claude session “" + sessionTitle(s) + "”");
  if ($("slogStop").dataset.html !== stop) { $("slogStop").dataset.html = stop; $("slogStop").innerHTML = stop; }
  const prs = (s.prs || []).map(sessionPrButton).join("");
  if ($("slogPrs").dataset.html !== prs) { $("slogPrs").dataset.html = prs; $("slogPrs").innerHTML = prs; }
}
bindModal(slogModal, () => { if (slog) clearInterval(slog.timer); slog = null; });

async function fetchSessionLog() {
  const cur = slog;
  if (!cur || cur.busy || document.hidden) return;
  cur.busy = true;
  try {
    for (let i = 0; i < 20 && slog === cur; i++) {  // catch up on a burst, a step at a time
      const r = await fetch(`api/session-log?id=${encodeURIComponent(cur.sid)}&from=${cur.offset}`,
        { cache: "no-store", headers: { "X-Dashboard": "1" } });
      const d = await r.json().catch(() => ({ message: "HTTP " + r.status }));
      if (slog !== cur) return;
      if (!r.ok) { $("slogNote").textContent = "Can't load the log: " + d.message; return; }
      const el = $("slog");
      const atBottom = cur.offset < 0 || el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      el.insertAdjacentHTML("beforeend", d.events.map(logEvent).join(""));
      cur.offset = d.offset;
      if (atBottom) el.scrollTop = el.scrollHeight;
      $("slogNote").textContent = "Live · updates every few seconds, one message or tool call at a time";
      if (!d.more) break;
    }
  } catch (e) {
    if (slog === cur) $("slogNote").textContent = "Can't reach the dashboard server.";
  } finally {
    cur.busy = false;
  }
}

const hms = t => { const d = new Date(t); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
// Long text folds to its first lines; click to expand.
function fold(text, lines, cls) {
  const all = text.replace(/\s+$/, "").split("\n");
  if (all.length <= lines) return `<div class="${cls}">${esc(all.join("\n"))}</div>`;
  return `<details class="${cls}"><summary>${esc(all.slice(0, lines).join("\n"))}\n<span class="more">… ${all.length - lines} more lines</span></summary>${esc(all.slice(lines).join("\n"))}</details>`;
}
// One row per event: the time in a narrow left column, the content beside it.
// Prompts stand out as a tinted band, replies read as prose (rendered Markdown),
// and tool calls and their output stay monospace, with the output set off by a rule.
function logEvent(e) {
  const row = (cls, html, time = true) => `<div class="ev ${cls}"><span class="t">${time ? hms(e.t) : ""}</span><div class="c">${html}</div></div>`;
  if (e.kind === "user") return row("user", esc(e.text));
  if (e.kind === "text") return row("text", `<div class="prose">${md(e.text)}</div>`);
  if (e.kind === "tool") {
    const cmd = e.cmd && e.cmd !== e.text ? `<div class="cmdline">$ ${esc(e.cmd)}</div>` : "";
    return row("tool", `<b>${esc(e.tool)}</b> ${esc(e.text)}${cmd}`);
  }
  if (e.kind === "result") {
    const text = (e.text || "(no output)") + (e.cut ? "\n[truncated]" : "");
    return row("", fold(text, 4, "res" + (e.error ? " err" : "")), false);
  }
  if (e.kind === "thinking") return row("", e.text ? fold(e.text, 2, "think") : '<div class="think">thinking…</div>', !e.text);
  return "";
}

$("claude").addEventListener("click", e => {
  const row = e.target.closest(".open-log");
  if (!row || e.target.closest("a, button") || String(getSelection())) return;
  openSessionLog(row.dataset.sid);
});
$("claude").addEventListener("keydown", e => {
  const row = e.target.closest(".open-log");
  if (row && e.target === row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openSessionLog(row.dataset.sid); }
});

const words = s => String(s).replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").replace(/\s*dialog$/i, "").toLowerCase();

// One line of what the session is doing or last said, like `claude agents`.
function sessionDetail(s) {
  if (s.status === "busy" && s.action) return (s.action.tool || "") + (s.action.detail ? " " + s.action.detail : "");
  if (s.status === "waiting" && s.waiting_for) return "waiting on " + words(s.waiting_for);
  if (s.status === "stopped") return "process exited";
  return s.reply || "";
}

// One row per session: what it's about, then its status and what it's doing
// or last said. The directory and how long it's been in that status sit on the right.
function renderClaude(d) {
  const list = d.claude || [];
  $("claudeCard").hidden = false;
  const now = Date.now() / 1000;
  const n = st => list.filter(s => s.status === st || (st === "idle" && s.status === "shell")).length;
  $("claudeCounts").innerHTML = [["busy", "working"], ["waiting", "need input"], ["idle", "idle"], ["stopped", "stopped"]]
    .map(([st, word]) => n(st) ? `<span class="${st}">${n(st)} ${word}</span>` : "").filter(Boolean).join(" ");
  slogHead();
  if (!list.length) { $("claude").innerHTML = '<div class="note">No sessions running</div>'; return; }
  $("claude").innerHTML = '<div class="rows">' + list.map(s => {
    const title = sessionTitle(s);
    const status = STATUS[s.status] || s.status;
    const detail = sessionDetail(s) || (s.status === "shell" ? "shell running" : "");
    const where = home(s.cwd) + (s.branch ? " · " + s.branch : "");
    return `<div class="sess${logAttrs(s)}>
      <span class="dot ${esc(s.status === "shell" ? "idle" : s.status)}" aria-hidden="true"></span>
      <div class="body">
        <div class="ttl" title="${esc(title)}">${esc(title)}</div>
        <div class="d" title="${esc(detail)}"><b>${esc(status)}</b>${detail ? " · " + esc(detail) : ""}</div>
      </div>
      ${s.prs && s.prs.length ? `<span class="side">${s.prs.map(sessionPrLink).join(" ")}</span>` : ""}
      <span class="where" title="${esc(s.cwd + (s.branch ? "\nBranch " + s.branch : "") + "\npid " + s.pid)}">${esc(where)}</span>
      <span class="age">${s.status_since ? dur(now - s.status_since) : ""}</span>
      ${s.status === "stopped" ? "" : stopButton(s.pid, s.start, last.host.user, "Claude session “" + title + "”")}
    </div>`;
  }).join("") + "</div>";
}
