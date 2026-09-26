// Headless smoke test for sim-web/app.js: stubs Babylon and the DOM, then plays
// every scenario to the end and checks the final state matches the orchestrator.
const fs = require("fs"), path = require("path"), vm = require("vm");
const dir = path.join(__dirname, "..", "sim-web");
function mock() {
  const f = function () { return mock(); };
  const props = {};
  return new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => 0;
      if (!(k in props)) props[k] = mock();
      return props[k];
    },
    set(t, k, v) { props[k] = v; return true; },
    construct() { return mock(); },
    apply() { return mock(); },
  });
}
const els = {};
function el(id) {
  const e = { id, textContent: "", innerHTML: "", hidden: false, value: "", dataset: {}, children: [], className: "",
    classList: { toggle() {}, add() {} }, style: {}, listeners: {},
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    addEventListener(n, fn) { this.listeners[n] = fn; },
    querySelector() { return el("q"); }, scrollTop: 0, scrollHeight: 0 };
  Object.defineProperty(e, "innerHTML", { set(v) { this.children = []; this._h = v; }, get() { return this._h || ""; } });
  return e;
}
const document = { getElementById: (id) => (els[id] = els[id] || el(id)), createElement: () => el("new") };
const ctx = { window: {}, document, performance: { now: () => 0 }, console, Math, Number, String, Object, Array, JSON, Infinity, NaN };
ctx.window = ctx; ctx.globalThis = ctx;
ctx.BABYLON = mock();
ctx.addEventListener = () => {};
vm.createContext(ctx);
if (process.env.WITH_MODEL) ctx.MACHINE_STL_B64 = fs.readFileSync(process.env.WITH_MODEL).toString("base64");
ctx.atob = (b) => Buffer.from(b, "base64").toString("binary");
ctx.TextDecoder = TextDecoder; ctx.Float32Array = Float32Array; ctx.Uint32Array = Uint32Array; ctx.Uint8Array = Uint8Array;
ctx.ArrayBuffer = ArrayBuffer; ctx.DataView = DataView; ctx.location = { protocol: "file:" };
for (const f of ["cell-plan.js", "kinematics.js", "stl.js", "app.js"]) vm.runInContext(fs.readFileSync(path.join(dir, f), "utf8"), ctx, { filename: f });
const sim = ctx.__sim, plan = ctx.CELL_PLAN;
let fails = 0;
for (const [name, sc] of Object.entries(plan.scenarios)) {
  sim.loadScenario(name);
  const end = sc.events[sc.events.length - 1].t;
  for (let t = 0; t <= end; t += Math.max(0.25, end / 800)) sim.render(t);
  sim.render(end);
  const shown = els["t-state"].textContent;
  const ok = shown === sc.final_state && sim.state.moves.length > 0 === (sc.events.some((e) => e.device === "robot"));
  if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name.padEnd(20)} shows ${shown.padEnd(10)} expected ${sc.final_state.padEnd(10)} robot moves replayed: ${sim.state.moves.length}`
    + (name !== "nominal" && sc.final_state === "SAFE_STOP" ? ` banner: ${els["fault-banner"].hidden ? "HIDDEN" : "shown"}` : ""));
}
// every robot command in every log must map to a planned segment
for (const [name, sc] of Object.entries(plan.scenarios)) {
  const cmds = sc.events.filter((e) => e.type === "command" && e.device === "robot");
  const missing = cmds.filter((e) => !plan.segments[e.jaw].some((s) => s.from === e.frm && s.to === e.to));
  if (missing.length) { fails++; console.log(`FAIL ${name}: ${missing.length} robot commands without a planned segment`); }
}
if (process.env.WITH_MODEL) {
  const ok = els["model-label"].textContent.startsWith("Machine model (");
  if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"} machine model loaded: ${els["model-label"].textContent}`);
}
process.exit(fails ? 1 : 0);
