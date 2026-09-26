"""Optional STEP support through CadQuery/OpenCascade.

Install with:  pip install cadquery
Without CadQuery, importing this module raises ImportError and the rest of
the pipeline falls back to STL input and DXF + STL output, which Mastercam
imports directly.

NOTE: this module could not be exercised in the environment where the rest of
the package was verified (CadQuery was unavailable there). tests/test_step_io.py
runs automatically wherever CadQuery is installed; run it before relying on
STEP output.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import cadquery as cq  # noqa: F401  (ImportError here is the intended signal)


def step_to_mesh(path: str | Path, tolerance: float = 0.02, angular: float = 0.2) -> np.ndarray:
    shape = cq.importers.importStep(str(path)).val()
    verts, faces = shape.tessellate(tolerance, angular)
    v = np.array([[p.x, p.y, p.z] for p in verts], dtype=float)
    return v[np.asarray(faces, dtype=int)]


def pocketed_blank_step(path: str | Path, thickness, width, height, loops, depth) -> None:
    """Blank in jaw WCS (x 0..T, y -W/2..W/2, z -H..0) minus the prismatic pocket."""
    body = cq.Workplane("XY").box(thickness, width, height, centered=(False, True, False)).translate((0, 0, -height))
    for loop in loops:
        pts = [(float(x), float(y)) for x, y in loop]
        cutter = cq.Workplane("XY").workplane(offset=-depth).polyline(pts).close().extrude(depth + 1.0)
        body = body.cut(cutter)
    cq.exporters.export(body, str(path))
