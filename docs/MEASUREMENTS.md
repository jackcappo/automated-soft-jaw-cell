# Cell measurements to replace estimates

`python -m softjaw plan` lists every assumed or estimated value it used. The ones that
most affect reach (vise distance from the robot) come first. Record in mm, then update
the value and set `"status": "measured"` in the named profile.

The reach margin is only about **10 mm** (the vise could sit 10 mm further in before the
robot cannot load it), so measure the first rows before building the cart.

Table height, door width and front-to-spindle distance come from the Haas layout drawing
(Mini Mill MLD, 2/10/2022, on 76 mm leveling pads); confirm them on your machine.

| Value | Profile field | Current value |
|---|---|---|
| Front face of machine to table centre, table centred under the spindle | machines/haas-mini-mill.json `enclosure_estimates.front_wall_to_table_center` | 595 (published) |
| Table jog toward door and sideways at exchange | `automation.robot_exchange_pose.*` | 152 (front of Y travel) / 0 |
| Vise offset on the table toward the door | cells/haas-mini-mill-b601.json `vise_on_table.offset_from_table_center` | (-60, 0), overhangs the table front ~76 |
| Table top height above floor | `enclosure_estimates.table_top_height_from_floor` | 1009 (published) |
| Door opening width / bottom / top | `enclosure_estimates.door_opening_*` | 653 (published) / 890 / 1700 |
| Spindle head width and depth | `enclosure_estimates.spindle_head_*` | 160 / 145 |
| Vise jaw-seat height above table | `vise_on_table.seat_height_above_table` | 98 |
| Cart docked position (floor under the centre of its front edge, world frame) | `cart.docked_position` | (-70, -40) |
| Cart deck top height above floor (casters down, leveling feet set) | `cart.deck_top_height` | 1130 |
| Robot flange centre on the cart (cart frame) | `cart.robot_mount.xy` | (-55, 40), riser 120 → flange at (-125, 0, 1250) docked |
| Rack origin, slot 0 base centre on the cart (cart frame) | `cart.rack_origin_xy` | (-450, -210), plate 20 → (-520, -250, 1150) docked |
| Blank width / height / thickness | blanks/delrin-125x45x25.json | 125 / 45 / 25 |
| Parallel height, hard-jaw thickness, loading gap | vises/vevor-5in-accu-lock.json `robot_machining_setup.*` | 12 / 18 / 6 |

Measure with the machine at the intended robot exchange pose and the door open.
Measure the cart values with the cart docked; the robot mount and rack are measured on the
cart itself and do not change when it is moved.
