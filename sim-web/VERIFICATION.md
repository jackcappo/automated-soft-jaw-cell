# Verification record

## 2026-09-26: simulation MVP (automated)

Run `python -m unittest discover -s tests -t .` to repeat. Result: 25 passed, 1 skipped
(STEP round trip, needs CadQuery).

Verified:
- Jaw generator: all 7 example jobs reach their expected status; failure cases report the
  requirement that failed; hex gets exactly one corner relief per sharp corner; output is
  deterministic.
- Exports: every jaw STL is watertight; STL volume matches blank minus pocket within 1%;
  DXF pocket area matches the computed pocket within 2%.
- Kinematics: sampled maximum reach matches the published 767 mm; IK round trips to 0.5 mm.
- Planner: every waypoint for rack slots 0-5 reachable; broad-phase collision sweep of every
  move is clear (after fixing: unreachable home/transit, blank grazing the fixed jaw,
  elbow hitting the front wall).
- Controller: nominal cycle completes with both finished jaws in the rack; each of 8 faults
  ends in SAFE_STOP with no further commands; recovery needs confirmed inventory and never
  resumes; replay is identical; the physical command path is disabled; blocked jaws never run.
- Simulator: JS kinematics equal Python to 1e-6 mm; headless replay of all 9 scenarios
  shows the logged final state; every robot command maps to a planned path; the machine
  model loads when present.
- Machine model importer: units and up axis auto-detected; the door side faces the robot
  only for the correct `--front` option.

Not yet verified:
- Rendering in a real browser. The headless test stubs Babylon.js.
- Anything physical. Layout values are estimates; see docs/MEASUREMENTS.md.
- STEP import/export (needs CadQuery).

## 2026-09-25: first browser MVP (superseded)
The earlier hand-posed animation was watched in a browser. It used provisional joint
waypoints and had a URDF rotation-order error and a left-handed scene; it has been replaced.
