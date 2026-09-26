"""Regenerate examples/parts/*.stl and config/jobs/*.json."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from softjaw import testparts

PROFILES = {
    "vise": "config/vises/vevor-5in-accu-lock.json",
    "blank": "config/blanks/delrin-125x45x25.json",
    "gripper": "config/grippers/placeholder-parallel.json",
    "robot": "config/robots/rebot-b601-dm.json",
    "cam": "config/cam/mastercam.json",
    "machine": "config/machines/haas-mini-mill.json",
}

def pose(x=0.0, y=0.0, z=32.0):
    return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]]

JOBS = {
    "hex_fitting":  dict(pose=pose(), grip=(0, 10), expect="provisional"),
    "flanged_hub":  dict(pose=pose(), grip=(0, 7.5), expect="provisional"),
    "round_bar":    dict(pose=pose(z=30), grip=(5, 10), expect="provisional"),
    "cam_plate":    dict(pose=pose(x=-10), grip=(0, 10), expect="provisional"),
    "l_bracket":    dict(pose=pose(), grip=(0, 10), expect="provisional"),
    "fail_too_wide": dict(pose=pose(), grip=(0, 10), expect="blocked"),
    "fail_no_grip": dict(pose=pose(), grip=(0, 10), expect="blocked"),
}

def main():
    testparts.write_all(ROOT / "examples" / "parts")
    for name, spec in JOBS.items():
        job = {
            "job_id": name.replace("_", "-"),
            "description": testparts.parts()[name]["description"],
            "expected_status": spec["expect"],
            "units": "mm",
            "resolution_mm": 0.05,
            "part": {"file": f"examples/parts/{name}.stl", "pose_in_vise": spec["pose"],
                     "approved_grip": {"from_part_bottom_mm": spec["grip"][0], "height_mm": spec["grip"][1]}},
            "profiles": PROFILES,
            "fixture": {"nest_depth_mm": 8.0, "minimum_jaw_gap_mm": 2.0, "cavity_clearance_mm": 0.15,
                        "minimum_wall_mm": 4.0, "max_cavity_depth_mm": 20.0, "min_part_protrusion_mm": 3.0,
                        "min_locking_contact_mm": 2.0},
            "process": {"expected_force_n": [250.0, 250.0, 150.0], "safety_factor": 2.0,
                        "part_clamp_force_n": 8000.0, "cutter_diameter_mm": 6.0, "maximum_cutter_reach_mm": 25.0},
            "outputs": {"directory": f"output/{name}"},
        }
        (ROOT / "config" / "jobs" / f"{name}.json").write_text(json.dumps(job, indent=2) + "\n")
    print("wrote", len(JOBS), "jobs")

if __name__ == "__main__":
    main()
