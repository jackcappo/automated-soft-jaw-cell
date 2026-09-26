"""Write the CAM package for a generated job (CAM-001, CAM-002, GEO-007)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import geometry as G
from .jawgen import JobResult
from .profiles import ROOT


def to_wcs(side: str, g: float, x, y):
    """Vise XY -> jaw setup WCS. +X into the jaw from its face; right-handed."""
    if side == "right":
        return x - g, y
    return -x - g, -y


def _dxf(path: Path, layers: dict[str, list[np.ndarray]]):
    out = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4",
           "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    for layer, loops in layers.items():
        for loop in loops:
            out += ["0", "POLYLINE", "8", layer, "66", "1", "70", "1", "10", "0.0", "20", "0.0", "30", "0.0"]
            for x, y in loop:
                out += ["0", "VERTEX", "8", layer, "10", f"{x:.4f}", "20", f"{y:.4f}", "30", "0.0"]
            out += ["0", "SEQEND", "8", layer]
    out += ["0", "ENDSEC", "0", "EOF"]
    path.write_text("\n".join(out) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_package(result: JobResult, out_dir: str | None = None, stl_res: float = 0.5) -> dict:
    job, grid, p = result.job, result.grid, result.params
    out = Path(out_dir) if out_dir else ROOT / job["outputs"]["directory"]
    out.mkdir(parents=True, exist_ok=True)
    g = p["jaw_face_gap_mm"] / 2
    W, H, T = p["blank"]["width"], p["blank"]["height"], p["blank"]["thickness"]
    floor_wcs = -p["pocket_depth_from_top"]
    files = {}
    jaws_manifest = {}
    tol = grid.res * 0.75

    for side, jr in result.jaws.items():
        loops = [G.simplify_closed(l, tol) for l in G.trace_contours(jr.cut, grid)]
        wcs_loops = []
        for l in loops:
            x, y = to_wcs(side, g, l[:, 0], l[:, 1])
            pts = np.column_stack([x, y])
            if G.polygon_area(pts) < 0:
                pts = pts[::-1]
            wcs_loops.append(pts)
        stock = np.array([[0, -W / 2], [T, -W / 2], [T, W / 2], [0, W / 2]], float)
        face = np.array([[0, -W / 2], [0, W / 2]], float)
        dxf = out / f"{side}_jaw_pocket.dxf"
        _dxf(dxf, {"POCKET": wcs_loops, "STOCK": [stock], "FACE_EDGE": [face]})

        # inspection solid: heightfield at stl_res in WCS
        hg = G.Grid.covering(0, T, -W / 2, W / 2, stl_res)
        xs, ys = np.meshgrid(hg.xs(), hg.ys())
        vx, vy = (xs + g, ys) if side == "right" else (-(xs + g), -ys)
        ii = np.clip(np.round((vx - grid.x0) / grid.res - 0.5).astype(int), 0, grid.nx - 1)
        jj = np.clip(np.round((vy - grid.y0) / grid.res - 0.5).astype(int), 0, grid.ny - 1)
        cut = jr.cut[jj, ii]
        top = np.where(cut, floor_wcs, 0.0)
        mesh = G.heightfield_solid(top, hg, -H)
        stl = out / f"{side}_jaw.stl"
        G.write_stl(stl, mesh, header=f"{job['job_id']} {side} jaw (inspection solid)")

        step = None
        try:
            from .step_io import pocketed_blank_step
            step = out / f"{side}_jaw.step"
            pocketed_blank_step(step, T, W, H, wcs_loops, p["pocket_depth_from_top"])
        except ImportError:
            step = None

        files[side] = [dxf, stl] + ([step] if step else [])
        reliefs = [dict(zip(("x", "y"), map(lambda v: round(float(v), 4), to_wcs(side, g, r["x"], r["y"]))), r=r["r"])
                   for r in jr.reliefs]
        gy = None if jr.grasp_y is None else round(jr.grasp_y if side == "right" else -jr.grasp_y, 3)
        jaws_manifest[side] = {
            "wcs": "origin at blank top face on the face edge, Y centred; +X into jaw, +Z up",
            "stock_mm": {"x": T, "y": W, "z": H},
            "pocket": {"floor_z": round(floor_wcs, 4), "depth_from_face_x": round(jr.depth_from_face, 4),
                       "chain_count": len(wcs_loops), "chain_vertex_counts": [len(l) for l in wcs_loops],
                       "corner_reliefs": reliefs},
            "robot": {"finger_grasp_y_wcs": gy},
            "files": {f.suffix.lstrip("."): {"path": f.name, "sha256": _sha(f)} for f in files[side]},
        }

    svg = out / "preview.svg"
    write_svg(result, svg)
    manifest = {
        "job_id": job["job_id"],
        "release_status": result.status,
        "generator_version": p["generator_version"],
        "units": "mm",
        "material": "Delrin",
        "tool": {"cutter_diameter_mm": p["cutter_diameter_mm"]},
        "machining_setup": "Blank stands in the hard jaws on a parallel; cut only the POCKET chain from the top to floor_z. Mounting holes are pre-drilled.",
        "source": {"part_file": p["part_file"], "part_sha256": p["part_sha256"],
                   "pose_in_vise": job["part"]["pose_in_vise"], "approved_grip": job["part"].get("approved_grip")},
        "parameters": {k: v for k, v in p.items() if k not in ("profiles",)},
        "profiles": p["profiles"],
        "unverified_dimensions": result.unverified,
        "jaws": jaws_manifest,
        "cam_approval": {"approved": False, "approved_by": None, "post_processor": None, "program_id": None,
                         "program_sha256": None, "note": "CAM-003: a person must review Mastercam stock, WCS, tools and simulation, then fill this in"},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    report = {"job_id": job["job_id"], "status": result.status,
              "checks": [c.as_dict() for c in result.checks], "unverified_dimensions": result.unverified}
    (out / "validation_report.json").write_text(json.dumps(report, indent=2, default=str))
    return {"directory": str(out), "status": result.status, "manifest": manifest}


def write_svg(result: JobResult, path: Path, scale: float = 4.0):
    grid, p = result.grid, result.params
    W, T = p["blank"]["width"], p["blank"]["thickness"]
    g = p["jaw_face_gap_mm"] / 2
    x0, y0 = grid.x0, grid.y0
    w, h = grid.nx * grid.res, grid.ny * grid.res
    def poly(loop, cls):
        pts = " ".join(f"{(x - x0) * scale:.2f},{(h - (y - y0)) * scale:.2f}" for x, y in loop)
        return f'<polygon class="{cls}" points="{pts}"/>'
    parts = []
    for side, sign in (("left", -1), ("right", 1)):
        xa, xb = sorted((sign * g, sign * (g + T)))
        parts.append(poly(np.array([[xa, -W / 2], [xb, -W / 2], [xb, W / 2], [xa, W / 2]]), "blank"))
    for jr in result.jaws.values():
        for l in G.trace_contours(jr.cut, grid):
            parts.append(poly(G.simplify_closed(l, grid.res), "pocket"))
    for l in G.trace_contours(result.part_grip, grid):
        parts.append(poly(G.simplify_closed(l, grid.res), "part"))
    for jr in result.jaws.values():
        for r in jr.reliefs:
            parts.append(f'<circle class="relief" cx="{(r["x"] - x0) * scale:.2f}" cy="{(h - (r["y"] - y0)) * scale:.2f}" r="{r["r"] * scale:.2f}"/>')
    color = {"released": "#3c9", "provisional": "#e9a23b", "needs_acknowledgement": "#e9a23b", "blocked": "#e55"}[result.status]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -40 {w * scale:.0f} {h * scale + 40:.0f}" font-family="sans-serif">
<style>.blank{{fill:#e6a05d;stroke:#8a5a2b;stroke-width:1}}.pocket{{fill:#fff3;stroke:#222;stroke-width:1.2}}
.part{{fill:#59c7d655;stroke:#1a7f8e;stroke-width:1.2}}.relief{{fill:none;stroke:#d33;stroke-dasharray:4 3}}</style>
<text x="4" y="-22" font-size="16">{result.job["job_id"]} - top view in vise frame (left jaw | right jaw)</text>
<text x="4" y="-4" font-size="14" fill="{color}">status: {result.status}</text>
{"".join(parts)}
</svg>'''
    path.write_text(svg)
