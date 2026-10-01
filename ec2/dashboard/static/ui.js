// Shared pieces of the modals: the shell's behavior, small icons, and Markdown.

const CLOSE_ICON = '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
const CHEVRON = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M3.5 1.5L7 5l-3.5 3.5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const EXT_ICON = '<svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M5 2H2v8h8V7M7 2h3v3M10 2L5.5 6.5"/></svg>';

// Every modal closes from its × button and from a click on the backdrop
// (anywhere outside the dialog box). Esc is the browser's own.
function bindModal(dlg, onClose) {
  const x = dlg.querySelector(".m-close");
  x.innerHTML = CLOSE_ICON;
  x.onclick = () => dlg.close();
  dlg.addEventListener("click", e => {
    if (e.target !== dlg) return;  // clicks inside land on the head, body or foot
    const r = dlg.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dlg.close();
  });
  if (onClose) dlg.addEventListener("close", onClose);
}

// <dl class="stats">: rows are [label, text] (escaped) or [label, null, html] (trusted markup)
const stats = rows => rows.filter(Boolean).map(([k, v, html]) =>
  `<div><dt>${esc(k)}</dt><dd>${html != null ? html : esc(v)}</dd></div>`).join("");

// A collapsed section inside a modal body
const foldSection = (title, html, attrs = "") =>
  `<details class="fold"${attrs}><summary><h3>${CHEVRON}${esc(title)}</h3></summary>${html}</details>`;

// A command or path in a box with a Copy button; `shown` is trusted markup.
const codeRow = (copy, shown, title) =>
  `<div class="coderow"><code>${shown}</code><button type="button" class="btn small" data-copy="${esc(copy)}" title="${esc(title || "Copy")}">Copy</button></div>`;

// Minimal Markdown for the summaries agents write (they become PR descriptions).
// Everything is escaped first; only headings, lists, code, bold and http(s)
// links are then marked up, so the text can't inject markup of its own.
function md(src) {
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  let out = "", para = [], list = [], code = null;
  const flush = () => {
    if (para.length) out += `<p>${para.map(inline).join("<br>")}</p>`;
    if (list.length) out += `<ul>${list.map(i => `<li>${inline(i)}</li>`).join("")}</ul>`;
    para = []; list = [];
  };
  for (const line of String(src || "").split("\n")) {
    let m;
    if (code !== null) {
      if (/^\s*```/.test(line)) { out += `<pre>${esc(code.join("\n"))}</pre>`; code = null; }
      else code.push(line);
    } else if (/^\s*```/.test(line)) { flush(); code = []; }
    else if ((m = /^#{1,6}\s+(.*)$/.exec(line))) { flush(); out += `<h4>${inline(m[1])}</h4>`; }
    else if ((m = /^\s*(?:[-*]|\d+\.)\s+(.*)$/.exec(line))) { if (para.length) flush(); list.push(m[1]); }
    else if (!line.trim()) flush();
    else if (list.length && /^\s/.test(line)) list[list.length - 1] += " " + line.trim();
    else { if (list.length) flush(); para.push(line); }
  }
  if (code !== null) out += `<pre>${esc(code.join("\n"))}</pre>`;
  flush();
  return out;
}
