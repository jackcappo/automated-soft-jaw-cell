# Automated Soft-Jaw Cell

Simulation-first system that turns a part model and its orientation in the vise into a
pair of machinable Delrin soft jaws, then plans and simulates a reBot B601-DM moving the
blanks between a rack and a Haas Mini Mill.

First cell profile: Haas Mini Mill, VEVOR 5-inch vise with pneumatic actuation,
reBot B601-DM, Mastercam. Machines, vises, blanks, grippers, robots and CAM systems
are data profiles under `config/`, so others can be added without code changes.

> **Status: simulation only.** No physical robot or CNC command path exists in this
> build (constructing one raises `PhysicalCommandPathDisabled`). Many layout and vise
> dimensions are still assumed; every job stays `provisional` until they are measured.

## Quick start

```bash
pip install -r requirements.txt          # numpy + scipy (CadQuery optional, for STEP)
python -m softjaw jaws --all             # generate + validate jaws for the example parts
python -m softjaw plan                   # robot reach / collision study
python -m softjaw sim                    # run the cell controller scenarios for the simulator
cd sim-web && python -m http.server 8070 # open http://localhost:8070
python -m unittest discover -s tests -t .  # 25 tests (~2 min)
```

## What each part does

**Jaw generator** (`softjaw/jawgen.py`). Slices the posed part over the jaw height,
offsets it by the cavity clearance, and cuts a 2.5D pocket (planar profile + flat floor)
into each jaw. The jaw gap comes from how deep the part should nest into each jaw.
Sharp inside corners the cutter cannot reach get automatic corner reliefs. It then runs
the PRD checks and reports measured value vs limit for each:

| Check | What it guards |
|---|---|
| GEO-002/003 | valid rigid pose; an approved grip band is required |
| VAL-001 | wall behind the pocket, thin material features, mounting-hole clearance |
| VAL-002 | every pocket point reachable by the cutter; depth vs cutter reach |
| VAL-003 | part protrudes for loading/removal |
| VAL-004 | robot payload, gripper opening, finger room to regrasp the finished jaw |
| VAL-005 | contact on both jaws; X/Y/Z resistance to machining loads with a safety factor |
| VAL-008 | standing blank exposes the pocket above the hard jaws (cutter never meets steel) |
| VAL-009 | jaws do not touch; the vise opening can reach the required gap |
| CFG-003 | any assumed dimension keeps the job `provisional` |

Status is `blocked` (a check failed), `provisional` (unverified dimensions),
`needs_acknowledgement` (warnings) or `released`.

**CAM package** (`softjaw/export.py`), written to `output/<job>/` per jaw:
`*_jaw_pocket.dxf` (POCKET chain for a Mastercam 2D pocket + contour, plus STOCK and
FACE_EDGE), `*_jaw.stl` (watertight inspection solid), `manifest.json` (WCS, floor depth,
reliefs, checksums, profile versions, unverified dimensions, CAM approval block that a
person must fill in), `validation_report.json` and `preview.svg`. STEP output is added
automatically when CadQuery is installed.

**Cell planner** (`softjaw/kinematics.py`, `softjaw/cellplan.py`). Forward/inverse
kinematics from the B601-DM URDF, waypoints for every rack slot and the vise (straight-line
Cartesian approach and retreat), a broad-phase collision sweep of every move against the
machine, vise, rack and payload, and a reach-margin study.

**Cell controller** (`softjaw/orchestrator.py`). The PRD state machine with guards
(CTL-004 cycle start, CTL-005 robot entry), timeouts, SAFE_STOP, explicit operator
recovery that never resumes motion, inventory tracking, and simulated adapters with eight
injectable faults. Simulated time makes every run replay identically.

**Simulator** (`sim-web/`). Replays the planner's paths and the controller's event logs;
it decides nothing itself. See `sim-web/README.md`.

## The robot process (why blanks stand in the vise)

A robot cannot bolt soft jaws on. Each pre-drilled Delrin blank is clamped **standing up**
in the hard jaws on a parallel, so the pocket region sits above the steel. The cell
machines only the cavity; mounting holes are drilled in batches beforehand. The finished
jaw goes back to the rack for a person to install. Details in `docs/DESIGN-DECISIONS.md`.

## Before trusting any result: measure

`python -m softjaw plan` reports **18 estimated layout values**, and the vise can sit only
about **40 mm** further into the machine than assumed before the arm cannot reach it with
the gripper pointing down. Complete `docs/vevor-vise-measurement-sheet.md` and the machine
and cell measurements in `docs/MEASUREMENTS.md`, update the `status` of each value in
`config/`, and re-run.

## Adding your own parts

Put an STL (or STEP with CadQuery) in `examples/parts/`, copy a file in `config/jobs/`,
set `part.file`, `part.pose_in_vise` (4x4, mm, vise frame: origin at vise centre on the
jaw seat, +X across the jaws, +Z up) and `approved_grip`, then `python -m softjaw jaws <name>`.

## Machine model for the simulator

`python tools/import_machine_model.py path/to/model.stl` orients (units and up axis are
auto-detected; use `--front=+y` etc. for the door side), simplifies and places a downloaded
model in `sim-web/assets/`. It is visual only and git-ignored because downloaded models
belong to their authors.

## Layout

```
config/    machines, vises, blanks, grippers, robots, cells, cam, jobs  (data profiles)
softjaw/   geometry, jawgen, export, kinematics, cellplan, orchestrator, simplan, CLI
sim-web/   browser simulator (Babylon.js 7.54.3 from jsDelivr, or vendor/babylon.js offline)
tools/     example generator, machine-model importer, simulator bundler and smoke test
tests/     unit and integration tests
docs/      PRD, design decisions, measurement sheets
```
