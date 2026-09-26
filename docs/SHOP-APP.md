# Shop web app

`python -m softjaw serve` runs the cell's shop-floor site on port 8080 (open
http://localhost:8080, or http://&lt;shop-pc&gt;:8080 from another machine on the network).
Standard library only; data lives in `data/` (SQLite database, uploads, default CAM hot
folders). There are no logins: anyone who can reach the port can use it, and reviews and
recoveries are signed with a typed name. Use `--host 127.0.0.1` to keep it on one PC.

`python tools/seed_shop_demo.py` fills an empty `data/` with demo jaw sets, programs, jobs
and downtime windows.

**Simulation only.** A run plans the robot paths for its rack slots, executes the cell
controller against simulated adapters, and plays the event log back at the configured speed.
No robot or CNC is connected.

## Workflow

| Step | Who | Where |
|---|---|---|
| Create a jaw set per part setup (left + right programs, or one shared) | programmer | Jaw sets |
| Upload the finished jaw design (STEP/STL/DXF/.mcam/PDF) | programmer | jaw set page |
| Program the jaws in Mastercam from the CAM outbox package | programmer | CAM |
| Post NC into the CAM inbox as `<jaw-set>_left.nc` / `_right.nc` (or upload) | programmer | CAM / jaw set page |
| Review the automatic checks, sign and approve each program | programmer / lead | jaw set page |
| Add production jobs with their need-by date and jaw set | planner | Production jobs |
| Set the times the Haas is free | planner | Downtime & queue |
| Load pre-drilled blanks and mark the rack slots | operator | Dashboard |
| Runs start in a downtime window that fits (auto-run) or by hand | cell | Dashboard / Cell runs |
| Collect finished jaws and record where they are stored | operator | jaw set page |

Adding a production job whose jaws are not made queues a run automatically (setting
"Queue a jaw run when a production job needs jaws"). The queue is ordered by need-by date;
jobs whose jaws will not be ready in time are flagged.

## CAM hot folders

* **Outbox** (`data/cam/outbox/<jaw-set>/` by default): uploaded design files,
  `blank_top_face.dxf` (stock outline in the jaw WCS), `jaw_setup.json` (blank, WCS, depth
  limit, finger room, expected NC file names) and a README for the programmer.
* **Inbox** (`data/cam/inbox/`): NC files named after the jaw set are imported every few
  seconds, checked, and held for approval; imported files move to `imported/`. Files the app
  cannot match stay put and show on the dashboard and the CAM link page.

Point both at a network share the CAM PC can reach (Settings). This works with Mastercam's
normal post output, or any other CAM. A direct Mastercam NET-Hook add-in remains future work
(`config/cam/mastercam.json`).

## NC checks (`softjaw/shop/ncparse.py`)

Fanuc/Haas-style G-code, WCS per the CAM contract (origin on the blank top face at the face
edge, Y centred, +X into the jaw). Arcs (G2/G3, I/J or R), G90/G91, G20/G21 and drilling
cycles are followed.

| Check | Fails when |
|---|---|
| NC-001 | no M30/M02 |
| NC-002/003 | no G20/G21 or no work offset (warning) |
| NC-004 | a cut goes deeper than the blank's height above the hard jaws minus 2 mm (VAL-008) |
| NC-005 | cutting strays more than 10 mm off the blank top face (warning: check the WCS) |
| NC-006 | a rapid ends below the top face, or moves sideways below it, over the blank |
| NC-007/008 | a feed move with the spindle stopped, or before any F word |
| NC-010 | no room beside the pocket for the fingers to regrasp the finished jaw (VAL-004); also sets the grasp offset used by the robot |

A program with a failing check cannot be approved. The cycle-time estimate (feeds, rapids,
tool changes) sets each run's expected duration. These catch setup mistakes; they do not
replace CAM simulation and a person's review (CAM-003).

## Runs, stops and recovery

One run at a time, using the first two rack slots holding blanks. A SAFE STOP (injected
fault, the Stop button, or the app restarting mid-run) pauses auto-run until an operator
confirms where each jaw is (blank back in the rack, finished in the rack, removed, scrapped).
The interrupted cycle is never resumed (CTL-003); if the jaws are still needed a new run is
queued. Each run keeps its event log and a 3D replay (`/runs/<id>/sim/`).

While a run plays, the dashboard and the run monitor embed the 3D simulator following it
live: the server publishes the run's simulation clock (`GET /api/runs/<id>/clock`) and the
embedded view (`/runs/<id>/sim/?embed=1&follow=<id>`) animates to it, so the robot, door,
vise and rack in the view match the logged state. "Replay from start" replays locally;
"Follow the run" returns to live.
