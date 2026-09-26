import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from softjaw import geometry as G, testparts as tp
from softjaw.profiles import ROOT


class ImportMachineModelTests(unittest.TestCase):
    def test_door_side_faces_the_robot_only_for_the_right_option(self):
        body = G.extrude_polygon(np.array([[-600, -500], [600, -500], [600, 500], [-600, 500]], float), 0, 2000)
        sides = {"-y": (0, -500), "+y": (0, 500), "-x": (-600, 0), "+x": (600, 0)}
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "m.stl", Path(d) / "out"
            for true_side, (dx, dy) in sides.items():
                mk = G.extrude_polygon(tp.circle(60, n=200), 900, 1100)
                mk[:, :, 0] += dx
                mk[:, :, 1] += dy
                G.write_stl(src, np.concatenate([body, mk]))
                hits = []
                for given in sides:
                    subprocess.run([sys.executable, str(ROOT / "tools/import_machine_model.py"), str(src), f"--front={given}",
                                    "--units", "mm", "--up", "z", "--out", str(out)], capture_output=True, check=True)
                    v = G.read_stl(out / "machine.stl").reshape(-1, 3)
                    m = v[(v[:, 2] > 880) & (v[:, 2] < 1120) & (np.abs(v[:, 1]) < 80) & (v[:, 0] < 150)]
                    if len(m) and m[:, 0].min() < 1.0:
                        hits.append(given)
                self.assertEqual(hits, [true_side])

    def test_inch_y_up_export_is_detected(self):
        body = G.extrude_polygon(np.array([[-30, -25], [30, -25], [30, 25], [-30, 25]], float), 0, 80)[:, :, [0, 2, 1]]
        body[:, :, 2] *= -1
        with tempfile.TemporaryDirectory() as d:
            G.write_stl(Path(d) / "m.stl", body)
            r = subprocess.run([sys.executable, str(ROOT / "tools/import_machine_model.py"), str(Path(d) / "m.stl"),
                                "--out", str(Path(d) / "o")], capture_output=True, text=True, check=True)
            self.assertIn('"source_units": "in"', r.stdout)
            self.assertIn('"height_z": 2032.0', r.stdout)


@unittest.skipUnless(importlib.util.find_spec("cadquery"), "CadQuery not installed (STEP support is optional)")
class StepTests(unittest.TestCase):
    def test_step_round_trip(self):
        from softjaw.step_io import pocketed_blank_step, step_to_mesh
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "j.step"
            pocketed_blank_step(p, 25, 125, 45, [np.array([[0, -10], [8, -10], [8, 10], [0, 10]], float)], 10)
            m = step_to_mesh(p)
            self.assertAlmostEqual(abs(G.mesh_volume(m)), 25 * 125 * 45 - 8 * 20 * 10, delta=50)


if __name__ == "__main__":
    unittest.main()
