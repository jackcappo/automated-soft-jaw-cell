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
};

const ground = BABYLON.MeshBuilder.CreateGround("ground", { width: 3.2, height: 2.6 }, scene);
ground.rotation.x = Math.PI / 2;                  // Babylon ground lies in XZ; turn it into the XY floor
ground.position.copyFromFloats(0.1, 0, -0.001);
ground.material = M.floor;

function boxFromMinMax(name, lo, hi, material) {
  const b = BABYLON.MeshBuilder.CreateBox(name, { size: 1 }, scene);
  b.scaling.copyFromFloats((hi[0] - lo[0]) * MM, (hi[1] - lo[1]) * MM, (hi[2] - lo[2]) * MM);
  b.position.copyFromFloats((hi[0] + lo[0]) / 2 * MM, (hi[1] + lo[1]) / 2 * MM, (hi[2] + lo[2]) / 2 * MM);
  b.material = material;
  return b;
}

const meshes = {};
PLAN.boxes.forEach((b) => {
  if (b.kind === "rack_blank") return;             // rack contents are drawn from the event snapshots
  const material = b.name.startsWith("front_wall") ? M.wall : b.name === "table" ? M.table
    : b.name === "spindle_head" ? M.spindle : b.kind === "vise_jaw" ? M.jaw : b.kind === "machine" ? M.machine : M.stat;
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
  // the detailed model replaces the plain enclosure walls; keep table, vise and spindle boxes
  PLAN.boxes.filter((b) => b.name.startsWith("front_wall")).forEach((b) => meshes[b.name].setEnabled(false));
  const box = $("show-model");
  box.disabled = false;
  $("model-label").textContent = `Machine model (${stl.count.toLocaleString()} triangles)`;
  $("model-note").textContent = `Loaded from ${source}. Visual only; collision uses the measured boxes.`;
  box.addEventListener("change", () => {
    mesh.setEnabled(box.checked);
    PLAN.boxes.filter((b) => b.name.startsWith("front_wall")).forEach((b) => meshes[b.name].setEnabled(!box.checked));
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

$("job-id").textContent = PLAN.job.job_id;
$("job-meta").textContent = `jaw release: ${PLAN.job.release_status} / program ${PLAN.job.program_id} / slots L${PLAN.job.slots.left} R${PLAN.job.slots.right}`;
$("plan-checks").textContent = `${PLAN.plan_issues.length} reach/collision issues in the plan. Reach margin: vise could sit ${PLAN.reach_margin_mm} mm further inside. `
  + `Layout uses estimated dimensions until measured.`;
Object.keys(PLAN.scenarios).forEach((name) => {
  const o = document.createElement("option");
  o.value = name;
  o.textContent = name === "nominal" ? "Nominal cycle" : `Fault: ${name.replaceAll("_", " ")}`;
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
  $("scenario-note").textContent = DESCR[name] || `Injected fault: ${name.replaceAll("_", " ")}. Expect SAFE_STOP with no further commands.`;
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

let last = performance.now();
engine.runRenderLoop(() => {
  const now = performance.now(), dt = (now - last) / 1000;
  last = now;
  if (state.playing) {
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
window.__sim = { state, loadScenario, render };   // test hook

loadScenario("nominal");
