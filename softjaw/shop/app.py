"""Shop app logic: jaw sets, CAM hot folders, NC review, production jobs, downtime, rack and cell runs.

Runs are simulated: each one is planned for its rack slots, executed by the orchestrator's
simulated adapters, then played back in (scaled) real time so the site can monitor it.
There is no physical command path (PRD section 14).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .. import simplan
from ..export import _dxf
from ..orchestrator import FAULTS, Orchestrator
from ..profiles import ROOT
from . import schedule as S
from .ncparse import analyze
from .setup import jaw_setup
from .store import Store, now_iso

NC_EXT = {".nc", ".tap", ".ngc", ".cnc", ".eia", ".txt", ".min"}
SIDE_WORDS = {"left": "left", "l": "left", "lh": "left", "right": "right", "r": "right", "rh": "right"}
MOTION_OVERHEAD_S = 210.0          # robot moves, door, clamp for both jaws (from the motion plan, rounded up)
DEFAULT_CYCLE_S = 240.0
ACTIVE = ("planning", "running")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "jaw-set"


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)[:120] or "file"


class ShopApp:
    def __init__(self, data_dir: Path | str = ROOT / "data", background: bool = True):
        self.data = Path(data_dir)
        self.store = Store(self.data / "shop.db")
        self.setup = jaw_setup()
        self.unmatched: dict[str, str] = {}
        self._stop: dict[int, threading.Event] = {}
        self._threads: dict[int, threading.Thread] = {}
        st = self.store
        for key, value in (("outbox_dir", str(self.data / "cam" / "outbox")), ("inbox_dir", str(self.data / "cam" / "inbox")),
                           ("auto_run", True), ("sim_speed", 10.0), ("tool_radius", 3.0), ("auto_queue_for_jobs", True)):
            if st.setting(key) is None:
                st.set_setting(key, value)
        for r in st.all("SELECT id FROM runs WHERE status IN ('planning', 'running')"):   # server restarted mid-run
            st.update("runs", r["id"], status="safe_stop", finished_at=now_iso(),
                      fault=json.dumps({"cause": "server_restart", "detail": "the app stopped while this run was active"}))
            st.log("alert", "Run interrupted by an app restart: confirm where the jaws are", run_id=r["id"])
        self._alive = background
        if background:
            threading.Thread(target=self._loop, daemon=True, name="shop-tick").start()
            threading.Thread(target=self.idle_plan, daemon=True, name="idle-plan").start()   # ready before the first page load

    # ------------------------------------------------------------------ jaw sets
    def create_jaw_set(self, name, part_number="", description="", program_mode="per_side"):
        if not name.strip():
            raise ValueError("name is required")
        if program_mode not in ("per_side", "shared"):
            raise ValueError("program_mode must be per_side or shared")
        base = slug = slugify(name)
        n = 2
        while self.store.get("jaw_sets", slug, "slug"):
            slug, n = f"{base}-{n}", n + 1
        jid = self.store.insert("jaw_sets", slug=slug, name=name.strip(), part_number=part_number, description=description,
                                program_mode=program_mode, created_at=now_iso(), updated_at=now_iso())
        self.store.log("jaw_set", f"Jaw set {name} created", jaw_set_id=jid)
        self.write_outbox(jid)
        return jid

    def update_jaw_set(self, jid, **fields):
        allowed = {k: v for k, v in fields.items() if k in ("name", "part_number", "description", "program_mode", "location", "archived")}
        if "program_mode" in allowed and allowed["program_mode"] not in ("per_side", "shared"):
            raise ValueError("program_mode must be per_side or shared")
        self.store.update("jaw_sets", jid, **allowed, updated_at=now_iso())
        if "location" in allowed:
            self.store.log("jaw_set", f"Location set to {allowed['location'] or 'not stored'}", jaw_set_id=jid)
        self.write_outbox(jid)

    def _jaw_set(self, jid):
        js = self.store.get("jaw_sets", jid)
        if not js:
            raise KeyError(f"jaw set {jid} not found")
        return js

    def sides(self, js):
        return ("both",) if js["program_mode"] == "shared" else ("left", "right")

    def latest_nc(self, jid):
        """Newest non-superseded program per side."""
        out = {}
        for nc in self.store.all("SELECT * FROM nc_programs WHERE jaw_set_id = ? AND review_status != 'superseded' ORDER BY id", (jid,)):
            out[nc["side"]] = nc
        return out

    def stage(self, js) -> dict:
        """Where the jaw set is in its life: design -> CAM -> review -> ready -> made."""
        jid = js["id"]
        active = self.store.one("SELECT * FROM runs WHERE jaw_set_id = ? AND status IN ('planning', 'running', 'safe_stop') "
                                "ORDER BY id DESC", (jid,))
        if active:
            label = {"planning": "Machining", "running": "Machining", "safe_stop": "Stopped - needs recovery"}[active["status"]]
            return {"key": active["status"], "label": label, "run_id": active["id"]}
        base = self._base_stage(js)
        queued = self.store.one("SELECT id FROM runs WHERE jaw_set_id = ? AND status = 'queued' ORDER BY id", (jid,))
        if queued and base["key"] == "ready":
            return {"key": "queued", "label": "Queued", "run_id": queued["id"]}
        if queued:
            return {**base, "label": base["label"] + " - run queued", "run_id": queued["id"]}
        return base

    def _base_stage(self, js) -> dict:
        jid = js["id"]
        nc = self.latest_nc(jid)
        need = self.sides(js)
        if js["made_count"] and js["location"]:
            return {"key": "made", "label": f"Made - {js['location']}"}
        files = self.store.one("SELECT COUNT(*) AS n FROM files WHERE jaw_set_id = ?", (jid,))["n"]
        missing = [s for s in need if s not in nc]
        if missing and not files and not nc:
            return {"key": "design", "label": "Needs jaw design"}
        if missing:
            return {"key": "cam", "label": "Awaiting NC from CAM (" + ", ".join(missing) + ")"}
        if any(nc[s]["review_status"] == "rejected" for s in need):
            return {"key": "rejected", "label": "NC rejected - repost"}
        if any(nc[s]["review_status"] == "pending" for s in need):
            failing = any(nc[s]["check_status"] == "fail" for s in need)
            return {"key": "review", "label": "NC failed checks" if failing else "NC to review"}
        return {"key": "ready", "label": "Ready to machine"}

    def jaw_set_summary(self, js):
        return {**js, "stage": self.stage(js), "jobs": self.store.all(
            "SELECT id, name, need_by, status FROM production_jobs WHERE jaw_set_id = ? AND status != 'done' ORDER BY need_by", (js["id"],))}

    def list_jaw_sets(self, archived=False):
        rows = self.store.all("SELECT * FROM jaw_sets WHERE archived = ? ORDER BY updated_at DESC", (1 if archived else 0,))
        return [self.jaw_set_summary(js) for js in rows]

    def jaw_set_detail(self, jid):
        js = self._jaw_set(jid)
        ncs = self.store.all("SELECT * FROM nc_programs WHERE jaw_set_id = ? ORDER BY id DESC", (jid,))
        return {**self.jaw_set_summary(js),
                "files": self.store.all("SELECT * FROM files WHERE jaw_set_id = ? ORDER BY id DESC", (jid,)),
                "nc_programs": ncs, "current_nc": self.latest_nc(jid), "sides": self.sides(js),
                "runs": self.store.all("SELECT id, status, trigger, created_at, started_at, finished_at, state FROM runs "
                                       "WHERE jaw_set_id = ? ORDER BY id DESC LIMIT 20", (jid,)),
                "readiness": self.readiness(js), "outbox": str(self.outbox_dir() / js["slug"]),
                "nc_names": self.nc_names(js)}

    def nc_names(self, js):
        return [f"{js['slug']}.nc"] if js["program_mode"] == "shared" else [f"{js['slug']}_left.nc", f"{js['slug']}_right.nc"]

    # ------------------------------------------------------------------ files
    def _save(self, js, filename, data: bytes, sub):
        folder = self.data / "files" / js["slug"] / sub
        folder.mkdir(parents=True, exist_ok=True)
        stored = folder / f"{datetime.now():%Y%m%d-%H%M%S}_{safe_name(filename)}"
        stored.write_bytes(data)
        return stored, hashlib.sha256(data).hexdigest()

    def add_design_file(self, jid, filename, data: bytes, side="both"):
        js = self._jaw_set(jid)
        if side not in ("left", "right", "both"):
            raise ValueError("side must be left, right or both")
        stored, sha = self._save(js, filename, data, "design")
        fid = self.store.insert("files", jaw_set_id=jid, side=side, filename=safe_name(filename), stored=str(stored),
                                sha256=sha, size=len(data), uploaded_at=now_iso())
        self.store.update("jaw_sets", jid, updated_at=now_iso())
        self.store.log("design", f"Design file {filename} ({side}) uploaded", jaw_set_id=jid)
        self.write_outbox(jid)
        return fid

    def add_nc(self, jid, side, filename, data: bytes, source="upload"):
        js = self._jaw_set(jid)
        if side not in self.sides(js):
            raise ValueError(f"side must be one of {', '.join(self.sides(js))} for this jaw set")
        text = data.decode("utf-8", errors="replace")
        analysis = analyze(text, self.setup, float(self.store.setting("tool_radius", 3.0)))
        stored, sha = self._save(js, filename, data, "nc")
        dup = self.store.one("SELECT id FROM nc_programs WHERE jaw_set_id = ? AND side = ? AND sha256 = ? AND review_status != 'superseded'",
                             (jid, side, sha))
        if dup:
            return dup["id"]
        self.store.run("UPDATE nc_programs SET review_status = 'superseded' WHERE jaw_set_id = ? AND side = ? AND review_status != 'superseded'",
                       (jid, side))
        nid = self.store.insert("nc_programs", jaw_set_id=jid, side=side, filename=safe_name(filename), stored=str(stored), sha256=sha,
                                program_number=analysis["program_number"], source=source, uploaded_at=now_iso(), analysis=analysis,
                                check_status=analysis["status"], review_status="pending")
        self.store.update("jaw_sets", jid, updated_at=now_iso())
        how = "from the CAM inbox" if source == "hotfolder" else "uploaded"
        self.store.log("nc", f"NC {filename} ({side}) {how}: checks {analysis['status']}", jaw_set_id=jid)
        return nid

    def review_nc(self, nid, decision, by, note=""):
        nc = self.store.get("nc_programs", nid)
        if not nc:
            raise KeyError("program not found")
        if not by.strip():
            raise ValueError("enter your name to sign the review")
        if decision not in ("approved", "rejected"):
            raise ValueError("decision must be approved or rejected")
        if nc["review_status"] == "superseded":
            raise ValueError("a newer program has replaced this one")
        if decision == "approved" and nc["check_status"] == "fail":
            raise ValueError("this program failed a safety check; fix it in CAM and repost")
        self.store.update("nc_programs", nid, review_status=decision, reviewed_by=by.strip(), reviewed_at=now_iso(), review_note=note)
        self.store.log("nc", f"NC {nc['filename']} ({nc['side']}) {decision} by {by.strip()}", jaw_set_id=nc["jaw_set_id"])

    # ------------------------------------------------------------------ CAM hot folders
    def outbox_dir(self):
        return Path(self.store.setting("outbox_dir"))

    def inbox_dir(self):
        return Path(self.store.setting("inbox_dir"))

    def write_outbox(self, jid):
        """Package a jaw set for the CAM programmer: design files, setup contract, stock outline."""
        js = self._jaw_set(jid)
        folder = self.outbox_dir() / js["slug"]
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.store.log("alert", f"CAM outbox not writable: {e}")
            return None
        su = self.setup
        T, W = su["blank"]["thickness"], su["blank"]["width"]
        for f in self.store.all("SELECT * FROM files WHERE jaw_set_id = ?", (jid,)):
            dest = folder / (f["filename"] if f["side"] == "both" else f"{f['side']}_{f['filename']}")
            if Path(f["stored"]).exists() and not dest.exists():
                shutil.copyfile(f["stored"], dest)
        _dxf(folder / "blank_top_face.dxf", {"STOCK": [np.array([[0, -W / 2], [T, -W / 2], [T, W / 2], [0, W / 2]], float)],
                                            "FACE_EDGE": [np.array([[0, -W / 2], [0, W / 2]], float)]})
        contract = {"jaw_set": js["name"], "slug": js["slug"], "part_number": js["part_number"], "program_mode": js["program_mode"],
                    "post_nc_to": str(self.inbox_dir()), "nc_file_names": self.nc_names(js), "setup": su}
        (folder / "jaw_setup.json").write_text(json.dumps(contract, indent=2))
        b = su["blank"]
        (folder / "README.txt").write_text(
            f"Soft jaw set: {js['name']} ({js['part_number'] or 'no part number'})\n\n"
            f"Stock: {b['material']} blank {b['thickness']:g} x {b['width']:g} x {b['height']:g} mm, standing in the {su['vise']} "
            f"on the {su['machine']}.\n"
            f"WCS: {su['wcs']}.\n"
            f"The blank top face is X 0..{b['thickness']:g}, Y {-b['width'] / 2:g}..{b['width'] / 2:g} (blank_top_face.dxf).\n"
            f"Maximum cut depth: Z-{su['max_cut_depth']:g} (the blank stands {su['exposed_above_hard_jaws']:g} mm above the hard jaws).\n"
            f"Leave at least {su['finger_width'] + 4:g} mm of intact jaw on one side of the pocket, {su['finger_grip_depth']:g} mm deep, "
            f"for the robot's fingers.\n\n"
            f"Post the program(s) as {' and '.join(self.nc_names(js))} into:\n  {self.inbox_dir()}\n"
            f"The cell app picks them up, checks them and holds them for approval.\n")
        return folder

    def scan_inbox(self):
        inbox = self.inbox_dir()
        try:
            inbox.mkdir(parents=True, exist_ok=True)
            files = [p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in NC_EXT]
        except OSError:
            return []
        sets = sorted(self.store.all("SELECT * FROM jaw_sets WHERE archived = 0"), key=lambda j: -len(j["slug"]))
        imported, seen = [], set()
        for p in files:
            seen.add(p.name)
            stem = slugify(p.stem)
            js = next((j for j in sets if stem == j["slug"] or stem.startswith(j["slug"] + "-")), None)
            if not js:
                self.unmatched[p.name] = "no jaw set with a matching name"
                continue
            rest = stem[len(js["slug"]):].strip("-")
            side = SIDE_WORDS.get(rest.split("-")[-1] if rest else "", None)
            if js["program_mode"] == "shared":
                side = "both"
            if side is None:
                self.unmatched[p.name] = f"cannot tell left or right: name it {js['slug']}_left or {js['slug']}_right"
                continue
            try:
                nid = self.add_nc(js["id"], side, p.name, p.read_bytes(), source="hotfolder")
                done = inbox / "imported"
                done.mkdir(exist_ok=True)
                p.replace(done / f"{datetime.now():%Y%m%d-%H%M%S}_{p.name}")
                imported.append(nid)
                self.unmatched.pop(p.name, None)
            except (OSError, ValueError) as e:
                self.unmatched[p.name] = str(e)
        for name in list(self.unmatched):
            if name not in seen:
                self.unmatched.pop(name)
        return imported

    # ------------------------------------------------------------------ production jobs
    def save_job(self, jid=None, **fields):
        cols = {k: fields[k] for k in ("name", "part_number", "customer", "quantity", "need_by", "jaw_set_id", "status", "notes") if k in fields}
        if "status" in cols and cols["status"] not in ("planned", "in_production", "done"):
            raise ValueError("status must be planned, in_production or done")
        if jid is None:
            if not str(cols.get("name", "")).strip():
                raise ValueError("job name is required")
            jid = self.store.insert("production_jobs", **cols, created_at=now_iso())
            self.store.log("job", f"Production job {cols['name']} added", jaw_set_id=cols.get("jaw_set_id"))
        else:
            self.store.update("production_jobs", jid, **cols)
        job = self.store.get("production_jobs", jid)
        if job["jaw_set_id"] and job["status"] != "done" and self.store.setting("auto_queue_for_jobs", True):
            self.ensure_queued(job["jaw_set_id"], job["need_by"])
        return jid

    def ensure_queued(self, jaw_set_id, need_by=None):
        """A production job needs this jaw set: queue a run unless jaws exist or one is already queued."""
        js = self._jaw_set(jaw_set_id)
        if js["made_count"] and js["location"]:
            return None
        existing = self.store.one("SELECT * FROM runs WHERE jaw_set_id = ? AND status IN ('queued', 'planning', 'running')", (jaw_set_id,))
        if existing:
            if need_by and existing["status"] == "queued" and (not existing["need_by"] or need_by < existing["need_by"]):
                self.store.update("runs", existing["id"], need_by=need_by)
            return existing["id"]
        return self.queue_run(jaw_set_id, trigger="auto", need_by=need_by)

    def list_jobs(self):
        jobs = self.store.all("SELECT * FROM production_jobs ORDER BY status = 'done', need_by IS NULL, need_by, id")
        sets = {j["id"]: j for j in self.store.all("SELECT * FROM jaw_sets")}
        proj = self.projection()
        for job in jobs:
            js = sets.get(job["jaw_set_id"])
            job["jaw_set"] = {"id": js["id"], "name": js["name"], "stage": self.stage(js)} if js else None
            job["jaws_ready_at"] = None
            job["at_risk"] = False
            if js:
                act = self._active_run()
                run = self.store.one("SELECT id FROM runs WHERE jaw_set_id = ? AND status = 'queued' ORDER BY id", (js["id"],))
                end = self.active_end() if act and act["jaw_set_id"] == js["id"] else proj.get(run["id"], {}).get("end") if run else None
                job["jaws_ready_at"] = end
                if job["need_by"] and job["status"] == "planned" and not (js["made_count"] and js["location"]):
                    job["at_risk"] = (end is None) or end[:10] > job["need_by"][:10]
        return jobs

    # ------------------------------------------------------------------ downtime
    def save_downtime(self, did=None, **w):
        cols = {k: w[k] for k in ("kind", "start", "end", "days", "start_time", "end_time", "label", "enabled") if k in w}
        kind = cols.get("kind") or (self.store.get("downtime", did) or {}).get("kind")
        if kind == "once":
            if did is None or "start" in cols or "end" in cols:
                s, e = S.parse(cols["start"]), S.parse(cols["end"])
                if e <= s:
                    raise ValueError("end must be after start")
                cols["start"], cols["end"] = S.iso(s), S.iso(e)
        elif kind == "weekly":
            if did is None and not str(cols.get("days", "")).strip():
                raise ValueError("pick at least one day")
            for k in ("start_time", "end_time"):
                if k in cols:
                    cols[k] = datetime.strptime(cols[k], "%H:%M").strftime("%H:%M")
        else:
            raise ValueError("kind must be once or weekly")
        if did is None:
            did = self.store.insert("downtime", **cols)
        else:
            self.store.update("downtime", did, **cols)
        return did

    def list_downtime(self):
        rows = self.store.all("SELECT * FROM downtime ORDER BY kind DESC, start, start_time")
        for r in rows:
            r["summary"] = S.describe(r)
        return rows

    def windows(self, days=7, now=None):
        now = now or datetime.now()
        return [{"start": S.iso(s), "end": S.iso(e), "label": l}
                for s, e, l in S.expand(self.store.all("SELECT * FROM downtime"), now, now + timedelta(days=days))]

    # ------------------------------------------------------------------ rack
    def set_rack(self, slot, content, jaw_set_id=None, side=None):
        if content not in ("empty", "blank", "finished"):
            raise ValueError("content must be empty, blank or finished")
        if self._active_run() and slot in self._busy_slots():
            raise ValueError("that slot is in use by the running cycle")
        self.store.update("rack", slot, key="slot", content=content, jaw_set_id=jaw_set_id if content == "finished" else None,
                          side=side if content == "finished" else None, updated_at=now_iso())
        if content == "empty":
            self._maybe_clear_location()

    def _maybe_clear_location(self):
        """Jaw sets whose location is the rack but no longer have jaws there."""
        for js in self.store.all("SELECT * FROM jaw_sets WHERE location LIKE 'Rack%'"):
            if not self.store.one("SELECT 1 FROM rack WHERE jaw_set_id = ? AND content = 'finished'", (js["id"],)):
                self.store.update("jaw_sets", js["id"], location="")

    def collect(self, jaw_set_id, location, by=""):
        """Operator takes a finished jaw set out of the rack and stores it."""
        if not location.strip():
            raise ValueError("enter where the jaws are stored")
        self.store.run("UPDATE rack SET content = 'empty', jaw_set_id = NULL, side = NULL, updated_at = ? "
                       "WHERE jaw_set_id = ? AND content = 'finished'", (now_iso(), jaw_set_id))
        self.store.update("jaw_sets", jaw_set_id, location=location.strip(), updated_at=now_iso())
        self.store.log("jaw_set", f"Jaws collected from the rack{' by ' + by if by else ''}; stored at {location.strip()}", jaw_set_id=jaw_set_id)

    def rack(self):
        rows = self.store.all("SELECT r.*, j.name AS jaw_set_name FROM rack r LEFT JOIN jaw_sets j ON j.id = r.jaw_set_id ORDER BY slot")
        busy = self._busy_slots()
        for r in rows:
            r["busy"] = r["slot"] in busy
        return rows

    # ------------------------------------------------------------------ runs
    def _est_duration(self, js):
        nc = self.latest_nc(js["id"])
        cyc = [(nc[s]["analysis"] or {}).get("est_cycle_s") or DEFAULT_CYCLE_S if s in nc else DEFAULT_CYCLE_S for s in self.sides(js)]
        if js["program_mode"] == "shared":
            cyc = cyc * 2
        return round(sum(cyc) + MOTION_OVERHEAD_S)

    def queue_run(self, jaw_set_id, trigger="manual", need_by=None, fault=None, priority=0):
        js = self._jaw_set(jaw_set_id)
        if fault and fault not in FAULTS:
            raise ValueError(f"unknown fault {fault}")
        rid = self.store.insert("runs", jaw_set_id=jaw_set_id, status="queued", trigger=trigger, need_by=need_by, priority=priority,
                                fault=json.dumps({"inject": fault}) if fault else None, created_at=now_iso(),
                                est_duration_s=self._est_duration(js))
        self.store.log("run", f"Run queued for {js['name']}" + (f" (fault test: {fault})" if fault else ""), jaw_set_id=jaw_set_id, run_id=rid)
        return rid

    def cancel_run(self, rid):
        run = self.store.get("runs", rid)
        if not run or run["status"] != "queued":
            raise ValueError("only queued runs can be cancelled")
        self.store.update("runs", rid, status="cancelled", finished_at=now_iso())
        self.store.log("run", "Run cancelled", jaw_set_id=run["jaw_set_id"], run_id=rid)

    def queue(self):
        return self.store.all("SELECT r.*, j.name AS jaw_set_name FROM runs r JOIN jaw_sets j ON j.id = r.jaw_set_id WHERE r.status = 'queued' "
                              "ORDER BY r.need_by IS NULL, r.need_by, r.priority DESC, r.id")

    def projection(self, now=None):
        now = now or datetime.now()
        end = self.active_end()
        busy = S.parse(end) if end else None
        ready =[r for r in self.queue() if not self.readiness(self._jaw_set(r["jaw_set_id"]))]   # blocked runs get no slot
        return S.project(ready, self.store.all("SELECT * FROM downtime"), now, busy)

    def active_end(self):
        """When the active run is expected to finish (wall clock), or None."""
        act = self._active_run()
        if not act or not act["started_at"]:
            return None
        speed = max(float(self.store.setting("sim_speed", 1.0)), 1e-6)
        return S.iso(S.parse(act["started_at"]) + timedelta(seconds=(act["sim_duration_s"] or act["est_duration_s"] or 0) / speed))

    def _active_run(self):
        return self.store.one("SELECT * FROM runs WHERE status IN ('planning', 'running') ORDER BY id DESC")

    def _busy_slots(self):
        act = self._active_run()
        return set((act["slots"] or {}).values()) if act and act["slots"] else set()

    def readiness(self, js) -> list[str]:
        """Reasons this jaw set cannot be machined right now (empty = ready)."""
        why = []
        nc = self.latest_nc(js["id"])
        for s in self.sides(js):
            if s not in nc:
                why.append(f"no NC program for {'the jaws' if s == 'both' else 'the ' + s + ' jaw'}")
            elif nc[s]["review_status"] != "approved":
                why.append(f"{'NC' if s == 'both' else s.capitalize() + ' NC'} not approved")
        blanks = [r for r in self.store.all("SELECT * FROM rack WHERE content = 'blank' ORDER BY slot")]
        if len(blanks) < 2:
            why.append(f"needs 2 blanks in the rack ({len(blanks)} loaded)")
        return why

    def start_run(self, rid, manual=True, confirm_outside_window=False):
        run = self.store.get("runs", rid)
        if not run or run["status"] != "queued":
            raise ValueError("only queued runs can be started")
        if self._active_run():
            raise ValueError("another run is active; one cycle at a time")
        js = self._jaw_set(run["jaw_set_id"])
        why = self.readiness(js)
        if why:
            raise ValueError("; ".join(why))
        if manual and not confirm_outside_window and not S.current_window(self.store.all("SELECT * FROM downtime"), datetime.now()):
            raise PermissionError("the machine is not in a downtime window; confirm it is free for the cell")
        blanks = [r["slot"] for r in self.store.all("SELECT slot FROM rack WHERE content = 'blank' ORDER BY slot")][:2]
        nc = self.latest_nc(js["id"])
        pick = (lambda s: nc["both"]) if js["program_mode"] == "shared" else (lambda s: nc[s])
        programs = {s: {"nc_id": pick(s)["id"], "program": pick(s)["program_number"] or f"NC{pick(s)['id']}",
                        "cycle_s": max(30.0, (pick(s)["analysis"] or {}).get("est_cycle_s") or DEFAULT_CYCLE_S),
                        "grasp_y": (pick(s)["analysis"] or {}).get("grasp_y") or 0.0, "sha256": pick(s)["sha256"]}
                    for s in ("left", "right")}
        self.store.update("runs", rid, status="planning", started_at=now_iso(), trigger=run["trigger"] if not manual else "manual",
                          slots={"left": blanks[0], "right": blanks[1]}, programs=programs, state="PLANNING")
        self.store.log("run", f"Run started ({'manual' if manual else 'auto, downtime window'}) for {js['name']}",
                       jaw_set_id=js["id"], run_id=rid)
        stop = threading.Event()
        self._stop[rid] = stop
        t = threading.Thread(target=self._execute, args=(rid, stop), daemon=True, name=f"run-{rid}")
        self._threads[rid] = t
        t.start()
        return rid

    def stop_run(self, rid):
        if rid not in self._stop:
            raise ValueError("run is not active")
        self._stop[rid].set()

    def _execute(self, rid, stop: threading.Event):
        st = self.store
        run = st.get("runs", rid)
        js = st.get("jaw_sets", run["jaw_set_id"])
        progs, slots = run["programs"], run["slots"]
        try:
            job = {"job_id": js["slug"], "release_status": "released", "program_id": progs["left"]["program"],
                   "programs": {s: progs[s]["program"] for s in progs}, "slots": slots,
                   "cycle_time_s": max(p["cycle_s"] for p in progs.values()),
                   "cycle_times": {s: progs[s]["cycle_s"] for s in progs}, "grasp_y": {s: progs[s]["grasp_y"] for s in progs}}
            cell, plan = simplan.plan_job(job, reach=False)
            if plan["issues"]:
                st.update("runs", rid, status="failed", finished_at=now_iso(), state="PLAN_REJECTED",
                          error=f"motion plan has {len(plan['issues'])} issue(s): " + json.dumps(plan["issues"][:3]))
                st.log("alert", "Run not started: the motion plan found reach/collision issues", jaw_set_id=js["id"], run_id=rid)
                return
            inject = (json.loads(run["fault"]) if run["fault"] else {}).get("inject")
            faults = {inject: "vise_above" if inject == "comms_loss" else True} if inject else None
            result = Orchestrator(job, plan, faults).run()
            folder = self.data / "runs" / str(rid)
            folder.mkdir(parents=True, exist_ok=True)
            outcome = "completed" if result["final_state"] == "COMPLETE" else f"ended in SAFE_STOP ({inject or 'fault'})"
            notes = {f"run-{rid}": {"label": f"Run {rid} - {js['name']}",
                                    "note": f"Replay of cell run {rid}: rack slots {slots['left']}/{slots['right']}, programs "
                                            f"{progs['left']['program']}/{progs['right']['program']}; the run {outcome}."}}
            (folder / "cell-plan.js").write_text(simplan.plan_js(job, cell, plan, {f"run-{rid}": result}, notes))
            total = max(result["sim_time_s"], 1e-6)
            st.update("runs", rid, status="running", sim_duration_s=result["sim_time_s"], sim_t=0.0)
            # simulation clock: advances at the current speed setting, so a speed change applies mid-run;
            # published as runs.sim_t for the live 3D view (GET /api/runs/<id>/clock)
            clock, last, published = 0.0, time.monotonic(), 0.0
            for ev in result["events"]:
                while clock < ev["t"]:
                    if stop.wait(0.1):
                        st.update("runs", rid, sim_t=round(clock, 2))
                        return self._operator_stop(rid, js, slots)
                    now = time.monotonic()
                    clock += (now - last) * max(float(st.setting("sim_speed", 1.0)), 1e-6)
                    last = now
                    if now - published >= 0.5:
                        st.update("runs", rid, sim_t=round(min(clock, ev["t"]), 2))
                        published = now
                if stop.is_set():
                    return self._operator_stop(rid, js, slots)
                data = {k: v for k, v in ev.items() if k not in ("seq", "t", "type", "state", "world")}
                st.insert("run_events", run_id=rid, seq=ev["seq"], t=ev["t"], type=ev["type"], state=ev["state"], data=data)
                st.update("runs", rid, state=ev["to"] if ev["type"] == "transition" else ev["state"], jaw=ev.get("jaw"),
                          progress=round(ev["t"] / total, 4), world=ev["world"], sim_t=ev["t"])
            self._finish(rid, js, slots, result)
        except Exception as e:                                    # never leave a run looking active
            st.update("runs", rid, status="failed", finished_at=now_iso(), error=f"{type(e).__name__}: {e}")
            st.log("alert", f"Run failed: {e}", jaw_set_id=js["id"], run_id=rid)
        finally:
            self._stop.pop(rid, None)

    def _finish(self, rid, js, slots, result):
        st = self.store
        for side, slot in slots.items():
            content = result["rack"].get(slot)
            if content and content.endswith("finished"):
                st.update("rack", slot, key="slot", content="finished", jaw_set_id=js["id"], side=side, updated_at=now_iso())
            elif content and content.endswith("blank"):
                st.update("rack", slot, key="slot", content="blank", jaw_set_id=None, side=None, updated_at=now_iso())
            else:
                st.update("rack", slot, key="slot", content="empty", jaw_set_id=None, side=None, updated_at=now_iso())
        res = {"final_state": result["final_state"], "inventory": result["inventory"], "sim_time_s": result["sim_time_s"]}
        if result["final_state"] == "COMPLETE":
            st.update("runs", rid, status="complete", finished_at=now_iso(), progress=1.0, result=res, state="COMPLETE")
            st.update("jaw_sets", js["id"], made_count=js["made_count"] + 1,
                      location=f"Rack slots {slots['left']}, {slots['right']}", updated_at=now_iso())
            st.log("run", f"Jaw set {js['name']} finished: collect from rack slots {slots['left']} and {slots['right']}",
                   jaw_set_id=js["id"], run_id=rid)
        else:
            fault = next((e for e in result["events"] if e["type"] == "fault"), {})
            st.update("runs", rid, status="safe_stop", finished_at=now_iso(), result=res, state="SAFE_STOP",
                      fault=json.dumps({"cause": fault.get("cause"), "detail": fault.get("detail")}))
            st.log("alert", f"SAFE_STOP: {fault.get('cause')} - {fault.get('detail')}. Confirm where the jaws are before the cell runs again.",
                   jaw_set_id=js["id"], run_id=rid)

    def _operator_stop(self, rid, js, slots):
        st = self.store
        run = st.get("runs", rid)
        w = run["world"] or {}
        inv = {}
        for side, slot in slots.items():
            held = str(w.get("holding") or "")
            if held.startswith(side):
                inv[side] = "unknown"
            elif str(w.get("vise_holds") or "").startswith(side):
                inv[side] = "vise"
            else:
                c = str((w.get("rack") or {}).get(str(slot)) or "")
                inv[side] = f"rack:{slot}:finished" if c.endswith("finished") else f"rack:{slot}" if c else "unknown"
        st.update("runs", rid, status="safe_stop", finished_at=now_iso(), state="SAFE_STOP",
                  result={"final_state": "SAFE_STOP", "inventory": inv, "sim_time_s": None},
                  fault=json.dumps({"cause": "operator_stop", "detail": "stopped from the app"}))
        st.log("alert", "Run stopped by the operator. Confirm where the jaws are before the cell runs again.", jaw_set_id=js["id"], run_id=rid)

    def recover_run(self, rid, by, locations: dict):
        """CTL-003: the operator confirms where each jaw is. The interrupted cycle is never resumed."""
        run = self.store.get("runs", rid)
        if not run or run["status"] != "safe_stop":
            raise ValueError("only stopped runs need recovery")
        if not by.strip():
            raise ValueError("enter your name to sign the recovery")
        slots = run["slots"] or {}
        for side in ("left", "right"):
            loc = locations.get(side)
            if loc not in ("blank_in_rack", "finished_in_rack", "removed", "scrapped"):
                raise ValueError(f"confirm where the {side} jaw is")
        js = self._jaw_set(run["jaw_set_id"])
        finished = 0
        for side in ("left", "right"):
            slot, loc = slots.get(side), locations[side]
            if slot is None:
                continue
            if loc == "blank_in_rack":
                self.store.update("rack", slot, key="slot", content="blank", jaw_set_id=None, side=None, updated_at=now_iso())
            elif loc == "finished_in_rack":
                self.store.update("rack", slot, key="slot", content="finished", jaw_set_id=js["id"], side=side, updated_at=now_iso())
                finished += 1
            else:
                self.store.update("rack", slot, key="slot", content="empty", jaw_set_id=None, side=None, updated_at=now_iso())
        self.store.update("runs", rid, status="recovered", recovered_by=by.strip(), note=json.dumps(locations))
        self.store.log("run", f"Recovery confirmed by {by.strip()}: " + ", ".join(f"{s} {l.replace('_', ' ')}" for s, l in locations.items()),
                       jaw_set_id=js["id"], run_id=rid)
        if finished == 2:
            self.store.update("jaw_sets", js["id"], made_count=js["made_count"] + 1,
                              location=f"Rack slots {slots['left']}, {slots['right']}")
        elif not (js["made_count"] and js["location"]):              # jaws still needed: try again
            self.queue_run(js["id"], trigger="retry", need_by=run["need_by"])

    def run_detail(self, rid, after=0):
        run = self.store.get("runs", rid)
        if not run:
            raise KeyError("run not found")
        run["jaw_set"] = self.store.get("jaw_sets", run["jaw_set_id"])
        run["events"] = self.store.all("SELECT seq, t, type, state, data FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
                                       (rid, after))
        run["replay"] = (self.data / "runs" / str(rid) / "cell-plan.js").exists()
        if isinstance(run.get("fault"), str):
            run["fault"] = json.loads(run["fault"])
        return run

    _idle_lock = threading.Lock()

    def idle_plan(self) -> Path | None:
        """cell-plan.js for the idle 3D view (the cell at rest), rebuilt when a config profile changes."""
        path = self.data / "idle" / "cell-plan.js"
        newest = max(p.stat().st_mtime for p in (ROOT / "config").rglob("*.json"))
        if path.exists() and path.stat().st_mtime >= newest:
            return path
        if not self._idle_lock.acquire(blocking=False):
            return path if path.exists() else None                 # being rebuilt; serve the old one meanwhile
        try:
            job = {"job_id": "cell-at-rest", "release_status": "released", "program_id": "O00000", "slots": {"left": 0, "right": 1},
                   "cycle_time_s": 60.0, "grasp_y": {"left": 0.0, "right": 0.0}}
            cell, plan = simplan.plan_job(job, reach=False)
            result = Orchestrator(job, plan).run()
            notes = {"idle": {"label": "Cell at rest", "note": "No cycle running. The rack shows the shop app's live slot contents."}}
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(simplan.plan_js(job, cell, plan, {"idle": result}, notes))
            tmp.replace(path)
            return path
        finally:
            self._idle_lock.release()

    def run_clock(self, rid):
        """Where a run's playback is, for the live 3D view: simulation seconds and the current speed."""
        run = self.store.one("SELECT id, status, state, sim_t, sim_duration_s FROM runs WHERE id = ?", (rid,))
        if not run:
            raise KeyError("run not found")
        if run["status"] == "complete":
            run["sim_t"] = run["sim_duration_s"]
        return {**run, "speed": float(self.store.setting("sim_speed", 1.0))}

    def list_runs(self, limit=50):
        rows = self.store.all("SELECT r.id, r.jaw_set_id, r.status, r.trigger, r.created_at, r.started_at, r.finished_at, r.state, "
                              "r.progress, r.fault, r.need_by, r.est_duration_s, j.name AS jaw_set_name FROM runs r JOIN jaw_sets j "
                              "ON j.id = r.jaw_set_id ORDER BY r.id DESC LIMIT ?", (limit,))
        for r in rows:
            if isinstance(r.get("fault"), str):
                r["fault"] = json.loads(r["fault"])
        return rows

    # ------------------------------------------------------------------ scheduler
    def tick(self, now=None):
        now = now or datetime.now()
        self.scan_inbox()
        if self._active_run() or not self.store.setting("auto_run", True):
            return None
        if self.store.one("SELECT 1 FROM runs WHERE status = 'safe_stop'"):
            return None                                           # a stopped run blocks auto mode until recovered
        win = S.current_window(self.store.all("SELECT * FROM downtime"), now)
        if not win:
            return None
        for run in self.queue():
            js = self._jaw_set(run["jaw_set_id"])
            est = timedelta(seconds=(run["est_duration_s"] or 0) / max(float(self.store.setting("sim_speed", 1.0)), 1e-6))
            if now + est > win[1] or self.readiness(js):
                continue
            return self.start_run(run["id"], manual=False)
        return None

    def _loop(self):
        while self._alive:
            try:
                self.tick()
            except Exception as e:                               # keep the scheduler alive
                self.store.log("alert", f"scheduler error: {e}")
            time.sleep(3.0)

    def close(self):
        self._alive = False
        for ev in list(self._stop.values()):
            ev.set()

    # ------------------------------------------------------------------ dashboard
    def status(self):
        now = datetime.now()
        downtime = self.store.all("SELECT * FROM downtime")
        win = S.current_window(downtime, now)
        upcoming = S.expand(downtime, now, now + timedelta(days=7))
        nxt = next(((s, e, l) for s, e, l in upcoming if s > now), None)
        act = self._active_run()
        if act:
            act["jaw_set_name"] = self.store.get("jaw_sets", act["jaw_set_id"])["name"]
        proj = self.projection(now)
        queue = [{**r, "projected": proj.get(r["id"])} for r in self.queue()]
        for r in queue:
            r["blocked"] = self.readiness(self._jaw_set(r["jaw_set_id"]))
        alerts = []
        for r in self.store.all("SELECT r.id, j.name, r.fault FROM runs r JOIN jaw_sets j ON j.id = r.jaw_set_id WHERE r.status = 'safe_stop'"):
            f = json.loads(r["fault"]) if isinstance(r["fault"], str) else (r["fault"] or {})
            alerts.append({"level": "danger", "text": f"Run {r['id']} ({r['name']}) stopped: {f.get('cause')}. Confirm jaw locations.",
                           "link": f"#/runs/{r['id']}"})
        for nc in self.store.all("SELECT n.id, n.side, n.filename, n.check_status, j.id AS jid, j.name FROM nc_programs n JOIN jaw_sets j "
                                 "ON j.id = n.jaw_set_id WHERE n.review_status = 'pending'"):
            alerts.append({"level": "danger" if nc["check_status"] == "fail" else "warn",
                           "text": f"{nc['name']}: {nc['filename']} ({nc['side']}) " +
                                   ("failed checks - repost from CAM" if nc["check_status"] == "fail" else "waiting for review"),
                           "link": f"#/jaws/{nc['jid']}"})
        for job in self.list_jobs():
            if job["at_risk"]:
                alerts.append({"level": "warn", "text": f"Job {job['name']} needs jaws by {job['need_by'][:10]} but they are not scheduled in time",
                               "link": "#/jobs"})
        for name, why in self.unmatched.items():
            alerts.append({"level": "warn", "text": f"CAM inbox file {name}: {why}", "link": "#/cam"})
        pending = self.store.all("SELECT n.id, n.side, n.filename, n.check_status, n.program_number, n.source, n.uploaded_at, n.analysis, "
                                 "j.id AS jaw_set_id, j.name AS jaw_set_name FROM nc_programs n JOIN jaw_sets j ON j.id = n.jaw_set_id "
                                 "WHERE n.review_status = 'pending' ORDER BY n.id")
        for p in pending:
            a = p.pop("analysis") or {}
            p.update(min_z=a.get("min_z"), est_cycle_s=a.get("est_cycle_s"),
                     failed=[c["title"] for c in a.get("checks", []) if c["status"] == "fail"])
        library = {}
        for js in self.store.all("SELECT * FROM jaw_sets WHERE archived = 0"):
            k = self._base_stage(js)["key"]
            library[k] = library.get(k, 0) + 1
        week0 = datetime.combine(now.date(), datetime.min.time())
        return {
            "now": S.iso(now), "auto_run": self.store.setting("auto_run", True), "sim_speed": self.store.setting("sim_speed", 1.0),
            "window": {"start": S.iso(win[0]), "end": S.iso(win[1]), "label": win[2]} if win else None,
            "next_window": {"start": S.iso(nxt[0]), "end": S.iso(nxt[1]), "label": nxt[2]} if nxt else None,
            "active": act, "queue": queue, "rack": self.rack(), "alerts": alerts, "pending_nc": pending, "library": library,
            "utilisation": self.utilisation(now), "active_end": self.active_end(),
            "windows_week": [{"start": S.iso(s), "end": S.iso(e), "label": l} for s, e, l in S.expand(downtime, week0, week0 + timedelta(days=7))],
            "activity": self.store.all("SELECT * FROM activity ORDER BY id DESC LIMIT 25"),
        }

    def utilisation(self, now=None, days=7):
        """Per day (oldest first): downtime hours available so far and the share the cell spent running."""
        now = now or datetime.now()
        downtime = self.store.all("SELECT * FROM downtime")
        runs = self.store.all("SELECT started_at, finished_at FROM runs WHERE started_at IS NOT NULL")
        first = self.store.one("SELECT MIN(at) AS at FROM activity")["at"]
        since = S.parse(first) if first else now                  # no history before the app was in use
        out = []
        for i in range(days - 1, -1, -1):
            d0 = datetime.combine((now - timedelta(days=i)).date(), datetime.min.time())
            d1 = min(d0 + timedelta(days=1), now)
            start = max(d0, since)
            avail = sum((e - s).total_seconds() for s, e, _ in S.expand(downtime, start, d1)) if d1 > start else 0.0
            used = 0.0
            for r in runs:
                s, e = S.parse(r["started_at"]), S.parse(r["finished_at"]) if r["finished_at"] else now
                used += max(0.0, (min(e, d1) - max(s, d0)).total_seconds())
            out.append({"date": d0.strftime("%Y-%m-%d"), "available_h": round(avail / 3600, 2), "run_h": round(used / 3600, 3),
                        "pct": round(min(100.0, 100 * used / avail), 1) if avail else None})
        return out

    def settings(self):
        return {k: self.store.setting(k) for k in ("outbox_dir", "inbox_dir", "auto_run", "sim_speed", "tool_radius", "auto_queue_for_jobs")}

    def save_settings(self, **s):
        for k, v in s.items():
            if k not in self.settings():
                raise ValueError(f"unknown setting {k}")
            if k == "sim_speed" and not (0.1 <= float(v) <= 1000):
                raise ValueError("simulation speed must be between 0.1 and 1000")
            self.store.set_setting(k, v)
