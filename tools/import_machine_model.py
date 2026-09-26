"""Import a downloaded machine model (e.g. the GrabCAD Haas Mini Mill) for the simulator.

    python tools/import_machine_model.py ~/Downloads/haas_mini_mill.stl
    python tools/import_machine_model.py model.step --up y --units in --front=+y   (note the = for signed sides)

What it does
  1. Reads STL (binary or ASCII), or STEP/IGES when CadQuery is installed.
  2. Converts units to mm and rotates so +Z is up (CAD exports are often Y-up).
  3. Simplifies the mesh by vertex clustering so the browser stays fast.
  4. Places it in the cell frame: floor at Z=0, the front face on the door plane
     (X=0, machine extends toward +X) and centred on the door opening (Y=0).
  5. Writes sim-web/assets/machine.stl + machine.json. sim-web/assets/ is in
     .gitignore because downloaded models belong to their authors.

The model is visual only. Collision checking keeps using the measured boxes in
config/machines/*.json, because a downloaded model will not match your machine
to the millimetre.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from softjaw import geometry as G  # noqa: E402

UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
UP = {"z": np.eye(3), "y": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float),
      "x": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], float)}


def load(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".stl":
        return G.read_stl(path)
    if path.suffix.lower() in (".step", ".stp", ".igs", ".iges"):
        try:
            from softjaw.step_io import step_to_mesh
        except ImportError:
            sys.exit("STEP/IGES needs CadQuery (pip install cadquery), or export STL from your CAD program.")
        return step_to_mesh(path, tolerance=1.0, angular=0.5)
    sys.exit(f"unsupported format {path.suffix}; use STL (or STEP with CadQuery)")


def guess_units(tris):
    """Machine tools are 1.5-3 m tall. Pick the unit that makes the largest dimension plausible."""
    size = float(np.ptp(tris.reshape(-1, 3), axis=0).max())
    for name, k in (("mm", 1.0), ("in", 25.4), ("m", 1000.0), ("cm", 10.0)):
        if 800 <= size * k <= 5000:
            return name
    return "mm"


def simplify(tris: np.ndarray, cell: float) -> np.ndarray:
    """Vertex clustering: snap vertices to a grid, drop collapsed and duplicate triangles."""
    v = tris.reshape(-1, 3)
    key = np.round(v / cell).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, inv, v)
    centers = sums / np.bincount(inv, minlength=len(uniq))[:, None]
    f = inv.reshape(-1, 3)
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    f = f[keep]
    canon = np.sort(f, axis=1)
    _, first = np.unique(canon, axis=0, return_index=True)
    return centers[f[np.sort(first)]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model")
    ap.add_argument("--units", choices=list(UNITS), help="source units (default: guessed from size)")
    ap.add_argument("--up", choices=list(UP), default="auto", nargs="?", help="source up axis (default: guess)")
    ap.add_argument("--front", choices=["-x", "+x", "-y", "+y"], default="-y",
                    help="side of the (Z-up) model the door is on; default -y, the usual CAD 'front'")
    ap.add_argument("--cell", type=float, default=8.0, help="simplification grid in mm (bigger = lighter)")
    ap.add_argument("--max-triangles", type=int, default=150_000)
    ap.add_argument("--out", default=str(ROOT / "sim-web" / "assets"))
    a = ap.parse_args(argv)

    src = Path(a.model).expanduser()
    tris = load(src)
    units = a.units or guess_units(tris)
    tris = tris * UNITS[units]

    if a.up in (None, "auto"):
        # the vertical axis of a mill is normally its tallest dimension
        ext = np.ptp(tris.reshape(-1, 3), axis=0)
        up = "xyz"[int(np.argmax(ext))]
    else:
        up = a.up
    tris = tris @ UP[up].T

    # turn the door side to face -X (toward the robot), machine body along +X
    # Rz(turn) must map the door direction onto -X:  -y -> -90 deg, +y -> +90 deg, +x -> 180 deg
    turn = {"-x": 0.0, "-y": -np.pi / 2, "+y": np.pi / 2, "+x": np.pi}[a.front]
    c, s = np.cos(turn), np.sin(turn)
    tris = tris @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]).T

    n_in = len(tris)
    cell = a.cell
    simple = simplify(tris, cell)
    while len(simple) > a.max_triangles:
        cell *= 1.4
        simple = simplify(tris, cell)

    v = simple.reshape(-1, 3)
    lo, hi = v.min(0), v.max(0)
    offset = np.array([-lo[0], -(lo[1] + hi[1]) / 2, -lo[2]])
    simple = simple + offset
    size = (hi - lo).round(1)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    G.write_stl(out / "machine.stl", simple, header=f"machine model from {src.name}")
    info = {"source": src.name, "source_units": units, "source_up_axis": up, "door_side": a.front,
            "triangles_in": n_in, "triangles_out": int(len(simple)), "cluster_mm": round(cell, 2),
            "size_mm": {"depth_x": float(size[0]), "width_y": float(size[1]), "height_z": float(size[2])},
            "placement": "floor at Z=0, front face at X=0, centred on Y=0 (door opening)",
            "use": "visual only; collision uses config/machines/*.json boxes"}
    (out / "machine.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    if not (1000 <= size[2] <= 3500):
        print(f"WARNING: height {size[2]:.0f} mm is unusual for a mill; check --units / --up", file=sys.stderr)
    return info


if __name__ == "__main__":
    main()
