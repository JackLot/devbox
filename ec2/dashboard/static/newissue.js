// New issue: the button in the Issues card (or N anywhere on the page) opens a
// form that files an issue labeled agent in one of the runner's repos. One
// text box: the first line is the title, the rest the body.

const newIssueModal = $("newIssueModal");
bindModal(newIssueModal);
const NOTE = $("newIssueNote").textContent;

function openNewIssue() {
  const repos = (last && last.runner && last.runner.repos) || [];
  if (!repos.length || newIssueModal.open) return;
  const pick = $("newIssueRepo").value || localStorage.getItem("newIssueRepo");
  $("newIssueRepo").innerHTML = repos.map(x => `<option value="${esc(x.name)}">${esc(x.name)} (${esc(x.slug)})</option>`).join("");
  if (repos.some(x => x.name === pick)) $("newIssueRepo").value = pick;
  $("newIssueNote").textContent = NOTE;
  newIssueModal.showModal();
  $("newIssueText").focus();
}
$("newIssueBtn").onclick = openNewIssue;

document.addEventListener("keydown", e => {
  if ((e.key !== "n" && e.key !== "N") || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
  if (document.querySelector("dialog[open]") || (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]"))) return;
  e.preventDefault();
  openNewIssue();
});
$("newIssueText").addEventListener("keydown", e => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("newIssueForm").requestSubmit(); }
});

$("newIssueForm").addEventListener("submit", async e => {
  e.preventDefault();
  const [title, ...rest] = $("newIssueText").value.trim().split("\n");
  const repo = $("newIssueRepo").value, btn = $("newIssueSubmit");
  btn.disabled = true; btn.textContent = "Creating…";
  try {
    const r = await fetch("api/issue", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Dashboard": "1" },
      body: JSON.stringify({ repo, title: title.trim(), body: rest.join("\n") }),
    });
    const res = await r.json().catch(() => ({ message: "HTTP " + r.status }));
    if (!r.ok) throw new Error(res.message);
    localStorage.setItem("newIssueRepo", repo);
    $("newIssueText").value = "";
    newIssueModal.close();
  } catch (err) {
    $("newIssueNote").textContent = "Couldn't create the issue: " + err.message;
  }
  btn.disabled = false; btn.textContent = "Create issue";
});
