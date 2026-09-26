"""Read a posted NC program (Fanuc/Haas-style G-code) and check it against the soft-jaw setup.

The jaw WCS (CAM output contract): origin on the blank top face at the face edge, Y centred,
+X into the jaw, +Z up. So the blank top face spans X 0..thickness, Y +/-width/2, and every
cut below Z0 removes jaw material. This is a sanity check before a person approves the
program, not a replacement for CAM simulation.
"""
from __future__ import annotations

import math
import re

WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
PROGRAM = re.compile(r"^\s*O\s*(\d+)")
CANNED = {73, 74, 76, 81, 82, 83, 84, 85, 86, 87, 88, 89}
EPS = 0.01


def _clean(line: str) -> str:
    line = re.sub(r"\([^)]*\)", "", line)
    return line.split(";")[0].upper().strip()


def _arc_points(p0, p1, center, cw, n=24):
    a0 = math.atan2(p0[1] - center[1], p0[0] - center[0])
    a1 = math.atan2(p1[1] - center[1], p1[0] - center[0])
    r = math.hypot(p0[0] - center[0], p0[1] - center[1])
    sweep = a1 - a0
    if cw and sweep >= 0:
        sweep -= 2 * math.pi
    if not cw and sweep <= 0:
        sweep += 2 * math.pi
    pts = []
    for k in range(1, n + 1):
        a = a0 + sweep * k / n
        pts.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a), p0[2] + (p1[2] - p0[2]) * k / n))
    return pts, abs(sweep) * r


def _r_center(p0, p1, r, cw):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy)
    if d < 1e-9 or abs(r) < d / 2:
        return None
    h = math.sqrt(max(r * r - d * d / 4, 0.0))
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    sign = (-1 if cw else 1) * (1 if r > 0 else -1)
    return (mx - sign * h * dy / d, my + sign * h * dx / d)


class _Box:
    def __init__(self):
        self.lo, self.hi = [math.inf] * 3, [-math.inf] * 3

    def add(self, p):
        for i in range(3):
            if p[i] is not None:
                self.lo[i], self.hi[i] = min(self.lo[i], p[i]), max(self.hi[i], p[i])

    def as_dict(self):
        if self.lo[0] == math.inf:
            return None
        return {"min": [round(v, 3) for v in self.lo], "max": [round(v, 3) for v in self.hi]}


def analyze(text: str, setup: dict, tool_radius: float = 3.0) -> dict:
    T, W = setup["blank"]["thickness"], setup["blank"]["width"]
    rapid = setup["rapid_mm_min"]

    def over_blank(x, y, grow=tool_radius):
        return x is not None and y is not None and -grow <= x <= T + grow and -W / 2 - grow <= y <= W / 2 + grow

    program = None
    units, absolute, motion, feed, cycle = None, True, 0, None, None
    cycle_r = cycle_z = None
    pos = [None, None, None]
    spindle_on = False
    tools, wcs, spindles, feeds = [], [], [], []
    cut, pocket = _Box(), _Box()
    ends = False
    time_s = 0.0
    problems = {"rapid_into_stock": [], "cut_spindle_off": [], "no_feed": [], "plane": [], "feed_per_rev": []}
    lines = text.splitlines()
    for n, raw in enumerate(lines, 1):
        m = PROGRAM.match(raw.upper())
        if m and program is None:
            program = "O" + m.group(1).zfill(5)
        line = _clean(raw)
        if not line or line == "%":
            continue
        words = WORD.findall(line)
        g = [float(v) for k, v in words if k == "G"]
        mcodes = [int(float(v)) for k, v in words if k == "M"]
        val = {k: float(v) for k, v in words if k not in ("G", "M")}
        for code in g:
            c = int(code)
            if c in (20, 21):
                units = "in" if c == 20 else "mm"
            elif c in (90, 91):
                absolute = c == 90
            elif c in (0, 1, 2, 3):
                motion, cycle = c, None
            elif c in CANNED:
                cycle = c
            elif c == 80:
                cycle = None
            elif 54 <= c <= 59 or c == 154:
                wcs.append(f"G{c}" + (f" P{int(val['P'])}" if c == 154 and "P" in val else ""))
            elif c in (18, 19):
                problems["plane"].append(n)
            elif c == 95:
                problems["feed_per_rev"].append(n)
            elif c == 4:
                p = val.get("P", 0.0)
                time_s += p / 1000.0 if float(p).is_integer() else p
        k = 25.4 if units == "in" else 1.0
        if "F" in val:
            feed = val["F"] * k
            feeds.append(feed)
        if "S" in val:
            spindles.append(val["S"])
        if "T" in val and int(val["T"]) not in tools:
            tools.append(int(val["T"]))
        for mc in mcodes:
            if mc in (3, 4):
                spindle_on = True
            elif mc in (5, 30, 2):
                spindle_on = False
            if mc == 6:
                time_s += setup["tool_change_s"]
            if mc in (30, 2):
                ends = True
        if any(int(c) in (28, 53) for c in g):          # machine-coordinate moves: position becomes unknown (usually up)
            for i, ax in enumerate("XYZ"):
                if ax in val:
                    pos[i] = None
            continue
        target = list(pos)
        moved = False
        for i, ax in enumerate("XYZ"):
            if ax in val and not (cycle and ax == "Z"):
                v = val[ax] * k
                target[i] = v if absolute or pos[i] is None else pos[i] + v
                moved = True
        if cycle:
            if "R" in val:
                cycle_r = val["R"] * k
            if "Z" in val:
                cycle_z = val["Z"] * k
            if moved and cycle_z is not None:
                if not spindle_on:
                    problems["cut_spindle_off"].append(n)
                hole = (target[0], target[1], cycle_z)
                cut.add(hole)
                if cycle_z < -EPS and over_blank(hole[0], hole[1]):
                    pocket.add(hole)
                depth = abs((cycle_r if cycle_r is not None else 2.0) - cycle_z)
                time_s += depth / feed * 60 if feed else 0
                time_s += 2 * depth / rapid * 60
                pos = [target[0], target[1], cycle_r if cycle_r is not None else pos[2]]
            continue
        if not moved:
            continue
        seg = 0.0
        pts = [tuple(target)]
        if motion in (2, 3) and None not in pos[:2] and None not in target[:2]:
            p0 = (pos[0], pos[1], pos[2] if pos[2] is not None else target[2] or 0.0)
            p1 = (target[0], target[1], target[2] if target[2] is not None else p0[2])
            if "I" in val or "J" in val:
                center = (p0[0] + val.get("I", 0.0) * k, p0[1] + val.get("J", 0.0) * k)
            else:
                center = _r_center(p0, p1, val.get("R", 0.0) * k, motion == 2)
            if center is not None:
                pts, seg = _arc_points(p0, p1, center, motion == 2)
        elif None not in pos and None not in target:
            seg = math.dist(pos, target)
        if motion == 0:
            time_s += seg / rapid * 60
            # a straight retract up out of the pocket is fine; ending below the top face, or moving
            # sideways while below it, drives the tool through material at rapid
            z_end, z_start = target[2], pos[2]
            sideways = target[0] != pos[0] or target[1] != pos[1]
            ends_low = z_end is not None and z_end < -EPS
            moves_low = sideways and z_start is not None and z_start < -EPS
            if (ends_low or moves_low) and (over_blank(target[0], target[1], 0.0) or over_blank(pos[0], pos[1], 0.0)):
                problems["rapid_into_stock"].append(n)
        else:
            if feed is None:
                problems["no_feed"].append(n)
            else:
                time_s += seg / feed * 60
            if not spindle_on:
                problems["cut_spindle_off"].append(n)
            for p in pts:
                cut.add(p)
                if p[2] is not None and p[2] < -EPS and over_blank(p[0], p[1]):
                    pocket.add(p)
        pos = target

    cut_d, pocket_d = cut.as_dict(), pocket.as_dict()
    min_z = pocket_d["min"][2] if pocket_d else (cut_d["min"][2] if cut_d else None)
    checks = []

    def check(cid, title, status, message):
        checks.append({"id": cid, "title": title, "status": status, "message": message})

    check("NC-001", "Program ends with M30/M02", "pass" if ends else "fail",
          "program end found" if ends else "no M30 or M02: the controller would not know the program is finished")
    check("NC-002", "Units declared", "pass" if units else "warn",
          f"G{'20 (inch)' if units == 'in' else '21 (mm)'}" if units else "no G20/G21; assumed mm - set it explicitly in the post")
    check("NC-003", "Work offset declared", "pass" if wcs else "warn",
          ", ".join(sorted(set(wcs))) if wcs else "no G54-G59/G154: the program would run in whatever offset is active")
    max_depth = setup["max_cut_depth"]
    if min_z is None:
        check("NC-004", "Cut depth stays above the hard jaws", "fail", "no cutting moves below Z0 over the blank were found")
    else:
        ok = min_z >= -max_depth - EPS
        check("NC-004", "Cut depth stays above the hard jaws", "pass" if ok else "fail",
              f"deepest cut Z{min_z:.3f}; limit Z-{max_depth:.3f} (blank stands {setup['exposed_above_hard_jaws']:.1f} mm above the hard jaws, "
              f"{max_depth:.1f} mm usable)" + ("" if ok else ": the cutter would reach the steel jaws"))
    if cut_d:
        lo, hi = cut_d["min"], cut_d["max"]
        margin = 10.0
        inside = lo[0] >= -margin and hi[0] <= T + margin and lo[1] >= -W / 2 - margin and hi[1] <= W / 2 + margin
        check("NC-005", "Cutting stays on the blank", "pass" if inside else "warn",
              f"tool centre X {lo[0]:.1f}..{hi[0]:.1f}, Y {lo[1]:.1f}..{hi[1]:.1f}; blank face X 0..{T:g}, Y {-W / 2:g}..{W / 2:g}"
              + ("" if inside else ". Check the WCS: origin on the blank top face at the face edge, Y centred"))
    rp = problems["rapid_into_stock"]
    check("NC-006", "No rapid moves into the blank", "fail" if rp else "pass",
          f"G0 below Z0 over the blank on line(s) {', '.join(map(str, rp[:8]))}" if rp else "all rapids stay above the blank top")
    off = problems["cut_spindle_off"]
    check("NC-007", "Spindle on while cutting", "fail" if off else "pass",
          f"feed moves with the spindle stopped on line(s) {', '.join(map(str, off[:8]))}" if off else "spindle running for every cutting move")
    nf = problems["no_feed"]
    if nf:
        check("NC-008", "Feed rate set before cutting", "fail", f"no F word before line(s) {', '.join(map(str, nf[:8]))}")
    if problems["plane"] or problems["feed_per_rev"]:
        check("NC-009", "Supported motion modes", "warn",
              "G18/G19 arcs or G95 feed-per-rev found; extents and time are approximate")

    # finished-jaw regrasp: fingers need intact material beside the pocket in the top band
    grasp_y = 0.0
    fw = setup["finger_width"]
    if pocket_d:
        y0, y1 = pocket_d["min"][1] - tool_radius, pocket_d["max"][1] + tool_radius
        rooms = {"-Y": (y0 - (-W / 2), (-W / 2 + y0) / 2), "+Y": (W / 2 - y1, (y1 + W / 2) / 2)}
        side, (room, centre) = max(rooms.items(), key=lambda kv: kv[1][0])
        need = fw + 4.0
        if room >= need:
            grasp_y = round(centre, 2)
            check("NC-010", "Gripper can regrasp the finished jaw", "pass",
                  f"{room:.1f} mm of intact jaw on the {side} side of the pocket for {fw:g} mm fingers; grasp at Y{grasp_y:+.1f}")
        else:
            check("NC-010", "Gripper can regrasp the finished jaw", "fail",
                  f"only {max(r for r, _ in rooms.values()):.1f} mm beside the pocket (tool radius {tool_radius:g} mm assumed); "
                  f"{fw:g} mm fingers need {need:.0f} mm")
    status = "fail" if any(c["status"] == "fail" for c in checks) else "warn" if any(c["status"] == "warn" for c in checks) else "pass"
    return {"program_number": program, "units": units or "mm (assumed)", "lines": len(lines), "tools": tools,
            "work_offsets": sorted(set(wcs)), "spindle_max": max(spindles) if spindles else None,
            "feed_range": [round(min(feeds), 1), round(max(feeds), 1)] if feeds else None,
            "cut_extents": cut_d, "pocket_extents": pocket_d, "min_z": min_z, "grasp_y": grasp_y,
            "est_cycle_s": round(time_s, 1), "tool_radius_assumed": tool_radius, "checks": checks, "status": status}
