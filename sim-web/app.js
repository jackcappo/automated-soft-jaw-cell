/* global BABYLON, SoftJawKin, CELL_PLAN */
/* Replays the motion plan and orchestrator event logs produced by
 * `python -m softjaw sim`. Nothing here decides motion: every robot pose comes
 * from the planner's IK paths (collision-checked in Python), and every device
 * state comes from the orchestrator's logged world snapshots. */
"use strict";

const PLAN = window.CELL_PLAN;
const MM = 0.001;
const $ = (id) => document.getElementById(id);

if (!PLAN || !window.BABYLON) {
  $("run-status").textContent = !PLAN ? "cell-plan.js missing: run python -m softjaw sim" : "Babylon.js failed to load";
  throw new Error("simulator prerequisites missing");
}

// ------------------------------------------------------------------ scene
const canvas = $("render-canvas");
const engine = new BABYLON.Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true });
const scene = new BABYLON.Scene(engine);
scene.useRightHandedSystem = true;              // URDF / world frame is right-handed, Z up
scene.clearColor = new BABYLON.Color4(0.025, 0.04, 0.055, 1);

const camera = new BABYLON.ArcRotateCamera("cam", 0, 0, 2.6, new BABYLON.Vector3(0.0, -0.05, 0.85), scene);
camera.upVector = new BABYLON.Vector3(0, 0, 1);
camera.setPosition(new BABYLON.Vector3(-1.55, -1.75, 1.75));
camera.lowerRadiusLimit = 0.5;
camera.upperRadiusLimit = 6;
camera.wheelDeltaPercentage = 0.012;
camera.panningSensibility = 900;
camera.minZ = 0.01;
camera.attachControl(canvas, true);
if (/[?&]embed\b/.test(typeof location !== "undefined" ? location.search || "" : "")) {
  // embedded panels are narrower than a full page: fix the horizontal field of view so the whole cell fits across
  camera.fovMode = BABYLON.Camera.FOVMODE_HORIZONTAL_FIXED;
  camera.fov = 1.15;
}

new BABYLON.HemisphericLight("sky", new BABYLON.Vector3(-0.3, -0.4, 1), scene).intensity = 0.85;
const sun = new BABYLON.DirectionalLight("sun", new BABYLON.Vector3(0.4, 0.6, -1), scene);
sun.intensity = 0.55;

function mat(name, hex, alpha = 1, emissive = 0) {
  const m = new BABYLON.StandardMaterial(name, scene);
  m.diffuseColor = BABYLON.Color3.FromHexString(hex);
  m.specularColor = new BABYLON.Color3(0.12, 0.13, 0.14);
  m.alpha = alpha;
  if (emissive) m.emissiveColor = BABYLON.Color3.FromHexString(hex).scale(emissive);
  if (alpha < 1) m.backFaceCulling = false;
  return m;
}
const M = {
  floor: mat("floor", "#17222b"), machine: mat("machine", "#c9d1d4"), wall: mat("wall", "#c9d1d4", 0.16),
  table: mat("table", "#495963"), jaw: mat("jaw", "#5d86b5"), stat: mat("stat", "#2a3a46"),
  robot: mat("robot", "#c9e52d", 0.92), robotDark: mat("robotDark", "#20292e"), blank: mat("blank", "#e6a05d"),
  finished: mat("finished", "#4fce8b"), door: mat("door", "#47808b", 0.3), spindle: mat("spindle", "#aab5b8"),
  hot: mat("hot", "#ef6464", 1, 0.5), fault: mat("fault", "#ef6464", 0.95, 0.4),
  cart: mat("cart", "#4a6a80"), deck: mat("deck", "#8a9aa3"), tyre: mat("tyre", "#15191c"), dock: mat("dock", "#d9a93a"),
};

const ground = BABYLON.MeshBuilder.CreateGround("ground", { width: 14, height: 14 }, scene);   // shop floor to the horizon
ground.rotation.x = Math.PI / 2;                  // Babylon ground lies in XZ; turn it into the XY floor
ground.position.copyFromFloats(0.4, 0, -0.001);
ground.material = M.floor;

function boxFromMinMax(name, lo, hi, material) {
  const b = BABYLON.MeshBuilder.CreateBox(name, { size: 1 }, scene);
  b.scaling.copyFromFloats((hi[0] - lo[0]) * MM, (hi[1] - lo[1]) * MM, (hi[2] - lo[2]) * MM);
  b.position.copyFromFloats((hi[0] + lo[0]) / 2 * MM, (hi[1] + lo[1]) / 2 * MM, (hi[2] + lo[2]) / 2 * MM);
  b.material = material;
  return b;
}

// caster box -> swivel mount plate + fork + wheel rolling along X (cylinder axis is local Y = world Y)
function casterFromBox(name, lo, hi) {
  const plate = 12, d = Math.min(hi[0] - lo[0], hi[2] - lo[2] - plate - 10);
  const cx = (lo[0] + hi[0]) / 2, cy = (lo[1] + hi[1]) / 2;
  boxFromMinMax(`${name}-plate`, [cx - 45, cy - 45, hi[2] - plate], [cx + 45, cy + 45, hi[2]], M.cart);
  boxFromMinMax(`${name}-fork`, [cx - 20, lo[1], lo[2] + d / 2], [cx + 20, hi[1], hi[2] - plate], M.cart);
  const w = BABYLON.MeshBuilder.CreateCylinder(`${name}-wheel`, { diameter: d * MM, height: (hi[1] - lo[1] - 16) * MM, tessellation: 24 }, scene);
  w.position.copyFromFloats(cx * MM, cy * MM, (lo[2] + d / 2) * MM);
  w.material = M.tyre;
  return w;
}

const meshes = {};
PLAN.boxes.forEach((b) => {
  if (b.kind === "rack_blank") return;             // rack contents are drawn from the event snapshots
  if (b.kind === "cart_caster") { meshes[b.name] = casterFromBox(b.name, b.min, b.max); return; }
  const material = b.name.startsWith("front_wall") ? M.wall : b.name === "table" ? M.table
    : b.name === "spindle_head" ? M.spindle : b.kind === "vise_jaw" ? M.jaw : b.kind === "machine" ? M.machine
    : b.name === "cart_deck" ? M.deck : b.kind === "cart" ? M.cart : b.name === "dock_block" ? M.dock : M.stat;
  meshes[b.name] = boxFromMinMax(b.name, b.min, b.max, material);
});

// door panel across the opening between the two side wall pieces
const wl = PLAN.boxes.find((b) => b.name === "front_wall_left"), wr = PLAN.boxes.find((b) => b.name === "front_wall_right");
const door = boxFromMinMax("door", [-20, wr.max[1], wl.min[2]], [-10, wl.min[1], wl.max[2]], M.door);
const doorWidth = (wl.min[1] - wr.max[1]) * MM;

// ------------------------------------------------------------------ optional machine model
// sim-web/assets/machine.stl (from tools/import_machine_model.py) or an embedded copy in a
// bundled page. Purely visual: the planner's collision boxes stay authoritative.
const machineModel = { mesh: null };
function buildMachineMesh(buffer, source) {
  const stl = SoftJawStl.parse(buffer);
  const pos = new Float32Array(stl.positions.length);
  for (let i = 0; i < pos.length; i++) pos[i] = stl.positions[i] * MM;
  const idx = new Uint32Array(stl.count * 3).map((_, i) => i);
  const normals = [];
  BABYLON.VertexData.ComputeNormals(pos, idx, normals);
  const vd = new BABYLON.VertexData();
  vd.positions = pos; vd.indices = idx; vd.normals = normals;
  const mesh = new BABYLON.Mesh("machine-model", scene);
  vd.applyToMesh(mesh);
  mesh.material = mat("machine-model", "#d8dee0", 0.45);
  mesh.isPickable = false;
  machineModel.mesh = mesh;
  // the detailed model replaces the plain enclosure walls and door (it has its own); keep
  // table, vise and spindle boxes. Door state is still shown in the live-state panel.
  const plain = () => PLAN.boxes.filter((b) => b.name.startsWith("front_wall")).map((b) => meshes[b.name]).concat([door]);
  plain().forEach((m) => m.setEnabled(false));
  const box = $("show-model");
  box.disabled = false;
  $("model-label").textContent = `Machine model (${stl.count.toLocaleString()} triangles)`;
  $("model-note").textContent = `Loaded from ${source}. Visual only; collision uses the measured boxes.`;
  box.addEventListener("change", () => {
    mesh.setEnabled(box.checked);
    plain().forEach((m) => m.setEnabled(!box.checked));
  });
}
function loadMachineModel() {
  try {
    if (window.MACHINE_STL_B64) return buildMachineMesh(SoftJawStl.fromBase64(window.MACHINE_STL_B64), "the bundled page");
  } catch (err) { console.warn("embedded machine model unusable", err); }
  if (typeof fetch !== "function" || location.protocol === "file:") return;   // fetch needs a local web server
  fetch("assets/machine.stl").then((r) => (r.ok ? r.arrayBuffer() : null))
    .then((buf) => { if (buf) buildMachineMesh(buf, "sim-web/assets/machine.stl"); })
    .catch(() => {});                                  // no model: plain boxes remain
}
loadMachineModel();

// ------------------------------------------------------------------ robot
const R = PLAN.robot;
const radii = PLAN.robot.radii;
const links = [], joints = [];
for (let k = 0; k < 7; k++) {
  const c = BABYLON.MeshBuilder.CreateCylinder(`link${k}`, { diameter: 1, height: 1, tessellation: 20 }, scene);
  c.material = k === 6 ? M.robotDark : M.robot;
  c.rotationQuaternion = new BABYLON.Quaternion();
  links.push(c);
  const s = BABYLON.MeshBuilder.CreateSphere(`jointball${k}`, { diameter: 1, segments: 12 }, scene);
  s.material = M.robotDark;
  s.scaling.setAll(2 * radii[Math.min(k, radii.length - 1)] * MM * 0.98);
  joints.push(s);
}
const fingers = [0, 1].map((i) => {
  const f = BABYLON.MeshBuilder.CreateBox(`finger${i}`, { size: 1 }, scene);
  f.material = M.robotDark;
  f.rotationQuaternion = new BABYLON.Quaternion();
  return f;
});
const G = PLAN.gripper, B = PLAN.blank;

function payloadMesh(name) {
  const m = BABYLON.MeshBuilder.CreateBox(name, { size: 1 }, scene);
  m.scaling.copyFromFloats(B.T * MM, B.W * MM, B.H * MM);
  m.material = M.blank;
  return m;
}
const payloads = { left: payloadMesh("left"), right: payloadMesh("right") };

const UP = new BABYLON.Vector3(0, 1, 0);
function orientCylinder(mesh, a, b, r) {
  const va = new BABYLON.Vector3(a[0] * MM, a[1] * MM, a[2] * MM), vb = new BABYLON.Vector3(b[0] * MM, b[1] * MM, b[2] * MM);
  const d = vb.subtract(va), len = d.length();
  mesh.position = va.add(vb).scale(0.5);
  mesh.scaling.copyFromFloats(2 * r * MM, Math.max(len, 1e-4), 2 * r * MM);
  const dir = len > 1e-9 ? d.scale(1 / len) : UP;
  const axis = BABYLON.Vector3.Cross(UP, dir);
  const ang = Math.acos(Math.max(-1, Math.min(1, BABYLON.Vector3.Dot(UP, dir))));
  mesh.rotationQuaternion = axis.length() < 1e-9 ? (ang > 1 ? BABYLON.Quaternion.RotationAxis(new BABYLON.Vector3(1, 0, 0), Math.PI) : BABYLON.Quaternion.Identity())
    : BABYLON.Quaternion.RotationAxis(axis.normalize(), ang);
}

function quatFromFrame(T) {
  // T is row-major with column vectors as axes; Babylon matrices use row vectors, so pass the transpose.
  const m = BABYLON.Matrix.FromValues(T[0], T[4], T[8], 0, T[1], T[5], T[9], 0, T[2], T[6], T[10], 0, 0, 0, 0, 1);
  return BABYLON.Quaternion.FromRotationMatrix(m);
}

let tcpFrame = null;
function setPose(q, gripClosed) {
  const F = SoftJawKin.frames(R, q);
  const P = F.map((T) => [T[3], T[7], T[11]]);
  for (let k = 0; k < 7; k++) {
    orientCylinder(links[k], P[k], P[k + 1], radii[Math.min(k, radii.length - 1)]);
    joints[k].position.copyFromFloats(P[k][0] * MM, P[k][1] * MM, P[k][2] * MM);
  }
  const T = F[F.length - 1];
  tcpFrame = T;
  const ax = [T[0], T[4], T[8]], fy = [T[1], T[5], T[9]], tcp = [T[3], T[7], T[11]];
  const half = B.T / 2 + (gripClosed ? 4 + 3 : 18);
  const q0 = quatFromFrame(T);
  fingers.forEach((f, i) => {
    const s = i ? -1 : 1;
    // finger extends from the tips back toward the flange along -approach
    const c = [0, 1, 2].map((k) => tcp[k] + s * fy[k] * half - ax[k] * G.finger_length / 2);
    f.position.copyFromFloats(c[0] * MM, c[1] * MM, c[2] * MM);
    f.scaling.copyFromFloats(G.finger_length * MM, 6 * MM, G.finger_width * MM);
    f.rotationQuaternion = q0;
  });
  state.q = q.slice();
  updateJointControls();
}

// ------------------------------------------------------------------ playback model
const state = { scenario: "nominal", t: 0, playing: false, speed: 10, q: null, events: [], idx: 0, manual: false };

function segFor(jaw, from, to) {
  return (PLAN.segments[jaw] || []).find((s) => s.from === from && s.to === to);
}
function jointsAt(jaw, name) {
  return (PLAN.joints[jaw] && PLAN.joints[jaw][name]) || PLAN.joints.left[name] || PLAN.joints.left.home;
}
function samplePath(path, u) {
  const e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
  const x = e * (path.length - 1), i = Math.min(path.length - 2, Math.floor(x)), f = x - i;
  return path[i].map((v, k) => v + (path[i + 1][k] - v) * f);
}

/** Robot moves as [t0, t1, jaw, path] intervals, built from command/ack pairs. */
function buildMotion(events) {
  const moves = [];
  events.forEach((e, i) => {
    if (e.type === "command" && e.device === "robot") {
      const ack = events.slice(i + 1).find((a) => a.type === "ack" && a.device === "robot");
      const seg = segFor(e.jaw, e.frm, e.to);
      if (ack && seg) moves.push({ t0: e.t, t1: ack.t, jaw: e.jaw, path: seg.path, to: e.to });
    }
  });
  return moves;
}

function currentEvent(t) {
  let e = state.events[0];
  for (const ev of state.events) { if (ev.t <= t) e = ev; else break; }
  return e;
}

function robotPose(t, ev) {
  const m = state.moves.find((mv) => t >= mv.t0 && t < mv.t1);
  if (m) return samplePath(m.path, (t - m.t0) / Math.max(1e-6, m.t1 - m.t0));
  return jointsAt(ev.jaw || "left", ev.world.robot_at).slice();
}

const slotOf = {};
Object.entries(PLAN.job.slots).forEach(([side, slot]) => { slotOf[slot] = side; });

function placeBlank(mesh, center, finished) {
  mesh.setEnabled(true);
  mesh.position.copyFromFloats(center[0] * MM, center[1] * MM, center[2] * MM);
  mesh.material = finished ? M.finished : M.blank;
}

function applyWorld(w, gripClosed) {
  // door slides sideways, spindle glows while running
  const tDoor = w.door_open ? doorWidth * 0.95 : 0;
  door.position.y += ((wr.max[1] + wl.min[1]) / 2 * MM + tDoor - door.position.y) * 0.15;
  meshes.spindle_head.material = w.spindle ? M.hot : M.spindle;
  const jm = meshes.hard_jaw_moving;
  const clampShift = w.clamped ? 6 * MM : 0;       // moving jaw closes the loading gap
  const jb = PLAN.boxes.find((b) => b.name === "hard_jaw_moving");
  jm.position.x = (jb.min[0] + jb.max[0]) / 2 * MM + clampShift;
  Object.values(payloads).forEach((m) => m.setEnabled(false));
  // rack contents
  Object.entries(w.rack).forEach(([slot, item]) => {
    if (!item || item === "unexpected_object") return;
    const side = item.split("_")[0], c = PLAN.rack_slots[Number(slot)];
    placeBlank(payloads[side], [c[0], c[1], c[2] + B.H / 2], item.endsWith("finished"));
  });
  if (w.vise_holds) {
    const side = w.vise_holds.split("_")[0], c = PLAN.vise_blank_center;
    placeBlank(payloads[side], c, w.vise_holds.endsWith("finished"));
  }
  if (w.holding && tcpFrame) {
    const side = w.holding.split("_")[0], fin = w.holding.endsWith("finished");
    const gy = fin ? (PLAN.job.grasp_y[side] || 0) : 0;
    const T = tcpFrame, tcp = [T[3], T[7], T[11]];
    placeBlank(payloads[side], [tcp[0], tcp[1] - gy, tcp[2] + G.finger_grip_depth - B.H / 2], fin);
  }
}

// ------------------------------------------------------------------ UI
const ui = { play: $("play-button"), reset: $("reset-button"), status: $("run-status"), pill: $("status-pill"), scen: $("scenario"), speed: $("speed"),
  banner: $("fault-banner"), log: $("event-log"), timeline: $("timeline"), joints: $("joint-controls") };
const DESCR = { nominal: "Full left + right jaw cycle, no faults." };
// optional per-scenario {label, note}, e.g. the shop app's replay of one logged run
const NOTES = PLAN.scenario_notes || {};
const scenarioLabel = (name) => NOTES[name]?.label || (name === "nominal" ? "Nominal cycle" : `Fault: ${name.replaceAll("_", " ")}`);
const scenarioNote = (name) => NOTES[name]?.note || DESCR[name] || `Injected fault: ${name.replaceAll("_", " ")}. Expect SAFE_STOP with no further commands.`;

$("job-id").textContent = PLAN.job.job_id;
$("job-meta").textContent = `jaw release: ${PLAN.job.release_status} / program ${PLAN.job.program_id} / slots L${PLAN.job.slots.left} R${PLAN.job.slots.right}`;
$("plan-checks").textContent = `${PLAN.plan_issues.length} reach/collision issues in the plan. `
  + (PLAN.reach_margin_mm != null ? `Reach margin: vise could sit ${PLAN.reach_margin_mm} mm further inside. ` : "")
  + `Layout uses estimated dimensions until measured.`;
Object.keys(PLAN.scenarios).forEach((name) => {
  const o = document.createElement("option");
  o.value = name;
  o.textContent = scenarioLabel(name);
  ui.scen.appendChild(o);
});

R.joints.forEach((j, i) => {
  const row = document.createElement("label");
  row.className = "joint-control";
  row.innerHTML = `<span>J${i + 1}</span><input type="range" min="${j.lower}" max="${j.upper}" step="0.01" value="0"><output>0°</output>`;
  row.querySelector("input").addEventListener("input", (ev) => {
    state.playing = false; state.manual = true;
    const q = state.q.slice(); q[i] = Number(ev.target.value);
    setPose(q, false);
    refreshButtons();
  });
  ui.joints.appendChild(row);
});
function updateJointControls() {
  [...ui.joints.children].forEach((row, i) => {
    row.querySelector("input").value = String(state.q[i]);
    row.querySelector("output").textContent = `${Math.round(state.q[i] * 180 / Math.PI)}°`;
  });
}

function loadScenario(name) {
  state.scenario = name;
  const s = PLAN.scenarios[name];
  state.events = s.events;
  state.moves = buildMotion(s.events);
  state.end = s.events[s.events.length - 1].t;
  state.t = 0; state.playing = false; state.manual = false;
  const fault = s.events.find((e) => e.type === "fault");
  ui.banner.hidden = true;
  $("scenario-note").textContent = scenarioNote(name);
  ui.timeline.innerHTML = "";
  s.events.filter((e) => e.type === "transition").forEach((e) => {
    const li = document.createElement("li");
    li.dataset.t = e.t;
    li.innerHTML = `<span></span><small>${e.to.replaceAll("_", " ")}</small>`;
    if (e.to === "SAFE_STOP") li.classList.add("fault");
    ui.timeline.appendChild(li);
  });
  ui.log.innerHTML = "";
  state.logged = 0;
  state.fault = fault;
  render(0);
  refreshButtons();
}

function refreshButtons() {
  ui.play.textContent = state.playing ? "Pause" : state.t >= state.end ? "Replay" : "Run";
}

function render(t) {
  const ev = currentEvent(t);
  const w = ev.world;
  if (!state.manual) setPose(robotPose(t, ev), !!w.holding);
  applyWorld(w);
  $("t-state").textContent = ev.type === "transition" ? ev.to : ev.state;
  $("t-jaw").textContent = ev.jaw || "-";
  $("t-time").textContent = `${t.toFixed(1)} s`;
  $("t-robot").textContent = w.robot_at.replaceAll("_", " ");
  $("t-door").textContent = w.door_open ? "Open" : "Closed";
  $("t-spindle").textContent = w.alarm ? "ALARM" : w.spindle ? "Running" : "Stopped";
  $("t-vise").textContent = w.clamped ? "Clamped" : "Open";
  $("t-hold").textContent = w.holding ? w.holding.replace("_", " ") : "-";
  const stateName = $("t-state").textContent;
  ui.status.textContent = state.playing ? `Running / ${stateName}` : stateName === "COMPLETE" ? "Complete" : stateName === "SAFE_STOP" ? "SAFE STOP" : "Paused";
  ui.pill.classList.toggle("stopped", stateName === "SAFE_STOP");
  ui.pill.classList.toggle("done", stateName === "COMPLETE");
  if (state.fault && t >= state.fault.t) {
    ui.banner.hidden = false;
    ui.banner.textContent = `SAFE_STOP: ${state.fault.cause.replaceAll("_", " ")}. ${state.fault.detail}. Automatic motion inhibited; operator recovery required.`;
  }
  [...ui.timeline.children].forEach((li, i, arr) => {
    const t0 = Number(li.dataset.t), t1 = i + 1 < arr.length ? Number(arr[i + 1].dataset.t) : Infinity;
    li.classList.toggle("active", t >= t0 && t < t1);
    li.classList.toggle("complete", t >= t1);
  });
  while (state.logged < state.events.length && state.events[state.logged].t <= t) {
    const e = state.events[state.logged++];
    if (e.type !== "transition" && e.type !== "fault" && e.type !== "command") continue;
    const li = document.createElement("li");
    li.className = e.type;
    li.textContent = `${e.t.toFixed(1)}s ` + (e.type === "transition" ? `-> ${e.to}` : e.type === "fault" ? `FAULT ${e.cause}` : `${e.device} ${e.action}${e.to ? " " + e.to : ""}`);
    ui.log.appendChild(li);
    ui.log.scrollTop = ui.log.scrollHeight;
  }
}

ui.scen.addEventListener("change", () => loadScenario(ui.scen.value));
ui.speed.addEventListener("change", () => { state.speed = Number(ui.speed.value); });
ui.reset.addEventListener("click", () => loadScenario(state.scenario));
ui.play.addEventListener("click", () => {
  if (state.t >= state.end) loadScenario(state.scenario);
  state.manual = false;
  state.playing = !state.playing;
  refreshButtons();
});

// ------------------------------------------------------------------ follow a live run (shop app)
// ?follow=<run id> tracks the shop app's playback clock (GET /api/runs/<id>/clock) instead of the
// local play button; ?embed hides the side panel for use inside the shop app's run monitor.
const params = new URLSearchParams(typeof location !== "undefined" && location.search ? location.search : "");
if (params.has("embed") && document.body) document.body.classList.add("embed");
const follow = { run: params.get("follow"), on: false, simT: 0, speed: 1, at: 0, status: null };
const badge = document.createElement("div");
badge.className = "embed-badge";
$("render-canvas")?.parentElement?.appendChild?.(badge);
async function pollClock() {
  try {
    const c = await (await fetch(`/api/runs/${follow.run}/clock`, { cache: "no-store" })).json();
    Object.assign(follow, { simT: c.sim_t || 0, speed: c.speed || 1, at: performance.now(), status: c.status });
  } catch { /* keep the last known clock */ }
}
if (follow.run && typeof fetch === "function") {
  follow.on = true;
  pollClock();
  setInterval(() => { if (follow.on && ["planning", "running", null].includes(follow.status)) pollClock(); }, 1000);
}
// ?idle shows the cell at rest between runs: robot home, door shut, and the shop app's live rack
// contents (GET /api/rack, one blank per slot).
const idle = { on: params.has("idle") && !follow.on, rack: null };
const idleBlanks = PLAN.rack_slots.map((_, i) => { const m = payloadMesh(`idle-slot-${i}`); m.setEnabled(false); return m; });
async function pollRack() {
  try { idle.rack = await (await fetch("/api/rack", { cache: "no-store" })).json(); } catch { /* keep the last rack */ }
}
if (idle.on && typeof fetch === "function") {
  pollRack();
  setInterval(pollRack, 3000);
  if (document.body) document.body.classList.add("idle");
}
function applyIdle() {
  const w = state.events[0].world;
  applyWorld({ ...w, rack: {}, holding: null, vise_holds: null, door_open: false, spindle: false, clamped: false, alarm: false });
  (idle.rack || []).forEach((r) => {
    const m = idleBlanks[r.slot], c = PLAN.rack_slots[r.slot];
    if (!m || !c) return;
    if (r.content === "blank" || r.content === "finished") placeBlank(m, [c[0], c[1], c[2] + B.H / 2], r.content === "finished");
    else m.setEnabled(false);
  });
}

function followTime(now) {
  const live = follow.status === "running";
  return Math.min(state.end, follow.simT + (live ? (now - follow.at) / 1000 * follow.speed : 0));
}

let last = performance.now();
engine.runRenderLoop(() => {
  const now = performance.now(), dt = Math.min(0.1, (now - last) / 1000);   // no jump after a hidden tab
  last = now;
  if (follow.on) {
    state.playing = false; state.manual = false;
    state.t = followTime(now);
    render(state.t);
    badge.textContent = follow.status === "running" ? "LIVE" : follow.status === "complete" ? "Run complete" : follow.status === "safe_stop" ? "Stopped" : "Waiting";
    badge.dataset.live = follow.status === "running" ? "1" : "";
  } else if (idle.on) {
    applyIdle();
    badge.textContent = "Idle";
  } else if (state.playing) {
    const ev = currentEvent(state.t);
    const machining = ev.state === "CNC_CYCLE" || (ev.type === "transition" && ev.to === "CYCLE_COMPLETE");
    state.t = Math.min(state.end, state.t + dt * state.speed * (machining ? 6 : 1));
    if (state.t >= state.end) state.playing = false;
    render(state.t);
    refreshButtons();
  } else {
    applyWorld(currentEvent(state.t).world);
  }
  scene.render();
});
window.addEventListener("resize", () => engine.resize());
// the canvas can change size without a window resize (embedded frames, layout settling), so watch it directly
if (typeof ResizeObserver === "function") new ResizeObserver(() => engine.resize()).observe(canvas);
// give the WebGL context back as soon as the page goes away (browsers cap live contexts per tab)
window.addEventListener("pagehide", () => { try { engine.dispose(); } catch { /* already gone */ } });
canvas.addEventListener("webglcontextlost", () => { window.__simLost = true; });
window.__sim = {
  state, loadScenario, render,                        // test hook
  replay() { follow.on = false; loadScenario(state.scenario); state.playing = true; badge.textContent = "Replay"; badge.dataset.live = ""; refreshButtons(); },
  followLive() { if (follow.run) { follow.on = true; pollClock(); } },
  get following() { return follow.on; },
};

loadScenario(PLAN.scenarios.nominal ? "nominal" : Object.keys(PLAN.scenarios)[0]);
document.body?.classList?.remove("load-failed");     // started after all, e.g. after a slow download
