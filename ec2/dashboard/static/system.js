// System section: CPU / memory / disk tiles, the CPU and memory modal with
// its top processes, listening ports, and the Stop buttons.

// Stop buttons: only for processes the dashboard's own user owns (the server
// can't signal anyone else's), including the dashboard itself.
function stopButton(pid, start, user, label) {
  const h = last && last.host;
  if (!h || start == null || user !== h.user) return "";
  return `<button type="button" class="stop" data-pid="${pid}" data-start="${start}" data-label="${esc(label)}" title="Stop pid ${pid} (SIGTERM)">Stop</button>`;
}

document.addEventListener("click", async e => {
  const b = e.target.closest("button.stop");
  if (!b) return;
  const label = b.dataset.label.length > 140 ? b.dataset.label.slice(0, 140) + "…" : b.dataset.label;
  const isDashboard = last && last.host && Number(b.dataset.pid) === last.host.pid;
  const note = isDashboard ? "\n\nThis is the dashboard serving this page; it stops updating until the server is started again." : "";
  if (!confirm(`Stop ${label}?\n\nSends SIGTERM to pid ${b.dataset.pid}.${note}`)) return;
  b.disabled = true;
  try {
    const r = await fetch("api/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Dashboard": "1" },
      body: JSON.stringify({ pid: Number(b.dataset.pid), start: Number(b.dataset.start) }),
    });
    const res = await r.json().catch(() => ({ message: "HTTP " + r.status }));
    if (!r.ok) alert("Couldn't stop it: " + res.message);
  } catch (err) {
    alert("Couldn't reach the dashboard server.");
  }
  setTimeout(poll, 800);
});

// Listening ports: a row click opens that port on this host in a new tab.
// The port number is also a real link, for keyboard and middle-click.
const portUrl = port => `http://${location.hostname}:${port}/`;
$("ports").addEventListener("click", e => {
  const tr = e.target.closest("tr.open");
  if (!tr || e.target.closest("a, button") || String(getSelection())) return;
  window.open(tr.dataset.url, "_blank", "noopener");
});

function procTable(rows, key) {
  if (!rows || !rows.length) return '<div class="note">Collecting samples…</div>';
  const max = Math.max(...rows.map(r => r[key] || 0)) || 1;
  // Just the sorted metric and the command; pid, user and age are in the row's tooltip.
  return `<table class="tbl">
    <thead><tr><th class="num" style="width:112px">${key === "cpu" ? "CPU" : "Memory"}</th><th>Command</th><th style="width:52px"></th></tr></thead><tbody>` +
    rows.map(r => {
      const val = key === "cpu" ? (r.cpu == null ? "–" : r.cpu.toFixed(1) + "%") : bytes(r.rss, 0);
      return `<tr title="${esc(`pid ${r.pid} · ${r.user} · running ${dur(r.age)}\n${r.cmd}`)}">
        <td class="num"><span class="bar" style="width:${Math.max(1, (r[key] || 0) / max * 40)}px"></span>${val}</td>
        <td class="cmd">${esc(r.cmd)}</td>
        <td class="num">${stopButton(r.pid, r.start, r.user, r.cmd)}</td></tr>`;
    }).join("") + "</tbody></table>";
}

// What the CPU and memory tiles and their modal both show.
const pctFmt = v => v == null ? "–" : v.toFixed(0) + "%";
// Swap only gets a mention when some is in use (the hibernation swapfile never counts)
const swapUsed = d => (d.swap || []).filter(s => !s.role.startsWith("hibernation")).reduce((a, s) => a + (s.used || 0), 0);
function metric(d, kind) {
  const col = i => d.history.rows.map(r => r[i]);
  if (kind === "cpu") {
    return { title: "CPU", value: pctFmt(d.cpu.percent), values: col(1), label: "CPU percent, last hour",
      sub: `load ${d.cpu.load[0].toFixed(2)} · ${d.host.nproc} vCPU`,
      detail: `load ${d.cpu.load.map(l => l.toFixed(2)).join(" · ")} (1, 5, 15 min) on ${d.host.nproc} vCPU`,
      procs: d.processes.top_cpu, key: "cpu" };
  }
  const m = d.memory, swap = swapUsed(d);
  const sub = bytes(m.used) + " of " + bytes(m.total) + (swap ? " · swap " + bytes(swap) : "");
  return { title: "Memory", value: pctFmt(m.used / m.total * 100), values: col(3), label: "Memory used percent, last hour",
    sub, detail: sub, procs: d.processes.top_mem, key: "rss" };
}

// CPU / memory modal: the tile's number and chart at full size, then the
// processes using the most of it. Re-rendered on every poll while open.
const metricModal = $("metricModal");
let metricOpen = null;  // "cpu" or "mem"
function openMetric(kind) {
  metricOpen = kind;
  renderMetric();
  if (!metricModal.open) metricModal.showModal();
}
function renderMetric() {
  if (!metricOpen || !last) return;
  const m = metric(last, metricOpen);
  $("metricTitle").textContent = m.title;
  $("metricV").textContent = m.value;
  $("metricS").textContent = m.detail;
  spark($("metricC"), last.history.rows.map(r => r[0]), [{ values: m.values, color: "var(--s1)" }],
    { max: 100, ticks: [50, 100], axis: true, fmt: pctFmt, label: m.label });
  // Leave the table alone while the pointer is on it, so a Stop button doesn't move under a click
  if (!$("metricProcs").matches(":hover")) $("metricProcs").innerHTML = procTable(m.procs, m.key);
}
bindModal(metricModal, () => { metricOpen = null; });
document.querySelectorAll("[data-metric]").forEach(tile => {
  tile.onclick = () => openMetric(tile.dataset.metric);
  tile.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openMetric(tile.dataset.metric); } };
});

function renderSystem(d) {
  const T = d.history.rows.map(r => r[0]);
  for (const kind of ["cpu", "mem"]) {
    const m = metric(d, kind);
    $(kind + "V").textContent = m.value;
    $(kind + "S").textContent = m.sub;
    spark($(kind + "C"), T, [{ values: m.values, color: "var(--s1)" }], { max: 100, fmt: pctFmt, label: m.label });
  }
  renderMetric();

  // The headline is the fullest disk; every disk gets a meter underneath.
  const disks = d.disks || [], pct = x => x.total ? x.used / x.total * 100 : 0;
  const full = disks.reduce((a, x) => !a || pct(x) > pct(a) ? x : a, null);
  $("diskV").textContent = full ? pct(full).toFixed(0) + "%" : "–";
  $("diskS").textContent = full ? `${bytes(full.total - full.used)} free on ${full.mount}` : "No disks found";
  $("disks").innerHTML = disks.map(x => meterRow(x.mount, x.used, x.total, `${x.device} · ${x.fstype}`)).join("");

  $("ports").innerHTML = (d.ports && d.ports.length) ? `<table class="tbl">
    <thead><tr><th class="num" style="width:64px">Port</th><th>Process</th><th style="width:52px"></th></tr></thead><tbody>` +
    d.ports.map(p => `<tr class="open" data-url="${portUrl(p.port)}" title="${esc(`Open ${portUrl(p.port)} in a new tab\nListening on ${p.addr}${p.pid ? " · pid " + p.pid : ""}${p.user ? " · " + p.user : ""}`)}">
      <td class="num"><a href="${portUrl(p.port)}" target="_blank" rel="noopener">${p.port}</a></td>
      <td class="cmd">${p.cmd ? esc(p.cmd) : '<span class="dim">owned by another user</span>'}</td>
      <td class="num">${p.pid ? stopButton(p.pid, p.start, p.user, `${p.cmd} (port ${p.port})`) : ""}</td></tr>`).join("") +
    "</tbody></table>" : '<div class="note">None</div>';
}
