"""Cell layout, IK waypoints, broad-phase collision sweep and reach study.

Collision checking is broad-phase: robot links are capsules along the
joint-origin chain, the gripper is a capsule plus two fingertip spheres, the
payload is a sampled box, and the cell is axis-aligned boxes built from the
profiles. It is good enough to reject layouts and waypoints early (SIM-005
pre-screen); it is NOT a substitute for verified collision meshes before
commissioning.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from .kinematics import Arm
from .profiles import Tracker, load_json, ROOT

DOWN = (0, 0, -1)
FINGERS_X = (1, 0, 0)


@dataclass
class Box:
    name: str
    lo: np.ndarray
    hi: np.ndarray
    kind: str = "static"      # static | vise_jaw | rack_blank | machine

    def distance(self, p):
        d = np.maximum(np.maximum(self.lo - p, p - self.hi), 0)
        return np.linalg.norm(d, axis=-1)

    def as_dict(self):
        return {"name": self.name, "kind": self.kind, "min": self.lo.round(2).tolist(), "max": self.hi.round(2).tolist()}


def B(name, x, y, z, kind="static"):
    return Box(name, np.array([x[0], y[0], z[0]], float), np.array([x[1], y[1], z[1]], float), kind)


@dataclass
class Cell:
    profile: dict
    arm: Arm
    boxes: list
    frames: dict
    blank: dict
    gripper: dict
    tracker: Tracker
    notes: list = field(default_factory=list)


def build_cell(cell_path="config/cells/haas-mini-mill-b601.json", vise_shift=(0.0, 0.0)) -> Cell:
    tr = Tracker()
    cell = load_json(cell_path)
    prof = {k: load_json(v) for k, v in cell["profiles"].items()}
    mach, vise, robot, grip, blank = prof["machine"], prof["vise"], prof["robot"], prof["gripper"], prof["blank"]
    est = mach["enclosure_estimates"]
    table_z = tr.get(mach, "enclosure_estimates", "table_top_height_from_floor")
    door_w = tr.get(mach, "enclosure_estimates", "door_opening_width")
    door_lo = tr.get(mach, "enclosure_estimates", "door_opening_bottom_from_floor")
    door_hi = tr.get(mach, "enclosure_estimates", "door_opening_top_from_floor")
    table_cx = tr.get(mach, "enclosure_estimates", "front_wall_to_table_center")
    shift_in = tr.get(mach, "automation", "robot_exchange_pose", "table_shift_toward_door")
    shift_side = tr.get(mach, "automation", "robot_exchange_pose", "table_shift_sideways")
    nose_max = tr.get(mach, "spindle", "nose_to_table_max")
    head_w = tr.get(mach, "enclosure_estimates", "spindle_head_width")
    head_d = tr.get(mach, "enclosure_estimates", "spindle_head_depth")
    tbl_l = tr.get(mach, "table", "length")
    tbl_w = tr.get(mach, "table", "width")
    seat = tr.get(cell, "vise_on_table", "seat_height_above_table")
    env = vise["published"]["approximate_envelope"]
    T = tr.get(blank, "thickness")
    W = tr.get(blank, "width")
    H = tr.get(blank, "height")
    hard_h = tr.get(vise, "robot_machining_setup", "hard_jaw_height")
    hard_t = tr.get(vise, "robot_machining_setup", "hard_jaw_thickness")
    par = tr.get(vise, "robot_machining_setup", "parallel_height")
    open_extra = tr.get(vise, "robot_machining_setup", "loading_open_gap_extra")
    base_xyz = tr.get(cell, "robot_base", "xyz")
    rack_o = np.array(tr.get(cell, "rack", "origin"), float)

    # vise at the exchange pose: table jogged toward the door and sideways
    vx = table_cx - shift_in + vise_shift[0]
    vy = shift_side + vise_shift[1]
    seat_z = table_z + seat
    blank_bottom = seat_z + par
    boxes = []
    hw = door_w / 2
    boxes += [B("front_wall_below_door", (-50, 0), (-800, 800), (0, door_lo), "machine"),
              B("front_wall_above_door", (-50, 0), (-800, 800), (door_hi, 1900), "machine"),
              B("front_wall_left", (-50, 0), (hw, 800), (door_lo, door_hi), "machine"),
              B("front_wall_right", (-50, 0), (-800, -hw), (door_lo, door_hi), "machine"),
              B("table", (vx - tbl_w / 2, vx + tbl_w / 2), (vy - tbl_l / 2, vy + tbl_l / 2), (table_z - 60, table_z), "machine"),
              B("vise_body", (vx - env["length"] / 2, vx + env["length"] / 2), (vy - env["width"] / 2, vy + env["width"] / 2), (table_z, seat_z), "machine"),
              B("spindle_head", (table_cx - head_d / 2, table_cx + head_d / 2), (-head_w / 2, head_w / 2), (table_z + nose_max, 1900), "machine"),
              B("hard_jaw_fixed", (vx + T / 2, vx + T / 2 + hard_t), (vy - W / 2, vy + W / 2), (seat_z, seat_z + hard_h), "vise_jaw"),
              B("hard_jaw_moving", (vx - T / 2 - open_extra - hard_t, vx - T / 2 - open_extra), (vy - W / 2, vy + W / 2), (seat_z, seat_z + hard_h), "vise_jaw"),
              B("parallel", (vx - T / 2, vx + T / 2), (vy - W / 2, vy + W / 2), (seat_z, blank_bottom), "vise_jaw"),
              B("robot_pedestal", (base_xyz[0] - 60, base_xyz[0] + 60), (base_xyz[1] - 60, base_xyz[1] + 60), (0, base_xyz[2] - 5))]
    pitch, nslot = cell["rack"]["slot_pitch_x"], cell["rack"]["slot_count"]
    boxes.append(B("rack_plate", (rack_o[0] - 40, rack_o[0] + pitch * (nslot - 1) + 40), (rack_o[1] - W / 2 - 15, rack_o[1] + W / 2 + 15), (rack_o[2] - 20, rack_o[2])))
    slots = []
    for k in range(nslot):
        c = rack_o + np.array([k * pitch, 0, 0])
        slots.append(c)
        boxes.append(B(f"rack_blank_{k}", (c[0] - T / 2, c[0] + T / 2), (c[1] - W / 2, c[1] + W / 2), (c[2], c[2] + H), "rack_blank"))

    arm = Arm(robot, base_xyz, cell["robot_base"].get("yaw_rad", 0.0))
    frames = {"vise_blank_center": np.array([vx, vy, blank_bottom + H / 2]), "vise_blank_top": blank_bottom + H,
              "hard_jaw_top": seat_z + hard_h, "rack_slots": slots, "rack_top": rack_o[2] + H,
              "door_transit": np.array(cell["clearances"]["door_transit"], float),
              "approach": cell["clearances"]["approach_height"], "base": np.array(base_xyz, float),
              "joint_speed": robot.get("commissioning_joint_speed_rad_s", 0.6),
              "load_x_offset": -open_extra / 2,
              "home": np.array(cell["clearances"]["home_tcp"], float)}
    return Cell(cell, arm, boxes, frames, {"T": T, "W": W, "H": H}, grip, tr)


# ----------------------------------------------------------------- collision

def robot_collisions(cell: Cell, q, holding: bool, ignore=(), margin=0.0):
    """Return list of (robot_part, obstacle, penetration_mm)."""
    arm, g = cell.arm, cell.gripper
    pts, rad, seg = arm.link_points(q)
    hits = []
    Tt = arm.tcp(q)
    tcp, ax, fy = Tt[:3, 3], Tt[:3, 0], Tt[:3, 1]
    # gripper body: flange->TCP capsule stops finger_grip_depth short of the tips
    grip_seg = seg == seg.max()
    keep = ~grip_seg | (np.linalg.norm(pts - tcp, axis=1) >= g["finger_grip_depth"] + 10)
    pts, rad, seg = pts[keep], rad[keep], seg[keep]
    half = cell.blank["T"] / 2 + 4.0 + 3.0          # finger inner face clearance + half finger thickness
    tips = np.array([tcp + fy * half + ax * 0, tcp - fy * half, tcp + fy * half - ax * g["finger_grip_depth"],
                     tcp - fy * half - ax * g["finger_grip_depth"]])
    pts = np.vstack([pts, tips])
    rad = np.concatenate([rad, [3.0] * 4])
    names = [f"link{s}" for s in seg] + ["fingertip"] * 4
    if holding:
        T, W, H = cell.blank["T"], cell.blank["W"], cell.blank["H"]
        gd = g["finger_grip_depth"]
        loc = [(x, y, z) for x in (-T / 2 + 1, T / 2 - 1) for y in np.linspace(-W / 2 + 1, W / 2 - 1, 7)
               for z in (-(H - gd) + 1, gd - 1)]
        R = np.column_stack([fy, np.cross(-ax, fy), -ax])   # payload frame: x=finger axis, z=up
        ppts = tcp + np.array(loc) @ R.T
        pts = np.vstack([pts, ppts])
        rad = np.concatenate([rad, [0.5] * len(ppts)])
        names += ["payload"] * len(ppts)
    for b in cell.boxes:
        if b.name in ignore:
            continue
        d = b.distance(pts) - rad - margin
        bad = d < 0
        if b.name == "robot_pedestal":
            bad &= np.array([n not in ("link0",) for n in names])
        if bad.any():
            k = int(np.argmin(np.where(bad, d, np.inf)))
            hits.append((names[k], b.name, round(float(-d[k]), 2)))
    return hits


# ----------------------------------------------------------------- waypoints

def waypoint_targets(cell: Cell, slot: int, grasp_y: float = 0.0):
    f, g = cell.frames, cell.gripper
    gd, app = g["finger_grip_depth"], f["approach"]
    slot_c = f["rack_slots"][slot]
    rack_tcp = np.array([slot_c[0], slot_c[1], f["rack_top"] - gd])
    vise_tcp = np.array([f["vise_blank_center"][0], f["vise_blank_center"][1], f["vise_blank_top"] - gd])
    off = np.array([0, grasp_y, 0])
    load = vise_tcp + [f["load_x_offset"], 0, 0]   # centred in the opened jaws
    return {
        "home": f["home"],
        "rack_above": rack_tcp + [0, 0, app],
        "rack_grasp": rack_tcp,
        "door_transit": f["door_transit"],
        "vise_above": load + [0, 0, app],
        "vise_place": load,
        "vise_above_finished": vise_tcp + off + [0, 0, app],
        "vise_grasp_finished": vise_tcp + off,
        "rack_above_finished": rack_tcp + off + [0, 0, app],
        "rack_place_finished": rack_tcp + off,
    }


# (from, to, holding, obstacles legitimately touched at the end points)
def jaw_route(slot):
    rb = f"rack_blank_{slot}"
    return [
        ("home", "rack_above", False, ()),
        ("rack_above", "rack_grasp", False, (rb,)),
        ("rack_grasp", "rack_above", True, (rb,)),
        ("rack_above", "home", True, (rb,)),
        ("home", "door_transit", True, ()),
        ("door_transit", "vise_above", True, ()),
        ("vise_above", "vise_place", True, ("parallel",)),
        ("vise_place", "vise_above", False, ()),
        ("vise_above", "door_transit", False, ()),
        ("door_transit", "home", False, ()),
        ("home", "door_transit", False, ()),
        ("door_transit", "vise_above_finished", False, ()),
        ("vise_above_finished", "vise_grasp_finished", False, ()),
        ("vise_grasp_finished", "vise_above_finished", True, ("parallel",)),
        ("vise_above_finished", "door_transit", True, ()),
        ("door_transit", "home", True, ()),
        ("home", "rack_above_finished", True, (rb,)),
        ("rack_above_finished", "rack_place_finished", True, (rb, "rack_plate")),
        ("rack_place_finished", "rack_above_finished", False, (rb,)),
        ("rack_above_finished", "home", False, ()),
    ]


def plan_jaw(cell: Cell, slot: int, grasp_y: float = 0.0, seed=None, samples=40):
    targets = waypoint_targets(cell, slot, grasp_y)
    route = jaw_route(slot)
    rb = f"rack_blank_{slot}"
    ik, q_prev, issues = {}, seed, []
    order = []
    for a, b, *_ in route:
        for n in (a, b):
            if n not in order:
                order.append(n)
    for name in order:
        r = cell.arm.ik(targets[name], DOWN, FINGERS_X, seeds=None if q_prev is None else [q_prev])
        ik[name] = r
        if not r["ok"]:
            issues.append({"type": "unreachable", "waypoint": name, "target_mm": targets[name].round(1).tolist(),
                           "pos_err_mm": round(r["pos_err_mm"], 2), "approach_err_deg": round(r["approach_err_deg"], 2)})
        q_prev = r["q"]
    speed = cell.frames["joint_speed"]
    segments = []
    for a, b, holding, touch in route:
        pa, pb = targets[a], targets[b]
        linear = np.allclose(pa[:2], pb[:2]) and abs(pa[2] - pb[2]) > 1e-6
        if linear:   # straight-line Cartesian approach/retreat, IK every 5 mm
            n = int(np.ceil(np.linalg.norm(pb - pa) / 5.0))
            path, q = [ik[a]["q"]], ik[a]["q"]
            for t in np.linspace(0, 1, n + 1)[1:]:
                r = cell.arm.ik(pa + (pb - pa) * t, DOWN, FINGERS_X, seeds=[q])
                if not r["ok"]:
                    issues.append({"type": "unreachable", "waypoint": f"{a}->{b} at t={t:.2f}"})
                q = r["q"]
                path.append(q)
            path[-1] = ik[b]["q"] if np.linalg.norm(ik[b]["q"] - q) < 0.05 else q
        else:
            path = [ik[a]["q"], ik[b]["q"]]
        ignore = set(touch) | ({rb} if holding or "finished" in b or "finished" in a else set())
        worst = []
        per = max(2, samples // (len(path) - 1))
        for q0, q1 in zip(path[:-1], path[1:]):
            for t in np.linspace(0, 1, per):
                hits = robot_collisions(cell, q0 + (q1 - q0) * t, holding, ignore=ignore)
                worst += [h for h in hits]
        steps = [float(np.max(np.abs(q1 - q0))) for q0, q1 in zip(path[:-1], path[1:])]
        dur = sum(steps) / speed + (1.0 if linear else 0.4)
        seg = {"from": a, "to": b, "holding": holding, "linear": bool(linear), "duration_s": round(dur, 2),
               "path": [[round(float(x), 5) for x in q] for q in path], "collisions": worst[:6]}
        if worst:
            issues.append({"type": "collision", "segment": f"{a}->{b}", "first": worst[0], "count": len(worst)})
        segments.append(seg)
    return {"slot": slot, "targets": {k: v.round(2).tolist() for k, v in targets.items()},
            "joints": {k: [round(float(x), 5) for x in v["q"]] for k, v in ik.items()},
            "segments": segments, "issues": issues, "cycle_motion_s": round(sum(s["duration_s"] for s in segments), 1)}


def reach_margin(cell_path="config/cells/haas-mini-mill-b601.json", step=10.0, limit=400.0):
    """How far further into the machine (+X) the vise could sit and still be loadable."""
    d = 0.0
    last_ok = None
    while d <= limit:
        c = build_cell(cell_path, vise_shift=(d, 0.0))
        t = waypoint_targets(c, 0)
        ok = all(c.arm.ik(t[n], DOWN, FINGERS_X)["ok"] for n in ("vise_place", "vise_above"))
        if not ok:
            break
        last_ok = d
        d += step
    return last_ok
