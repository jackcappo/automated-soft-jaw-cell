# Cell measurements to replace estimates

`python -m softjaw plan` lists every assumed or estimated value it used. The ones that
most affect reach (vise distance from the robot) come first. Record in mm, then update
the value and set `"status": "measured"` in the named profile.

| Value | Profile field | Current estimate |
|---|---|---|
| Front face of machine to table centre (door closed) | machines/haas-mini-mill.json `enclosure_estimates.front_wall_to_table_center` | 302.5 |
| Table top height above floor | `enclosure_estimates.table_top_height_from_floor` | 760 |
| Door opening width / bottom / top | `enclosure_estimates.door_opening_*` | 700 / 650 / 1450 |
| Spindle head width and depth | `enclosure_estimates.spindle_head_*` | 160 / 145 |
| Table jog toward door and sideways at exchange | `automation.robot_exchange_pose.*` | 100 / 150 |
| Vise jaw-seat height above table | cells/haas-mini-mill-b601.json `vise_on_table.seat_height_above_table` | 98 |
| Robot base position (centre of flange, floor frame) | `robot_base.xyz` | (-165, 0, 860) |
| Rack origin (slot 0 base centre) | `rack.origin` | (-520, -250, 760) |
| Blank width / height / thickness | blanks/delrin-125x45x25.json | 125 / 45 / 25 |
| Parallel height, hard-jaw thickness, loading gap | vises/vevor-5in-accu-lock.json `robot_machining_setup.*` | 12 / 18 / 6 |

Measure with the machine at the intended robot exchange pose and the door open.
