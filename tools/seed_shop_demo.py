"""Fill a shop-app data folder with demo jaw sets, programs, jobs and downtime windows.

    python tools/seed_shop_demo.py [DATA_DIR]      (default: data/, the folder `python -m softjaw serve` uses)

Refuses to touch a data folder that already has jaw sets.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from softjaw.shop.app import ShopApp  # noqa: E402

NC = ROOT / "examples" / "nc"


def main(data_dir=ROOT / "data"):
    app = ShopApp(data_dir, background=False)
    if app.store.one("SELECT 1 FROM jaw_sets"):
        sys.exit(f"{data_dir} already has jaw sets; seed an empty folder")
    today = date.today()

    hexs = app.create_jaw_set("Hex fitting OP1", "HX-100", "36 mm A/F hex, 40 mm tall. Nest 8 mm deep; corner reliefs on the left jaw.")
    app.add_design_file(hexs, "hex_fitting_jaws.stl", (ROOT / "examples/parts/hex_fitting.stl").read_bytes(), "both")
    for side in ("left", "right"):
        nid = app.add_nc(hexs, side, f"hex-fitting-op1_{side}.nc", (NC / f"hex-fitting-op1_{side}.nc").read_bytes())
        app.review_nc(nid, "approved", "Demo programmer", "checked in Mastercam simulation")

    cam = app.create_jaw_set("Cam plate OP2", "CP-220", "Plate held on edge for the second op.")
    app.add_design_file(cam, "cam_plate.stl", (ROOT / "examples/parts/cam_plate.stl").read_bytes(), "both")
    app.add_nc(cam, "left", "cam-plate-op2_left.nc", (NC / "cam-plate-op2_left.nc").read_bytes())

    app.create_jaw_set("Flanged hub OP1", "FH-310", "Round flange, grip on the 60 mm diameter.", program_mode="shared")

    app.save_job(name="WO-2291 hex fittings", part_number="HX-100", customer="Acme Hydraulics", quantity=120,
                 need_by=str(today + timedelta(days=2)), jaw_set_id=hexs)
    app.save_job(name="WO-2304 cam plates", part_number="CP-220", customer="Delta Motion", quantity=40,
                 need_by=str(today + timedelta(days=5)), jaw_set_id=cam)

    app.save_downtime(kind="weekly", label="Nights", days="0,1,2,3,4", start_time="18:00", end_time="06:00")
    app.save_downtime(kind="weekly", label="Lunch", days="0,1,2,3,4", start_time="12:00", end_time="12:45")
    app.save_downtime(kind="weekly", label="Weekend", days="5,6", start_time="00:00", end_time="23:59")
    for slot in (0, 1, 2, 3):
        app.set_rack(slot, "blank")
    app.close()
    print(f"demo data written to {data_dir}; start the app with: python -m softjaw serve")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data")
