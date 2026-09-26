"""Soft-jaw pocket generation and validation.

Vise frame (all mm): origin at the vise centre on the jaw seat (bottom of the
soft jaws when installed). +X points from the LEFT jaw to the RIGHT jaw
(clamping axis), +Y runs along the jaw width, +Z is up.

When the jaws clamp the part their faces sit at x = -g and x = +g, where
g = jaw_face_gap/2. Each jaw is a blank of thickness T (X), width W (Y) and
height H (Z). The cavity is a 2.5D pocket cut from the top: a planar profile
from the blank top down to a flat floor at the lowest point of the part.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from . import geometry as G
from .profiles import Tracker, load_json, file_sha256, ROOT

GENERATOR_VERSION = "0.2.0"


@dataclass
class Check:
    id: str
    requirement: str
    status: str               # pass | warn | fail
    measured: object = None
    limit: object = None
    message: str = ""
    suggestion: str = ""
    jaw: str | None = None

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None and v != ""}


@dataclass
class JawResult:
    side: str
    cut: np.ndarray            # pocket pixels in the vise grid
    material: np.ndarray       # jaw blank pixels in the vise grid
    reliefs: list = field(default_factory=list)
    depth_from_face: float = 0.0
    grasp_y: float | None = None


@dataclass
class JobResult:
    job: dict
    grid: G.Grid
    part_tris: np.ndarray
    part_all: np.ndarray       # union of sections inside jaw height
    part_grip: np.ndarray      # union of sections in the approved grip band
    jaws: dict
    checks: list
    params: dict
    unverified: list

    @property
    def status(self):
        s = {c.status for c in self.checks}
        if "fail" in s:
            return "blocked"
        if self.unverified:
            return "provisional"
        if "warn" in s:
            return "needs_acknowledgement"
        return "released"


def load_part(path: str) -> np.ndarray:
    full = ROOT / path
    suffix = full.suffix.lower()
    if suffix == ".stl":
        return G.read_stl(full)
    if suffix in (".step", ".stp"):
        from .step_io import step_to_mesh
        return step_to_mesh(full)
    raise ValueError(f"unsupported part format {suffix}; use STL, or STEP with CadQuery installed")


def generate(job_path: str) -> JobResult:
    job = load_json(job_path)
    tr = Tracker()
    prof = {k: load_json(v) for k, v in job["profiles"].items()}
    vise, blank, grip_prof, robot = prof["vise"], prof["blank"], prof["gripper"], prof["robot"]
    fx, proc = job["fixture"], job["process"]
    res = float(job.get("resolution_mm", 0.05))
    checks: list[Check] = []

    # ---------------------------------------------------------------- inputs
    W = tr.get(blank, "width")
    H = tr.get(blank, "height")
    T = tr.get(blank, "thickness")
    jaw_w = tr.get(vise, "published", "jaw_width")
    clearance = fx["cavity_clearance_mm"]
    min_wall = fx["minimum_wall_mm"]
    r_cut = proc["cutter_diameter_mm"] / 2.0
    mu = blank.get("friction_coefficient_on_part", 0.2)

    part_file = job["part"]["file"]
    tris = G.transform(load_part(part_file), job["part"]["pose_in_vise"])
    checks.append(Check("GEO-002", "Explicit rigid part-to-vise transform", "pass",
                        message="4x4 pose is orthonormal with det=+1"))
    z_bot, z_top = float(tris[:, :, 2].min()), float(tris[:, :, 2].max())

    grip = job["part"].get("approved_grip")
    if not grip:
        checks.append(Check("GEO-003", "Approved grip region required", "fail",
                            message="part.approved_grip is missing; orientation alone does not authorise a jaw",
                            suggestion="Add approved_grip {from_part_bottom_mm, height_mm} after reviewing the part"))
        grip = {"from_part_bottom_mm": 0.0, "height_mm": 0.0}
    else:
        checks.append(Check("GEO-003", "Approved grip region required", "pass",
                            measured=grip, message="grip band supplied by the job"))
    g_lo = z_bot + grip["from_part_bottom_mm"]
    g_hi = g_lo + grip["height_mm"]

    # ----------------------------------------------------------- engagement
    if z_bot <= 0:
        checks.append(Check("VAL-ENG", "Part rests on the pocket floor inside the jaw", "fail",
                            measured=round(z_bot, 3), limit="> 0",
                            message="part extends below the jaw seat",
                            suggestion="raise the part in part.pose_in_vise"))
    engage = min(H, z_top) - z_bot
    if z_bot >= H or engage < grip["height_mm"] - 1e-6 or g_hi > H + 1e-6:
        checks.append(Check("VAL-ENG", "Grip band lies inside the jaw height", "fail",
                            measured={"engagement": round(engage, 3), "grip_top": round(g_hi, 3)}, limit={"jaw_height": H},
                            message="the approved grip band is not fully inside the soft jaws",
                            suggestion="lower the part or shrink the grip band"))
    else:
        checks.append(Check("VAL-ENG", "Grip band lies inside the jaw height", "pass",
                            measured=round(engage, 3), limit=f">= {grip['height_mm']}"))
    protrusion = z_top - H
    checks.append(Check("VAL-003", "Part protrudes above the jaws for loading/removal", 
                        "pass" if protrusion >= fx.get("min_part_protrusion_mm", 3.0) else "warn",
                        measured=round(protrusion, 3), limit=f">= {fx.get('min_part_protrusion_mm', 3.0)}",
                        message="insertion/removal is straight down/up the prismatic pocket",
                        suggestion="raise the part so an operator or gripper can reach it"))

    # ------------------------------------------------------- jaw face gap
    # Faces sit symmetric about the vise centre. By default the gap comes from how
    # deep the part should nest into each jaw; jaw_face_gap_mm overrides it.
    probe = G.Grid.covering(-300, 300, -W / 2, W / 2, max(res, 0.2))
    footprint = G.section_union(tris, max(z_bot, 0.0), min(H, z_top), probe)
    cols = footprint.any(axis=0)
    if cols.any():
        px = probe.xs()[cols]
        x_lo, x_hi = float(px.min()) - probe.res / 2, float(px.max()) + probe.res / 2
    else:
        x_lo = x_hi = 0.0
    if "jaw_face_gap_mm" in fx:
        g = fx["jaw_face_gap_mm"] / 2.0
    else:
        g = min(x_hi, -x_lo) - fx.get("nest_depth_mm", 8.0)
    min_gap = fx.get("minimum_jaw_gap_mm", 2.0)
    hard_t = tr.get(vise, "robot_machining_setup", "hard_jaw_thickness")
    max_open = tr.get(vise, "published", "maximum_opening")
    needed_open = 2 * g + 2 * (T - hard_t)
    if 2 * g < min_gap:
        checks.append(Check("VAL-009", "Jaw faces stay apart when clamped", "fail",
                            measured=round(2 * g, 3), limit=f">= {min_gap}",
                            message="part is too narrow across the clamp axis for the nest depth; the jaws would touch before gripping",
                            suggestion="reduce nest_depth_mm, or rotate the part so it is wider across X"))
        g = min_gap / 2
    else:
        checks.append(Check("VAL-009", "Jaw faces stay apart when clamped", "pass",
                            measured=round(2 * g, 3), limit=f">= {min_gap}"))
    checks.append(Check("VAL-009", "Vise opening can reach the clamped jaw gap",
                        "pass" if needed_open <= max_open else "fail",
                        measured=round(needed_open, 3), limit=f"<= {max_open} (published opening, corrected for soft-jaw thickness)",
                        suggestion="rotate the part so its narrow side is across the clamp axis"))
    offset = (x_hi + x_lo) / 2
    if abs(offset) > 0.5:
        checks.append(Check("VAL-009", "Part centred between the jaws", "warn", measured=round(offset, 3), limit="|offset| <= 0.5",
                            message="off-centre parts nest deeper into one jaw", suggestion="shift the pose along X"))

    # ------------------------------------------------------------ sections
    margin = 2.0
    grid = G.Grid.covering(-(g + T + margin), g + T + margin, -(W / 2 + margin), W / 2 + margin, res)
    z_in_hi = min(H, z_top)
    part_all = G.section_union(tris, max(z_bot, 0.0), z_in_hi, grid)
    part_grip = G.section_union(tris, max(g_lo, 0.0), min(g_hi, H), grid)
    cavity = G.dilate(part_all, clearance, res)
    xs, ys = grid.xs(), grid.ys()

    pocket_depth_z = H - max(z_bot, 0.0)
    jaws = {}
    for side, sign in (("left", -1), ("right", 1)):
        x_face = sign * g
        x_back = sign * (g + T)
        mat = grid.mask_rect(min(x_face, x_back), max(x_face, x_back), -W / 2, W / 2)
        cut = cavity & mat
        jr = JawResult(side, cut, mat)
        # corner relief: cutter can travel through the pocket and the air around the blank.
        # Uncut material is judged by depth (mm from the reachable region), not pixel
        # count, so single-pixel quantisation on curved edges is not mistaken for a corner.
        noise = 2 * res
        for _ in range(4):
            reach = G.opening(cut | ~mat, r_cut, res)
            uncut = cut & ~reach
            dist_out = G.edt(~reach, res)
            lab, n = ndimage.label(uncut)
            placed = False
            for k in range(1, n + 1):
                comp = lab == k
                d = np.where(comp, dist_out, -1)
                if d.max() <= noise:
                    continue
                j, i = np.unravel_index(np.argmax(d), comp.shape)
                cx, cy = float(xs[i]), float(ys[j])
                jr.reliefs.append({"x": round(cx, 4), "y": round(cy, 4), "r": r_cut})
                cut = cut | (G.disk(grid, cx, cy, r_cut) & mat)
                placed = True
            if not placed:
                break
        reach = G.opening(cut | ~mat, r_cut, res)
        uncut = cut & ~reach
        worst_uncut = float(G.edt(~reach, res)[uncut].max()) if uncut.any() else 0.0
        jr.cut = cut
        checks.append(Check("VAL-002", "Every pocket point reachable by the cutter",
                            "pass" if worst_uncut <= noise else "fail", jaw=side,
                            measured={"max_uncut_depth_mm": round(worst_uncut, 3), "reliefs_added": len(jr.reliefs)},
                            limit=f"<= {noise:.2f} mm (raster quantisation) with cutter Ø{2 * r_cut}",
                            message="corner reliefs added where the cutter radius cannot reach" if jr.reliefs else "",
                            suggestion="use a smaller cutter"))
        jaws[side] = jr

        # contact: part must reach into this jaw
        if not cut.any():
            checks.append(Check("VAL-005", "Part contacts both jaws", "fail", jaw=side,
                                message="the part does not extend past this jaw face",
                                suggestion="reduce nest_depth_mm (or jaw_face_gap_mm), or check the pose"))
            continue
        cols = cut.any(axis=0)
        depth = float(np.max(np.abs(xs[cols])) - g + res / 2)
        jr.depth_from_face = depth
        wall = T - depth
        checks.append(Check("VAL-001", "Minimum wall between pocket and jaw back", 
                            "pass" if wall >= min_wall - 1e-6 else "fail", jaw=side,
                            measured=round(wall, 3), limit=f">= {min_wall}",
                            message=f"pocket reaches {depth:.2f} mm into a {T} mm blank",
                            suggestion="reduce part width across the clamp axis, rotate the part, or use thicker blanks"))

        # thin material fingers between pocket lobes
        material = mat & ~cut
        thin = material & ~G.opening(material, min_wall / 2, res)
        lab, n = ndimage.label(thin)
        worst = 0.0
        for sl in ndimage.find_objects(lab):
            ext = max((sl[0].stop - sl[0].start), (sl[1].stop - sl[1].start)) * res
            worst = max(worst, ext)
        checks.append(Check("VAL-001", "No material features thinner than the minimum wall",
                            "pass" if worst <= min_wall else "fail", jaw=side,
                            measured=round(worst, 3), limit=f"thin-feature length <= {min_wall}",
                            suggestion="increase clearance, change the pose, or accept a merged pocket"))

        # mounting holes (pre-drilled, run through the thickness in X)
        n_bolt = tr.get(vise, "jaw_interface", "bolt_count_per_jaw")
        spacing = tr.get(vise, "jaw_interface", "bolt_center_spacing")
        zh = tr.get(vise, "jaw_interface", "bolt_center_height_from_jaw_bottom")
        cb_r = tr.get(vise, "jaw_interface", "counterbore_diameter") / 2
        cb_d = tr.get(vise, "jaw_interface", "counterbore_depth")
        thread = tr.get(vise, "jaw_interface", "bolt_thread")
        hole_r = (float(str(thread).lstrip("M").split("x")[0]) + 1.0) / 2
        ys_b = [0.0] if n_bolt == 1 else list(np.linspace(-spacing / 2, spacing / 2, int(n_bolt)))
        j_idx, i_idx = np.nonzero(cut)
        local_x = np.abs(xs[i_idx]) - g
        worst_margin = np.inf
        for yb in ys_b:
            r_eff = np.where(local_x > T - cb_d - min_wall, cb_r, hole_r)
            near = np.abs(ys[j_idx] - yb) < r_eff + min_wall
            if near.any():
                need = zh + float(r_eff[near].max()) + min_wall
                worst_margin = min(worst_margin, z_bot - need)
        ok = worst_margin >= 0
        checks.append(Check("VAL-001", "Pocket clears the mounting holes and counterbores",
                            "pass" if ok else "fail", jaw=side,
                            measured=None if np.isinf(worst_margin) else round(float(worst_margin), 3), limit=">= 0 mm margin",
                            message="pocket does not overlap any hole in Y" if np.isinf(worst_margin) else "",
                            suggestion="raise the part in the jaws or move it along Y away from the bolts"))

        # finished-jaw regrasp: fingers need intact face and back in the top band
        fw = grip_prof["finger_width"]
        top_band = pocket_depth_z > 0
        blocked = cut.any(axis=1) if top_band else np.zeros(grid.ny, bool)
        free = ~blocked & (np.abs(ys) <= W / 2)          # rows of intact jaw face
        win = int(np.ceil(fw / res))
        run = np.convolve(free.astype(int), np.ones(win, int), mode="same") >= win  # finger centre positions
        if run.any():
            cand = ys[run]
            jr.grasp_y = float(cand[np.argmin(np.abs(cand))])
            checks.append(Check("VAL-004", "Gripper can regrasp the finished jaw", "pass", jaw=side,
                                measured={"grasp_y": round(jr.grasp_y, 2)},
                                message="fingers use an unpocketed section of the jaw"))
        else:
            checks.append(Check("VAL-004", "Gripper can regrasp the finished jaw", "fail", jaw=side,
                                message=f"no {fw} mm wide unpocketed section for the fingers",
                                suggestion="grip below the pocket floor or narrow the fingers"))

    # ------------------------------------------------------ depth / reach
    checks.append(Check("VAL-002", "Pocket depth within limits", 
                        "pass" if pocket_depth_z <= min(fx["max_cavity_depth_mm"], proc["maximum_cutter_reach_mm"]) else "fail",
                        measured=round(pocket_depth_z, 3),
                        limit=f"<= max_cavity_depth {fx['max_cavity_depth_mm']} and cutter reach {proc['maximum_cutter_reach_mm']}",
                        suggestion="raise the part in the jaws or use a longer-reach cutter"))
    hard = tr.get(vise, "robot_machining_setup", "hard_jaw_height")
    par = tr.get(vise, "robot_machining_setup", "parallel_height")
    exposed = par + H - hard
    need = max(pocket_depth_z + 2.0, grip_prof["finger_grip_depth"])
    checks.append(Check("VAL-008", "Standing blank exposes the pocket above the hard jaws",
                        "pass" if exposed >= need - 1e-6 else "fail",
                        measured=round(exposed, 3), limit=f">= {need:.2f} (pocket depth + 2 mm, and finger grip depth)",
                        message="cutter must never reach the hardened jaws",
                        suggestion="use a taller parallel under the blank or a taller blank"))

    # ------------------------------------------------------ constraint score
    both = all(jaws[s].cut.any() for s in jaws)
    if both:
        sd = G.edt(~part_grip, res) - G.edt(part_grip, res)
        gy, gx = np.gradient(sd, res)
        norm = np.hypot(gx, gy) + 1e-12
        nx_, ny_ = gx / norm, gy / norm
        boundary = part_grip & ~ndimage.binary_erosion(part_grip)
        cut_all = jaws["left"].cut | jaws["right"].cut
        near_wall = G.edt(cut_all, res) <= clearance + 1.5 * res
        contact = boundary & near_wall & ~(np.abs(grid.xs())[None, :] < g)
        lengths = {"x+": float((contact & (nx_ > 0.3)).sum() * res), "x-": float((contact & (nx_ < -0.3)).sum() * res),
                   "y+": float((contact & (ny_ > 0.5)).sum() * res), "y-": float((contact & (ny_ < -0.5)).sum() * res)}
        clamp = proc["part_clamp_force_n"]
        sf = proc.get("safety_factor", 2.0)
        fx_n, fy_n, fz_n = proc["expected_force_n"]
        friction = mu * clamp * 2
        min_lock = fx.get("min_locking_contact_mm", 2.0)
        y_locked = lengths["y+"] >= min_lock and lengths["y-"] >= min_lock
        score = {
            "contact_length_mm": {k: round(v, 2) for k, v in lengths.items()},
            "x": {"resistance_n": clamp, "required_n": fx_n * sf, "mode": "clamp"},
            "y": {"resistance_n": "positive" if y_locked else round(friction, 1), "required_n": fy_n * sf,
                  "mode": "geometric lock" if y_locked else "friction"},
            "z_pullout": {"resistance_n": round(friction, 1), "required_n": fz_n * sf, "mode": "friction"},
        }
        x_ok = lengths["x+"] >= min_lock and lengths["x-"] >= min_lock and clamp >= fx_n * sf
        y_ok = y_locked or friction >= fy_n * sf
        z_ok = friction >= fz_n * sf
        status = "pass" if (x_ok and y_ok and z_ok) else "fail"
        checks.append(Check("VAL-005", "Fixture resists the expected machining loads", status,
                            measured=score, limit=f"safety factor {sf}",
                            message="" if status == "pass" else "grip cannot hold the stated loads",
                            suggestion="enlarge the grip band, raise clamp force, or add a locating feature"))

    # ------------------------------------------------------- payload / reach
    mass = W * H * T / 1000.0 * blank["density_g_cm3"] / 1000.0
    payload = tr.get(robot, "payload_kg")
    total = mass + grip_prof["mass_kg"]
    checks.append(Check("VAL-004", "Robot payload covers blank + gripper",
                        "pass" if total <= payload else "fail",
                        measured=round(total, 3), limit=f"<= {payload} kg",
                        message=f"blank {mass * 1000:.0f} g + gripper {grip_prof['mass_kg'] * 1000:.0f} g"))
    stroke = grip_prof["finger_stroke_per_side"] * 2
    checks.append(Check("VAL-004", "Gripper opens wider than the blank", 
                        "pass" if stroke >= T + 10 else "fail", measured=stroke, limit=f">= {T + 10}"))
    if (W > jaw_w + 1e-6):
        checks.append(Check("CFG-002", "Blank width matches vise jaw width", "warn", measured=W, limit=jaw_w))

    params = {"resolution_mm": res, "jaw_face_gap_mm": 2 * g, "cavity_clearance_mm": clearance,
              "minimum_wall_mm": min_wall, "cutter_diameter_mm": 2 * r_cut,
              "pocket_floor_z_vise": round(max(z_bot, 0.0), 4), "pocket_depth_from_top": round(pocket_depth_z, 4),
              "blank": {"width": W, "height": H, "thickness": T}, "grip_band_z": [round(g_lo, 4), round(g_hi, 4)],
              "part_file": part_file, "part_sha256": file_sha256(ROOT / part_file),
              "part_bbox_vise": [[round(float(v), 4) for v in tris.reshape(-1, 3).min(0)],
                                 [round(float(v), 4) for v in tris.reshape(-1, 3).max(0)]],
              "blank_mass_kg": round(mass, 4),
              "profiles": {k: {"path": p["_path"], "sha256": p["_sha256"], "id": p.get("id")} for k, p in prof.items()},
              "generator_version": GENERATOR_VERSION}
    if tr.unverified:
        checks.append(Check("CFG-003", "Fit-critical dimensions verified", "warn",
                            measured=len(tr.unverified), limit=0,
                            message="job uses assumed/estimated dimensions; output is PROVISIONAL and blocked from production",
                            suggestion="complete docs/vevor-vise-measurement-sheet.md and mark values measured"))
    uniq = {(u["profile"], u["field"]): u for u in tr.unverified}
    return JobResult(job, grid, tris, part_all, part_grip, jaws, checks, params, list(uniq.values()))
