# Automated Soft-Jaw Cell

This project defines a simulation-first cell that generates machinable soft-jaw
geometry from a part pose, machines the jaws, and uses a reBot B601-DM to move
Delrin blanks between a rack and a CNC machine.

> Status: system specification and MVP contract. No real machine or robot may be
> driven from this repository until the safety I/O and dry-run acceptance tests
> below have been implemented and reviewed.

## MVP boundary

The first working version should:

1. Import a part as STEP and accept a fixture pose (`4x4` transform).
2. Import the vise, jaw blank, rack, robot, gripper, and CNC enclosure models.
3. Generate left and right jaw inserts with configurable clearance, grip depth,
   corner relief, minimum wall thickness, and protected mounting features.
4. Reject invalid jaws before CAM if the part is underconstrained, geometry is
   too thin, tool access is impossible, or the cavity intersects a keep-out.
5. Export jaw STEP/STL plus a manufacturing manifest.
6. Simulate rack pickup, CNC loading, door/chuck or vise handshakes, unloading,
   and return-to-rack with collision checking.
7. Run the full cell using simulated CNC and robot adapters before either real
   adapter can be enabled.

Automatic CAM and unattended machine start are intentionally later milestones.

## First supported cell profile

The first target is a current-generation Haas Mini Mill, VEVOR 5-inch ACCU
lock-down vise, pneumatic vise actuator, reBot B601-DM, and Mastercam. The
profile files are deliberately data-only so another machine, vise, robot, or CAM
system can be added without changing the geometry kernel:

- `config/machines/haas-mini-mill.json`
- `config/vises/vevor-5in-accu-lock.json`
- `config/cam/mastercam.json`

An immediately runnable layout and sequence simulator is available in
`sim-web/`. It uses the published B601-DM joint geometry with simplified link,
machine, vise, rack, and gripper solids. See `sim-web/README.md` for startup and
current limitations.

The selected VEVOR product is SKU `TQ5CDXZDZJMPKQ001V0`. VEVOR publishes its
125 mm jaw width, 125 mm opening, 40 mm jaw height, 24 kN maximum clamping
force, and approximate overall envelope, but not the replaceable-jaw bolt and
counterbore pattern. Those fit-critical dimensions remain explicitly
unverified in the profile. Do not cut jaw blanks from the profile until the
measurements in `docs/vevor-vise-measurement-sheet.md` are completed.

## Recommended stack

- **Geometry:** Python 3.12, CadQuery/OpenCascade, trimesh, NumPy.
- **Robot and cell control:** Ubuntu 24.04, ROS 2 Jazzy, MoveIt 2.
- **Fast development simulation:** MuJoCo using the available B601-DM ROS stack.
- **Higher-fidelity digital twin:** NVIDIA Isaac Sim when enclosure, sensor, and
  synthetic-camera fidelity becomes important.
- **Task orchestration:** a ROS 2 lifecycle/state-machine node. Keep geometry,
  motion planning, CNC communication, and safety I/O in separate processes.
- **CNC adapter:** controller-specific. Use documented cycle-start, door, vise,
  feed-hold, alarm, and program-complete signals through a safety-rated cell
  controller; do not automate the CNC through screen clicks.
- **Initial CAM adapter:** export STEP, named WCS/planes, stock metadata, and a
  job manifest for Mastercam. CloudNC Soft Jaw Designer can be used as a manual
  baseline while our generated geometry and validation are developed. Direct
  Mastercam integration is a later adapter using the supported Mastercam SDK.

The B601-DM is a 6-DOF arm plus gripper and communicates over a USB-to-CAN
bridge. Its published ROS integration exposes joint states, trajectory actions,
gripper control, MoveIt 2 planning, and simulated drivers. The official project
also publishes URDF/mesh assets and MuJoCo/Isaac Sim examples.

## System architecture

```text
Part STEP + requested fixture pose
                |
                v
      Jaw geometry generator
   (contact, clearance, keep-outs)
                |
         validation report
                |
                v
        STEP/STL + manifest
                |
          approved CAM job
                |
                v
 Cell orchestrator / state machine
       |          |          |
    MoveIt 2   CNC adapter  Safety PLC
       |          |          |
  B601 driver  CNC control  door/E-stop/vise
```

The digital twin uses the same state-machine transitions and adapter interfaces
as the real cell. Only the adapter implementations change.

## Jaw-generation algorithm

Inputs are defined in `config/example-job.json`.

1. Transform the part into the vise coordinate frame using `part_pose_in_vise`.
2. Intersect the part with the allowed grip-height band on each side of the vise
   center plane.
3. Offset the captured surfaces by `cavity_clearance_mm`. Apply a separate
   negative or zero allowance only to explicitly selected locating pads.
4. Subtract the two resulting cavity volumes from the left and right blanks.
5. Add tool-radius corner relief and optional chip-clearance scallops.
6. Preserve mounting holes, counterbores, serrations, and all configured
   keep-out volumes.
7. Verify minimum wall thickness, cavity depth, insertion direction, cutter
   reach, part removal, and collision-free gripper access.
8. Compute a constraint score. Do not release a job that cannot resist the
   expected machining forces in all required directions.

Part orientation alone is not enough to produce a safe jaw. The generator also
needs the desired grip region or approved candidate surfaces, machining loads,
blank/vise geometry, cutter limits, and allowable cosmetic/contact zones.

## Cell sequence

```text
IDLE -> JOB_VALIDATED -> PICK_BLANK -> VERIFY_GRIP
     -> REQUEST_LOAD -> DOOR_OPEN_CONFIRMED -> LOAD_BLANK
     -> FIXTURE_CLAMPED_CONFIRMED -> ROBOT_CLEAR_CONFIRMED
     -> DOOR_CLOSED_CONFIRMED -> CNC_CYCLE
     -> CYCLE_COMPLETE -> SPINDLE_ZERO_CONFIRMED -> DOOR_OPEN_CONFIRMED
     -> UNCLAMP -> PICK_FINISHED_JAW -> RETURN_TO_RACK -> COMPLETE
```

Every transition has a timeout and enters `SAFE_STOP` on disagreement, loss of
communications, unexpected motion, dropped part, CNC alarm, or safety input.
Recovery must be explicit and must never resume mid-motion automatically.

## Safety requirements

- Use a guarded cell, safety-rated E-stop chain, door interlock, and appropriate
  risk assessment. Software state alone is not a safety function.
- The CNC must confirm spindle stopped and axes in a robot-safe exchange pose
  before the door can open or the robot can enter.
- The robot must confirm it is outside the machine envelope before cycle start.
- Independently sense gripper possession, rack occupancy, fixture clamp state,
  and door state. A camera may supplement but must not replace safety signals.
- Start with reduced speed, no tool, spindle disabled, and sacrificial blanks.
- Confirm the real B601-DM payload, reach, repeatability, duty cycle, ingress
  protection, and fail-safe behavior. Treat it as development hardware until a
  formal assessment shows it is suitable for the intended production cell.

## Delivery phases

1. **Geometry proof:** generate and inspect jaw STEP files for ten representative
   parts and poses; machine them manually.
2. **Digital twin:** model rack, vise, CNC door/envelope, robot base, gripper,
   blanks, and TCP; validate reach and collision-free trajectories.
3. **Simulated cell:** execute the state machine against fake robot/CNC/safety
   adapters, including injected faults and recovery.
4. **Robot dry runs:** physical robot and rack, no CNC entry and no spindle.
5. **CNC tending dry runs:** machine powered, tool removed, cycle start disabled.
6. **Supervised cutting:** single-cycle operation with conservative motion and
   inspection after every jaw.
7. **Production hardening:** metrology feedback, tool-life tracking, retries,
   traceability, and a completed machine-safety review.

## Information needed to begin implementation

- CNC make/model/controller and available automation I/O or API.
- Vise make/model, jaw mounting pattern, blank dimensions, and blank rack CAD.
- Part CAD examples and how the desired orientation/grip region will be supplied.
- Gripper model/finger CAD and the mass of one blank/finished jaw.
- Cell layout dimensions or CAD, including CNC door motion and exchange pose.
- Target jaw tolerances, cutter library, expected machining forces, and whether
  CAM should target Fusion, FreeCAD Path, Mastercam, or controller-native output.

## Upstream references

- B601-DM hardware: https://github.com/Seeed-Projects/reBot-DevArm
- ROS 2 / MoveIt 2 guide: https://wiki.seeedstudio.com/rebot_arm_b601_dm_ros2_integration/
- Digital twin guide: https://wiki.seeedstudio.com/rebot_arm_b601_dm_web_simulator_developer_guide/
- Isaac Sim guide: https://wiki.seeedstudio.com/rebot_arm_b601_dm_isaacsim/
- Haas Mini Mill specifications: https://www.haascnc.com/machines/vertical-mills/mini-mills/models/minimill.html
- Selected VEVOR vise: https://www.vevor.com/mill-vise-c_10811/5-milling-machine-lockdown-vise-swivel-base-swivel-base-hardened-metal-cnc-p_010165314250
- CloudNC Soft Jaw Designer: https://www.cloudnc.com/blog/soft-jaw-fixtures-for-free
- Mastercam developer program: https://www.mastercam.com/community/3rd-party-developers/
