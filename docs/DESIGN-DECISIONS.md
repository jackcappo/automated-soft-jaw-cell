# Design decisions (amendments to PRD v0.1)

These were made while implementing the MVP and change or add to `docs/PRD.md`.

## 1. Blanks are machined standing in the hard jaws
A robot cannot bolt soft jaws onto a vise. Each blank is clamped standing up, across its
thickness, on a parallel, so the top of the blank protrudes above the hard jaws by
`parallel_height + blank_height - hard_jaw_height`. The pocket must fit in that exposed
band with 2 mm to spare (VAL-008), so the cutter never reaches steel. The robot grips the
same exposed band, so it must also be at least `finger_grip_depth`.

## 2. Mounting holes are pre-drilled
A standing blank cannot have its horizontal mounting holes drilled on a 3-axis mill. Blanks
are prepared in batches (or bought) with holes and counterbores. The generator checks the
pocket keeps a minimum wall to those holes (VAL-001).

## 3. Pockets are 2.5D
A top-down 3-axis pocket is a planar profile plus a flat floor at the part's lowest point.
The profile is the union of the part's sections through the jaw height, offset by the
clearance. This matches how soft jaws are normally cut and maps directly onto a Mastercam
2D pocket. Undercut or 3D-contoured nests (e.g. a V cradle) are future work.

## 4. Jaw gap comes from nest depth
Instead of a fixed gap, the jaw faces sit `nest_depth_mm` inside the part's extent on each
side, so parts up to the vise's capacity fit (VAL-009). `jaw_face_gap_mm` still overrides.

## 5. DXF + STL are the primary CAM outputs
The CAM handoff is a DXF pocket chain in a defined jaw WCS plus a watertight STL, both of
which Mastercam imports directly. STEP (PRD CAM-001) is produced when CadQuery is installed;
the geometry kernel itself only needs NumPy/SciPy.

## 6. Finger width recommendation
The stock B601-DM fingers are about 26 mm wide. With pockets up to ~85 mm wide on a 125 mm
jaw, fingers must regrasp the finished jaw beside the pocket. The placeholder gripper uses
20 mm fingers; set the real value from your gripper CAD. VAL-004 checks this per job.

## 7. Table jog before robot entry
At the exchange pose the table moves toward the door and sideways so the vise is out from
under the spindle and within reach (`automation.robot_exchange_pose` in the machine
profile). The planner assumes 100 mm toward the door and 150 mm sideways; confirm these fit
your machine's travels and door.

## 8. Collision checking is broad-phase
Robot links are capsules along the URDF joint chain, the cell is boxes from the profiles.
This rejects bad layouts early. It is not a substitute for verified collision meshes before
commissioning (PRD SIM-005).
