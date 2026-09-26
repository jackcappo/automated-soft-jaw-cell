"""Build the motion plan + orchestrator scenarios and export them for sim-web."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import cellplan as C
from .orchestrator import FAULTS, Orchestrator, build_job
from .profiles import ROOT


def outside_waypoints(cell, joints: dict, wall_x=-50.0):
    out = []
    for name, q in joints.items():
        pts, rad, _ = cell.arm.link_points(np.array(q))
        if float(np.max(pts[:, 0] + rad)) < wall_x:
            out.append(name)
    return sorted(out)


def build(manifest_path: str, slots=None, cycle_time_s=240.0):
    manifest = json.loads(Path(manifest_path).read_text())
    job = build_job(manifest, slots, cycle_time_s)
    cell = C.build_cell()
    jaws = {side: C.plan_jaw(cell, job["slots"][side], grasp_y=job["grasp_y"][side] or 0.0) for side in ("left", "right")}
    outside = sorted(set(outside_waypoints(cell, jaws["left"]["joints"])) & set(outside_waypoints(cell, jaws["right"]["joints"])))
    plan = {"jaws": jaws, "outside_waypoints": outside,
            "issues": jaws["left"]["issues"] + jaws["right"]["issues"],
            "reach_margin_mm": C.reach_margin(),
            "unverified_layout": list({(u["profile"], u["field"]): u for u in cell.tracker.unverified}.values())}
    scenarios = {"nominal": Orchestrator(job, plan).run()}
    for fault in FAULTS:
        trigger = "vise_above" if fault == "comms_loss" else True
        scenarios[fault] = Orchestrator(job, plan, {fault: trigger}).run()
    return job, cell, plan, scenarios


def export_js(job, cell, plan, scenarios, path=ROOT / "sim-web" / "cell-plan.js"):
    robot = cell.arm
    data = {
        "generated_by": "python -m softjaw sim",
        "job": {k: v for k, v in job.items()},
        "units": "mm",
        "robot": {"base": cell.frames["base"].tolist(), "joints": robot.joints, "end_link": robot.end, "radii": robot.radii},
        "boxes": [b.as_dict() for b in cell.boxes],
        "blank": cell.blank,
        "vise_blank_center": cell.frames["vise_blank_center"].tolist(),
        "rack_slots": [s.tolist() for s in cell.frames["rack_slots"]],
        "gripper": {k: cell.gripper[k] for k in ("finger_width", "finger_length", "finger_grip_depth")},
        "segments": {side: plan["jaws"][side]["segments"] for side in ("left", "right")},
        "joints": {side: plan["jaws"][side]["joints"] for side in ("left", "right")},
        "outside_waypoints": plan["outside_waypoints"],
        "reach_margin_mm": plan["reach_margin_mm"],
        "plan_issues": plan["issues"],
        "scenarios": {name: {"final_state": r["final_state"], "sim_time_s": r["sim_time_s"],
                             "inventory": r["inventory"], "events": r["events"]} for name, r in scenarios.items()},
    }
    Path(path).write_text("// Generated file - do not edit. Rebuild with: python -m softjaw sim\n"
                          "window.CELL_PLAN = " + json.dumps(data, separators=(",", ":")) + ";\n")
    return path
