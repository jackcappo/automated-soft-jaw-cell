# Playback verification

## 2026-09-25 browser MVP

The complete simulated cycle was watched in the in-app browser, with playback
paused for visual and telemetry checks at the following phases:

- Pick blank: robot moved to the rack pose, door was open, gripper closed.
- Load vise: payload followed the gripper into the CNC exchange volume.
- Machine: robot was at home, door was closed, payload was in the vise.
- Unload/return: payload was retrieved and returned to the rack.
- Complete: robot returned home, door closed, spindle stopped, gripper open,
  and payload cleared.

The first playback found that spindle state was being enabled at the end of the
Machine phase. The sequence was corrected so `machineStart` runs on phase entry
and `machineComplete` runs on phase exit. Playback was repeated after the fix.

This verifies the browser state machine and animation sequence only. It does not
verify collision clearance, real robot reach, CNC interlocks, or machine safety.
