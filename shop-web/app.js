/* Soft Jaw Cell shop app. Talks to the JSON API served by `python -m softjaw serve`. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const view = $("#view");
const dialog = $("#dialog");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ------------------------------------------------------------------ helpers
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; }
  if (opts.body !== undefined) { init.body = opts.body; init.headers["Content-Type"] = "application/octet-stream"; }
  const res = await fetch(path, init);
  const data = res.headers.get("Content-Type")?.includes("json") ? await res.json() : null;
  if (!res.ok) { const e = new Error(data?.error || res.statusText); e.status = res.status; throw e; }
  return data;
}

let toastTimer;
function toast(msg, err = false) {
  $(".toast")?.remove();
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.setAttribute("role", err ? "alert" : "status");
  t.textContent = msg;
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), err ? 7000 : 3500);
}

const store = {
  get(k, d = "") { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
const operatorName = () => store.get("sjc-name");

const pad = (n) => String(n).padStart(2, "0");
const toDate = (iso) => (iso ? new Date(iso) : null);
const fmt = {
  dt(iso) { const d = toDate(iso); return d ? d.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "-"; },
  time(iso) { const d = toDate(iso); return d ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "-"; },
  date(iso) { const d = toDate(iso); return d ? d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) : "-"; },
  ago(iso) {
    const d = toDate(iso); if (!d) return "-";
    const s = (Date.now() - d) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return fmt.date(iso);
  },
  dur(s) { if (s == null) return "-"; s = Math.round(s); if (s < 90) return `${s} s`; const m = Math.round(s / 60); return m < 90 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`; },
  local(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`; },
};

const badge = (key, label) => `<span class="badge b-${esc(key)}">${esc(label ?? key)}</span>`;
const STATE_TEXT = {
  PLANNING: "Planning robot paths", JOB_VALIDATED: "Job validated", PICK_BLANK: "Picking blank from rack", VERIFY_GRIP: "Verifying grip",
  REQUEST_LOAD: "Machine to exchange pose", DOOR_OPEN_CONFIRMED: "Door open", LOAD_BLANK: "Loading blank into vise",
  FIXTURE_CLAMPED_CONFIRMED: "Vise clamped", ROBOT_CLEAR_CONFIRMED: "Robot clear of machine", DOOR_CLOSED_CONFIRMED: "Door closed",
  CNC_CYCLE: "Machining", CYCLE_COMPLETE: "Cycle complete", SPINDLE_ZERO_CONFIRMED: "Spindle stopped", UNCLAMP: "Unclamping jaw",
  PICK_FINISHED_JAW: "Picking finished jaw", RETURN_TO_RACK: "Returning jaw to rack", COMPLETE: "Complete", SAFE_STOP: "SAFE STOP",
  PLAN_REJECTED: "Plan rejected", IDLE: "Idle",
};
const stateText = (s) => STATE_TEXT[s] || (s ? s.replace(/_/g, " ").toLowerCase() : "-");
// the controller names each passed check after the fault it guards against; say what was confirmed
const CHECK_OK = {
  lost_grip: "gripper is holding the part", clamp_disagreement: "vise clamp matches command", door_disagreement: "door position matches command",
  spindle_not_stopped: "spindle stopped", axes_not_at_exchange: "axes at exchange pose", robot_not_clear: "robot clear of the machine",
  cnc_alarm: "no CNC alarm", timeout: "cycle-complete signal received", occupied_slot: "rack slot free", "job validated": "job validated",
};
const RUN_STATUS = { queued: "Queued", planning: "Planning", running: "Running", complete: "Complete", safe_stop: "Stopped - recover",
  recovered: "Recovered", cancelled: "Cancelled", failed: "Failed" };
const runBadge = (s) => badge(s, RUN_STATUS[s] || s);
const stageBadge = (st) => badge({ made: "made", ready: "ready", review: "review", cam: "cam", design: "design", rejected: "rejected",
  queued: "queued", planning: "running", running: "running", safe_stop: "safe_stop" }[st.key] || "design", st.label);

function openDialog(html, onSubmit) {
  dialog.innerHTML = html;
  dialog.showModal();
  $$("[data-close]", dialog).forEach((b) => b.addEventListener("click", () => dialog.close()));
  const form = $("form", dialog);
  if (form && onSubmit) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = $("button[type=submit]", form);
      btn && (btn.disabled = true);
      try { await onSubmit(new FormData(form), form); dialog.close(); }
      catch (err) { toast(err.message, true); }
      finally { btn && (btn.disabled = false); }
    });
  }
}

function confirmDialog(title, body, okLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    openDialog(`<form method="dialog" class="form"><h2>${esc(title)}</h2><p class="muted">${body}</p>
      <div class="row" style="justify-content:flex-end"><button type="button" data-close>Back</button>
      <button type="submit" class="${danger ? "stop" : "primary"}" value="ok">${esc(okLabel)}</button></div></form>`);
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
  });
}

async function readFile(file) { return new Uint8Array(await file.arrayBuffer()); }

// ------------------------------------------------------------------ live status (top bar)
let STATUS = null;
async function refreshStatus() {
  try {
    STATUS = await api("/api/status");
  } catch {
    $("#cell-text").textContent = "App offline"; $("#cell-dot").className = "dot stop"; return;
  }
  const a = STATUS.active;
  const stopped = STATUS.alerts.some((x) => x.level === "danger" && x.link?.startsWith("#/runs/"));
  $("#cell-dot").className = "dot " + (a ? "run" : stopped ? "stop" : "ok");
  $("#cell-text").textContent = a ? `${stateText(a.state)} - ${a.jaw_set_name}` : stopped ? "Stopped - recovery needed" : "Cell idle";
  $("#cell-pill").onclick = a ? () => (location.hash = `#/runs/${a.id}`) : null;
  $("#cell-pill").style.cursor = a ? "pointer" : "";
  const w = STATUS.window, n = STATUS.next_window;
  $("#window-text").textContent = w ? `Downtime window until ${fmt.time(w.end)}${w.label ? " (" + w.label + ")" : ""}`
    : n ? `Next downtime ${fmt.dt(n.start)}` : "No downtime windows set";
  $("#auto-run").checked = !!STATUS.auto_run;
  const count = STATUS.alerts.length;
  $("#nav-alerts").hidden = !count; $("#nav-alerts").textContent = count;
}
$("#auto-run").addEventListener("change", async (e) => {
  try { await api("/api/settings", { method: "PATCH", json: { auto_run: e.target.checked } }); toast(e.target.checked ? "Auto-run on: queued jaws start in downtime windows" : "Auto-run off"); refreshStatus(); }
  catch (err) { toast(err.message, true); }
});

// ------------------------------------------------------------------ router
let liveTimer = null;
const routes = [
  [/^#?\/?$/, "dash", dashboard], [/^#\/jaws$/, "jaws", jawSets], [/^#\/jaws\/(\d+)$/, "jaws", jawSet],
  [/^#\/jobs$/, "jobs", jobs], [/^#\/schedule$/, "schedule", schedulePage], [/^#\/runs$/, "runs", runs],
  [/^#\/runs\/(\d+)$/, "runs", runPage], [/^#\/cam$/, "cam", camPage], [/^#\/settings$/, "settings", settingsPage],
];
async function route() {
  clearInterval(liveTimer); liveTimer = null;
  const hash = location.hash || "#/";
  for (const [re, nav, fn] of routes) {
    const m = hash.match(re);
    if (!m) continue;
    $$("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.route === nav));
    const title = TITLES[nav];
    $("#page-title").textContent = title;
    document.title = `${title} - Soft Jaw Cell`;
    try { await fn(...m.slice(1).map(Number)); }
    catch (err) { view.innerHTML = `<div class="banner">${esc(err.message)}</div>`; }
    $$(".page-head h1", view).forEach((h) => { h.hidden = h.textContent.trim() === title; });   // the top bar already says it
    return;
  }
  view.innerHTML = `<div class="empty">Page not found. <a href="#/">Back to the dashboard</a></div>`;
}
const TITLES = { dash: "Control centre", jaws: "Jaw sets", jobs: "Production jobs", schedule: "Downtime & queue", runs: "Cell runs", cam: "CAM link", settings: "Settings" };

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  $$("[data-theme-btn]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeBtn === t)));
}
applyTheme(document.documentElement.dataset.theme || "dark");
$$("[data-theme-btn]").forEach((b) => b.addEventListener("click", () => { applyTheme(b.dataset.themeBtn); store.set("sjc-theme", b.dataset.themeBtn); }));

function live(fn, ms) { liveTimer = setInterval(() => { if (!dialog.open) fn().catch(() => {}); }, ms); }
window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });

// ------------------------------------------------------------------ control centre (dashboard)
const icon = (name, cls = "i") => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const clock = (s) => { if (s == null || s < 0) return "--:--:--"; s = Math.round(s); return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`; };

async function dashboard() {
  view.innerHTML = `
    <div class="cc">
      <div class="cc-main">
        <div class="cc-top">
          <section class="card cell-card" id="cc-cell" aria-live="polite"></section>
          <section class="card sim-card cc-sim"><div class="card-head"><h2>Live cell</h2><a class="more" id="cc-sim-link" href="#/runs">Run monitor ${icon("arrow")}</a></div>
            <div id="cc-sim"></div></section>
        </div>
        <div class="cc-pair">
          <section class="card" id="cc-queue"></section>
          <section class="card" id="cc-review"></section>
        </div>
        <section class="card" id="cc-week"></section>
        <section class="card" id="cc-rack"></section>
      </div>
      <div class="cc-side">
        <section class="card" id="cc-util"></section>
        <section class="card" id="cc-lib"></section>
        <section class="card" id="cc-quick"></section>
        <section class="card" id="cc-alerts"></section>
        <section class="card" id="cc-activity"></section>
      </div>
    </div>`;
  let sets = null;
  const draw = async () => {
    await refreshStatus();
    const s = STATUS;
    if (!s) return;
    if (!sets) sets = await api("/api/jaw-sets");
    drawCell(s); drawSim(s); drawUpNext(s); drawReview(s); drawWeek(s); drawRack(s);
    drawUtil(s); drawLibrary(s); drawQuick(s, sets); drawAlerts(s);
    $("#cc-activity").innerHTML = `<div class="card-head"><h2>Activity</h2></div>${activityView(s.activity.slice(0, 8))}`;
  };
  await draw();
  live(async () => { sets = null; await draw(); }, 2000);
}

function drawCell(s) {
  const a = s.active, now = new Date(s.now);
  const stopped = s.alerts.find((x) => x.level === "danger" && x.link?.startsWith("#/runs/"));
  const next = s.queue.find((q) => !q.blocked?.length);
  const R = 76, C = 2 * Math.PI * R;
  let title, sub, btn, stats, pct = 0;
  if (a) {
    pct = a.progress || 0;
    const elapsed = (now - new Date(a.started_at)) / 1000;
    const remaining = s.active_end ? (new Date(s.active_end) - now) / 1000 : null;
    title = esc(stateText(a.state));
    sub = `<a href="#/jaws/${a.jaw_set_id}">${esc(a.jaw_set_name)}</a>${a.jaw ? ` - ${esc(a.jaw)} jaw` : ""}`;
    btn = `<button class="ring-btn live" data-stop="${a.id}" aria-label="Stop the cell">${icon("stop", "")}</button>`;
    stats = [["Running for", clock(elapsed)], ["Time left", clock(remaining)]];
  } else if (stopped) {
    title = "Cell stopped";
    sub = "Confirm where the jaws are";
    btn = `<a class="ring-btn" style="display:grid;place-items:center;background:var(--danger)" href="${esc(stopped.link)}" aria-label="Open recovery">${icon("alert", "")}</a>`;
    stats = [["Auto-run", "Paused"], ["Queued", String(s.queue.length)]];
  } else {
    title = next ? "Ready to run" : "Cell idle";
    sub = next ? esc(next.jaw_set_name) : s.queue.length ? "Queued runs are waiting" : "Nothing queued";
    btn = `<button class="ring-btn ${next ? "" : "idle"}" ${next ? `data-start="${next.id}"` : "disabled"} aria-label="${next ? "Start the next run now" : "Nothing ready to start"}">${icon("play", "")}</button>`;
    const w = s.window, n = s.next_window;
    stats = [["Queued", String(s.queue.length)], w ? ["Window ends", fmt.time(w.end)] : ["Next window", n ? fmt.time(n.start) : "none"]];
  }
  $("#cc-cell").innerHTML = `
    <h2>${title}</h2><div class="sub">${sub}</div>
    <div class="ring-wrap"><svg class="ring" viewBox="0 0 170 170" width="170" height="170" aria-hidden="true">
      <circle class="track" cx="85" cy="85" r="${R}" fill="none" stroke-width="6"/>
      <circle class="fill" cx="85" cy="85" r="${R}" fill="none" stroke-width="6" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - pct)}"/></svg>${btn}</div>
    <div class="stat-pair">${stats.map(([k, v]) => `<div class="stat"><small>${esc(k)}</small><b>${esc(v)}</b></div>`).join("")}</div>`;
  bindStop($("#cc-cell")); bindQueue(route, $("#cc-cell"));
}

// ------------------------------------------------------------------ embedded 3D views
// A view that fails to start (server restarting, CDN hiccup, lost WebGL context) is reloaded by the
// watchdog below, up to 5 times, then offers a Retry button instead of staying broken.
const simFrame = (src, title) => `<iframe src="${src}" data-src="${src}" data-born="${Date.now()}" data-tries="0" title="${esc(title)}"></iframe>`;

function simHealthy(f) {
  try { const w = f.contentWindow; return !!(w && w.__sim && !w.__simLost); } catch { return false; }
}

// a frame stuck on the browser's network-error page does not reliably navigate again when its src
// changes, so a retry swaps in a new iframe element
function reloadSim(f, tries = Number(f.dataset.tries) + 1) {
  const tmp = document.createElement("div");
  tmp.innerHTML = simFrame(f.dataset.src, f.title);
  const fresh = tmp.firstElementChild;
  fresh.dataset.tries = tries;
  f.replaceWith(fresh);
  return fresh;
}

function simLoading(f) {
  try { return f.contentWindow.document.readyState !== "complete"; } catch { return false; }   // error pages are unreadable
}

function simWatchdog() {
  $$(".sim-frame iframe[data-src]").forEach((f) => {
    const box = f.parentElement;
    if (simHealthy(f)) { f.dataset.tries = "0"; box.querySelector(".sim-fail")?.remove(); return; }
    const age = Date.now() - Number(f.dataset.born);
    if (age < 15000 || (simLoading(f) && age < 30000)) return;           // still starting (3D library is large)
    if (Number(f.dataset.tries) < 5) return reloadSim(f);
    if (!box.querySelector(".sim-fail")) {
      box.insertAdjacentHTML("beforeend", `<div class="sim-fail"><b>3D view unavailable</b><span class="faint">The page could not start the 3D view (server restarting, no internet for the 3D library, or the graphics card is busy).</span><button class="small" type="button">Retry</button></div>`);
      box.querySelector(".sim-fail button").addEventListener("click", () => { box.querySelector(".sim-fail").remove(); reloadSim(f, 0); });
    }
  });
}
setInterval(simWatchdog, 3000);

// the 3D cell is always on: it follows the running cycle, otherwise it shows the cell at rest with the live rack
function drawSim(s) {
  const box = $("#cc-sim"), a = s.active;
  const run = a && a.status === "running" ? a.id : null;
  const mode = run ? `run-${run}` : "idle";
  if (box.dataset.mode !== mode) {                   // swap only when the mode changes, so the view keeps playing
    box.dataset.mode = mode;
    const src = run ? `/runs/${run}/sim/?embed=1&follow=${run}` : "/sim/?embed=1&idle=1";
    box.innerHTML = `<div class="sim-frame">${simFrame(src, run ? `3D view of the cell following run ${run}` : "3D view of the cell at rest")}</div>
      <p class="faint" id="cc-sim-note" style="margin:10px 0 0"></p>`;
  }
  $("#cc-sim-link").href = run ? `#/runs/${run}` : "#/runs";
  $("#cc-sim-note").textContent = run ? `Following run ${run}: ${stateText(a.state)}.`
    : a ? "Planning robot paths; the view switches to the run when it starts."
    : s.window ? "No cycle running. The machine is free; queued runs start here when ready."
    : s.next_window ? `No cycle running. Next downtime window ${fmt.dt(s.next_window.start)}.` : "No cycle running. Add a downtime window so queued jaws can run.";
}

function drawUpNext(s) {
  const a = s.active;
  const items = [];
  if (a) items.push(`<div class="task now"><button class="round fill" data-stop="${a.id}" aria-label="Stop">${icon("pause", "")}</button>
    <div style="min-width:0"><div class="t-title">${esc(a.jaw_set_name)}</div><div class="t-sub">${esc(stateText(a.state))} - ${Math.round((a.progress || 0) * 100)}%</div></div>
    <a class="small btn" href="#/runs/${a.id}">Watch</a></div>`);
  for (const r of s.queue.slice(0, a ? 3 : 4)) {
    const blocked = r.blocked?.length;
    items.push(`<div class="task"><button class="round" data-start="${r.id}" ${blocked ? "disabled" : ""} aria-label="Start ${esc(r.jaw_set_name)} now">${icon("play", "")}</button>
      <div style="min-width:0"><div class="t-title"><a href="#/jaws/${r.jaw_set_id}" style="color:inherit">${esc(r.jaw_set_name)}</a></div>
        <div class="t-sub ${blocked ? "warn" : ""}">${blocked ? esc(r.blocked[0]) : r.projected?.start ? `Starts ${esc(fmt.dt(r.projected.start))}` : "No window fits"}${r.need_by ? ` - need by ${esc(fmt.date(r.need_by))}` : ""}</div></div>
      <button class="small" data-cancel="${r.id}" aria-label="Cancel">Cancel</button></div>`);
  }
  $("#cc-queue").innerHTML = `<div class="card-head"><h2>Up next <span class="num-chip">${s.queue.length + (a ? 1 : 0)}</span></h2><a class="more" href="#/schedule">Manage ${icon("arrow")}</a></div>
    ${items.length ? items.join("") : `<div class="empty">Nothing queued. Queue jaws from a jaw set or add a production job.</div>`}`;
  bindQueue(route, $("#cc-queue")); bindStop($("#cc-queue"));
}

function drawReview(s) {
  const tiles = s.pending_nc.slice(0, 3).map((n) => {
    const fail = n.check_status === "fail";
    return `<div class="review ${fail ? "fail" : ""}">
      <div class="r-top"><span class="r-side">${esc(n.side === "both" ? "BOTH JAWS" : n.side.toUpperCase() + " JAW")}</span><span class="r-icon">${icon(fail ? "alert" : "file")}</span></div>
      <div class="r-prog">${esc(n.program_number || "NC")}</div>
      <div class="r-desc"><a href="#/jaws/${n.jaw_set_id}" style="color:inherit">${esc(n.jaw_set_name)}</a><br>${fail ? `Failed: ${esc(n.failed.join(", "))}` : `Checks ${esc(n.check_status)} - Z${n.min_z != null ? n.min_z.toFixed(1) : "?"} - ${fmt.dur(n.est_cycle_s)}`}</div>
      ${fail ? `<a class="btn small" href="#/jaws/${n.jaw_set_id}">Open</a>` : `<div class="row"><button class="small primary" data-approve="${n.id}">Approve</button><a class="btn small" href="#/jaws/${n.jaw_set_id}">Review</a></div>`}
    </div>`;
  });
  tiles.push(`<button class="review add" id="cc-upload" type="button"><span class="plus">${icon("plus")}</span>Upload NC program</button>`);
  $("#cc-review").innerHTML = `<div class="card-head"><h2>Programs to review <span class="num-chip">${s.pending_nc.length}</span></h2><a class="more" href="#/cam">CAM link ${icon("arrow")}</a></div>
    <div class="review-grid">${tiles.join("")}</div>`;
  $("#cc-upload").addEventListener("click", () => uploadNcDialog());
  $$("[data-approve]").forEach((b) => b.addEventListener("click", () => approveDialog(Number(b.dataset.approve))));
}

function approveDialog(id) {
  const n = STATUS.pending_nc.find((x) => x.id === id);
  openDialog(`<form class="form"><h2>Approve ${esc(n?.program_number || "program")}</h2>
    <p class="muted" style="margin:0">${esc(n?.jaw_set_name || "")} - ${esc(n?.side || "")} jaw. Approve only after checking stock, WCS and tools in CAM simulation.</p>
    <label class="field"><span>Approved by</span><input name="by" required value="${esc(operatorName())}" autofocus></label>
    <div class="row" style="justify-content:flex-end"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Approve</button></div></form>`,
  async (fd) => {
    store.set("sjc-name", fd.get("by"));
    await api(`/api/nc/${id}/review`, { method: "POST", json: { decision: "approved", by: fd.get("by") } });
    toast("Program approved"); route();
  });
}

async function uploadNcDialog() {
  const sets = await api("/api/jaw-sets");
  if (!sets.length) return toast("Create a jaw set first", true);
  const sideOptions = (j) => (j.program_mode === "shared" ? [["both", "Both jaws"]] : [["left", "Left jaw"], ["right", "Right jaw"]]).map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
  openDialog(`<form class="form"><h2>Upload NC program</h2>
    <label class="field"><span>Jaw set</span><select name="jaw" id="up-jaw">${sets.map((j) => `<option value="${j.id}">${esc(j.name)} - ${esc(j.stage.label)}</option>`).join("")}</select></label>
    <label class="field"><span>Which jaw</span><select name="side" id="up-side">${sideOptions(sets[0])}</select></label>
    <label class="field"><span>Posted program</span><input type="file" name="file" required accept=".nc,.tap,.ngc,.cnc,.eia,.txt,.min"></label>
    <p class="faint" style="margin:0">It is checked against the jaw setup straight away and held for approval.</p>
    <div class="row" style="justify-content:flex-end"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Upload</button></div></form>`,
  async (fd) => {
    const f = fd.get("file");
    const nc = await api(`/api/jaw-sets/${fd.get("jaw")}/nc?side=${fd.get("side")}&filename=${encodeURIComponent(f.name)}`, { method: "POST", body: await readFile(f) });
    toast(nc.check_status === "fail" ? "Uploaded: the program failed a safety check" : "Uploaded and checked; ready to approve", nc.check_status === "fail");
    route();
  });
  $("#up-jaw", dialog).addEventListener("change", (e) => { $("#up-side", dialog).innerHTML = sideOptions(sets.find((j) => j.id === Number(e.target.value))); });
}

function drawWeek(s) {
  const now = new Date(s.now), day0 = new Date(now); day0.setHours(0, 0, 0, 0);
  const H = 300, y = (d, base) => Math.max(0, Math.min(H, ((d - base) / 864e5) * H));
  const runs = s.queue.filter((q) => q.projected?.start).map((q) => ({ s: new Date(q.projected.start), e: new Date(q.projected.end), name: q.jaw_set_name }));
  if (s.active && s.active_end) runs.push({ s: new Date(s.active.started_at), e: new Date(s.active_end), name: s.active.jaw_set_name });
  let head = `<div class="hd"></div>`, cols = `<div class="hours">${[0, 6, 12, 18].map((h) => `<span style="top:${(h / 24) * H + 1}px">${pad(h)}</span>`).join("")}</div>`;
  for (let i = 0; i < 7; i++) {
    const base = new Date(day0.getTime() + i * 864e5), next = new Date(base.getTime() + 864e5);
    head += `<div class="hd ${i === 0 ? "today" : ""}">${esc(base.toLocaleDateString([], { weekday: "short" }).toUpperCase())} <b>${base.getDate()}</b></div>`;
    let blocks = "";
    for (const w of s.windows_week) {
      const a = new Date(w.start), b = new Date(w.end);
      if (b <= base || a >= next) continue;
      const top = y(a, base), h = y(b, base) - top;
      blocks += `<div class="blk win" style="top:${top}px;height:${h}px" title="${esc(w.label)} ${esc(fmt.time(w.start))}-${esc(fmt.time(w.end))}">${h > 28 ? esc(w.label || "Downtime") : ""}</div>`;
    }
    for (const r of runs) {
      if (r.e <= base || r.s >= next) continue;
      const top = y(r.s, base), h = Math.max(4, y(r.e, base) - top);
      blocks += `<div class="blk run" style="top:${top}px;height:${h}px" title="${esc(r.name)} ${esc(fmt.time(r.s.toISOString()))}">${h > 18 ? esc(r.name) : ""}</div>`;
    }
    if (i === 0) blocks += `<div class="nowline" style="top:${y(now, base)}px"></div>`;
    cols += `<div class="col">${blocks}</div>`;
  }
  $("#cc-week").innerHTML = `<div class="card-head"><h2>Machine this week</h2>
      <div class="row"><div class="legend"><span><i style="background:var(--hatch),var(--panel-3)"></i>Haas on production</span><span><i style="background:color-mix(in srgb,var(--green) 40%,transparent)"></i>Free for the cell</span><span><i style="background:var(--accent)"></i>Cell run</span></div>
      <button class="small" id="cc-add-dt">${icon("plus")} Downtime</button></div></div>
    <div class="wk">${head}${cols}</div>`;
  $("#cc-add-dt").addEventListener("click", () => weeklyDialog());
}

function drawRack(s) {
  const empty = s.rack.filter((r) => r.content === "empty" && !r.busy).length;
  $("#cc-rack").innerHTML = `<div class="card-head"><h2>Blank rack <span class="num-chip">${s.rack.filter((r) => r.content === "blank").length} blanks</span></h2>
    <button class="small" id="cc-load" ${empty ? "" : "disabled"}>${icon("box")} ${empty ? `Mark ${empty} empty slot${empty === 1 ? "" : "s"} as loaded` : "No empty slots"}</button></div>${rackView(s.rack)}`;
  bindRack();
  $("#cc-load").addEventListener("click", async () => {
    if (!(await confirmDialog("Blanks loaded?", `Mark all ${empty} empty slot${empty === 1 ? "" : "s"} as holding a pre-drilled blank. Only do this after putting the blanks in.`, "Mark loaded"))) return;
    for (const r of s.rack.filter((x) => x.content === "empty" && !x.busy)) await api(`/api/rack/${r.slot}`, { method: "POST", json: { content: "blank" } });
    toast("Rack updated"); route();
  });
}

function drawUtil(s) {
  const days = s.utilisation;
  const pctText = (p) => (p == null ? "-" : p < 10 ? p.toFixed(1) : String(Math.round(p)));
  const avail = days.reduce((t, d) => t + (d.pct == null ? 0 : d.available_h), 0);
  const hrs = days.reduce((t, d) => t + d.run_h, 0);
  const avg = avail ? Math.min(100, (100 * hrs) / avail) : null;          // weighted by the hours available
  const today = days[days.length - 1];
  $("#cc-util").innerHTML = `<div class="card-head"><h2>Cell utilisation</h2><span class="faint">last 7 days</span></div>
    <div class="big-num">${pctText(avg)}<small>%</small></div>
    <div class="bars">${days.map((d, i) => {
      const p = d.pct == null ? 0 : Math.min(100, d.pct);
      const name = new Date(d.date + "T12:00:00").toLocaleDateString([], { weekday: "short" });
      return `<div class="bar ${i === days.length - 1 ? "today" : ""}" title="${esc(name)}: ${d.run_h.toFixed(2)} h run of ${d.available_h} h downtime">
        <div class="fill" style="height:${Math.max(p, p > 0 ? 3 : 0)}%"></div><div class="cap">${esc(name)}<b>${d.pct == null ? "-" : pctText(p) + "%"}</b></div></div>`;
    }).join("")}</div>
    <p class="faint" style="margin:12px 0 0">Share of downtime windows the cell spent running. ${hrs.toFixed(1)} h of cycles this week${today.available_h ? `, ${today.available_h} h free today` : ""}.</p>`;
}

function drawLibrary(s) {
  const parts = [["made", "Made", "var(--green)"], ["ready", "Ready to machine", "var(--blue)"], ["review", "To review", "var(--amber)"],
    ["cam", "Waiting for CAM", "var(--accent)"], ["rejected", "Rejected", "var(--danger)"], ["design", "Needs design", "var(--faint)"]];
  const total = Object.values(s.library).reduce((a, b) => a + b, 0);
  const R = 56, C = 2 * Math.PI * R;
  let off = 0, arcs = "";
  for (const [k, , col] of parts) {
    const n = s.library[k] || 0;
    if (!n) continue;
    const len = (n / total) * C;
    arcs += `<circle cx="69" cy="69" r="${R}" fill="none" stroke="${col}" stroke-width="10" stroke-linecap="round" stroke-dasharray="${Math.max(0.1, len - 6)} ${C}" stroke-dashoffset="${-off}"/>`;
    off += len;
  }
  $("#cc-lib").innerHTML = `<div class="card-head"><h2>Jaw library</h2><a class="more" href="#/jaws">All ${icon("arrow")}</a></div>
    <div class="donut-row"><div class="donut"><svg viewBox="0 0 138 138" width="138" height="138" aria-hidden="true"><circle cx="69" cy="69" r="${R}" fill="none" stroke="var(--panel-3)" stroke-width="10"/>${arcs}</svg>
      <div class="center"><b>${total}</b><small>jaw sets</small></div></div>
      <ul class="legend-list">${parts.filter(([k]) => s.library[k]).map(([k, label, col]) => `<li><i style="border-color:${col}"></i><span>${label}</span><b class="num">${s.library[k]}</b></li>`).join("") || `<li class="faint">No jaw sets yet</li>`}</ul></div>`;
}

function drawQuick(s, sets) {
  $("#cc-quick").innerHTML = `<div class="card-head"><h2>Quick actions</h2></div><div class="quick">
    <button id="q-set">${icon("plus")} New jaw set</button>
    <button id="q-nc">${icon("upload")} Upload NC</button>
    <button id="q-job">${icon("jobs")} Add job</button>
    <button id="q-dt">${icon("cal")} Downtime now</button>
    <button id="q-scan">${icon("cam")} Scan CAM inbox</button>
    <a class="btn" href="#/runs">${icon("runs")} Run history</a></div>`;
  $("#q-set").addEventListener("click", newJawSetDialog);
  $("#q-nc").addEventListener("click", () => uploadNcDialog());
  $("#q-job").addEventListener("click", () => jobDialog(null, sets));
  $("#q-dt").addEventListener("click", () => onceDialog());
  $("#q-scan").addEventListener("click", async () => {
    const r = await api("/api/cam/scan", { method: "POST" });
    toast(r.imported.length ? `Imported ${r.imported.length} program(s) from the CAM inbox` : "No new programs in the CAM inbox"); route();
  });
}

function drawAlerts(s) {
  $("#cc-alerts").innerHTML = `<div class="card-head"><h2>Needs attention <span class="num-chip">${s.alerts.length}</span></h2></div>${alertsView(s.alerts.slice(0, 5))}`;
}

function worldKv(w) {
  if (!w) return "";
  return `<dl class="kv" style="margin:14px 0 0">
    <div><dt>Robot at</dt><dd>${esc((w.robot_at || "-").replace(/_/g, " "))}</dd></div>
    <div><dt>Door</dt><dd>${w.door_open ? "Open" : "Closed"}</dd></div>
    <div><dt>Spindle</dt><dd>${w.spindle ? "Running" : "Stopped"}</dd></div>
    <div><dt>Vise</dt><dd>${w.clamped ? "Clamped" : "Open"}${w.vise_holds ? " - " + esc(w.vise_holds.replace("_", " ")) : ""}</dd></div>
    <div><dt>Gripper</dt><dd>${esc((w.holding || "empty").replace("_", " "))}</dd></div></dl>`;
}

function queueTable(queue) {
  if (!queue.length) return `<div class="empty">No runs queued. Queue one from a jaw set, or add a production job that needs jaws.</div>`;
  return `<div class="table-wrap"><table><thead><tr><th>Jaw set</th><th>Needed by</th><th>Est.</th><th>Starts</th><th></th></tr></thead><tbody>
    ${queue.map((r) => `<tr>
      <td><a href="#/jaws/${r.jaw_set_id}">${esc(r.jaw_set_name)}</a><div class="faint">${esc(r.trigger)}${r.fault ? " - fault test" : ""}</div>
        ${r.blocked?.length ? `<div class="faint" style="color:var(--warn)">Waiting: ${esc(r.blocked.join("; "))}</div>` : ""}</td>
      <td>${r.need_by ? esc(fmt.date(r.need_by)) : "-"}</td>
      <td class="num">${fmt.dur(r.est_duration_s)}</td>
      <td>${r.projected?.start ? esc(fmt.dt(r.projected.start)) : `<span class="faint">no window fits</span>`}</td>
      <td><div class="row" style="justify-content:flex-end"><button class="small primary" data-start="${r.id}" ${r.blocked?.length ? "disabled" : ""}>Start now</button>
        <button class="small" data-cancel="${r.id}">Cancel</button></div></td></tr>`).join("")}</tbody></table></div>`;
}

function bindQueue(after = route, root = document) {
  $$("[data-start]", root).forEach((b) => b.addEventListener("click", () => startRun(Number(b.dataset.start), after)));
  $$("[data-cancel]", root).forEach((b) => b.addEventListener("click", async () => {
    if (!(await confirmDialog("Cancel this run?", "It leaves the queue. The jaw set keeps its approved programs.", "Cancel run", true))) return;
    try { await api(`/api/runs/${b.dataset.cancel}/cancel`, { method: "POST" }); toast("Run cancelled"); after(); }
    catch (err) { toast(err.message, true); }
  }));
}

async function startRun(id, after = route) {
  const body = {};
  const ok = await confirmDialog("Start the cell now?",
    "Check the vise is empty, the hard jaws and parallel are in place, and nobody is inside the cell guarding.", "Start");
  if (!ok) return;
  try {
    await api(`/api/runs/${id}/start`, { method: "POST", json: body });
  } catch (err) {
    if (err.status !== 409) return toast(err.message, true);
    const again = await confirmDialog("Machine is not in a downtime window",
      "The schedule says the Haas may be needed for production now. Start only if the machine is free.", "Start anyway", true);
    if (!again) return;
    try { await api(`/api/runs/${id}/start`, { method: "POST", json: { confirm_outside_window: true } }); }
    catch (e2) { return toast(e2.message, true); }
  }
  toast("Run started");
  location.hash = `#/runs/${id}`;
}

function bindStop(root = document) {
  $$("[data-stop]", root).forEach((b) => b.addEventListener("click", async () => {
    if (!(await confirmDialog("Stop the cell?", "The cell goes to SAFE STOP. It will not resume: you confirm where the jaws are, then start a new run.", "Stop cell", true))) return;
    try { await api(`/api/runs/${b.dataset.stop}/stop`, { method: "POST" }); toast("Stop requested"); }
    catch (err) { toast(err.message, true); }
  }));
}

function rackView(rack) {
  return `<div class="rack">${rack.map((r) => `
    <button class="slot ${esc(r.content)} ${r.busy ? "busy" : ""}" data-slot="${r.slot}" aria-label="Rack slot ${r.slot}: ${esc(r.content)}">
      <span class="n">SLOT ${r.slot}</span>
      <span class="what">${r.content === "blank" ? "Blank" : r.content === "finished" ? "Finished jaw" : "Empty"}</span>
      <span class="who">${r.content === "finished" ? `${esc(r.jaw_set_name || "")} (${esc(r.side || "")})` : r.busy ? "in use by the run" : ""}</span>
    </button>`).join("")}</div>`;
}

function bindRack(after = route) {
  $$("[data-slot]").forEach((b) => b.addEventListener("click", () => {
    const slot = Number(b.dataset.slot);
    const r = STATUS?.rack.find((x) => x.slot === slot);
    if (r?.busy) return toast("That slot is in use by the running cycle", true);
    openDialog(`<form class="form"><h2>Rack slot ${slot}</h2>
      ${r?.content === "finished" ? `<p class="muted">Holds the ${esc(r.side)} jaw of <a href="#/jaws/${r.jaw_set_id}">${esc(r.jaw_set_name)}</a>. Use <b>Collect</b> on the jaw set to record where you store the pair.</p>` : ""}
      <label class="field"><span>What is in the slot now?</span><select name="content">
        <option value="blank" ${r?.content === "blank" ? "selected" : ""}>Blank loaded (pre-drilled Delrin)</option>
        <option value="empty" ${r?.content === "empty" ? "selected" : ""}>Empty</option></select></label>
      <div class="row" style="justify-content:flex-end"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Save</button></div></form>`,
    async (fd) => { await api(`/api/rack/${slot}`, { method: "POST", json: { content: fd.get("content") } }); toast(`Slot ${slot} updated`); after(); });
  }));
}

function alertsView(alerts) {
  if (!alerts.length) return `<div class="empty">Nothing needs attention.</div>`;
  return `<div class="stack">${alerts.map((a) => `<div class="alert ${a.level === "danger" ? "danger" : ""}"><span>${esc(a.text)}</span>${a.link ? `<a href="${esc(a.link)}">Open</a>` : ""}</div>`).join("")}</div>`;
}

function activityView(rows) {
  if (!rows.length) return `<div class="empty">No activity yet.</div>`;
  return `<ul class="feed">${rows.map((r) => `<li class="${r.kind === "alert" ? "alert-row" : ""}"><time title="${esc(r.at)}">${esc(fmt.ago(r.at))}</time>
    <span>${esc(r.message)}${r.run_id ? ` <a href="#/runs/${r.run_id}">run ${r.run_id}</a>` : ""}</span></li>`).join("")}</ul>`;
}

// ------------------------------------------------------------------ jaw sets
async function jawSets() {
  const sets = await api("/api/jaw-sets");
  view.innerHTML = `
    <div class="page-head"><div><h1>Jaw sets</h1><p>Each set is a left/right pair of soft jaws for one part setup. Upload the design, get NC back from CAM, approve it, and the cell machines it.</p></div>
      <button class="primary" id="new-set">New jaw set</button></div>
    <section class="card">${sets.length ? `<div class="table-wrap"><table><thead><tr><th>Jaw set</th><th>Part</th><th>Stage</th><th>Location</th><th>Used by</th><th>Updated</th></tr></thead><tbody>
      ${sets.map((j) => `<tr class="click" data-href="#/jaws/${j.id}">
        <td><a href="#/jaws/${j.id}">${esc(j.name)}</a><div class="faint">${j.program_mode === "shared" ? "one program for both jaws" : "left + right programs"}</div></td>
        <td>${esc(j.part_number || "-")}</td><td>${stageBadge(j.stage)}</td><td>${esc(j.location || "-")}</td>
        <td>${j.jobs.length ? j.jobs.map((x) => esc(x.name)).join(", ") : `<span class="faint">no jobs</span>`}</td>
        <td class="faint">${esc(fmt.ago(j.updated_at))}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No jaw sets yet. Create one for each part setup that needs soft jaws.</div>`}</section>`;
  $$("tr[data-href]").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("a")) location.hash = tr.dataset.href; }));
  $("#new-set").addEventListener("click", newJawSetDialog);
}

function newJawSetDialog() {
  openDialog(`<form class="form"><h2>New jaw set</h2>
    <label class="field"><span>Name</span><input name="name" required placeholder="e.g. Hex fitting OP1" autofocus></label>
    <div class="cols"><label class="field"><span>Part number</span><input name="part_number"></label>
      <label class="field"><span>Programs</span><select name="program_mode"><option value="per_side">Left and right differ (two programs)</option>
        <option value="shared">Both jaws identical (one program)</option></select></label></div>
    <label class="field"><span>Notes</span><textarea name="description" placeholder="Setup notes, customer, anything the programmer should know"></textarea></label>
    <div class="row" style="justify-content:flex-end"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Create</button></div></form>`,
  async (fd) => {
    const r = await api("/api/jaw-sets", { method: "POST", json: Object.fromEntries(fd) });
    toast("Jaw set created. Its CAM package is in the outbox.");
    location.hash = `#/jaws/${r.id}`;
  });
}

function stepsView(j) {
  const nc = j.current_nc, sides = j.sides;
  const hasNc = sides.every((s) => nc[s]);
  const approved = hasNc && sides.every((s) => nc[s].review_status === "approved");
  const made = j.made_count > 0;
  const stored = made && j.location && !j.location.startsWith("Rack");
  const steps = [["Design", j.files.length > 0 || hasNc], ["CAM / NC", hasNc], ["Review", approved], ["Machine", made], ["Store", stored]];
  const now = steps.findIndex(([, done]) => !done);
  return `<div class="steps">${steps.map(([name, done], i) => `<div class="${done ? "done" : i === now ? "now" : ""}"><b>${i + 1}. ${done ? "done" : i === now ? "next" : "later"}</b>${name}</div>`).join("")}</div>`;
}

async function jawSet(id) {
  clearInterval(liveTimer); liveTimer = null;
  const [j, setup] = await Promise.all([api(`/api/jaw-sets/${id}`), api("/api/setup")]);
  const nc = j.current_nc;
  const inRack = j.location?.startsWith("Rack");
  view.innerHTML = `
    <div class="crumb"><a href="#/jaws">Jaw sets</a> /</div>
    <div class="page-head"><div><h1>${esc(j.name)}</h1><p>${esc(j.part_number || "No part number")} - ${j.program_mode === "shared" ? "one program for both jaws" : "separate left and right programs"}${j.made_count ? ` - made ${j.made_count}x` : ""}</p></div>
      <div class="row">${stageBadge(j.stage)}<button id="edit-set">Edit</button></div></div>
    ${stepsView(j)}
    ${j.description ? `<p class="muted" style="margin:-4px 0 16px">${esc(j.description)}</p>` : ""}
    <div class="grid g-main">
      <div class="grid">
        <section class="card"><div class="card-head"><h2>1. Jaw design</h2><span class="faint">STEP, STL, IGES, DXF, Mastercam .mcam, PDF drawings</span></div>
          <div class="drop" id="drop"><span>Drop design files here, or</span>
            <div class="row"><select id="design-side" aria-label="Which jaw"><option value="both">Both jaws / assembly</option><option value="left">Left jaw</option><option value="right">Right jaw</option></select>
              <label class="btn">Choose files<input type="file" id="design-file" multiple hidden></label></div></div>
          ${j.files.length ? `<div class="table-wrap" style="margin-top:10px"><table><tbody>${j.files.map((f) => `<tr><td><a href="/api/files/${f.id}">${esc(f.filename)}</a></td>
            <td>${esc(f.side)}</td><td class="num faint">${(f.size / 1024).toFixed(0)} KB</td><td class="faint">${esc(fmt.ago(f.uploaded_at))}</td></tr>`).join("")}</tbody></table></div>` : ""}
        </section>
        <section class="card"><div class="card-head"><h2>2. NC programs</h2><a href="#/cam">How the CAM link works</a></div>
          <p class="muted" style="margin-top:0">Post from Mastercam (or any CAM) as <code>${j.nc_names.map(esc).join("</code> and <code>")}</code> into the CAM inbox, or upload here. Each program is checked against the jaw setup, then a person approves it.</p>
          <div class="grid ${j.sides.length > 1 ? "g2" : ""}">${j.sides.map((s) => ncCard(j, s, nc[s], setup)).join("")}</div>
          ${ncHistory(j)}
        </section>
      </div>
      <div class="grid" style="align-content:start">
        <section class="card"><div class="card-head"><h2>3. Machine it</h2></div>
          ${j.readiness.length ? `<ul class="checks">${j.readiness.map((r) => `<li>${badge("warn", "")}<span>${esc(r)}</span></li>`).join("")}</ul>`
            : `<p class="muted" style="margin-top:0">Programs approved and blanks loaded: ready.</p>`}
          <form class="form" id="queue-form" style="margin-top:12px">
            <label class="field"><span>Needed by (optional)</span><input type="date" name="need_by"></label>
            <details><summary class="faint">Simulation test: inject a fault</summary>
              <select name="fault" style="margin-top:8px;width:100%"><option value="">No fault (normal run)</option>${Object.entries(setup.faults).map(([k, v]) => `<option value="${esc(k)}">${esc(k.replace(/_/g, " "))} - ${esc(v)}</option>`).join("")}</select></details>
            <button class="primary" type="submit">Add to queue</button>
          </form>
          <p class="faint">Queued runs start automatically in the next downtime window that fits, or start them by hand from the queue.</p>
        </section>
        <section class="card"><div class="card-head"><h2>4. Storage</h2></div>
          <p class="muted" style="margin-top:0">Location: <b>${esc(j.location || "not made yet")}</b></p>
          <form class="form" id="loc-form"><label class="field"><span>${inRack ? "Collect from the rack and store at" : "Stored at"}</span>
            <input name="location" placeholder="e.g. Cabinet 2, shelf B" value="${inRack ? "" : esc(j.location || "")}"></label>
            <button type="submit">${inRack ? "Collect from rack" : "Save location"}</button></form>
        </section>
        <section class="card"><div class="card-head"><h2>Production jobs</h2><a href="#/jobs">All jobs</a></div>
          ${j.jobs.length ? `<ul class="feed">${j.jobs.map((x) => `<li><time>${x.need_by ? esc(fmt.date(x.need_by)) : "-"}</time><span>${esc(x.name)} ${badge(x.status === "planned" ? "pending" : "ok", x.status.replace("_", " "))}</span></li>`).join("")}</ul>`
            : `<div class="empty">No production jobs use this set.</div>`}
        </section>
        <section class="card"><div class="card-head"><h2>Runs</h2></div>
          ${j.runs.length ? `<ul class="feed">${j.runs.map((r) => `<li><time>${esc(fmt.date(r.created_at))}</time><span><a href="#/runs/${r.id}">Run ${r.id}</a> ${runBadge(r.status)}</span></li>`).join("")}</ul>`
            : `<div class="empty">Not machined yet.</div>`}
        </section>
      </div>
    </div>`;
  bindJawSet(j);
  // programs posted from CAM arrive through the inbox: redraw when the set changes, unless someone is typing
  const sig = (x) => JSON.stringify([x.updated_at, x.stage, x.nc_programs.map((n) => [n.id, n.review_status]), x.runs.map((r) => r.status), x.readiness]);
  const mine = sig(j);
  live(async () => {
    const fresh = await api(`/api/jaw-sets/${id}`);
    const typing = document.activeElement?.closest("form") && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if (sig(fresh) !== mine && !typing) jawSet(id);
  }, 4000);
}

function ncCard(j, side, nc, setup) {
  const title = side === "both" ? "Program (both jaws)" : `${side[0].toUpperCase() + side.slice(1)} jaw`;
  const upload = `<label class="btn small">${nc ? "Upload new version" : "Upload NC"}<input type="file" data-nc-side="${side}" hidden accept=".nc,.tap,.ngc,.cnc,.eia,.txt,.min"></label>`;
  if (!nc) return `<div class="card" style="background:var(--panel-2)"><div class="spread"><h3>${title}</h3>${upload}</div><div class="empty" style="margin-top:10px">Waiting for CAM</div></div>`;
  const a = nc.analysis || {};
  const canApprove = nc.review_status === "pending" && nc.check_status !== "fail";
  return `<div class="card" style="background:var(--panel-2)">
    <div class="spread"><h3>${title}</h3><div class="row">${badge(nc.check_status, "checks " + nc.check_status)}${badge(nc.review_status)}</div></div>
    <p class="faint" style="margin:6px 0 10px">${esc(nc.filename)} - ${esc(a.program_number || "no O-number")} - ${nc.source === "hotfolder" ? "from CAM inbox" : "uploaded"} ${esc(fmt.ago(nc.uploaded_at))}
      <br>Est. cycle ${fmt.dur(a.est_cycle_s)} - deepest Z${a.min_z != null ? a.min_z.toFixed(2) : "?"} - tools ${esc((a.tools || []).map((t) => "T" + t).join(", ") || "-")}</p>
    <ul class="checks">${(a.checks || []).map((c) => `<li>${badge(c.status, "")}<span>${esc(c.title)}<small>${esc(c.message)}</small></span></li>`).join("")}</ul>
    <details style="margin-top:10px"><summary class="faint">Program text</summary><pre class="code mono" data-nc-text="${nc.id}">Loading...</pre></details>
    ${nc.review_status === "pending" ? `<form class="form" data-review="${nc.id}" style="margin-top:12px">
      <div class="cols"><label class="field"><span>Reviewed by</span><input name="by" required value="${esc(operatorName())}"></label>
        <label class="field"><span>Note</span><input name="note" placeholder="optional"></label></div>
      <p class="faint" style="margin:0">Approve only after checking stock, WCS and tools in CAM simulation (CAM-003).</p>
      <div class="row"><button type="submit" name="decision" value="approved" class="primary" ${canApprove ? "" : "disabled"}>Approve</button>
        <button type="submit" name="decision" value="rejected" class="danger">Reject</button>${upload}</div></form>`
      : `<p class="faint" style="margin:10px 0 0">${nc.reviewed_by ? `${esc(nc.review_status)} by ${esc(nc.reviewed_by)} ${esc(fmt.ago(nc.reviewed_at))}${nc.review_note ? ": " + esc(nc.review_note) : ""}` : ""}</p><div class="row" style="margin-top:8px"><a class="btn small" href="/api/nc/${nc.id}/download">Download</a>${upload}</div>`}
  </div>`;
}

function ncHistory(j) {
  const old = j.nc_programs.filter((n) => n.review_status === "superseded");
  if (!old.length) return "";
  return `<details style="margin-top:12px"><summary class="faint">${old.length} earlier version${old.length > 1 ? "s" : ""}</summary>
    <div class="table-wrap"><table><tbody>${old.map((n) => `<tr><td><a href="/api/nc/${n.id}/download">${esc(n.filename)}</a></td><td>${esc(n.side)}</td><td>${badge(n.check_status)}</td><td class="faint">${esc(fmt.ago(n.uploaded_at))}</td></tr>`).join("")}</tbody></table></div></details>`;
}

function bindJawSet(j) {
  const reload = () => jawSet(j.id);
  const uploadDesign = async (files) => {
    const side = $("#design-side").value;
    for (const f of files) {
      try { await api(`/api/jaw-sets/${j.id}/files?side=${side}&filename=${encodeURIComponent(f.name)}`, { method: "POST", body: await readFile(f) }); }
      catch (err) { return toast(`${f.name}: ${err.message}`, true); }
    }
    toast(`${files.length} file${files.length > 1 ? "s" : ""} uploaded and copied to the CAM outbox`);
    reload();
  };
  $("#design-file").addEventListener("change", (e) => e.target.files.length && uploadDesign([...e.target.files]));
  const drop = $("#drop");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); e.dataTransfer.files.length && uploadDesign([...e.dataTransfer.files]); });

  $$("[data-nc-side]").forEach((inp) => inp.addEventListener("change", async () => {
    const f = inp.files[0]; if (!f) return;
    try {
      const nc = await api(`/api/jaw-sets/${j.id}/nc?side=${inp.dataset.ncSide}&filename=${encodeURIComponent(f.name)}`, { method: "POST", body: await readFile(f) });
      toast(nc.check_status === "fail" ? "Program failed a safety check - see the details" : "Program checked; ready for review", nc.check_status === "fail");
      reload();
    } catch (err) { toast(err.message, true); }
  }));
  $$("[data-nc-text]").forEach((pre) => pre.closest("details").addEventListener("toggle", async () => {
    if (pre.dataset.loaded) return;
    const nc = await api(`/api/nc/${pre.dataset.ncText}`);
    pre.textContent = nc.text; pre.dataset.loaded = "1";
  }, { once: true }));
  $$("[data-review]").forEach((form) => form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    store.set("sjc-name", fd.get("by"));
    try {
      await api(`/api/nc/${form.dataset.review}/review`, { method: "POST", json: { decision: e.submitter.value, by: fd.get("by"), note: fd.get("note") } });
      toast(e.submitter.value === "approved" ? "Program approved" : "Program rejected - repost from CAM"); reload();
    } catch (err) { toast(err.message, true); }
  }));
  $("#queue-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try { await api(`/api/jaw-sets/${j.id}/queue`, { method: "POST", json: { need_by: fd.get("need_by") || null, fault: fd.get("fault") || null } }); toast("Added to the queue"); reload(); }
    catch (err) { toast(err.message, true); }
  });
  $("#loc-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const loc = new FormData(e.target).get("location");
    try {
      if (j.location?.startsWith("Rack")) await api(`/api/jaw-sets/${j.id}/collect`, { method: "POST", json: { location: loc, by: operatorName() } });
      else await api(`/api/jaw-sets/${j.id}`, { method: "PATCH", json: { location: loc } });
      toast("Location saved"); reload();
    } catch (err) { toast(err.message, true); }
  });
  $("#edit-set").addEventListener("click", () => openDialog(`<form class="form"><h2>Edit jaw set</h2>
    <label class="field"><span>Name</span><input name="name" required value="${esc(j.name)}"></label>
    <div class="cols"><label class="field"><span>Part number</span><input name="part_number" value="${esc(j.part_number)}"></label>
      <label class="field"><span>Programs</span><select name="program_mode"><option value="per_side" ${j.program_mode === "per_side" ? "selected" : ""}>Left and right differ</option>
        <option value="shared" ${j.program_mode === "shared" ? "selected" : ""}>Both jaws identical</option></select></label></div>
    <label class="field"><span>Notes</span><textarea name="description">${esc(j.description)}</textarea></label>
    <label class="row"><input type="checkbox" name="archived" ${j.archived ? "checked" : ""}> Archived (hide from lists and the CAM inbox)</label>
    <div class="row" style="justify-content:flex-end"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Save</button></div></form>`,
  async (fd) => { await api(`/api/jaw-sets/${j.id}`, { method: "PATCH", json: { ...Object.fromEntries(fd), archived: fd.get("archived") ? 1 : 0 } }); toast("Saved"); reload(); }));
}

// ------------------------------------------------------------------ production jobs
async function jobs() {
  const [list, sets] = await Promise.all([api("/api/jobs"), api("/api/jaw-sets")]);
  view.innerHTML = `
    <div class="page-head"><div><h1>Production jobs</h1><p>Jobs coming up on the Haas and the soft jaws each one needs. Jaws that are not made yet are queued for the next downtime window.</p></div>
      <button class="primary" id="new-job">Add job</button></div>
    <section class="card">${list.length ? `<div class="table-wrap"><table><thead><tr><th>Job</th><th>Qty</th><th>Needed by</th><th>Jaw set</th><th>Jaws ready</th><th>Status</th><th></th></tr></thead><tbody>
      ${list.map((x) => `<tr>
        <td><b>${esc(x.name)}</b><div class="faint">${esc([x.part_number, x.customer].filter(Boolean).join(" - "))}</div></td>
        <td class="num">${esc(x.quantity ?? "-")}</td>
        <td>${x.need_by ? esc(fmt.date(x.need_by)) : "-"}</td>
        <td>${x.jaw_set ? `<a href="#/jaws/${x.jaw_set.id}">${esc(x.jaw_set.name)}</a><div>${stageBadge(x.jaw_set.stage)}</div>` : `<span class="faint">none</span>`}</td>
        <td>${x.jaw_set?.stage.key === "made" ? badge("ok", "Ready") : x.jaws_ready_at ? esc(fmt.dt(x.jaws_ready_at)) : "-"}${x.at_risk ? `<div>${badge("fail", "Not scheduled in time")}</div>` : ""}</td>
        <td><select data-job-status="${x.id}" aria-label="Status">${["planned", "in_production", "done"].map((s) => `<option value="${s}" ${x.status === s ? "selected" : ""}>${s.replace("_", " ")}</option>`).join("")}</select></td>
        <td><button class="small" data-job-edit="${x.id}">Edit</button></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No production jobs. Add the jobs coming up so the cell makes their jaws ahead of time.</div>`}</section>`;
  $("#new-job").addEventListener("click", () => jobDialog(null, sets));
  $$("[data-job-edit]").forEach((b) => b.addEventListener("click", () => jobDialog(list.find((x) => x.id === Number(b.dataset.jobEdit)), sets)));
  $$("[data-job-status]").forEach((s) => s.addEventListener("change", async () => {
    try { await api(`/api/jobs/${s.dataset.jobStatus}`, { method: "PATCH", json: { status: s.value } }); toast("Status updated"); route(); }
    catch (err) { toast(err.message, true); }
  }));
}

function jobDialog(job, sets) {
  openDialog(`<form class="form"><h2>${job ? "Edit job" : "Add production job"}</h2>
    <label class="field"><span>Job name</span><input name="name" required value="${esc(job?.name)}" placeholder="e.g. WO-2291 hex fittings"></label>
    <div class="cols"><label class="field"><span>Part number</span><input name="part_number" value="${esc(job?.part_number)}"></label>
      <label class="field"><span>Customer</span><input name="customer" value="${esc(job?.customer)}"></label></div>
    <div class="cols"><label class="field"><span>Quantity</span><input name="quantity" type="number" min="1" value="${esc(job?.quantity ?? "")}"></label>
      <label class="field"><span>Needed by</span><input name="need_by" type="date" value="${esc(job?.need_by?.slice(0, 10) ?? "")}"></label></div>
    <label class="field"><span>Soft jaws</span><select name="jaw_set_id"><option value="">None / not decided</option>
      ${sets.map((s) => `<option value="${s.id}" ${job?.jaw_set_id === s.id ? "selected" : ""}>${esc(s.name)} - ${esc(s.stage.label)}</option>`).join("")}</select></label>
    <label class="field"><span>Notes</span><textarea name="notes">${esc(job?.notes)}</textarea></label>
    <div class="spread">${job ? `<button type="button" class="danger" id="del-job">Delete</button>` : "<span></span>"}
      <div class="row"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Save</button></div></div></form>`,
  async (fd) => {
    const body = Object.fromEntries(fd);
    body.jaw_set_id = body.jaw_set_id ? Number(body.jaw_set_id) : null;
    body.quantity = body.quantity ? Number(body.quantity) : null;
    body.need_by = body.need_by || null;
    await api(job ? `/api/jobs/${job.id}` : "/api/jobs", { method: job ? "PATCH" : "POST", json: body });
    toast(body.jaw_set_id ? "Saved. Jaws not yet made are queued automatically." : "Saved"); route();
  });
  $("#del-job", dialog)?.addEventListener("click", async () => {
    dialog.close();
    if (!(await confirmDialog("Delete this job?", "Queued jaw runs stay in the queue.", "Delete", true))) return;
    await api(`/api/jobs/${job.id}`, { method: "DELETE" }); toast("Job deleted"); route();
  });
}

// ------------------------------------------------------------------ downtime & queue
async function schedulePage() {
  const [dt, s] = await Promise.all([api("/api/downtime?days=7"), api("/api/status")]);
  STATUS = s;
  const weekly = dt.windows.filter((w) => w.kind === "weekly"), once = dt.windows.filter((w) => w.kind === "once");
  view.innerHTML = `
    <div class="page-head"><div><h1>Downtime &amp; queue</h1><p>Tell the cell when the Haas is free (nights, lunch, changeovers). With auto-run on, queued jaw runs start inside these windows when the whole run fits.</p></div>
      <div class="row"><button id="add-weekly" class="primary">Add weekly window</button><button id="add-once">Add one-off window</button></div></div>
    <div class="grid">
      <section class="card"><div class="card-head"><h2>Next 7 days</h2>
        <div class="legend"><span><i style="background:color-mix(in srgb,var(--green) 45%,transparent)"></i>Machine free</span><span><i style="background:var(--accent)"></i>Planned cell run</span><span><i style="background:var(--danger)"></i>Now</span></div></div>
        ${weekView(dt.upcoming, s.queue, s.now)}</section>
      <div class="grid g2">
        <section class="card"><div class="card-head"><h2>Windows</h2></div>
          ${dt.windows.length ? `<div class="table-wrap"><table><tbody>${[...weekly, ...once].map((w) => `<tr>
            <td><b>${esc(w.label || (w.kind === "weekly" ? "Weekly" : "One-off"))}</b><div class="faint">${esc(w.summary)}</div></td>
            <td><label class="switch"><input type="checkbox" data-dt-toggle="${w.id}" ${w.enabled ? "checked" : ""}> ${w.enabled ? "On" : "Off"}</label></td>
            <td><button class="small danger" data-dt-del="${w.id}">Delete</button></td></tr>`).join("")}</tbody></table></div>`
            : `<div class="empty">No downtime windows. Add the times the Haas is not running production.</div>`}</section>
        <section class="card"><div class="card-head"><h2>Queue</h2><span class="faint">Order: need-by date, then when queued</span></div>${queueTable(s.queue)}</section>
      </div>
    </div>`;
  bindQueue(schedulePage);
  $("#add-weekly").addEventListener("click", () => weeklyDialog(schedulePage));
  $("#add-once").addEventListener("click", () => onceDialog(schedulePage));
  $$("[data-dt-toggle]").forEach((c) => c.addEventListener("change", async () => {
    await api(`/api/downtime/${c.dataset.dtToggle}`, { method: "PATCH", json: { enabled: c.checked ? 1 : 0 } }); schedulePage();
  }));
  $$("[data-dt-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!(await confirmDialog("Delete this window?", "Queued runs are re-planned into the remaining windows.", "Delete", true))) return;
    await api(`/api/downtime/${b.dataset.dtDel}`, { method: "DELETE" }); toast("Window deleted"); schedulePage();
  }));
}

function weeklyDialog(after = route) {
  openDialog(`<form class="form"><h2>Weekly downtime window</h2>
    <label class="field"><span>Label</span><input name="label" placeholder="e.g. Night shift off" required></label>
    <div class="field"><span>Days</span><div class="days">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => `<label><input type="checkbox" name="days" value="${i}" ${i < 5 ? "checked" : ""}>${d}</label>`).join("")}</div></div>
    <div class="cols"><label class="field"><span>From</span><input type="time" name="start_time" value="18:00" required></label>
      <label class="field"><span>Until</span><input type="time" name="end_time" value="06:00" required></label></div>
    <p class="faint" style="margin:0">An end time earlier than the start runs past midnight into the next day.</p>
    <div class="row" style="justify-content:flex-end"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Add</button></div></form>`,
  async (fd) => {
    await api("/api/downtime", { method: "POST", json: { kind: "weekly", label: fd.get("label"), days: fd.getAll("days").join(","), start_time: fd.get("start_time"), end_time: fd.get("end_time") } });
    toast("Window added"); after();
  });
}

function onceDialog(after = route) {
  const now = new Date(); now.setMinutes(0, 0, 0); now.setHours(now.getHours() + 1);
  const end = new Date(now.getTime() + 4 * 3600e3);
  openDialog(`<form class="form"><h2>One-off downtime window</h2>
    <label class="field"><span>Label</span><input name="label" placeholder="e.g. Waiting on material" required></label>
    <div class="cols"><label class="field"><span>From</span><input type="datetime-local" name="start" value="${fmt.local(now)}" required></label>
      <label class="field"><span>Until</span><input type="datetime-local" name="end" value="${fmt.local(end)}" required></label></div>
    <div class="row" style="justify-content:flex-end"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Add</button></div></form>`,
  async (fd) => { await api("/api/downtime", { method: "POST", json: { kind: "once", label: fd.get("label"), start: fd.get("start"), end: fd.get("end") } }); toast("Window added"); after(); });
}

function weekView(windows, queue, nowIso) {
  const now = new Date(nowIso);
  const day0 = new Date(now); day0.setHours(0, 0, 0, 0);
  const pct = (d, base) => Math.max(0, Math.min(100, ((d - base) / 864e5) * 100));
  const rows = [];
  for (let i = 0; i < 7; i++) {
    const base = new Date(day0.getTime() + i * 864e5), next = new Date(base.getTime() + 864e5);
    const bars = [];
    for (const w of windows) {
      const s = new Date(w.start), e = new Date(w.end);
      if (e <= base || s >= next) continue;
      bars.push(`<span class="win" style="left:${pct(s, base)}%;width:${pct(e, base) - pct(s, base)}%" title="${esc(w.label)} ${esc(fmt.dt(w.start))} - ${esc(fmt.time(w.end))}"></span>`);
    }
    for (const q of queue) {
      if (!q.projected?.start) continue;
      const s = new Date(q.projected.start), e = new Date(q.projected.end);
      if (e <= base || s >= next) continue;
      bars.push(`<span class="job" style="left:${pct(s, base)}%;width:max(4px,${pct(e, base) - pct(s, base)}%)" title="${esc(q.jaw_set_name)} ${esc(fmt.time(q.projected.start))}-${esc(fmt.time(q.projected.end))}"></span>`);
    }
    if (i === 0) bars.push(`<span class="nowline" style="left:${pct(now, base)}%"></span>`);
    rows.push(`<div class="day"><span>${esc(base.toLocaleDateString([], { weekday: "short", day: "numeric" }))}</span><div class="bar">${bars.join("")}</div></div>`);
  }
  return `<div class="week"><div class="hours"><span></span><div><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div></div>${rows.join("")}</div>`;
}

// ------------------------------------------------------------------ runs
async function runs() {
  const list = await api("/api/runs");
  view.innerHTML = `
    <div class="page-head"><div><h1>Cell runs</h1><p>Every cycle the cell has run or has queued, with its full event log.</p></div></div>
    <section class="card">${list.length ? `<div class="table-wrap"><table><thead><tr><th>Run</th><th>Jaw set</th><th>Status</th><th>Started</th><th>Finished</th><th>Trigger</th></tr></thead><tbody>
      ${list.map((r) => `<tr class="click" data-href="#/runs/${r.id}"><td><a href="#/runs/${r.id}">Run ${r.id}</a></td><td>${esc(r.jaw_set_name)}</td>
        <td>${runBadge(r.status)}${r.fault?.cause ? `<div class="faint">${esc(r.fault.cause)}</div>` : ""}</td>
        <td>${esc(fmt.dt(r.started_at))}</td><td>${esc(fmt.dt(r.finished_at))}</td><td class="faint">${esc(r.trigger)}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No runs yet.</div>`}</section>`;
  $$("tr[data-href]").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("a")) location.hash = tr.dataset.href; }));
}

const TIMELINE = ["PICK_BLANK", "LOAD_BLANK", "CNC_CYCLE", "UNCLAMP", "RETURN_TO_RACK"];
async function runPage(id) {
  let events = [], lastSeq = 0;
  const describe = (e) => {
    const d = e.data || {};
    if (e.type === "transition") return stateText(d.to);
    if (e.type === "fault") return `FAULT ${d.cause}: ${d.detail}`;
    if (e.type === "command") return `${d.device} ${d.action}${d.to ? " -> " + String(d.to).replace(/_/g, " ") : ""}${d.program_id ? " " + d.program_id : ""}`;
    if (e.type === "confirm") return `check ok: ${CHECK_OK[d.check] || String(d.check).replace(/_/g, " ")}`;
    if (e.type === "ack") return `${d.device} ack${d.at ? " at " + String(d.at).replace(/_/g, " ") : ""}${d.holding !== undefined ? ", holding " + (d.holding || "nothing") : ""}`;
    return e.type;
  };
  // the 3D view lives outside the parts that redraw, so it keeps playing instead of reloading
  view.innerHTML = `<div id="run-top"></div>
    <section class="card sim-card" id="sim-card" hidden style="margin-bottom:16px">
      <div class="card-head"><h2 id="sim-title">Live 3D view</h2>
        <div class="row"><button class="small" id="sim-replay">Replay from start</button><button class="small" id="sim-live" hidden>Follow the run</button>
          <a class="btn small" href="/runs/${id}/sim/" target="_blank" rel="noopener">Full screen</a></div></div>
      <div class="sim-frame"></div>
      <p class="faint" style="margin:8px 0 0">The planner's collision-checked robot paths, driven by this run's event log. Drag to orbit, wheel to zoom.</p>
    </section>
    <div id="run-body"></div>`;
  const simCard = $("#sim-card");
  const simApi = () => $(".sim-frame iframe")?.contentWindow?.__sim;
  $("#sim-replay").addEventListener("click", () => { simApi()?.replay(); $("#sim-live").hidden = false; });
  $("#sim-live").addEventListener("click", () => { simApi()?.followLive(); $("#sim-live").hidden = true; });
  const draw = async () => {
    const r = await api(`/api/runs/${id}?after=${lastSeq}`);
    if (r.replay && !$(".sim-frame iframe")) {
      $(".sim-frame").innerHTML = simFrame(`/runs/${id}/sim/?embed=1&follow=${id}`, `3D view of the cell following run ${id}`);
      simCard.hidden = false;
    }
    events = events.concat(r.events);
    if (events.length) lastSeq = events[events.length - 1].seq;
    const activeStatus = ["planning", "running"].includes(r.status);
    const seen = events.filter((e) => e.type === "transition").map((e) => ({ jaw: e.data?.jaw || "", to: e.data.to }));
    const steps = ["left", "right"].flatMap((side) => TIMELINE.map((st) => ({ side, st })));
    const lastT = seen.length ? seen[seen.length - 1] : null;
    const tl = steps.map(({ side, st }) => {
      const hit = seen.some((x) => x.jaw === side && x.to === st);
      const now = lastT && lastT.jaw === side && lastT.to === st && activeStatus;
      return `<li class="${now ? "now" : hit ? "done" : ""}" title="${side} - ${stateText(st)}"></li>`;
    }).join("");
    const fault = r.fault?.cause ? r.fault : null;
    const inv = r.result?.inventory || {};
    $("#sim-title").textContent = activeStatus ? "Live 3D view" : "3D view";
    $("#run-top").innerHTML = `
      <div class="crumb"><a href="#/runs">Cell runs</a> /</div>
      <div class="page-head"><div><h1>Run ${r.id} - ${esc(r.jaw_set.name)}</h1>
        <p>${runBadge(r.status)} ${esc(r.trigger)} run - queued ${esc(fmt.dt(r.created_at))}${r.started_at ? `, started ${esc(fmt.dt(r.started_at))}` : ""}${r.finished_at ? `, ended ${esc(fmt.dt(r.finished_at))}` : ""}</p></div>
        <div class="row">${activeStatus ? `<button class="stop" data-stop="${r.id}">Stop cell</button>` : ""}
          ${r.status === "queued" ? `<button class="primary" data-start="${r.id}">Start now</button><button data-cancel="${r.id}">Cancel</button>` : ""}</div></div>
      ${r.status === "planning" ? `<div class="banner info" style="margin-bottom:16px">Planning robot paths for rack slots ${r.slots ? `${r.slots.left} and ${r.slots.right}` : ""}. The 3D view appears when the plan is ready.</div>` : ""}
      ${fault ? `<div class="banner" style="margin-bottom:16px"><b>SAFE STOP: ${esc(String(fault.cause).replace(/_/g, " "))}</b> - ${esc(fault.detail || "")}. The interrupted cycle will not resume.</div>` : ""}
      ${r.error ? `<div class="banner" style="margin-bottom:16px">${esc(r.error)}</div>` : ""}`;
    $("#run-body").innerHTML = `
      <div class="grid g-main">
        <div class="grid" style="align-content:start">
          <section class="card"><div class="hero"><div class="stack" style="gap:6px"><span class="label">${activeStatus ? "Now" : "Final state"}</span>
            <div class="state">${esc(stateText(r.state || (r.status === "queued" ? "IDLE" : "")))}${r.jaw && activeStatus ? ` <span class="muted">- ${esc(r.jaw)} jaw</span>` : ""}</div>
            <div class="progress"><span style="width:${Math.round((r.progress || 0) * 100)}%"></span></div></div></div>
            <ol class="timeline" aria-label="Cycle steps, left jaw then right jaw">${tl}</ol>
            <div class="spread faint" style="margin-top:6px"><span>Left jaw</span><span>Right jaw</span></div>
            ${worldKv(r.world)}</section>
          ${r.status === "safe_stop" ? recoveryForm(r, inv) : ""}
          <section class="card"><div class="card-head"><h2>Programs and slots</h2></div>
            ${r.programs ? `<div class="table-wrap"><table><thead><tr><th>Jaw</th><th>Program</th><th>Rack slot</th><th>Cycle</th><th>Grasp Y</th></tr></thead><tbody>
              ${["left", "right"].map((s) => `<tr><td>${s}</td><td class="mono">${esc(r.programs[s].program)}</td><td>${r.slots?.[s] ?? "-"}</td><td>${fmt.dur(r.programs[s].cycle_s)}</td><td class="num">${r.programs[s].grasp_y.toFixed(1)} mm</td></tr>`).join("")}</tbody></table></div>`
              : `<p class="muted">Assigned when the run starts.</p>`}</section>
        </div>
        <section class="card"><div class="card-head"><h2>Event log</h2><span class="faint">${events.length} events${activeStatus ? " - live" : ""}</span></div>
          ${events.length ? `<ul class="feed events">${events.slice().reverse().map((e) => `<li class="${esc(e.type)}"><time>${e.t.toFixed(1)} s</time><span>${esc(describe(e))}</span></li>`).join("")}</ul>`
            : `<div class="empty">${r.status === "queued" ? "Not started." : r.status === "planning" ? "Planning robot paths..." : "No events."}</div>`}</section>
      </div>`;
    bindStop(); bindQueue(() => runPage(id));
    const rf = $("#recover-form");
    rf?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(rf);
      store.set("sjc-name", fd.get("by"));
      try {
        await api(`/api/runs/${id}/recover`, { method: "POST", json: { by: fd.get("by"), locations: { left: fd.get("left"), right: fd.get("right") } } });
        toast("Recovery recorded. The cell can run again."); clearInterval(liveTimer); runPage(id);
      } catch (err) { toast(err.message, true); }
    });
    if (!activeStatus && r.status !== "queued") clearInterval(liveTimer);
  };
  await draw();
  live(draw, 1000);
}

function recoveryForm(r, inv) {
  const opt = (side) => {
    const now = inv[side] || "unknown";
    const guess = now.startsWith("rack:") ? (now.endsWith("finished") ? "finished_in_rack" : "blank_in_rack") : "";
    return `<label class="field"><span>${side[0].toUpperCase() + side.slice(1)} jaw - system last saw it: <b>${esc(now.replace(/_/g, " "))}</b></span>
      <select name="${side}" required><option value="">Where is it now?</option>
        ${[["blank_in_rack", `Unmachined blank, back in rack slot ${r.slots?.[side] ?? "?"}`], ["finished_in_rack", `Finished jaw, in rack slot ${r.slots?.[side] ?? "?"}`],
           ["removed", "Taken out of the cell"], ["scrapped", "Scrapped"]].map(([v, t]) => `<option value="${v}" ${v === guess ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
  };
  return `<section class="card" style="border-color:var(--danger)"><div class="card-head"><h2>Recover the cell</h2></div>
    <p class="muted" style="margin-top:0">Go to the cell, find both jaws, put anything loose back where you say below. Then sign. Auto-run stays paused until this is done.</p>
    <form class="form" id="recover-form">${opt("left")}${opt("right")}
      <label class="field"><span>Recovered by</span><input name="by" required value="${esc(operatorName())}"></label>
      <button type="submit" class="primary">Confirm jaw locations</button></form></section>`;
}

// ------------------------------------------------------------------ CAM link
async function camPage() {
  const c = await api("/api/cam");
  const su = c.setup, b = su.blank;
  view.innerHTML = `
    <div class="page-head"><div><h1>CAM link</h1><p>How jaw designs get to Mastercam (or any CAM) and posted programs come back. Uses two shared folders, so it works without plug-ins.</p></div>
      <button id="scan">Scan inbox now</button></div>
    <div class="grid g2">
      <section class="card"><h2>Folders</h2><div class="stack">
        <div><span class="label">Outbox - the site writes here</span><div class="copy"><code>${esc(c.outbox)}</code><button class="small" data-copy="${esc(c.outbox)}">Copy</button></div>
          <p class="faint">One folder per jaw set: the uploaded design files, <code>blank_top_face.dxf</code> (stock outline in the jaw WCS), <code>jaw_setup.json</code> and a README with the limits below.</p></div>
        <div><span class="label">Inbox - post NC here</span><div class="copy"><code>${esc(c.inbox)}</code><button class="small" data-copy="${esc(c.inbox)}">Copy</button></div>
          <p class="faint">Files named <code>&lt;jaw-set&gt;_left.nc</code> / <code>_right.nc</code> (or <code>&lt;jaw-set&gt;.nc</code> for one shared program) are picked up within a few seconds, checked, and held for approval. Imported files move to <code>imported/</code>.</p></div>
        <p class="faint">Put both folders on a network share the CAM PC can see, then set them in <a href="#/settings">Settings</a>.</p></div></section>
      <section class="card"><h2>Mastercam setup</h2><ol class="muted" style="padding-left:18px;margin:0;display:grid;gap:6px">
        <li>Open the jaw set's outbox folder; import the design (STEP/STL) and <code>blank_top_face.dxf</code>.</li>
        <li>Stock: ${esc(b.material)} ${b.thickness} x ${b.width} x ${b.height} mm. WCS: ${esc(su.wcs)}.</li>
        <li>Pocket from the top face. Deepest cut <b>Z-${su.max_cut_depth}</b>: the blank stands ${su.exposed_above_hard_jaws} mm above the hard jaws.</li>
        <li>Leave at least ${su.finger_width + 4} mm of intact jaw beside the pocket, ${su.finger_grip_depth} mm deep, for the robot's fingers.</li>
        <li>Post with your Haas post (G54, G21 or G20, ends with M30) straight into the inbox using the jaw set's file names.</li>
        <li>Review and approve the program on the jaw set page.</li></ol></section>
      <section class="card"><h2>Inbox status</h2>
        ${Object.keys(c.unmatched).length ? `<div class="stack">${Object.entries(c.unmatched).map(([n, why]) => `<div class="alert"><span><b>${esc(n)}</b> - ${esc(why)}</span></div>`).join("")}</div>` : `<div class="empty">Nothing waiting in the inbox.</div>`}
        ${c.imported.length ? `<h3 style="margin:14px 0 6px">Recently imported</h3><ul class="feed">${c.imported.map((n) => `<li><time>${esc(n.slice(0, 8))}</time><span class="mono">${esc(n.slice(16))}</span></li>`).join("")}</ul>` : ""}</section>
      <section class="card"><h2>What the checks cover</h2><ul class="muted" style="padding-left:18px;margin:0;display:grid;gap:4px">
        <li>Program end (M30/M02), units and work offset declared</li><li>Deepest cut stays ${2} mm above the hard jaws</li>
        <li>No rapid moves into or through the blank; spindle on and feed set while cutting</li><li>Cutting stays on the blank top face</li>
        <li>Room beside the pocket for the fingers to pick up the finished jaw</li><li>Cycle time estimate from feeds and rapids</li></ul>
        <p class="faint">They catch setup mistakes; they do not replace CAM simulation and a person's approval.</p>
        ${su.unverified.length ? `<p class="faint">Limits use ${su.unverified.length} unmeasured values (e.g. ${esc(su.unverified[0])}). Measure them before trusting the depth limit.</p>` : ""}</section>
    </div>`;
  $$("[data-copy]").forEach((btn) => btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(btn.dataset.copy); toast("Copied"); } catch { toast("Copy failed; select the path instead", true); }
  }));
  $("#scan").addEventListener("click", async () => {
    const r = await api("/api/cam/scan", { method: "POST" });
    toast(r.imported.length ? `Imported ${r.imported.length} program(s)` : "No new programs"); camPage();
  });
}

// ------------------------------------------------------------------ settings
async function settingsPage() {
  const s = await api("/api/settings");
  view.innerHTML = `
    <div class="page-head"><div><h1>Settings</h1><p>Shared by everyone using this cell.</p></div></div>
    <section class="card" style="max-width:720px"><form class="form" id="settings">
      <label class="field"><span>CAM outbox folder (design packages for the programmer)</span><input name="outbox_dir" value="${esc(s.outbox_dir)}"></label>
      <label class="field"><span>CAM inbox folder (posted NC comes back here)</span><input name="inbox_dir" value="${esc(s.inbox_dir)}"></label>
      <div class="cols">
        <label class="field"><span>Simulation speed (x real time)</span><input name="sim_speed" type="number" min="0.1" max="1000" step="0.1" value="${esc(s.sim_speed)}"></label>
        <label class="field"><span>Tool radius assumed by NC checks (mm)</span><input name="tool_radius" type="number" min="0" step="0.5" value="${esc(s.tool_radius)}"></label>
      </div>
      <label class="row"><input type="checkbox" name="auto_run" ${s.auto_run ? "checked" : ""}> Start queued runs automatically in downtime windows</label>
      <label class="row"><input type="checkbox" name="auto_queue_for_jobs" ${s.auto_queue_for_jobs ? "checked" : ""}> Queue a jaw run when a production job needs jaws that are not made</label>
      <label class="field"><span>Your name (this browser only; pre-fills reviews and recoveries)</span><input name="me" value="${esc(operatorName())}"></label>
      <div class="row"><button type="submit" class="primary">Save</button></div></form></section>`;
  $("#settings").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    store.set("sjc-name", fd.get("me") || "");
    try {
      await api("/api/settings", { method: "PATCH", json: { outbox_dir: fd.get("outbox_dir"), inbox_dir: fd.get("inbox_dir"), sim_speed: Number(fd.get("sim_speed")),
        tool_radius: Number(fd.get("tool_radius")), auto_run: !!fd.get("auto_run"), auto_queue_for_jobs: !!fd.get("auto_queue_for_jobs") } });
      toast("Settings saved"); refreshStatus();
    } catch (err) { toast(err.message, true); }
  });
}

// ------------------------------------------------------------------ boot
refreshStatus();
setInterval(() => { if (!liveTimer) refreshStatus(); }, 4000);
route();
