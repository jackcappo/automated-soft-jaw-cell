# Browser cell simulator

This is the first runnable digital-twin shell for the automated soft-jaw cell.
It models the Haas Mini Mill envelope, VEVOR vise, blank rack, Delrin blanks,
and reBot B601-DM motion sequence.

The B601-DM joint origins, joint axes, and limits are taken from Seeed's
published `ReBot_Arm_DM.urdf`. Link shapes are intentionally simplified for the
layout prototype; they are not collision-certified geometry.

## Run

From this directory:

```powershell
python -m http.server 8070
```

Open <http://localhost:8070>.

The simulator is self-contained and does not require npm. Babylon.js is vendored
under `vendor/` so the scene works offline.

## Implemented

- Orbit, pan, and zoom around the cell.
- B601-DM six-joint kinematic chain and joint-limit sliders.
- Simplified Haas Mini Mill, table, vise, exchange volume, and sliding door.
- Six-slot Delrin blank rack.
- Animated rack-to-CNC-to-rack sequence.
- Simulated door, spindle, gripper, and payload state.
- Pause, reset, and manual joint inspection.

## Known limitations

- Sequence poses are provisional joint-space waypoints, not IK-planned paths.
- Machine, vise, rack, and robot links use simplified geometry.
- There is no physics, collision rejection, reach study, or cycle-time model.
- The current gripper is a placeholder matching the stock parallel-gripper
  envelope. Replace it when the production gripper CAD is ready.
- No real machine or robot interface exists in this browser simulator.

## Next simulation milestone

1. Replace simplified robot solids with official visual/collision meshes.
2. Move scene transforms to a versioned cell-layout configuration file.
3. Add TCP targets and numerical inverse kinematics.
4. Add broad-phase collision checks for robot, machine, vise, rack, and payload.
5. Export the validated layout and named waypoints to ROS 2 / MoveIt 2.

## Sources

- B601-DM URDF and ROS 2 project:
  https://github.com/Seeed-Projects/reBotArmController_ROS2
- Haas Mini Mill specifications:
  https://www.haascnc.com/machines/vertical-mills/mini-mills/models/minimill.html

