/* global BABYLON */

const canvas = document.getElementById("render-canvas");
const engine = new BABYLON.Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true });
const scene = new BABYLON.Scene(engine);
scene.clearColor = new BABYLON.Color4(0.025, 0.04, 0.055, 1);

const camera = new BABYLON.ArcRotateCamera(
  "camera",
  -1.02,
  1.08,
  2.35,
  new BABYLON.Vector3(0.1, 0, 0.75),
  scene
);
camera.upVector = new BABYLON.Vector3(0, 0, 1);
camera.setPosition(new BABYLON.Vector3(-1.75, -2.05, 1.65));
camera.setTarget(new BABYLON.Vector3(0.15, -0.05, 0.72));
camera.lowerRadiusLimit = 0.7;
camera.upperRadiusLimit = 4.5;
camera.wheelDeltaPercentage = 0.012;
camera.panningSensibility = 900;
camera.attachControl(canvas, true);

new BABYLON.HemisphericLight("sky", new BABYLON.Vector3(-0.4, -0.5, 1), scene).intensity = 0.82;
const workLight = new BABYLON.PointLight("work-light", new BABYLON.Vector3(0.5, -0.4, 1.75), scene);
workLight.intensity = 65;
workLight.range = 3;

const colors = {
  floor: "#17222b",
  line: "#334550",
  machine: "#d9e0e2",
  machineDark: "#263744",
  machineGlass: "#47808b",
  table: "#495963",
  vise: "#356c9a",
  robot: "#c9e52d",
  robotDark: "#171d20",
  metal: "#aab5b8",
  blank: "#e6a05d",
  rack: "#596872",
  danger: "#ef6464",
  zone: "#59c7d6"
};

function material(name, hex, alpha = 1, emissive = 0) {
  const mat = new BABYLON.StandardMaterial(name, scene);
  mat.diffuseColor = BABYLON.Color3.FromHexString(hex);
  mat.specularColor = new BABYLON.Color3(0.15, 0.17, 0.18);
  mat.alpha = alpha;
  if (emissive) mat.emissiveColor = BABYLON.Color3.FromHexString(hex).scale(emissive);
  return mat;
}

const mats = Object.fromEntries(Object.entries(colors).map(([key, value]) => [key, material(`mat-${key}`, value)]));
mats.glass = material("mat-glass", colors.machineGlass, 0.24);
mats.zone = material("mat-zone", colors.zone, 0.12, 0.08);
mats.zone.backFaceCulling = false;

function box(name, size, position, mat, parent = null) {
  const mesh = BABYLON.MeshBuilder.CreateBox(name, { size: 1 }, scene);
  mesh.scaling.copyFromFloats(size[0], size[1], size[2]);
  mesh.position.copyFromFloats(position[0], position[1], position[2]);
  mesh.material = mat;
  if (parent) mesh.parent = parent;
  return mesh;
}

function cylinder(name, diameter, height, position, mat, parent = null) {
  const mesh = BABYLON.MeshBuilder.CreateCylinder(name, { diameter, height, tessellation: 28 }, scene);
  mesh.rotation.x = Math.PI / 2;
  mesh.position.copyFromFloats(position[0], position[1], position[2]);
  mesh.material = mat;
  if (parent) mesh.parent = parent;
  return mesh;
}

function createGrid() {
  box("floor", [3.2, 2.5, 0.035], [0, 0, -0.025], mats.floor);
  const lines = [];
  for (let x = -1.6; x <= 1.6; x += 0.1) lines.push([new BABYLON.Vector3(x, -1.25, 0), new BABYLON.Vector3(x, 1.25, 0)]);
  for (let y = -1.25; y <= 1.25; y += 0.1) lines.push([new BABYLON.Vector3(-1.6, y, 0), new BABYLON.Vector3(1.6, y, 0)]);
  const grid = BABYLON.MeshBuilder.CreateLineSystem("grid", { lines }, scene);
  grid.color = BABYLON.Color3.FromHexString(colors.line);
  grid.alpha = 0.22;
}

createGrid();

function createMachine() {
  const root = new BABYLON.TransformNode("haas-mini-mill", scene);
  root.position.copyFromFloats(0.78, 0.18, 0);

  box("machine-back", [0.62, 1.18, 1.56], [0.34, 0, 0.78], mats.machineDark, root);
  box("machine-left", [0.62, 0.16, 1.56], [0, -0.51, 0.78], mats.machine, root);
  box("machine-right", [0.62, 0.16, 1.56], [0, 0.51, 0.78], mats.machine, root);
  box("machine-header", [0.62, 0.86, 0.28], [0, 0, 1.42], mats.machine, root);
  box("machine-lower", [0.62, 0.86, 0.36], [0, 0, 0.18], mats.machine, root);
  box("machine-table", [0.48, 0.72, 0.07], [-0.19, 0, 0.67], mats.table, root);

  const spindle = cylinder("spindle", 0.105, 0.35, [-0.04, 0, 1.15], mats.metal, root);
  spindle.rotation.y = Math.PI / 2;

  const door = box("cnc-door", [0.025, 0.82, 0.78], [-0.325, 0, 0.91], mats.glass, root);
  door.metadata = { closedY: 0, openY: 0.76 };

  const zone = box("exchange-zone", [0.42, 0.68, 0.56], [-0.42, 0, 0.88], mats.zone, root);
  zone.isPickable = false;

  const viseRoot = new BABYLON.TransformNode("vevor-vise", scene);
  viseRoot.parent = root;
  viseRoot.position.copyFromFloats(-0.22, 0, 0.755);
  box("vise-body", [0.28, 0.22, 0.08], [0, 0, 0], mats.vise, viseRoot);
  box("vise-fixed-jaw", [0.045, 0.18, 0.105], [0.095, 0, 0.085], mats.vise, viseRoot);
  box("vise-moving-jaw", [0.045, 0.18, 0.105], [-0.095, 0, 0.085], mats.vise, viseRoot);
  box("vise-fixed-soft-jaw", [0.025, 0.125, 0.04], [0.064, 0, 0.137], mats.blank, viseRoot);
  box("vise-moving-soft-jaw", [0.025, 0.125, 0.04], [-0.064, 0, 0.137], mats.blank, viseRoot);

  return { root, door, viseRoot, exchangeZone: zone };
}

function createRack() {
  const root = new BABYLON.TransformNode("blank-rack", scene);
  root.position.copyFromFloats(-0.48, -0.58, 0);
  box("rack-base", [0.42, 0.28, 0.05], [0, 0, 0.05], mats.rack, root);
  box("rack-back", [0.04, 0.28, 0.62], [0.18, 0, 0.34], mats.rack, root);
  for (let row = 0; row < 3; row += 1) {
    box(`shelf-${row}`, [0.36, 0.25, 0.025], [0, 0, 0.16 + row * 0.18], mats.rack, root);
  }
  const blanks = [];
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 2; col += 1) {
      const blank = box(`delrin-blank-${row}-${col}`, [0.125, 0.032, 0.04], [-0.07 + col * 0.14, -0.01, 0.205 + row * 0.18], mats.blank, root);
      blanks.push(blank);
    }
  }
  return { root, blanks, pickup: blanks[4] };
}

const machine = createMachine();
const rack = createRack();

function quatFromRpy(rpy) {
  return BABYLON.Quaternion.RotationYawPitchRoll(rpy[2], rpy[1], rpy[0]);
}

const jointDefs = [
  { name: "joint1", xyz: [-0.00008416, 0, 0.08465], rpy: [0, 0, 0], axis: [0, 0, 1], min: -2.8, max: 2.8 },
  { name: "joint2", xyz: [0.020084, 0.031625, 0.05555], rpy: [-1.5708, 0, 0], axis: [0, 0, -1], min: -3.14, max: 0 },
  { name: "joint3", xyz: [-0.264, 0, 0], rpy: [0, 0, 0], axis: [0, 0, 1], min: -3.14, max: 0 },
  { name: "joint4", xyz: [0.2426, -0.054, -0.001625], rpy: [0, 0, 0], axis: [0, 0, 1], min: -1.87, max: 1.57 },
  { name: "joint5", xyz: [0.078308, -0.0375, -0.03], rpy: [-1.5708, 0, 0], axis: [0, 0, 1], min: -1.57, max: 1.57 },
  { name: "joint6", xyz: [0.028008, 0, 0.04], rpy: [0, 1.5708, 0], axis: [0, 0, 1], min: -3.14, max: 3.14 }
];

function createRobot() {
  const root = new BABYLON.TransformNode("rebot-b601-dm", scene);
  root.position.copyFromFloats(0.0, -0.46, 0.72);
  root.rotation.z = 0.18;
  cylinder("robot-pedestal", 0.23, 0.72, [0, 0, -0.36], mats.machineDark, root);
  cylinder("robot-base", 0.16, 0.085, [0, 0, 0.04], mats.robotDark, root);

  const joints = [];
  let parent = root;
  jointDefs.forEach((def, index) => {
    const node = new BABYLON.TransformNode(def.name, scene);
    node.parent = parent;
    node.position.copyFromFloats(...def.xyz);
    node.rotationQuaternion = quatFromRpy(def.rpy);
    node.metadata = { ...def, originQuaternion: node.rotationQuaternion.clone(), angle: 0 };
    joints.push(node);

    cylinder(`joint-hub-${index + 1}`, index < 3 ? 0.105 : 0.075, index < 3 ? 0.09 : 0.065, [0, 0, 0], mats.robotDark, node);
    if (index === 1) box("upper-arm", [0.27, 0.055, 0.065], [-0.132, 0, 0], mats.robot, node);
    if (index === 2) box("forearm", [0.245, 0.055, 0.06], [0.12, -0.027, 0], mats.robot, node);
    if (index === 3) box("wrist-link", [0.095, 0.052, 0.052], [0.045, -0.019, -0.015], mats.robot, node);
    if (index === 4) box("wrist-roll", [0.07, 0.05, 0.05], [0.03, 0, 0.02], mats.metal, node);
    parent = node;
  });

  const end = new BABYLON.TransformNode("gripper-tcp", scene);
  end.parent = parent;
  end.position.copyFromFloats(0, 0, 0.15539);
  end.rotationQuaternion = quatFromRpy([0, -1.5708, 3.1415]);
  cylinder("gripper-base", 0.09, 0.075, [0, 0, 0], mats.robotDark, end);
  const leftFinger = box("left-finger", [0.12, 0.018, 0.026], [-0.055, 0.044, 0], mats.robotDark, end);
  const rightFinger = box("right-finger", [0.12, 0.018, 0.026], [-0.055, -0.044, 0], mats.robotDark, end);

  return { root, joints, end, leftFinger, rightFinger, angles: new Array(6).fill(0), grip: 0 };
}

const robot = createRobot();

function setJointAngle(index, angle) {
  const node = robot.joints[index];
  const def = node.metadata;
  const clamped = Math.max(def.min, Math.min(def.max, angle));
  const axis = new BABYLON.Vector3(...def.axis).normalize();
  node.rotationQuaternion = def.originQuaternion.multiply(BABYLON.Quaternion.RotationAxis(axis, clamped));
  robot.angles[index] = clamped;
}

function setPose(pose, grip = robot.grip) {
  pose.forEach((angle, index) => setJointAngle(index, angle));
  robot.grip = grip;
  const spread = 0.025 + grip * -0.022;
  robot.leftFinger.position.y = spread;
  robot.rightFinger.position.y = -spread;
  updateJointControls();
}

const poses = {
  home: [0.1, -1.52, -1.45, -0.15, 0.35, 0],
  rackApproach: [1.78, -1.35, -1.72, -0.2, 0.55, 0.1],
  rackPick: [1.86, -1.68, -1.28, -0.35, 0.62, 0.1],
  rackLift: [1.76, -1.25, -1.62, -0.18, 0.44, 0.1],
  machineApproach: [-0.22, -1.15, -1.78, 0.1, 0.42, -0.2],
  machineLoad: [-0.18, -1.52, -1.38, 0.18, 0.62, -0.2]
};

const sequence = [
  { label: "Ready", detail: "Robot at safe home; CNC closed and stopped.", pose: poses.home, duration: 500, event: "reset" },
  { label: "Open door", detail: "Request machine access and confirm the spindle is stopped.", pose: poses.home, duration: 850, event: "doorOpen" },
  { label: "Approach rack", detail: "Move to the Delrin blank rack approach waypoint.", pose: poses.rackApproach, duration: 1500 },
  { label: "Pick blank", detail: "Close the gripper on one Delrin jaw blank.", pose: poses.rackPick, grip: 1, duration: 1000, event: "pick" },
  { label: "Lift", detail: "Clear the rack before traversing toward the machine.", pose: poses.rackLift, grip: 1, duration: 900 },
  { label: "Enter CNC", detail: "Enter the guarded exchange volume with the door confirmed open.", pose: poses.machineApproach, grip: 1, duration: 1650 },
  { label: "Load vise", detail: "Place the blank at the vise loading pose.", pose: poses.machineLoad, grip: 0, duration: 1050, event: "place" },
  { label: "Robot clear", detail: "Retract from the machine and return to the safe home pose.", pose: poses.home, grip: 0, duration: 1700, event: "clear" },
  { label: "Machine", detail: "Door closed; simulated soft-jaw machining cycle running.", pose: poses.home, grip: 0, duration: 2300, onEnter: "machineStart", event: "machineComplete" },
  { label: "Unload", detail: "Open the door and retrieve the finished soft jaw.", pose: poses.machineLoad, grip: 1, duration: 1800, event: "unload" },
  { label: "Return rack", detail: "Return the finished jaw to its rack location.", pose: poses.rackPick, grip: 0, duration: 1800, event: "return" },
  { label: "Complete", detail: "Robot returns home; simulated job is complete.", pose: poses.home, grip: 0, duration: 1500, event: "complete" }
];

const ui = {
  play: document.getElementById("play-button"),
  reset: document.getElementById("reset-button"),
  runStatus: document.getElementById("run-status"),
  detail: document.getElementById("step-detail"),
  robot: document.getElementById("robot-state"),
  door: document.getElementById("door-state"),
  spindle: document.getElementById("spindle-state"),
  gripper: document.getElementById("gripper-state"),
  payload: document.getElementById("payload-state"),
  timeline: document.getElementById("timeline"),
  joints: document.getElementById("joint-controls")
};

sequence.forEach((step, index) => {
  const item = document.createElement("li");
  item.dataset.index = String(index);
  item.innerHTML = `<span></span><small>${step.label}</small>`;
  ui.timeline.appendChild(item);
});

jointDefs.forEach((def, index) => {
  const row = document.createElement("label");
  row.className = "joint-control";
  row.innerHTML = `<span>J${index + 1}</span><input type="range" min="${def.min}" max="${def.max}" step="0.01" value="0"><output>0°</output>`;
  const input = row.querySelector("input");
  input.addEventListener("input", () => {
    if (state.playing) pauseCycle();
    setJointAngle(index, Number(input.value));
    row.querySelector("output").textContent = `${Math.round(Number(input.value) * 180 / Math.PI)}°`;
  });
  ui.joints.appendChild(row);
});

const state = {
  playing: false,
  stepIndex: 0,
  stepStart: 0,
  startPose: poses.home.slice(),
  payload: false,
  payloadPlaced: false,
  spindle: false,
  doorOpen: false
};

function updateJointControls() {
  [...ui.joints.querySelectorAll(".joint-control")].forEach((row, index) => {
    row.querySelector("input").value = String(robot.angles[index]);
    row.querySelector("output").textContent = `${Math.round(robot.angles[index] * 180 / Math.PI)}°`;
  });
}

function updateTimeline() {
  [...ui.timeline.children].forEach((item, index) => {
    item.classList.toggle("active", index === state.stepIndex);
    item.classList.toggle("complete", index < state.stepIndex);
  });
}

function updateUi() {
  const step = sequence[state.stepIndex];
  ui.runStatus.textContent = state.playing ? `Running · ${step.label}` : state.stepIndex === sequence.length - 1 ? "Complete" : "Paused";
  ui.detail.textContent = step.detail;
  ui.robot.textContent = state.playing ? "Moving" : "Holding";
  ui.door.textContent = state.doorOpen ? "Open" : "Closed";
  ui.spindle.textContent = state.spindle ? "Running (sim)" : "Stopped";
  ui.gripper.textContent = robot.grip > 0.5 ? "Closed" : "Open";
  ui.payload.textContent = state.payload ? "Delrin jaw" : state.payloadPlaced ? "In vise" : "None";
  ui.play.textContent = state.playing ? "Pause" : state.stepIndex === sequence.length - 1 ? "Run again" : "Run cycle";
  updateTimeline();
}

function applyEvent(event) {
  if (event === "reset") {
    state.payload = false;
    state.payloadPlaced = false;
    state.spindle = false;
    state.doorOpen = false;
  }
  if (event === "doorOpen") state.doorOpen = true;
  if (event === "pick") {
    state.payload = true;
    rack.pickup.setEnabled(false);
  }
  if (event === "place") {
    state.payload = false;
    state.payloadPlaced = true;
  }
  if (event === "clear") state.doorOpen = false;
  if (event === "machineComplete") {
    state.spindle = false;
    state.doorOpen = true;
  }
  if (event === "unload") {
    state.payload = true;
    state.payloadPlaced = false;
  }
  if (event === "return") {
    state.payload = false;
    rack.pickup.setEnabled(true);
  }
  if (event === "complete") state.doorOpen = false;
}

function startStep(index, now) {
  state.stepIndex = index;
  state.stepStart = now;
  state.startPose = robot.angles.slice();
  if (sequence[index].onEnter === "machineStart") {
    state.doorOpen = false;
    state.spindle = true;
  }
  updateUi();
}

function startCycle() {
  if (state.stepIndex >= sequence.length - 1) resetCycle();
  state.playing = true;
  startStep(Math.max(1, state.stepIndex), performance.now());
}

function pauseCycle() {
  state.playing = false;
  updateUi();
}

function resetCycle() {
  state.playing = false;
  state.stepIndex = 0;
  state.payload = false;
  state.payloadPlaced = false;
  state.spindle = false;
  state.doorOpen = false;
  rack.pickup.setEnabled(true);
  setPose(poses.home, 0);
  machine.door.position.y = machine.door.metadata.closedY;
  ui.runStatus.textContent = "Ready";
  ui.detail.textContent = "Cell is ready for a simulated cycle.";
  updateUi();
}

ui.play.addEventListener("click", () => state.playing ? pauseCycle() : startCycle());
ui.reset.addEventListener("click", resetCycle);

function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }

function tickSequence(now) {
  if (!state.playing) return;
  const step = sequence[state.stepIndex];
  const progress = Math.min(1, (now - state.stepStart) / step.duration);
  const e = ease(progress);
  const pose = step.pose.map((target, index) => state.startPose[index] + (target - state.startPose[index]) * e);
  const targetGrip = step.grip ?? robot.grip;
  setPose(pose, targetGrip);
  if (progress >= 1) {
    applyEvent(step.event);
    if (state.stepIndex >= sequence.length - 1) {
      state.playing = false;
      updateUi();
    } else {
      startStep(state.stepIndex + 1, now);
    }
  }
}

function updateWorld() {
  const doorTarget = state.doorOpen ? machine.door.metadata.openY : machine.door.metadata.closedY;
  machine.door.position.y += (doorTarget - machine.door.position.y) * 0.08;

  if (state.payload) {
    rack.pickup.setEnabled(true);
    rack.pickup.parent = null;
    const tcp = robot.end.getAbsolutePosition();
    rack.pickup.position.copyFrom(tcp.add(new BABYLON.Vector3(-0.07, 0, 0)));
    rack.pickup.rotationQuaternion = robot.end.absoluteRotationQuaternion?.clone() ?? BABYLON.Quaternion.Identity();
  } else if (state.payloadPlaced) {
    rack.pickup.setEnabled(true);
    rack.pickup.parent = machine.viseRoot;
    rack.pickup.position.copyFromFloats(0, 0, 0.17);
    rack.pickup.rotationQuaternion = BABYLON.Quaternion.Identity();
  } else if (rack.pickup.parent !== rack.root) {
    rack.pickup.parent = rack.root;
    rack.pickup.position.copyFromFloats(-0.07, -0.01, 0.565);
    rack.pickup.rotationQuaternion = BABYLON.Quaternion.Identity();
  }
}

setPose(poses.home, 0);
resetCycle();

engine.runRenderLoop(() => {
  tickSequence(performance.now());
  updateWorld();
  scene.render();
});

window.addEventListener("resize", () => engine.resize());
