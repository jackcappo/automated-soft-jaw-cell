"""Representative parts that need soft jaws, sized for a 125 mm (5 in) vise.

Each part is generated as a closed STL in its own part coordinates (Z up,
bottom on Z=0). Jobs in config/jobs/ place them in the vise with a pose.
Real customer parts are imported the same way (STL, or STEP when CadQuery is
installed); these exist so every process can be tested without CAD files.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .geometry import extrude_polygon, write_stl, mesh_volume


def circle(r, n=96, cx=0.0, cy=0.0):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)])


def rounded_rect(w, h, r, n=12):
    pts = []
    for cx, cy, a0 in ((w / 2 - r, -h / 2 + r, -np.pi / 2), (w / 2 - r, h / 2 - r, 0),
                       (-w / 2 + r, h / 2 - r, np.pi / 2), (-w / 2 + r, -h / 2 + r, np.pi)):
        for t in np.linspace(a0, a0 + np.pi / 2, n):
            pts.append((cx + r * np.cos(t), cy + r * np.sin(t)))
    return np.asarray(pts)


def rotate_x(tris, deg):
    a = np.radians(deg)
    r = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    return tris @ r.T


def stack(*prisms):
    return np.concatenate(prisms)


def parts() -> dict[str, dict]:
    """name -> {mesh, description, expect}."""
    out = {}

    # 1. Flanged round hub: round parts rotate and walk in flat jaws.
    out["flanged_hub"] = dict(
        mesh=stack(extrude_polygon(circle(40), 0, 8), extrude_polygon(circle(25), 8, 45)),
        description="Ø80 flange + Ø50 hub, gripped on the flange edge",
    )
    # 2. Hex fitting standing on end: grip across flats, locks rotation.
    hexagon = circle(36 / np.sqrt(3), n=6)
    hexagon = hexagon @ np.array([[np.cos(np.pi / 6), -np.sin(np.pi / 6)], [np.sin(np.pi / 6), np.cos(np.pi / 6)]]).T
    out["hex_fitting"] = dict(
        mesh=extrude_polygon(hexagon, 0, 40),
        description="36 mm A/F hex, 40 mm tall; sharp corners need cutter relief",
    )
    # 3. Round bar lying horizontally along Y: classic cradle jaw.
    bar = rotate_x(extrude_polygon(circle(15), -35, 35), 90)
    bar[:, :, 2] += 15
    out["round_bar"] = dict(
        mesh=bar,
        description="Ø30 x 70 bar lying along the jaw, second-op cradle",
    )
    # 4. Asymmetric cam profile: irregular outline, needs full-profile nest.
    t = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    rr = 22 + 7 * np.cos(t) + 3 * np.cos(2 * t)
    cam = np.column_stack([rr * np.cos(t) + 3, rr * np.sin(t) * 1.25])
    out["cam_plate"] = dict(
        mesh=extrude_polygon(cam, 0, 18),
        description="Irregular cam plate, 18 mm thick; nest locks X, Y and rotation",
    )
    # 5. L-bracket standing: asymmetric in Y so the pocket itself locates Y.
    l_shape = np.array([[-20, -30], [20, -30], [20, -18], [-8, -18], [-8, 30], [-20, 30]], float)
    out["l_bracket"] = dict(
        mesh=extrude_polygon(l_shape, 0, 30),
        description="40 x 60 L-bracket, 30 mm tall; pocket gives positive Y location",
    )
    # 6. Deliberately too wide: pocket breaks through the back of the jaw.
    out["fail_too_wide"] = dict(
        mesh=extrude_polygon(rounded_rect(150, 40, 4), 0, 20),
        description="EXPECTED FAIL: 150 mm across the clamp axis, beyond the vise opening",
    )
    # 7. Tiny pin: engagement too short and grips on almost nothing.
    out["fail_no_grip"] = dict(
        mesh=extrude_polygon(circle(0.6), 0, 20),
        description="EXPECTED FAIL: Ø1.2 pin narrower than the jaw gap, no contact",
    )
    return out


def write_all(directory: str | Path) -> list[Path]:
    directory = Path(directory)
    written = []
    for name, spec in parts().items():
        mesh = spec["mesh"]
        if mesh_volume(mesh) < 0:
            mesh = mesh[:, ::-1]
        path = directory / f"{name}.stl"
        write_stl(path, mesh, header=f"softjaw test part {name}")
        written.append(path)
    return written
