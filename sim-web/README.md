# Browser cell simulator

Replays the verified plan for the soft-jaw cell. It decides nothing itself:

- every robot pose comes from the planner's IK paths (`softjaw/cellplan.py`), which were
  collision-checked against the cell boxes;
- every device state (door, spindle, vise, gripper, rack) comes from the world snapshots
  in the cell controller's event log (`softjaw/orchestrator.py`).

## Run

```bash
python -m softjaw jaws hex_fitting   # once, to create the jaw manifest
python -m softjaw sim                # writes cell-plan.js
cd sim-web && python -m http.server 8070
```

Open <http://localhost:8070>. Babylon.js 7.54.3 loads from jsDelivr; to work offline,
save https://cdn.jsdelivr.net/npm/babylonjs@7.54.3/babylon.js as `vendor/babylon.js`.
`python -m softjaw bundle` writes a single self-contained HTML file.

## Features

- Scenario picker: the nominal cycle plus one run per injected fault
  (lost grip, occupied slot, door/clamp disagreement, CNC alarm, timeout, comms loss,
  spindle not stopped). Faults end in SAFE_STOP with a banner explaining why.
- Live state, event log, cycle timeline, playback speed (machining runs 6x faster).
- Robot drawn as its collision capsules, so what you see is what the planner checked.
- Manual joint sliders (pause playback).
- Optional detailed machine model: run `tools/import_machine_model.py` to create
  `assets/machine.stl`. It replaces the plain enclosure walls visually; collision still
  uses the measured boxes. The model is git-ignored (third-party CAD).

## Limitations

- Broad-phase collision model; not a substitute for verified meshes before commissioning.
- Layout dimensions are estimates until measured (see `docs/MEASUREMENTS.md`).
- The gripper is a placeholder; replace `config/grippers/placeholder-parallel.json` with
  values from your gripper CAD.
- No real machine or robot interface exists.

## Tests

`node ../tools/sim_smoke_test.js` plays every scenario headlessly (Babylon and the DOM are
stubbed) and checks the final state and banner. Set `WITH_MODEL=path/to/machine.stl` to
also test model loading. The Python suite checks the JS kinematics against Python to 1e-6 mm.
