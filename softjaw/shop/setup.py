"""The soft-jaw machining setup a CAM programmer works to, read from the profiles."""
from __future__ import annotations

from ..profiles import Tracker, load_json

RAPID_MM_MIN = 15240.0        # Haas Mini Mill rapid, 600 in/min
TOOL_CHANGE_S = 6.0
STEEL_MARGIN_MM = 2.0         # VAL-008: cutter stays this far above the hard jaws


def jaw_setup(cell_path="config/cells/haas-mini-mill-b601.json") -> dict:
    cell = load_json(cell_path)
    prof = {k: load_json(v) for k, v in cell["profiles"].items()}
    cam = load_json("config/cam/mastercam.json")
    tr = Tracker()
    blank, vise, grip = prof["blank"], prof["vise"], prof["gripper"]
    T, W, H = tr.get(blank, "thickness"), tr.get(blank, "width"), tr.get(blank, "height")
    hard = tr.get(vise, "robot_machining_setup", "hard_jaw_height")
    par = tr.get(vise, "robot_machining_setup", "parallel_height")
    exposed = par + H - hard
    return {
        "machine": prof["machine"]["model"], "vise": vise.get("model", vise["id"]),
        "blank": {"id": blank["id"], "material": blank["material"], "thickness": T, "width": W, "height": H},
        "wcs": cam["output_contract"]["coordinate_system"],
        "hard_jaw_height": hard, "parallel_height": par,
        "exposed_above_hard_jaws": exposed, "max_cut_depth": exposed - STEEL_MARGIN_MM,
        "finger_width": grip["finger_width"], "finger_grip_depth": grip["finger_grip_depth"],
        "rapid_mm_min": RAPID_MM_MIN, "tool_change_s": TOOL_CHANGE_S,
        "unverified": [f"{u['profile']}: {u['field']} ({u['status']})" for u in tr.unverified],
    }
