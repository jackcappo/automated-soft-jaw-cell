import glob
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from softjaw import export, geometry as G, jawgen
from softjaw.profiles import ROOT


def dxf_loops(path):
    lines = Path(path).read_text().split("\n")
    loops, cur, layer = [], None, None
    for i in range(0, len(lines) - 1, 2):
        code, val = lines[i].strip(), lines[i + 1].strip()
        if code == "0" and val == "POLYLINE":
            cur, layer = [], None
        elif code == "8" and cur is not None and layer is None:
            layer = val
        elif code == "0" and val == "VERTEX":
            cur.append([None, None])
        elif code == "10" and cur and cur[-1][0] is None:
            cur[-1][0] = float(val)
        elif code == "20" and cur and cur[-1][1] is None:
            cur[-1][1] = float(val)
        elif code == "0" and val == "SEQEND":
            loops.append((layer, np.array(cur)))
            cur = None
    return loops


class JawGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {Path(j).stem: jawgen.generate(j) for j in sorted(glob.glob(str(ROOT / "config/jobs/*.json")))}

    def test_every_example_job_reaches_its_expected_status(self):
        for name, r in self.results.items():
            with self.subTest(name):
                self.assertEqual(r.status, r.job["expected_status"],
                                 [c.as_dict() for c in r.checks if c.status == "fail"])

    def test_failures_name_the_requirement(self):
        wide = [c.id for c in self.results["fail_too_wide"].checks if c.status == "fail"]
        self.assertIn("VAL-009", wide)
        narrow = [c.id for c in self.results["fail_no_grip"].checks if c.status == "fail"]
        self.assertIn("VAL-005", narrow)

    def test_hex_gets_one_relief_per_sharp_corner(self):
        r = self.results["hex_fitting"]
        for side in ("left", "right"):
            self.assertEqual(len(r.jaws[side].reliefs), 2)

    def test_unverified_profiles_keep_jobs_provisional(self):
        r = self.results["hex_fitting"]
        self.assertTrue(r.unverified)
        self.assertEqual(r.status, "provisional")

    def test_exports_are_consistent(self):
        r = self.results["l_bracket"]
        with tempfile.TemporaryDirectory() as d:
            pkg = export.write_package(r, d)
            depth = r.params["pocket_depth_from_top"]
            for side in ("left", "right"):
                mesh = G.read_stl(Path(d) / f"{side}_jaw.stl")
                self.assertTrue(G.is_watertight(mesh))
                pocket = r.jaws[side].cut.sum() * r.grid.res ** 2
                self.assertAlmostEqual(G.mesh_volume(mesh), 25 * 125 * 45 - pocket * depth, delta=0.01 * 25 * 125 * 45)
                area = sum(abs(G.polygon_area(l)) for layer, l in dxf_loops(Path(d) / f"{side}_jaw_pocket.dxf") if layer == "POCKET")
                self.assertAlmostEqual(area, pocket, delta=0.02 * pocket)
            m = json.loads((Path(d) / "manifest.json").read_text())
            self.assertFalse(m["cam_approval"]["approved"])
            self.assertEqual(m["release_status"], "provisional")

    def test_generation_is_deterministic(self):
        a = jawgen.generate(str(ROOT / "config/jobs/hex_fitting.json"))
        b = self.results["hex_fitting"]
        for side in ("left", "right"):
            self.assertTrue(np.array_equal(a.jaws[side].cut, b.jaws[side].cut))


if __name__ == "__main__":
    unittest.main()
