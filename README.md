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

## Purpose

Automated Soft-Jaw Cell automates jaw machining and CNC tending, repetitive, low-skill work, so it runs unattended during otherwise idle machine time. It is built for machinists with variable schedules, a day job plus a home or small shop on evenings and weekends, and gives them back their most limited resource: time for higher-value work like fixturing, programming, and process development.

## Quick start

```bash
pip install -r requirements.txt          # numpy + scipy (CadQuery optional, for STEP)
python -m softjaw jaws --all             # generate + validate jaws for the example parts
python -m softjaw plan                   # robot reach / collision study
python -m softjaw sim                    # run the cell controller scenarios for the simulator
cd sim-web && python -m http.server 8070 # open http://localhost:8070
python -m softjaw serve                  # shop web app on http://localhost:8080 (see docs/SHOP-APP.md)
python -m unittest discover -s tests -t .  # 46 tests (~2 min)
```

## Running it on another computer

Works on Windows, macOS and Linux. The repository is private, so that computer needs your
GitHub login.

**1. Install once**

* **Python 3.10 or newer** from python.org. On Windows tick *Add python.exe to PATH* in the
  installer. If `python` is not found afterwards, use `py` in the commands below.
* **Git** from git-scm.com (Windows: `winget install --id Git.Git -e`).
* An internet connection the first time the 3D view opens: Babylon.js loads from
  jsDelivr. `sim-web/vendor/babylon.js` is the offline fallback.

**2. Download the project once**

```bash
git clone https://github.com/jackcappo/automated-soft-jaw-cell.git
cd automated-soft-jaw-cell
python -m pip install -r requirements.txt
```

Git opens a browser to sign in to GitHub the first time.

**3a. Shop web app with the live 3D cell (recommended)**

```bash
python tools/seed_shop_demo.py     # optional: demo jaw sets, programs, jobs, downtime (only on an empty data/ folder)
python -m softjaw serve            # leave this window open; Ctrl+C stops it
```

Open <http://localhost:8080>. The control centre shows the 3D cell straight away: idle
between runs, and live while a run plays. To start one, mark two rack slots as loaded
(*Blank rack*), then press the start button on a ready jaw set, or let auto-run start it
inside a downtime window.

* From another PC or tablet on the same network: open `http://<this-computer's-IP>:8080`
  and allow Python through the firewall when Windows asks. To keep it on this PC only:
  `python -m softjaw serve --host 127.0.0.1`.
* Port 8080 taken? `python -m softjaw serve --port 8090`.
* The app's database, uploads and CAM hot folders live in `data/`. It is not in git, so each
  computer starts empty. Copy that folder to move your jobs across.

**3b. Standalone simulator only (no shop app)**

```bash
cd sim-web
python -m http.server 8070
```

Open <http://localhost:8070>, pick a scenario (the nominal cycle or one of the injected
faults) and press *Run*. It replays `sim-web/cell-plan.js`, which is in the repository. After
changing anything in `config/`, rebuild it from the project folder:

```bash
python -m softjaw jaws hex_fitting
python -m softjaw sim
```

**Getting updates later**

```bash
git pull
python -m pip install -r requirements.txt
```

Then restart `python -m softjaw serve`, and hard-refresh the browser (Ctrl+Shift+R, or
Cmd+Shift+R on a Mac).

**If something looks wrong**

* The page is blank, or shows old screens: hard-refresh (Ctrl+Shift+R).
* The 3D view shows "3D view unavailable": check the internet connection (for the 3D
  library) and that `python -m softjaw serve` is still running, then press *Retry*.
* The detailed Haas model is missing (plain boxes instead): `sim-web/assets/machine.stl`
  did not come down with the clone. Re-import it with `tools/import_machine_model.py`
  (see *Machine model for the simulator*).
* Check the install: `python -m unittest discover -s tests -t .` should report
  `OK (skipped=3)` (the skips need Node.js or CadQuery, both optional).

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
machine, vise, rack, cart and payload, and a reach-margin study.

**Robot cart.** The robot and the blank rack sit on one wheeled cart that docks to the
machine, so the whole cell can be rolled away. Its size, deck height, robot mount and rack
position are in `cart` in `config/cells/*.json`; see `docs/DESIGN-DECISIONS.md` (8).

**Cell controller** (`softjaw/orchestrator.py`). The PRD state machine with guards
(CTL-004 cycle start, CTL-005 robot entry), timeouts, SAFE_STOP, explicit operator
recovery that never resumes motion, inventory tracking, and simulated adapters with eight
injectable faults. Simulated time makes every run replay identically.

**Shop web app** (`softjaw/shop/`, `shop-web/`). The site people use day to day: jaw sets
with uploaded designs, CAM hot folders (design package out, posted NC back in), automatic NC
checks with signed approval, production jobs and the jaws each needs, machine downtime
windows that auto-run fits queued jaw runs into, a blank-rack view, live run monitoring and
operator recovery after a SAFE STOP. See `docs/SHOP-APP.md`.

**Simulator** (`sim-web/`). Replays the planner's paths and the controller's event logs;
it decides nothing itself. See `sim-web/README.md`.

## The robot process (why blanks stand in the vise)

A robot cannot bolt soft jaws on. Each pre-drilled Delrin blank is clamped **standing up**
in the hard jaws on a parallel, so the pocket region sits above the steel. The cell
machines only the cavity; mounting holes are drilled in batches beforehand. The finished
jaw goes back to the rack for a person to install. Details in `docs/DESIGN-DECISIONS.md`.

## Before trusting any result: measure

`python -m softjaw plan` reports **18 estimated layout values**, and the vise can sit only
about **10 mm** further into the machine than assumed before the arm cannot reach it with
the gripper pointing down. Table height, door width and spindle depth come from the Haas
layout drawing; the robot stands on a raised column to reach down onto the table. Complete `docs/vevor-vise-measurement-sheet.md` and the machine
and cell measurements in `docs/MEASUREMENTS.md`, update the `status` of each value in
`config/`, and re-run.

## Adding your own parts

Put an STL (or STEP with CadQuery) in `examples/parts/`, copy a file in `config/jobs/`,
set `part.file`, `part.pose_in_vise` (4x4, mm, vise frame: origin at vise centre on the
jaw seat, +X across the jaws, +Z up) and `approved_grip`, then `python -m softjaw jaws <name>`.

## Machine model for the simulator

`python tools/import_machine_model.py path/to/model.stl` orients (units and up axis are
auto-detected; use `--front=+y` etc. for the door side), simplifies and places a downloaded
model in `sim-web/assets/`; the front panel (not a pendant arm or tray sticking out) lands on
the door plane, and `--lift` raises the model to match the published table height (the
GrabCAD Haas model needs `--lift 44`). It is visual only. `sim-web/assets/` is git-ignored because
downloaded models belong to their authors; this private repository includes the imported Haas
model (force-added) so the 3D view works after a clone. Remove it before making the repository
public.

## Layout

```
config/    machines, vises, blanks, grippers, robots, cells, cam, jobs  (data profiles)
softjaw/   geometry, jawgen, export, kinematics, cellplan, orchestrator, simplan, CLI
softjaw/shop/  shop web app: server, app logic, NC checks, downtime scheduling, SQLite store
shop-web/  shop web app UI (no build step)
sim-web/   browser simulator (Babylon.js 7.54.3 from jsDelivr, or vendor/babylon.js offline)
tools/     example generator, machine-model importer, simulator bundler, smoke test, shop demo seeder
examples/  test parts and sample posted NC programs (examples/nc)
data/      shop app database, uploads and CAM hot folders (created at first run, git-ignored)
tests/     unit and integration tests
docs/      PRD, design decisions, measurement sheets
```
