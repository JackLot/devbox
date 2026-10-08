// New issue: the button in the Issues card (or N anywhere on the page) opens a
// form that files an issue labeled agent in one of the runner's repos.

const newIssueModal = $("newIssueModal");
bindModal(newIssueModal);
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
if (isMac) $("newIssueKey").textContent = "⌘ ↵";

let newIssueRepo = localStorage.getItem("newIssueRepo");

function pickRepo(name) {
  newIssueRepo = name;
  for (const b of $("newIssueRepo").children) b.setAttribute("aria-checked", b.dataset.repo === name);
}

function openNewIssue() {
  const repos = (last && last.runner && last.runner.repos) || [];
  if (!repos.length || newIssueModal.open) return;
  // Alt+1..9 picks a repo even while typing in the title; plain digits work off the text fields.
  $("newIssueRepo").innerHTML = repos.map((x, i) =>
    `<button class="btn small" type="button" role="radio" data-repo="${esc(x.name)}" title="${esc(x.slug)}">${esc(x.name)}` +
    (i < 9 ? ` <kbd>${isMac ? "⌥" : "Alt "}${i + 1}</kbd>` : "") + `</button>`).join("");
  pickRepo(repos.some(x => x.name === newIssueRepo) ? newIssueRepo : repos[0].name);
  $("newIssueNote").hidden = true;
  newIssueModal.showModal();
  $("newIssueName").focus();
}
$("newIssueBtn").onclick = openNewIssue;
$("newIssueRepo").onclick = e => { const b = e.target.closest("[data-repo]"); if (b) pickRepo(b.dataset.repo); };

document.addEventListener("keydown", e => {
  if ((e.key !== "n" && e.key !== "N") || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
  if (document.querySelector("dialog[open]") || (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]"))) return;
  e.preventDefault();
  openNewIssue();
});
$("newIssueForm").addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("newIssueForm").requestSubmit(); return; }
  // e.code, since Option+digit on a Mac types a symbol (¡ ™ £ …) into e.key
  const d = /^Digit([1-9])$/.exec(e.code);
  if (!d || e.ctrlKey || e.metaKey || (!e.altKey && e.target.closest("input, textarea"))) return;
  const b = $("newIssueRepo").children[d[1] - 1];
  if (b) { e.preventDefault(); pickRepo(b.dataset.repo); }
});

$("newIssueForm").addEventListener("submit", async e => {
  e.preventDefault();
  const repo = newIssueRepo, btn = $("newIssueSubmit"), label = btn.innerHTML;
  btn.disabled = true; btn.textContent = "Creating…";
  try {
    const r = await fetch("api/issue", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Dashboard": "1" },
      body: JSON.stringify({ repo, title: $("newIssueName").value.trim(), body: $("newIssueText").value }),
    });
    const res = await r.json().catch(() => ({ message: "HTTP " + r.status }));
    if (!r.ok) throw new Error(res.message);
    localStorage.setItem("newIssueRepo", repo);
    $("newIssueName").value = $("newIssueText").value = "";
    newIssueModal.close();
  } catch (err) {
    $("newIssueNote").textContent = "Couldn't create the issue: " + err.message;
    $("newIssueNote").hidden = false;
  }
  btn.disabled = false; btn.innerHTML = label;
});
