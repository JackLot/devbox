// Auto-hibernate: the pill in the page header and its modal (countdown, a few
// facts, the idle checker's log, and Hibernate now).

const hibModal = $("hibModal");
bindModal(hibModal);
$("hibCard").onclick = () => hibModal.showModal();
$("hibLogFold").ontoggle = () => { if ($("hibLogFold").open) $("log").scrollTop = $("log").scrollHeight; };

function renderIdle(d) {
  const idle = d.idle, host = d.host;
  $("hibCard").hidden = !idle;
  if (!idle) { if (hibModal.open) hibModal.close(); return; }
  const now = Date.now() / 1000;
  let status, hero, sub, pill;
  if (!idle.enabled) {
    status = ICON.off + " Paused";
    hero = "Off";
    sub = "IDLE_HIBERNATE=off in /etc/devbox/idle.conf";
    pill = ICON.off + " Auto-hibernate off";
  } else if (idle.count > 0) {
    status = ICON.warning + ` Idle, check ${idle.count} of ${idle.needed}`;
    hero = idle.hibernate_at ? dur(idle.hibernate_at - now) : "–";
    sub = "until hibernation";
    pill = ICON.warning + " Idle · hibernates in " + hero;
  } else {
    const reason = idle.last_status && /^active \((.*)\)$/.exec(idle.last_status.message);
    status = ICON.good + " Active" + (reason ? ": " + esc(reason[1]) : "");
    hero = idle.hibernate_at ? dur(idle.hibernate_at - now) : "–";
    sub = "until hibernation";
    pill = ICON.good + " Hibernates in " + hero;
  }
  const steps = Array.from({ length: idle.needed }, (_, i) => `<span class="${i < idle.count ? "on" : ""}"></span>`).join("");
  // A pill in the header; the modal has the countdown, facts, log and Hibernate now.
  if ($("hibCard").dataset.html !== pill) { $("hibCard").dataset.html = pill; $("hibCard").innerHTML = pill; }
  $("hibCard").title = "Auto-hibernate: show details, the idle log and Hibernate now";
  $("hibModalTitle").innerHTML = status;
  $("hibHero").textContent = hero;
  // The idle-check countdown ticks live (tickLive); everything else is per-minute.
  $("hibSub").innerHTML = esc(sub) + (idle.enabled ? ' · <span class="liveNext"></span>' : "");
  $("hibSteps").innerHTML = steps;

  const awake = idle.awake_since_estimate || host.boot_time;
  $("hibFacts").innerHTML = stats([
    ["Awake for", null, `${esc(dur(now - awake))} <span class="dim">since ${esc(clock(awake))}</span>`],
    ["Last hibernated", idle.last_hibernate ? dur(now - idle.last_hibernate) + " ago" : "–"],
    ["Past 7 days", idle.log_available ? idle.hibernations_7d + (idle.hibernations_7d === 1 ? " hibernation" : " hibernations") : "–"],
    ["Hibernates after", null, `${idle.idle_minutes} min idle <span class="dim">load under ${idle.load_busy.toFixed(2)}, now ${d.cpu.load[0].toFixed(2)}</span>`],
    ["Claude heartbeat", null, '<span id="liveBeat"></span>'],
  ]);
  // Hibernate now: only on an EC2 devbox (idle checker + instance metadata present)
  $("hibFoot").hidden = !(host.instance && host.instance.instance_id);
  tickLive();
}

$("hibBtn").onclick = async () => {
  const sessions = (last && last.claude) || [];
  const busy = sessions.filter(s => s.status === "busy").length;
  const waiting = sessions.filter(s => s.status === "waiting").length;
  const running = [busy && `${busy} Claude session${busy > 1 ? "s are" : " is"} working`,
                   waiting && `${waiting} need${waiting > 1 ? "" : "s"} input`].filter(Boolean).join(" and ");
  const msg = "Hibernate the devbox now?\n\n" +
    (running ? running + ". They'll pause and resume where they left off on wake.\n\n" : "") +
    "SSH sessions and this page will disconnect. Wake it with `ssh devbox` or `devbox up`.";
  if (!confirm(msg)) return;
  const btn = $("hibBtn");
  btn.disabled = true; btn.textContent = "Hibernating…";
  try {
    const r = await fetch("api/hibernate", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Dashboard": "1" }, body: "{}",
    });
    const res = await r.json().catch(() => ({ message: "HTTP " + r.status }));
    if (!r.ok) throw new Error(res.message);
    hibernating = true; stopPolling();
    hibModal.close();
    document.querySelector("main").insertAdjacentHTML("afterbegin",
      `<div class="banner">Hibernating since ${hhmm(Date.now() / 1000)}. This page stops updating; reload it after waking the box.</div>`);
  } catch (err) {
    alert("Couldn't hibernate: " + err.message);
    btn.disabled = false; btn.textContent = "Hibernate now";
  }
};

async function pollLog() {
  if (!last || !last.idle) return;
  try {
    const d = await (await fetch("api/log?n=200", { cache: "no-store" })).json();
    const el = $("log");
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    if (!d.available) {
      el.innerHTML = "";
      $("logNote").textContent = d.path + " not found yet. It's written by the updated devbox-idle-check (re-run bootstrap.sh over SSM).";
      return;
    }
    el.innerHTML = d.lines.map(l => {
      const i = l.indexOf(" "), ts = l.slice(0, i), msg = l.slice(i + 1);
      const t = Date.parse(ts);
      const shown = isNaN(t) ? esc(ts) : new Date(t).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
      const cls = /hibernating|disabled/.test(msg) ? ' class="hi"' : "";
      return `<span class="t">${shown}</span>  <span${cls}>${esc(msg)}</span>`;
    }).join("\n");
    $("logNote").textContent = d.path + " · newest last";
    if (atBottom) el.scrollTop = el.scrollHeight;
  } catch (e) {}
}
