const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function bytes(n, d = 1) {
  if (n == null) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(i === 0 ? 0 : d) + " " + u[i];
}
// Durations are minute-granular so the page stays still between polls; only
// the two live counters (next idle check, Claude heartbeat) use durSec.
function dur(s) {
  if (s == null) return "–";
  s = Math.max(0, s);
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  if (d) return d + "d " + h + "h";
  if (h) return h + "h " + m + "m";
  return m ? m + "m" : "<1m";
}
function durSec(s) {
  if (s == null) return "–";
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), sec = s % 60;
  if (s >= 3600) return dur(s);
  return m ? m + "m " + String(sec).padStart(2, "0") + "s" : sec + "s";
}
const clock = t => t == null ? "–" : new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const hhmm = t => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

// Theme toggle: auto -> light -> dark
const themes = ["auto", "light", "dark"];
let theme = "auto";
try { theme = localStorage.getItem("dash-theme") || "auto"; } catch (e) {}
function applyTheme() {
  if (theme === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  $("theme").textContent = theme[0].toUpperCase() + theme.slice(1);
  $("theme").title = "Theme: " + theme + " (click to switch)";
}
$("theme").onclick = () => {
  theme = themes[(themes.indexOf(theme) + 1) % 3]; applyTheme();
  try { localStorage.setItem("dash-theme", theme); } catch (e) {}
};
applyTheme();

// Status icons: shape + label, never color alone
const ICON = {
  good: '<svg width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="6" fill="var(--good)"/><path d="M4 7.2l2 2 4-4.2" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  warning: '<svg width="14" height="14" viewBox="0 0 14 14"><path d="M7 1l6.2 11H.8z" fill="var(--warning)"/><path d="M7 5v3.2" stroke="#0b0b0b" stroke-width="1.6" stroke-linecap="round"/><circle cx="7" cy="10.2" r=".9" fill="#0b0b0b"/></svg>',
  off: '<svg width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--muted)" stroke-width="1.6"/><path d="M4 10l6-6" stroke="var(--muted)" stroke-width="1.6"/></svg>',
};

// The latest /api/stats snapshot (set by render in app.js); every file reads it.
let last = null, lastFetch = 0;

const home = p => p ? p.replace(/^\/home\/[^/]+(?=\/|$)/, "~") : "–";

// navigator.clipboard only exists on https/localhost; the dashboard is plain
// http over Tailscale, so fall back to a hidden textarea + execCommand.
// While a modal dialog is open everything outside it is inert, so the textarea
// has to go inside the dialog (`host`) or it can't be selected.
async function copyText(text, host) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) {}
  }
  const ta = document.createElement("textarea");
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
  (host || document.body).appendChild(ta); ta.select(); ta.setSelectionRange(0, text.length);
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) {}
  ta.remove();
  return ok;
}
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  const ok = await copyText(b.dataset.copy, b.closest("dialog"));
  const was = b.innerHTML;
  // The issues table re-renders every poll; the flash only has to last until then.
  b.classList.add("done"); b.textContent = ok ? "Copied" : "Couldn't copy";
  setTimeout(() => { if (b.isConnected) { b.classList.remove("done"); b.innerHTML = was; } }, 1200);
});
