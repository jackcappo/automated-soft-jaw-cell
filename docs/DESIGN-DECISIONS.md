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
At the exchange pose the table moves to the front of its Y travel (152 mm toward the door,
`automation.robot_exchange_pose` in the machine profile), and the vise is mounted 60 mm
forward of the table centre (`vise_on_table.offset_from_table_center`). The Haas layout
drawing puts the table top at 1009 mm and the spindle 595 mm behind the enclosure front, so
without both the B601-DM cannot reach the vise from outside the machine. Even so the reach
margin is about 10 mm; confirm the travels and the vise position on your machine.

## 8. Robot and rack ride on a docking cart
The robot and the blank rack share one wheeled cart (`cart` in the cell profile) instead of
a floor pedestal and a separate rack, so the cell rolls away from the machine as one unit.
The robot-to-rack geometry is fixed on the cart; only the cart-to-machine position depends
on where it is parked, so the cart docks against a floor-mounted block with tapered
locating pins, and leveling feet (or locking casters) take the load off the wheels while
the cell runs. The robot mount, rack and home pose are given in the cart frame and follow
`cart.docked_position`; the planner collision-checks the arm against the deck, legs,
riser and handle. Undocked, the vise is out of reach (a test checks this), so a cycle must
not start until docking is confirmed; add that interlock before physical commissioning.
The cart is modelled axis-aligned (yaw 0).

Because the table is at 1009 mm, the cart is tall: the deck is at 1130 mm, so the robot on
a short 120 mm riser has its flange at 1250 mm and the rack slots sit at 1150 mm straight on
the deck. A reach and collision sweep bounds the flange height: at 1200 mm the arm cannot
reach the vise, and at 1300 mm the elbow hits the wall above the door. The push bar is on
the back legs at 1000 mm. The cart is 660 mm wide and parks 40 mm to the operator's right
of the door centre so its legs clear the tray on the left of the door (from y=+300, about
250 mm deep, 780-940 mm up); the robot mount is offset on the cart to stay on the door
centreline. A deck this high on casters is top-heavy: keep the leveling feet down whenever
the robot moves, and consider a wider base or ballast on the lower shelf.

## 9. Collision checking is broad-phase
Robot links are capsules along the URDF joint chain, the cell is boxes from the profiles.
This rejects bad layouts early. It is not a substitute for verified collision meshes before
commissioning (PRD SIM-005).
