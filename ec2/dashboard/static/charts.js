/* Sparkline with a hover crosshair + tooltip. series: [{values, color}] over shared times.
   opts.ticks (values) adds labeled gridlines and opts.axis the start/end times, for the
   larger chart in the CPU / memory modal. */
function spark(el, times, series, opts = {}) {
  const W = 300, H = 56, n = times.length;
  if (n < 2) { el.innerHTML = '<div class="note">Collecting samples…</div>'; return; }
  let max = opts.max != null ? opts.max : 0;
  for (const s of series) for (const v of s.values) if (v != null && v > max) max = v;
  if (opts.ref != null) max = Math.max(max, opts.ref * 1.25);
  if (!max) max = 1;
  const t0 = times[0], t1 = times[n - 1];
  const x = t => (t - t0) / (t1 - t0 || 1) * W;
  const y = v => H - 2 - (v / max) * (H - 4);
  let body = `<line x1="0" x2="${W}" y1="${H - 1}" y2="${H - 1}" stroke="var(--axis)" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
  if (opts.ref != null) {
    body += `<line x1="0" x2="${W}" y1="${y(opts.ref)}" y2="${y(opts.ref)}" stroke="var(--muted)" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
  }
  // Gridlines are drawn in the SVG; their labels are HTML on top, since text
  // inside a stretched (preserveAspectRatio="none") SVG would stretch with it.
  const ticks = opts.ticks || [];
  let labels = "";
  for (const v of ticks) {
    body += `<line x1="0" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
    labels += `<span class="yl" style="top:${(y(v) / H * 100).toFixed(1)}%">${esc(opts.fmt(v))}</span>`;
  }
  series.forEach((s, si) => {
    // break the line across gaps (hibernation, restarts)
    let d = "", pen = false;
    for (let i = 0; i < n; i++) {
      const v = s.values[i];
      const gap = i > 0 && times[i] - times[i - 1] > 30;
      if (v == null || gap) pen = false;
      if (v == null) continue;
      d += (pen ? "L" : "M") + x(times[i]).toFixed(1) + " " + y(v).toFixed(1);
      pen = true;
    }
    if (si === 0 && series.length === 1) {
      body += `<path d="${d}V${H - 1}H0Z" fill="${s.color}" opacity="0.1" stroke="none"/>`;
    }
    body += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`;
  });
  body += `<line class="xh" y1="0" y2="${H}" stroke="var(--muted)" stroke-width="1" vector-effect="non-scaling-stroke" visibility="hidden"/>`;
  el.innerHTML = `<div class="plot"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(opts.label || "")}">${body}</svg>${labels}</div>` +
    (opts.axis ? `<div class="xl"><span>${hhmm(t0)}</span><span>${hhmm(t1)}</span></div>` : "") + '<div class="tip"></div>';
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), xh = el.querySelector(".xh");
  svg.onmousemove = e => {
    const r = svg.getBoundingClientRect();
    const tx = t0 + (e.clientX - r.left) / r.width * (t1 - t0);
    let i = 0, best = Infinity;
    for (let j = 0; j < n; j++) { const dd = Math.abs(times[j] - tx); if (dd < best) { best = dd; i = j; } }
    const px = x(times[i]) / W * r.width;
    xh.setAttribute("x1", x(times[i])); xh.setAttribute("x2", x(times[i])); xh.setAttribute("visibility", "visible");
    tip.style.display = "block"; tip.style.left = Math.min(Math.max(px, 50), r.width - 50) + "px";
    tip.innerHTML = hhmm(times[i]) + " · " + series.map(s =>
      (series.length > 1 ? `<i class="key" style="background:${s.color}"></i>` : "") + esc(opts.fmt(s.values[i]))).join("  ");
  };
  svg.onmouseleave = () => { tip.style.display = "none"; xh.setAttribute("visibility", "hidden"); };
}

function meterRow(label, used, total, title) {
  const pct = total ? used / total * 100 : 0;
  const cls = pct >= 90 ? "crit" : pct >= 75 ? "warn" : "";
  return `<div class="mrow" title="${esc(title || "")}"><div class="l"><b>${esc(label)}</b>
    <span>${bytes(used)} / ${bytes(total)}</span></div>
    <div class="meter" role="meter" aria-valuenow="${pct.toFixed(0)}" aria-valuemin="0" aria-valuemax="100" aria-label="${esc(label)}"><i class="${cls}" style="width:${Math.max(pct, 0.5)}%"></i></div></div>`;
}
