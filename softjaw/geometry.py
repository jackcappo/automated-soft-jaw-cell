"""Dependency-light geometry kernel (NumPy + SciPy only).

All lengths are millimetres. Meshes are float arrays of shape (N, 3, 3):
N triangles, 3 vertices, xyz.

The jaw generator works in 2.5D because a soft-jaw pocket machined from the
top on a 3-axis mill is a prismatic cut: a planar profile plus a floor depth.
That lets the kernel represent pockets exactly as a raster at a configurable
resolution and convert them to CAM chains (DXF) and meshes (STL).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage


# --------------------------------------------------------------------------- STL

def read_stl(path: str | Path) -> np.ndarray:
    """Read an ASCII or binary STL into an (N, 3, 3) float64 array."""
    data = Path(path).read_bytes()
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if 84 + count * 50 == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([
                ("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=count, offset=84)
            return rec["v"].astype(np.float64)
    text = data.decode("utf-8", errors="replace")
    verts = [list(map(float, line.split()[1:4]))
             for line in text.splitlines() if line.strip().startswith("vertex")]
    if not verts or len(verts) % 3:
        raise ValueError(f"{path}: not a valid STL file")
    return np.asarray(verts, dtype=np.float64).reshape(-1, 3, 3)


def write_stl(path: str | Path, tris: np.ndarray, header: str = "softjaw") -> None:
    tris = np.asarray(tris, dtype=np.float32)
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lens, out=np.zeros_like(normals), where=lens > 0)
    rec = np.zeros(len(tris), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = normals, tris
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(header.encode()[:80].ljust(80, b" "))
        fh.write(struct.pack("<I", len(tris)))
        fh.write(rec.tobytes())


def transform(tris: np.ndarray, matrix) -> np.ndarray:
    m = np.asarray(matrix, dtype=float)
    if m.shape != (4, 4):
        raise ValueError("pose must be a 4x4 homogeneous transform")
    rot = m[:3, :3]
    if not np.allclose(rot @ rot.T, np.eye(3), atol=1e-6) or np.linalg.det(rot) < 0:
        raise ValueError("pose rotation must be a proper rigid rotation (orthonormal, det=+1)")
    return tris @ rot.T + m[:3, 3]


def mesh_volume(tris: np.ndarray) -> float:
    """Signed volume via the divergence theorem (positive for outward normals)."""
    return float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6.0)


def is_watertight(tris: np.ndarray, decimals: int = 5) -> bool:
    """Every undirected edge must be shared by exactly two triangles with opposite direction."""
    v = np.round(tris, decimals)
    edges = np.concatenate([v[:, [0, 1]], v[:, [1, 2]], v[:, [2, 0]]])
    flat = edges.reshape(len(edges), 6)
    fwd = {tuple(e) for e in flat}
    for e in flat:
        if (tuple(e[3:]) + tuple(e[:3])) not in fwd:
            return False
    return len(fwd) == len(flat)


# ------------------------------------------------------------------ slicing

def slice_mesh(tris: np.ndarray, z: float) -> np.ndarray:
    """Intersect a mesh with the plane Z=z. Returns (M, 2, 2) XY segments."""
    d = tris[:, :, 2] - z
    d = np.where(np.abs(d) < 1e-9, 1e-9, d)  # nudge vertices lying on the plane
    above = d > 0
    n_above = above.sum(axis=1)
    hit = (n_above == 1) | (n_above == 2)
    t, d, above = tris[hit], d[hit], above[hit]
    segs = np.zeros((len(t), 2, 2))
    fill = np.zeros(len(t), dtype=int)
    for a, b in ((0, 1), (1, 2), (2, 0)):
        cross = above[:, a] != above[:, b]
        w = d[cross, a] / (d[cross, a] - d[cross, b])
        p = t[cross, a, :2] + (t[cross, b, :2] - t[cross, a, :2]) * w[:, None]
        idx = np.nonzero(cross)[0]
        segs[idx, fill[idx]] = p
        fill[idx] += 1
    return segs


@dataclass(frozen=True)
class Grid:
    """Pixel-centre raster: pixel (row j, col i) centre is (x0+(i+.5)r, y0+(j+.5)r)."""
    x0: float
    y0: float
    nx: int
    ny: int
    res: float

    @classmethod
    def covering(cls, xmin, xmax, ymin, ymax, res):
        nx = int(np.ceil((xmax - xmin) / res))
        ny = int(np.ceil((ymax - ymin) / res))
        return cls(float(xmin), float(ymin), nx, ny, float(res))

    def xs(self):
        return self.x0 + (np.arange(self.nx) + 0.5) * self.res

    def ys(self):
        return self.y0 + (np.arange(self.ny) + 0.5) * self.res

    def mask_rect(self, xmin, xmax, ymin, ymax) -> np.ndarray:
        xs, ys = self.xs(), self.ys()
        return (ys[:, None] >= ymin) & (ys[:, None] <= ymax) & (xs[None, :] >= xmin) & (xs[None, :] <= xmax)


def rasterize_segments(segs: np.ndarray, grid: Grid) -> np.ndarray:
    """Even-odd scanline fill of closed loops given as unordered segments."""
    out = np.zeros((grid.ny, grid.nx + 1), dtype=np.int32)
    if len(segs):
        y_a, y_b = segs[:, 0, 1], segs[:, 1, 1]
        ymin, ymax = np.minimum(y_a, y_b), np.maximum(y_a, y_b)
        # rows whose centre lies in [ymin, ymax)
        j0 = np.ceil((ymin - grid.y0) / grid.res - 0.5).astype(int)
        j1 = np.ceil((ymax - grid.y0) / grid.res - 0.5).astype(int)
        j0, j1 = np.clip(j0, 0, grid.ny), np.clip(j1, 0, grid.ny)
        counts = j1 - j0
        keep = counts > 0
        if keep.any():
            s, c, j0k = segs[keep], counts[keep], j0[keep]
            rep = np.repeat(np.arange(len(s)), c)
            rows = np.repeat(j0k, c) + (np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c))
            yc = grid.y0 + (rows + 0.5) * grid.res
            p, q = s[rep, 0], s[rep, 1]
            x = p[:, 0] + (q[:, 0] - p[:, 0]) * (yc - p[:, 1]) / (q[:, 1] - p[:, 1])
            col = np.clip(np.ceil((x - grid.x0) / grid.res - 0.5).astype(int), 0, grid.nx)
            np.add.at(out, (rows, col), 1)
    return (np.cumsum(out, axis=1)[:, :grid.nx] % 2).astype(bool)


def section_union(tris: np.ndarray, z_lo: float, z_hi: float, grid: Grid, step: float = 0.5) -> np.ndarray:
    """Union of the part's cross-sections for Z in [z_lo, z_hi].

    Samples a regular ladder of planes plus planes just above/below every
    distinct vertex height, so steps and flanges are never skipped.
    """
    mask = np.zeros((grid.ny, grid.nx), dtype=bool)
    if z_hi <= z_lo:
        return mask
    levels = set(np.arange(z_lo, z_hi, step).tolist()) | {z_lo, z_hi}
    for vz in np.unique(np.round(tris[:, :, 2], 6)):
        for off in (-1e-4, 1e-4):
            if z_lo <= vz + off <= z_hi:
                levels.add(float(vz + off))
    eps = 1e-4
    for z in sorted(levels):
        zc = min(max(z, z_lo + eps), z_hi - eps)
        mask |= rasterize_segments(slice_mesh(tris, zc), grid)
    return mask


# -------------------------------------------------------------- morphology

def edt(mask: np.ndarray, res: float) -> np.ndarray:
    """Distance (mm) from each True pixel to the nearest False pixel."""
    return ndimage.distance_transform_edt(mask, sampling=res)


# One tolerance for every "within radius r" test so disks, erosion and dilation
# agree on lattice points that sit exactly on the circle.
TOL = 1e-6


def dilate(mask, r, res):
    return edt(~mask, res) <= r + TOL if r > 0 else mask.copy()


def erode(mask, r, res):
    return edt(mask, res) > r + TOL if r > 0 else mask.copy()


def opening(mask, r, res):
    """Region a round cutter of radius r can reach while staying inside mask."""
    return dilate(erode(mask, r, res), r, res)


def disk(grid: Grid, cx, cy, r) -> np.ndarray:
    xs, ys = grid.xs(), grid.ys()
    return np.hypot(xs[None, :] - cx, ys[:, None] - cy) <= r + TOL


# ------------------------------------------------------------- contours

def trace_contours(mask: np.ndarray, grid: Grid) -> list[np.ndarray]:
    """Trace pixel-edge boundaries of a mask into closed XY polylines.

    Outer boundaries are counter-clockwise, holes clockwise. Diagonal
    pinch points are resolved by always turning left, which keeps each loop
    simple.
    """
    m = np.pad(mask, 1)
    ny, nx = mask.shape
    edges = {}
    # corner (cx, cy) indexes grid corners; pixel (j,i) spans corners i..i+1, j..j+1
    j, i = np.nonzero(m[1:-1, 1:-1])
    for dj, di, a, b in (
        (-1, 0, (0, 0), (1, 0)),   # below empty -> bottom edge, left->right
        (0, 1, (1, 0), (1, 1)),    # right empty -> right edge, bottom->top
        (1, 0, (1, 1), (0, 1)),    # above empty -> top edge, right->left
        (0, -1, (0, 1), (0, 0)),   # left empty  -> left edge, top->bottom
    ):
        sel = ~m[j + 1 + dj, i + 1 + di]
        for jj, ii in zip(j[sel], i[sel]):
            start = (ii + a[0], jj + a[1])
            end = (ii + b[0], jj + b[1])
            edges.setdefault(start, []).append(end)
    loops = []
    while edges:
        start = next(iter(edges))
        loop = [start]
        prev_dir = None
        cur = start
        while True:
            outs = edges[cur]
            if len(outs) == 1:
                nxt = outs.pop()
            else:  # pinch point: prefer the left turn relative to the incoming direction
                def turn_rank(p):
                    d = (p[0] - cur[0], p[1] - cur[1])
                    if prev_dir is None:
                        return 0
                    cross = prev_dir[0] * d[1] - prev_dir[1] * d[0]
                    return -cross
                outs.sort(key=turn_rank)
                nxt = outs.pop(0)
            if not outs:
                del edges[cur]
            prev_dir = (nxt[0] - cur[0], nxt[1] - cur[1])
            cur = nxt
            if cur == start:
                break
            loop.append(cur)
        pts = np.asarray(loop, dtype=float)
        pts[:, 0] = grid.x0 + pts[:, 0] * grid.res
        pts[:, 1] = grid.y0 + pts[:, 1] * grid.res
        loops.append(pts)
    return loops


def simplify_closed(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker for a closed polyline (first point not repeated)."""
    if len(pts) < 4:
        return pts

    def dp(seg):
        keep = np.zeros(len(seg), dtype=bool)
        keep[[0, -1]] = True
        stack = [(0, len(seg) - 1)]
        while stack:
            a, b = stack.pop()
            if b <= a + 1:
                continue
            p, q = seg[a], seg[b]
            d = q - p
            n = np.hypot(*d)
            rel = seg[a + 1:b] - p
            dist = np.abs(d[0] * rel[:, 1] - d[1] * rel[:, 0]) / n if n > 0 else np.hypot(rel[:, 0], rel[:, 1])
            k = int(np.argmax(dist))
            if dist[k] > tol:
                keep[a + 1 + k] = True
                stack += [(a, a + 1 + k), (a + 1 + k, b)]
        return seg[keep]

    far = int(np.argmax(np.hypot(*(pts - pts[0]).T)))
    first = dp(pts[: far + 1])
    second = dp(np.vstack([pts[far:], pts[:1]]))
    return np.vstack([first[:-1], second[:-1]])


def polygon_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


# ------------------------------------------------------ triangulation

def triangulate_polygon(pts: np.ndarray) -> list[tuple[int, int, int]]:
    """Ear clipping for a simple polygon. Returns CCW index triples."""
    n = len(pts)
    idx = list(range(n)) if polygon_area(pts) > 0 else list(range(n))[::-1]
    tris = []

    def inside(p, a, b, c):
        def s(u, v, w):
            return (u[0] - w[0]) * (v[1] - w[1]) - (v[0] - w[0]) * (u[1] - w[1])
        d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))

    guard = 0
    while len(idx) > 3 and guard < 10 * n * n:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 1e-12:
                continue
            if any(inside(pts[o], a, b, c) for o in idx if o not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            raise ValueError("polygon is not simple; cannot triangulate")
    tris.append(tuple(idx))
    return tris


def extrude_polygon(pts: np.ndarray, z0: float, z1: float) -> np.ndarray:
    """Closed prism mesh from a simple XY polygon."""
    pts = np.asarray(pts, dtype=float)
    if polygon_area(pts) < 0:
        pts = pts[::-1]
    caps = triangulate_polygon(pts)
    out = []
    for a, b, c in caps:
        out.append([[*pts[a], z1], [*pts[b], z1], [*pts[c], z1]])
        out.append([[*pts[a], z0], [*pts[c], z0], [*pts[b], z0]])
    n = len(pts)
    for k in range(n):
        p, q = pts[k], pts[(k + 1) % n]
        out.append([[*p, z0], [*q, z0], [*q, z1]])
        out.append([[*p, z0], [*q, z1], [*p, z1]])
    return np.asarray(out)


def heightfield_solid(top: np.ndarray, grid: Grid, z_bottom: float) -> np.ndarray:
    """Watertight mesh for columns of height top[j,i] (NaN = empty) above z_bottom."""
    ny, nx = top.shape
    xs = grid.x0 + np.arange(nx + 1) * grid.res
    ys = grid.y0 + np.arange(ny + 1) * grid.res
    filled = ~np.isnan(top)
    tris = []
    j, i = np.nonzero(filled)
    h = top[j, i]
    x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
    zb = np.full_like(h, z_bottom)
    def quad(p0, p1, p2, p3):
        tris.append(np.stack([p0, p1, p2], axis=1))
        tris.append(np.stack([p0, p2, p3], axis=1))
    P = lambda x, y, z: np.stack([x, y, z], axis=1)
    quad(P(x0, y0, h), P(x1, y0, h), P(x1, y1, h), P(x0, y1, h))          # top (+Z)
    quad(P(x0, y0, zb), P(x0, y1, zb), P(x1, y1, zb), P(x1, y0, zb))      # bottom (-Z)
    padded = np.full((ny + 2, nx + 2), np.nan)
    padded[1:-1, 1:-1] = top
    # Split every wall at all distinct heights so neighbouring walls share
    # vertical edges exactly (no T-junctions -> watertight).
    levels = np.unique(np.concatenate([[z_bottom], h]))
    for dj, di in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nb = padded[j + 1 + dj, i + 1 + di]
        nb_h = np.where(np.isnan(nb), z_bottom, nb)
        for lo_l, hi_l in zip(levels[:-1], levels[1:]):
            sel = (nb_h <= lo_l + 1e-9) & (h >= hi_l - 1e-9)
            if not sel.any():
                continue
            lo = np.full(sel.sum(), lo_l)
            hi = np.full(sel.sum(), hi_l)
            a0, a1, b0, b1 = x0[sel], x1[sel], y0[sel], y1[sel]
            if (dj, di) == (0, 1):
                quad(P(a1, b0, lo), P(a1, b1, lo), P(a1, b1, hi), P(a1, b0, hi))
            elif (dj, di) == (0, -1):
                quad(P(a0, b1, lo), P(a0, b0, lo), P(a0, b0, hi), P(a0, b1, hi))
            elif (dj, di) == (1, 0):
                quad(P(a1, b1, lo), P(a0, b1, lo), P(a0, b1, hi), P(a1, b1, hi))
            else:
                quad(P(a0, b0, lo), P(a1, b0, lo), P(a1, b0, hi), P(a0, b0, hi))
    return np.concatenate(tris)
