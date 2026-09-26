import unittest
import numpy as np
from softjaw import geometry as G, testparts as tp


class GeometryTests(unittest.TestCase):
    def test_test_parts_are_closed_solids(self):
        for name, spec in tp.parts().items():
            with self.subTest(name):
                self.assertTrue(G.is_watertight(spec["mesh"]))
                self.assertGreater(abs(G.mesh_volume(spec["mesh"])), 0)

    def test_hex_section_area_is_exact(self):
        m = tp.parts()["hex_fitting"]["mesh"]
        grid = G.Grid.covering(-30, 30, -30, 30, 0.05)
        area = G.section_union(m, 1, 39, grid).sum() * 0.05 ** 2
        self.assertAlmostEqual(area, 36 ** 2 * np.sqrt(3) / 2, delta=0.5)

    def test_heightfield_is_watertight_with_steps_and_holes(self):
        g = G.Grid.covering(0, 2, 0, 2, 1.0)
        for top, vol in ((np.zeros((2, 2)), 12.0), (np.array([[0., -1], [0, 0]]), 11.0),
                         (np.array([[0., -1], [-2, np.nan]]), 6.0)):
            m = G.heightfield_solid(top, g, -3)
            self.assertTrue(G.is_watertight(m))
            self.assertAlmostEqual(G.mesh_volume(m), vol)

    def test_opening_leaves_only_true_corner_residue(self):
        res = 0.05
        grid = G.Grid.covering(0, 40, -30, 30, res)
        mat = grid.mask_rect(10, 35, -62.5, 62.5)
        cut = grid.mask_rect(10, 20, -5, 5) & mat
        uncut = cut & ~G.opening(cut | ~mat, 3, res)
        expected = 2 * 9 * (1 - np.pi / 4)             # two 90 degree corners, r = 3
        self.assertAlmostEqual(uncut.sum() * res * res, expected, delta=0.5)

    def test_contour_matches_raster_area(self):
        m = tp.parts()["cam_plate"]["mesh"]
        grid = G.Grid.covering(-40, 40, -40, 40, 0.1)
        mask = G.section_union(m, 1, 17, grid)
        loops = G.trace_contours(mask, grid)
        self.assertAlmostEqual(sum(G.polygon_area(l) for l in loops), mask.sum() * 0.01, places=6)


if __name__ == "__main__":
    unittest.main()
