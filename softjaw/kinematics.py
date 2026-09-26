"""Forward and inverse kinematics for URDF-style serial arms (mm, rad).

Conventions follow URDF exactly: a joint's origin is Trans(xyz) * Rz(yaw) *
Ry(pitch) * Rx(roll), followed by a rotation of q about the joint axis.
sim-web/kinematics.js implements the same maths; tests compare the two.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares


def rpy_matrix(rpy):
    r, p, y = rpy
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return rz @ ry @ rx


def axis_angle(axis, q):
    k = np.asarray(axis, float)
    k = k / np.linalg.norm(k)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(q) * K + (1 - np.cos(q)) * K @ K


def hom(R=np.eye(3), t=(0, 0, 0)):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


class Arm:
    def __init__(self, robot_profile: dict, base_xyz, base_yaw=0.0):
        self.joints = robot_profile["joints"]
        self.end = robot_profile["end_link"]
        self.lower = np.array([j["lower"] for j in self.joints])
        self.upper = np.array([j["upper"] for j in self.joints])
        self.base = hom(rpy_matrix([0, 0, base_yaw]), base_xyz)
        self.radii = robot_profile.get("collision_radii_mm", [40] * 7)

    def frames(self, q):
        """World transforms of base, joint1..joint6 and the TCP (end_link)."""
        T = self.base.copy()
        out = [T.copy()]
        for jd, qi in zip(self.joints, q):
            T = T @ hom(rpy_matrix(jd["rpy"]), jd["xyz"]) @ hom(axis_angle(jd["axis"], qi))
            out.append(T.copy())
        T = T @ hom(rpy_matrix(self.end["rpy"]), self.end["xyz"])
        out.append(T)
        return out

    def tcp(self, q):
        return self.frames(q)[-1]

    def ik(self, pos, approach=(0, 0, -1), finger_axis=None, seeds=None, tol_mm=0.5, tol_deg=0.5):
        """Place the TCP at pos with its +X (approach) along `approach` and,
        optionally, the finger slide axis (+Y) parallel to `finger_axis`."""
        pos, a = np.asarray(pos, float), np.asarray(approach, float) / np.linalg.norm(approach)
        f = None if finger_axis is None else np.asarray(finger_axis, float) / np.linalg.norm(finger_axis)
        w = 200.0

        def resid(q):
            T = self.tcp(q)
            r = [T[:3, 3] - pos, w * (T[:3, 0] - a)]
            if f is not None:
                r.append(w * np.cross(T[:3, 1], f))
            return np.concatenate(r)

        mid = (self.lower + self.upper) / 2
        cand = list(seeds or []) + [mid, np.array([0, -1.2, -1.6, 0, 0, 0]), np.array([0.5, -1.0, -2.0, 0.3, 0.5, 0]),
                                    np.array([-0.5, -1.5, -1.2, -0.3, -0.5, 0])]
        rng = np.random.default_rng(7)
        cand += [rng.uniform(self.lower, self.upper) for _ in range(12)]
        best = None
        for s in cand:
            s = np.clip(np.asarray(s, float), self.lower + 1e-6, self.upper - 1e-6)
            sol = least_squares(resid, s, bounds=(self.lower, self.upper), xtol=1e-10, ftol=1e-10, max_nfev=400)
            T = self.tcp(sol.x)
            perr = float(np.linalg.norm(T[:3, 3] - pos))
            aerr = float(np.degrees(np.arccos(np.clip(T[:3, 0] @ a, -1, 1))))
            ferr = 0.0 if f is None else float(np.degrees(np.arcsin(np.clip(np.linalg.norm(np.cross(T[:3, 1], f)), 0, 1))))
            ok = perr <= tol_mm and aerr <= tol_deg and ferr <= tol_deg
            # prefer valid solutions, then the one closest to the first seed (branch continuity)
            key = (not ok, perr + aerr + ferr if not ok else float(np.linalg.norm(sol.x - cand[0])) if seeds else 0.0)
            if best is None or key < best[0]:
                best = (key, sol.x, ok, perr, aerr, ferr)
            if ok and (not seeds or float(np.max(np.abs(sol.x - cand[0]))) < 0.6):
                break   # first good answer, or one on the same branch as the seed
        _, q, ok, perr, aerr, ferr = best
        return {"q": q, "ok": ok, "pos_err_mm": perr, "approach_err_deg": aerr, "finger_err_deg": ferr}

    def link_points(self, q, step=15.0):
        """Points along capsule segments base->j1->...->j6->TCP with their radii."""
        P = [T[:3, 3] for T in self.frames(q)]
        pts, rad, seg = [], [], []
        for k in range(len(P) - 1):
            a, b = P[k], P[k + 1]
            n = max(2, int(np.ceil(np.linalg.norm(b - a) / step)) + 1)
            for t in np.linspace(0, 1, n):
                pts.append(a + (b - a) * t)
                rad.append(self.radii[min(k, len(self.radii) - 1)])
                seg.append(k)
        return np.array(pts), np.array(rad), np.array(seg)
