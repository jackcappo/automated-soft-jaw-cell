# Product Requirements Document: Automated Soft-Jaw Manufacturing Cell

**Document status:** Draft for engineering validation  
**Version:** 0.1  
**Date:** 2026-09-26  
**Initial platform:** reBot B601-DM, Haas Mini Mill, VEVOR 5-inch vise, Mastercam

## 1. Product summary

Build a simulation-first system that accepts a part model and intended machining
orientation, generates a manufacturable pair of custom soft jaws, prepares the
job for CAM, and coordinates a robot-assisted workflow for moving Delrin jaw
blanks between a storage rack and a CNC mill.

The long-term product is a reusable automated cell rather than a one-off machine
integration. Machines, vises, robots, grippers, blank formats, and CAM systems
must be represented through replaceable profiles and adapters. The first
supported cell uses a reBot B601-DM, Haas Mini Mill, VEVOR 5-inch vise, and
Mastercam.

The first release is a digital twin and engineering-validation tool. It must not
command a physical CNC machine or robot until the required safety system,
interlocks, hardware measurements, and staged commissioning tests have been
completed and approved.

## 2. Problem statement

Producing soft jaws for low-volume and varied parts currently requires repeated
manual work:

1. Decide how the part will sit in the vise.
2. Model a jaw cavity that supports and locates the part.
3. Check mounting features, wall thickness, tool access, and removal clearance.
4. Create and verify CAM operations.
5. Load two blank jaws into the machine.
6. Machine, unload, identify, and store the finished jaws.

This process is slow, dependent on individual experience, and difficult to
scale across varied part geometry. A bad jaw design can damage the part, scrap
the blanks, create an unstable setup, or cause a collision. A robotic workflow
adds further reach, payload, collision, state-management, and machine-safety
requirements.

## 3. Product vision

An operator should be able to provide a part CAD file, choose its desired pose
and grip region, select a supported cell profile, and receive:

- validated left- and right-jaw geometry;
- a clear explanation of any unsafe or unmanufacturable result;
- CAM-ready geometry and job metadata;
- a simulated, reviewable robot/CNC sequence;
- traceable job files for machining and storage; and
- eventually, a supervised automated cell cycle.

The system should make the common path fast while refusing to proceed when it
cannot establish that the jaw or cell plan is valid.

## 4. Users and stakeholders

### Primary users

- CNC machinists creating workholding for new or low-volume parts.
- Manufacturing engineers validating fixture designs and automation layouts.
- Robot integrators developing and commissioning the tending sequence.

### Secondary stakeholders

- CAM programmers who review or complete the Mastercam toolpath.
- Shop supervisors responsible for process approval and traceability.
- Safety personnel responsible for the cell risk assessment and interlocks.
- Quality personnel who inspect jaw geometry and finished parts.

## 5. Goals

### MVP goals

- Import a STEP part and an explicit part-to-vise pose.
- Let the user define or approve the intended grip region and contact strategy.
- Generate separate left and right soft-jaw solids from a measured blank and
  vise definition.
- Preserve all jaw mounting holes, counterbores, serrations, and keep-out zones.
- Validate basic manufacturability, retention, insertion, removal, and tool
  access before releasing geometry.
- Export STEP/STL jaw files, coordinate systems, stock data, and a versioned job
  manifest suitable for a Mastercam handoff.
- Simulate blank pickup, CNC loading, machining state, unloading, and return to
  the rack using the B601-DM and a placeholder gripper.
- Detect and report invalid state transitions and simulated faults.
- Keep machine, vise, CAM, robot, gripper, rack, and job definitions modular.

### Long-term goals

- Support multiple CNC machines, vises, robots, grippers, and CAM systems.
- Generate or update Mastercam operations through a supported integration.
- Use numerical inverse kinematics and collision-aware motion planning.
- Track blank and finished-jaw identity, location, revision, and inspection.
- Execute a supervised physical cycle after formal safety and commissioning
  gates are met.
- Use inspection feedback to compensate jaw geometry and improve repeatability.

## 6. Non-goals for the first release

- Unattended physical machine operation.
- Automatic CNC cycle start or automatic control of the pneumatic vise.
- Safety functions implemented only in application software.
- Guaranteed fixture adequacy from part orientation alone.
- Automatic CAM toolpath generation without human review.
- Production-certified collision avoidance using simplified visual geometry.
- Support for arbitrary machine, vise, robot, and CAM combinations in v0.1.
- Final gripper design; the initial simulation uses a replaceable placeholder.

## 7. Initial cell definition

| Component | Initial choice | MVP treatment |
| --- | --- | --- |
| Robot | reBot B601-DM | Six-axis kinematic model; published joint limits; simulated driver |
| CNC | Haas Mini Mill | Simplified enclosure, table, door, and exchange volume |
| Vise | VEVOR 5-inch ACCU lock-down vise | Profile from published dimensions; jaw mounting pattern must be measured |
| Jaw material | Delrin blank pairs | Configurable blank dimensions and rack slot identity |
| CAM | Mastercam | File-and-manifest handoff first; SDK integration later |
| Gripper | To be designed | Placeholder envelope, TCP, open/closed states, and payload ownership |
| Rack | Delrin blank/finished-jaw holder | Configurable slots, occupancy, pickup pose, and return pose |
| Vise actuation | Future pneumatic open/close | Simulated clamp state only in the current phase |

## 8. Core user workflow

### 8.1 Define the job

1. Import the part STEP file.
2. Select the machine, vise, blank, robot, gripper, rack, and CAM profiles.
3. Set or import the part pose in the vise coordinate system.
4. Define the approved grip band or candidate grip surfaces.
5. Enter expected machining loads, protected surfaces, clearance, grip depth,
   minimum wall thickness, cutter limits, and required tolerances.

### 8.2 Generate and validate the jaws

1. Transform the part into the vise frame.
2. Identify the left and right captured surfaces within the approved grip band.
3. Offset the cavity surfaces using the configured fit and clearance strategy.
4. Subtract the cavities from the measured jaw blank solids.
5. Add cutter-radius relief and chip-clearance features where required.
6. Preserve mounting features and keep-out volumes.
7. Validate wall thickness, cavity depth, cutter reach, insertion/removal,
   gripper access, and resistance to the supplied machining loads.
8. Present pass, warning, and fail results with geometry-linked explanations.

### 8.3 Prepare CAM

1. Export left- and right-jaw STEP files and optional inspection STL files.
2. Export named work coordinate systems, blank dimensions, material, job ID,
   jaw side, required tools, and generation settings in a manifest.
3. Open or import the package in Mastercam.
4. Require a human to review stock, work offsets, tools, feeds, speeds, clamps,
   simulation, and post output before approving the CNC program.

### 8.4 Simulate the cell cycle

1. Validate the approved job and required simulated device states.
2. Pick a matched blank pair from known rack slots and verify possession.
3. Request access to the CNC and confirm the door-open state.
4. Load the blank pair into the vise and confirm simulated clamp state.
5. Move the robot outside the protected machine volume.
6. Confirm door closed, robot clear, and job identity before machining state.
7. Simulate cycle complete and spindle stopped.
8. Open the door, retrieve the finished jaws, and return them to assigned rack
   slots.
9. Record cycle result, alarms, timing, and final inventory state.

## 9. Functional requirements

Requirement IDs are stable references for design, implementation, and testing.

### Geometry and job definition

- **GEO-001:** The system shall import STEP part geometry without changing its
  source units or coordinate system silently.
- **GEO-002:** The system shall require an explicit rigid transform from part
  coordinates to vise coordinates.
- **GEO-003:** The system shall require an approved grip region or candidate
  surfaces; orientation alone shall not authorize jaw generation.
- **GEO-004:** The system shall generate distinct left and right jaw bodies.
- **GEO-005:** Clearance, grip depth, relief radius, minimum wall thickness, and
  locating allowances shall be configurable per job.
- **GEO-006:** Mounting features and profile keep-outs shall remain unchanged.
- **GEO-007:** Every exported jaw shall retain references to its source part,
  part pose, profile versions, generator version, and parameter set.
- **GEO-008:** Re-running an unchanged job with the same software version shall
  produce geometrically equivalent output.

### Validation

- **VAL-001:** The system shall fail a job if a cavity intersects a protected
  mounting feature or violates minimum wall thickness.
- **VAL-002:** The system shall check cutter access and configured tool reach.
- **VAL-003:** The system shall check that the part can be inserted and removed
  along an allowed direction.
- **VAL-004:** The system shall check gripper access to blank and finished jaws.
- **VAL-005:** The system shall calculate and report a fixture constraint score
  using the supplied contact strategy and machining loads.
- **VAL-006:** Failed checks shall identify the requirement, affected geometry,
  measured value, required limit, and suggested corrective action.
- **VAL-007:** Warnings shall require explicit acknowledgement before export;
  failures shall block release.

### CAM handoff

- **CAM-001:** The system shall export STEP geometry for each jaw.
- **CAM-002:** The system shall export a machine-readable manifest containing
  stock, material, WCS, jaw side, setup, tolerance, tool, and revision data.
- **CAM-003:** The Mastercam adapter shall not mark a job approved until a human
  records CAM verification and postprocessor selection.
- **CAM-004:** CNC program identity and checksum shall be associated with the
  approved jaw job before physical execution is enabled.

### Simulation and motion

- **SIM-001:** The digital twin shall represent the robot, gripper, payload,
  rack, machine envelope, door, table, vise, and exchange volume.
- **SIM-002:** The simulation shall use the same named cell states and adapter
  contracts intended for the physical system.
- **SIM-003:** The user shall be able to play, pause, reset, and inspect the
  sequence and current device states.
- **SIM-004:** Motion planning shall enforce robot joint limits.
- **SIM-005:** Before physical commissioning, the simulation shall use detailed
  collision geometry and reject collisions across the full trajectory.
- **SIM-006:** The system shall support fault injection for lost grip, occupied
  slot, door disagreement, clamp disagreement, CNC alarm, timeout, and lost
  communications.
- **SIM-007:** A simulation run shall produce an event log with timestamps,
  transitions, commands, acknowledgements, and faults.

### Cell orchestration

- **CTL-001:** The orchestrator shall implement explicit states, guards,
  acknowledgements, and timeouts.
- **CTL-002:** Any disagreement or timeout shall enter `SAFE_STOP` and inhibit
  further automatic motion.
- **CTL-003:** Recovery shall require an explicit operator action and shall not
  resume an interrupted motion automatically.
- **CTL-004:** CNC cycle start shall be inhibited unless the robot is confirmed
  outside the protected volume, the door is closed, the fixture is confirmed
  clamped, and the approved job identity matches.
- **CTL-005:** Robot entry shall be inhibited unless the spindle is stopped,
  machine axes are in the approved exchange pose, and the access condition is
  confirmed.
- **CTL-006:** The system shall track whether each jaw is in the rack, gripper,
  vise, inspection station, or an unknown location.

### Configuration and extensibility

- **CFG-001:** Machine, vise, robot, gripper, rack, blank, and CAM definitions
  shall be versioned data profiles separated from core logic.
- **CFG-002:** Fit-critical dimensions shall carry a source and verification
  status: published, measured, inferred, or unverified.
- **CFG-003:** A profile with an unverified fit-critical dimension shall be
  blocked from production release.
- **CFG-004:** Adapter interfaces shall allow a new supported component to be
  added without changing the jaw geometry kernel.

## 10. State model

```text
IDLE
  -> JOB_VALIDATED
  -> PICK_BLANK
  -> VERIFY_GRIP
  -> REQUEST_LOAD
  -> DOOR_OPEN_CONFIRMED
  -> LOAD_BLANK
  -> FIXTURE_CLAMPED_CONFIRMED
  -> ROBOT_CLEAR_CONFIRMED
  -> DOOR_CLOSED_CONFIRMED
  -> CNC_CYCLE
  -> CYCLE_COMPLETE
  -> SPINDLE_ZERO_CONFIRMED
  -> DOOR_OPEN_CONFIRMED
  -> UNCLAMP
  -> PICK_FINISHED_JAW
  -> RETURN_TO_RACK
  -> COMPLETE
```

Any active state may transition to `SAFE_STOP`. `SAFE_STOP` records the cause,
removes automatic run permission, and requires an approved recovery procedure.

## 11. Data model and principal artifacts

Each job shall have a unique job ID and immutable released revision. The minimum
job record contains:

- source part identifier, file checksum, units, and revision;
- part-to-vise transform and approved grip definition;
- machine, vise, robot, gripper, rack, blank, and CAM profile versions;
- all jaw-generation parameters;
- left/right output file checksums;
- validation report and acknowledged warnings;
- CAM project/program identity and approval status;
- assigned rack slots and payload identities;
- simulation result and software version;
- physical commissioning authorization, when applicable; and
- event, alarm, recovery, and inspection history.

Primary generated artifacts are:

- left-jaw STEP and optional STL;
- right-jaw STEP and optional STL;
- manufacturing/job manifest;
- validation report;
- simulation event log;
- approved CNC program reference; and
- inspection record.

## 12. Non-functional requirements

- **NFR-001 — Safety:** No application-level success state may bypass a
  safety-rated guard, E-stop, or interlock.
- **NFR-002 — Traceability:** Released geometry, CAM, profiles, and results shall
  be reproducible from versioned inputs.
- **NFR-003 — Explainability:** Every blocked job shall provide a useful reason
  rather than a generic failure.
- **NFR-004 — Reliability:** Commands to robot and CNC adapters shall be
  idempotent where possible and paired with explicit acknowledgements.
- **NFR-005 — Units:** Internal units and conversions shall be explicit; no file
  may depend on an implicit inch/millimeter assumption.
- **NFR-006 — Security:** Physical adapters shall require authenticated access,
  least privilege, and an auditable configuration.
- **NFR-007 — Performance:** A typical jaw-generation validation run should
  complete in under 60 seconds on the reference engineering workstation,
  excluding CAM and high-fidelity motion planning.
- **NFR-008 — Portability:** The geometry service and simulation interfaces
  shall run without vendor-specific CNC hardware attached.
- **NFR-009 — Testability:** Hardware adapters shall have deterministic fake
  implementations for automated tests and fault injection.

## 13. Safety and commissioning gates

The product controls a potentially hazardous machine cell. A software PRD is
not a risk assessment and does not establish regulatory compliance.

Physical motion remains disabled until all applicable gates are signed off:

1. Vise, blanks, rack, gripper, machine, and robot are measured and modeled.
2. Robot payload, reach, repeatability, duty cycle, and failure behavior are
   confirmed for the intended operation.
3. A cell risk assessment defines guarding, safe distances, access control,
   reset behavior, and required performance levels.
4. Safety-rated E-stop, guard/door interlocks, and machine-permission circuits
   are installed and validated independently of the application software.
5. Detailed collision models and tool-center-point calibration are verified.
6. Dry runs pass at reduced speed with no cutting tool and spindle disabled.
7. CNC tending runs pass with the tool removed and cycle start inhibited.
8. Supervised cutting is approved with conservative limits and inspection after
   each cycle.

## 14. MVP acceptance criteria

The simulation-and-geometry MVP is accepted when:

- Ten representative STEP parts and poses can be imported and saved as jobs.
- The generator produces a correctly identified left/right jaw pair for every
  valid test case.
- Deliberately thin walls, blocked cutters, protected-feature intersections,
  and impossible removal directions are rejected with specific diagnostics.
- Exported jaw geometry opens correctly in the selected CAD/CAM validation
  tools and aligns with the defined WCS and blank.
- A machinist can use the manifest to create or validate the Mastercam setup
  without re-entering the part pose or blank definition.
- The B601-DM digital twin completes rack pickup, machine load, simulated cycle,
  unload, and return without violating joint limits or approved collision
  geometry.
- The simulation correctly enters `SAFE_STOP` for every required injected
  fault and does not resume automatically.
- Replaying an approved simulation produces a complete event log and the same
  final inventory state.
- Configuration profiles can be changed without modifying geometry or
  orchestration source code.
- No physical robot or CNC command path is enabled in the MVP build.

The physical pilot has separate acceptance criteria and cannot inherit approval
from a successful browser or software simulation.

## 15. Success metrics

Initial baselines will be measured during the geometry proof and supervised
pilot. Target metrics are:

- At least 80% reduction in engineering time from part orientation to
  CAM-ready jaw geometry for supported parts.
- At least 95% of valid reference jobs generate without manual CAD repair.
- 100% detection of the defined invalid-geometry regression cases.
- 100% successful detection and safe-stop response for required simulated
  faults.
- Zero uncommanded physical motion and zero bypassed interlocks during staged
  commissioning.
- Complete traceability from finished jaw pair to part, pose, parameters, CAM
  program, rack location, and inspection record.

## 16. Delivery plan

### Phase 0 — Current browser demonstrator

- Simplified cell layout and B601-DM joint model.
- Animated rack-to-machine-to-rack sequence.
- Manual playback, telemetry, and documented visual verification.

### Phase 1 — Measured digital twin

- Measure the VEVOR jaw interface and blank geometry.
- Add production gripper and rack CAD.
- Replace simplified collision geometry with verified models.
- Establish cell frames, TCP, exchange pose, and calibration procedure.

### Phase 2 — Jaw geometry proof

- Implement STEP import and parameterized jaw generation.
- Implement validation and reporting.
- Test ten representative parts.
- Machine generated jaws manually and compare against inspection results.

### Phase 3 — Mastercam handoff

- Finalize the manifest and naming rules.
- Validate repeatable Mastercam import and setup creation.
- Add human approval and CNC program checksum tracking.

### Phase 4 — Motion-planned simulated cell

- Integrate ROS 2, MoveIt 2, inverse kinematics, and collision checking.
- Execute the production state machine with simulated adapters.
- Add automated tests, fault injection, logs, and replay.

### Phase 5 — Hardware dry runs

- Commission robot, gripper, rack, machine exchange pose, and safety I/O in the
  staged sequence defined in Section 13.

### Phase 6 — Supervised pilot

- Machine sacrificial jaw pairs under direct supervision.
- Add inspection, compensation, tool-life, retry, and recovery procedures.

### Phase 7 — Extensible product

- Add supported component profiles and CAM/CNC adapters.
- Provide a guided job-setup UI, deployment tooling, and fleet-level
  traceability.

## 17. Dependencies and assumptions

- A valid part STEP file and intended setup are available.
- Expected machining forces or a conservative approved load envelope are known.
- The operator can identify acceptable grip/contact regions.
- Mastercam and the required postprocessor are licensed and available.
- Official or measured geometry can be obtained for collision-critical items.
- The B601-DM can meet the final payload and reach requirements; this remains to
  be verified and is not assumed by the current simulation.
- The Haas configuration exposes suitable documented automation I/O for the
  eventual physical integration.

## 18. Principal risks and mitigations

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| Incorrect vise or blank dimensions | Jaws do not fit or mounting features are cut | Block production profiles until critical dimensions are measured |
| Orientation treated as sufficient workholding data | Part movement or ejection | Require grip region, loads, contacts, and constraint validation |
| Simplified collision models | Robot, machine, or payload collision | Use simplified geometry only for concept work; require verified collision CAD before commissioning |
| B601-DM payload/reach is insufficient | Dropped jaw or unreachable exchange pose | Complete measured payload and reach study before buying or machining final tooling |
| CAM handoff mismatch | Wrong WCS, stock, tool, or program | Versioned manifest, checksum, simulation, and human approval |
| Stale or mismatched job identity | Wrong jaws or program loaded | Scan/identify payloads and require job/program/profile match before cycle permission |
| Sensor or communications failure | Unknown cell state | Timeouts, independent feedback, `SAFE_STOP`, and explicit recovery |
| Software mistaken for a safety system | Severe injury or equipment damage | Independent safety-rated hardware and formal risk assessment |

## 19. Open decisions

- Exact Haas Mini Mill generation, controller options, and available automation
  interface.
- Measured VEVOR removable-jaw bolt spacing, thread, counterbores, locating
  surfaces, and usable blank envelope.
- Final Delrin blank dimensions, tolerances, identification method, and whether
  blanks are handled singly or as a matched pair.
- Final gripper concept, finger geometry, compliance, sensing, payload, and TCP.
- Rack slot count, pitch, retention, datum scheme, and finished-jaw storage
  policy.
- How the user selects grip regions: face selection, painted regions, rules, or
  an optimizer with human approval.
- Machining-load input method and the first constraint-analysis model.
- Required jaw and part tolerances and inspection method.
- Mastercam version, SDK access, postprocessor, and desired automation depth.
- Simulation fidelity required before the first hardware purchase decision.

## 20. Immediate next steps

1. Complete the VEVOR vise measurement worksheet.
2. Select one representative STEP part and define its intended pose, grip
   region, loads, and allowable contact surfaces.
3. Establish exact Delrin blank dimensions and rack requirements.
4. Create the initial gripper envelope, payload model, TCP, and finger CAD.
5. Measure the intended cell layout and Haas exchange envelope.
6. Implement the first jaw geometry spike and compare it with a manually
   designed Mastercam-ready jaw.
7. Replace provisional animation waypoints with IK-planned, collision-checked
   paths using verified geometry.

