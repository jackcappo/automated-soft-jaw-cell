"""HTTP server for the shop app: JSON API, the single-page UI and per-run 3D replays.

Standard library only. Meant for a shop PC on a trusted network: there are no logins,
so anyone who can reach the port can use it. Reviews and recoveries are signed with a
typed name.
"""
from __future__ import annotations

import json
import mimetypes
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ..orchestrator import FAULTS
from ..profiles import ROOT
from .app import ShopApp

WEB = ROOT / "shop-web"
SIM = ROOT / "sim-web"
MAX_UPLOAD = 200 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    app: ShopApp = None
    server_version = "SoftJawCell/1"

    def log_message(self, fmt, *args):                  # keep the console quiet
        pass

    # ------------------------------------------------------------------ plumbing
    def _send(self, code, body: bytes, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str).encode())

    def error(self, code, message):
        self.json({"error": message}, code)

    def body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ValueError("file too large")
        return self.rfile.read(n) if n else b""

    def jbody(self) -> dict:
        raw = self.body()
        return json.loads(raw) if raw else {}

    def file(self, path: Path, download_name=None):
        path = Path(path)
        if not path.is_file():
            return self.error(404, "not found")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        extra = {"Content-Disposition": f'attachment; filename="{download_name}"'} if download_name else None
        self._send(200, path.read_bytes(), ctype, extra)

    def static(self, root: Path, rel: str):
        target = (root / rel).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            return self.error(404, "not found")
        return self.file(target)

    # ------------------------------------------------------------------ dispatch
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        url = urlparse(self.path)
        path, qs = unquote(url.path), {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if path.startswith("/api/"):
                for m, pattern, fn in ROUTES:
                    match = re.fullmatch(pattern, path)
                    if match and m == method:
                        return fn(self, qs, *[int(g) if g.isdigit() else g for g in match.groups()])
                return self.error(404, f"no route {method} {path}")
            if method != "GET":
                return self.error(405, "method not allowed")
            m = re.fullmatch(r"/sim/(.*)", path)              # the cell at rest (idle 3D view)
            if m:
                rel = m.group(1) or "index.html"
                if rel == "cell-plan.js":
                    return self.file(self.app.idle_plan() or SIM / "cell-plan.js")
                return self.static(SIM, rel)
            m = re.fullmatch(r"/runs/(\d+)/sim/(.*)", path)
            if m:
                rel = m.group(2) or "index.html"
                if rel == "cell-plan.js":
                    return self.file(self.app.data / "runs" / m.group(1) / "cell-plan.js")
                return self.static(SIM, rel)
            return self.static(WEB, path.lstrip("/") or "index.html")
        except KeyError as e:
            self.error(404, str(e).strip("'"))
        except PermissionError as e:
            self.error(409, str(e))
        except ValueError as e:
            self.error(400, str(e))
        except Exception as e:
            traceback.print_exc()
            self.error(500, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------- API
def status(h, qs):
    h.json(h.app.status())


def setup(h, qs):
    h.json({**h.app.setup, "faults": FAULTS})


def jaw_sets(h, qs):
    h.json(h.app.list_jaw_sets(archived=qs.get("archived") == "1"))


def jaw_set_create(h, qs):
    b = h.jbody()
    jid = h.app.create_jaw_set(b.get("name", ""), b.get("part_number", ""), b.get("description", ""), b.get("program_mode", "per_side"))
    h.json({"id": jid}, 201)


def jaw_set_get(h, qs, jid):
    h.json(h.app.jaw_set_detail(jid))


def jaw_set_patch(h, qs, jid):
    h.app.update_jaw_set(jid, **h.jbody())
    h.json(h.app.jaw_set_detail(jid))


def upload_design(h, qs, jid):
    fid = h.app.add_design_file(jid, qs.get("filename", "design"), h.body(), qs.get("side", "both"))
    h.json({"id": fid}, 201)


def upload_nc(h, qs, jid):
    nid = h.app.add_nc(jid, qs.get("side", "both"), qs.get("filename", "program.nc"), h.body())
    h.json(h.app.store.get("nc_programs", nid), 201)


def queue_jaw_set(h, qs, jid):
    b = h.jbody()
    rid = h.app.queue_run(jid, "manual", b.get("need_by") or None, b.get("fault") or None)
    h.json({"id": rid}, 201)


def collect(h, qs, jid):
    b = h.jbody()
    h.app.collect(jid, b.get("location", ""), b.get("by", ""))
    h.json(h.app.jaw_set_detail(jid))


def file_download(h, qs, fid):
    f = h.app.store.get("files", fid)
    if not f:
        raise KeyError("file not found")
    h.file(f["stored"], f["filename"])


def nc_get(h, qs, nid):
    nc = h.app.store.get("nc_programs", nid)
    if not nc:
        raise KeyError("program not found")
    nc["text"] = Path(nc["stored"]).read_text(errors="replace")[:200_000] if Path(nc["stored"]).exists() else ""
    h.json(nc)


def nc_download(h, qs, nid):
    nc = h.app.store.get("nc_programs", nid)
    if not nc:
        raise KeyError("program not found")
    h.file(nc["stored"], nc["filename"])


def nc_review(h, qs, nid):
    b = h.jbody()
    h.app.review_nc(nid, b.get("decision", ""), b.get("by", ""), b.get("note", ""))
    h.json(h.app.store.get("nc_programs", nid))


def jobs(h, qs):
    h.json(h.app.list_jobs())


def job_create(h, qs):
    h.json({"id": h.app.save_job(None, **h.jbody())}, 201)


def job_patch(h, qs, jid):
    h.json({"id": h.app.save_job(jid, **h.jbody())})


def job_delete(h, qs, jid):
    h.app.store.run("DELETE FROM production_jobs WHERE id = ?", (jid,))
    h.json({"ok": True})


def downtime(h, qs):
    h.json({"windows": h.app.list_downtime(), "upcoming": h.app.windows(int(qs.get("days", 7)))})


def downtime_create(h, qs):
    h.json({"id": h.app.save_downtime(None, **h.jbody())}, 201)


def downtime_patch(h, qs, did):
    h.json({"id": h.app.save_downtime(did, **h.jbody())})


def downtime_delete(h, qs, did):
    h.app.store.run("DELETE FROM downtime WHERE id = ?", (did,))
    h.json({"ok": True})


def runs(h, qs):
    h.json(h.app.list_runs(int(qs.get("limit", 50))))


def run_get(h, qs, rid):
    h.json(h.app.run_detail(rid, int(qs.get("after", 0))))


def run_clock(h, qs, rid):
    h.json(h.app.run_clock(rid))


def run_start(h, qs, rid):
    b = h.jbody()
    h.app.start_run(rid, manual=True, confirm_outside_window=bool(b.get("confirm_outside_window")))
    h.json({"ok": True})


def run_cancel(h, qs, rid):
    h.app.cancel_run(rid)
    h.json({"ok": True})


def run_stop(h, qs, rid):
    h.app.stop_run(rid)
    h.json({"ok": True})


def run_recover(h, qs, rid):
    b = h.jbody()
    h.app.recover_run(rid, b.get("by", ""), b.get("locations", {}))
    h.json({"ok": True})


def rack(h, qs):
    h.json(h.app.rack())


def rack_set(h, qs, slot):
    b = h.jbody()
    h.app.set_rack(slot, b.get("content", ""), b.get("jaw_set_id"), b.get("side"))
    h.json(h.app.rack())


def cam(h, qs):
    app = h.app
    inbox = app.inbox_dir()
    imported = sorted((inbox / "imported").glob("*"), reverse=True)[:20] if (inbox / "imported").exists() else []
    h.json({"outbox": str(app.outbox_dir()), "inbox": str(inbox), "unmatched": app.unmatched,
            "imported": [p.name for p in imported], "setup": app.setup})


def cam_scan(h, qs):
    h.json({"imported": h.app.scan_inbox(), "unmatched": h.app.unmatched})


def settings_get(h, qs):
    h.json(h.app.settings())


def settings_patch(h, qs):
    b = h.jbody()
    h.app.save_settings(**b)
    if {"outbox_dir"} & b.keys():
        for js in h.app.store.all("SELECT id FROM jaw_sets WHERE archived = 0"):
            h.app.write_outbox(js["id"])
    h.json(h.app.settings())


N = r"(\d+)"
ROUTES = [
    ("GET", "/api/status", status), ("GET", "/api/setup", setup),
    ("GET", "/api/jaw-sets", jaw_sets), ("POST", "/api/jaw-sets", jaw_set_create),
    ("GET", f"/api/jaw-sets/{N}", jaw_set_get), ("PATCH", f"/api/jaw-sets/{N}", jaw_set_patch),
    ("POST", f"/api/jaw-sets/{N}/files", upload_design), ("POST", f"/api/jaw-sets/{N}/nc", upload_nc),
    ("POST", f"/api/jaw-sets/{N}/queue", queue_jaw_set), ("POST", f"/api/jaw-sets/{N}/collect", collect),
    ("GET", f"/api/files/{N}", file_download),
    ("GET", f"/api/nc/{N}", nc_get), ("GET", f"/api/nc/{N}/download", nc_download), ("POST", f"/api/nc/{N}/review", nc_review),
    ("GET", "/api/jobs", jobs), ("POST", "/api/jobs", job_create),
    ("PATCH", f"/api/jobs/{N}", job_patch), ("DELETE", f"/api/jobs/{N}", job_delete),
    ("GET", "/api/downtime", downtime), ("POST", "/api/downtime", downtime_create),
    ("PATCH", f"/api/downtime/{N}", downtime_patch), ("DELETE", f"/api/downtime/{N}", downtime_delete),
    ("GET", "/api/runs", runs), ("GET", f"/api/runs/{N}", run_get), ("GET", f"/api/runs/{N}/clock", run_clock),
    ("POST", f"/api/runs/{N}/start", run_start), ("POST", f"/api/runs/{N}/cancel", run_cancel),
    ("POST", f"/api/runs/{N}/stop", run_stop), ("POST", f"/api/runs/{N}/recover", run_recover),
    ("GET", "/api/rack", rack), ("POST", f"/api/rack/{N}", rack_set),
    ("GET", "/api/cam", cam), ("POST", "/api/cam/scan", cam_scan),
    ("GET", "/api/settings", settings_get), ("PATCH", "/api/settings", settings_patch),
]


def make_server(host="0.0.0.0", port=8080, data_dir=None, background=True):
    app = ShopApp(data_dir or ROOT / "data", background=background)
    handler = type("BoundHandler", (Handler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler), app


def serve(host="0.0.0.0", port=8080, data_dir=None):
    srv, app = make_server(host, port, data_dir)
    print(f"Soft jaw cell app on http://localhost:{port}  (data in {app.data}; Ctrl+C to stop)")
    print(f"CAM outbox: {app.outbox_dir()}\nCAM inbox:  {app.inbox_dir()}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        srv.server_close()
