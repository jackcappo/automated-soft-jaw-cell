import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from softjaw.profiles import ROOT
from softjaw.shop import schedule as S
from softjaw.shop.app import ShopApp
from softjaw.shop.ncparse import analyze
from softjaw.shop.setup import jaw_setup

NC = ROOT / "examples" / "nc"
GOOD = (NC / "hex-fitting-op1_left.nc").read_text()


def status_of(a, cid):
    return next((c["status"] for c in a["checks"] if c["id"] == cid), None)


class NcCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.setup = jaw_setup()

    def test_sample_program_passes(self):
        a = analyze(GOOD, self.setup)
        self.assertEqual(a["status"], "pass", a["checks"])
        self.assertEqual(a["program_number"], "O01101")
        self.assertAlmostEqual(a["min_z"], -8.0)
        self.assertGreater(abs(a["grasp_y"]), 20)                     # fingers go beside the pocket

    def test_too_deep_and_rapid_into_stock_fail(self):
        a = analyze((NC / "cam-plate-op2_left.nc").read_text(), self.setup)
        self.assertEqual(status_of(a, "NC-004"), "fail")
        self.assertEqual(status_of(a, "NC-006"), "fail")

    def test_straight_retract_from_pocket_is_not_a_rapid_into_stock(self):
        a = analyze("G21 G90 G54\nT1 M6\nS5000 M3\nG0 X10 Y0 Z5\nG1 Z-5 F200\nG1 X15\nG0 Z20\nM30\n", self.setup)
        self.assertEqual(status_of(a, "NC-006"), "pass")

    def test_inch_program_is_converted(self):
        a = analyze("G20 G90 G54\nT1 M6\nS5000 M3\nG0 X0.5 Y0 Z0.2\nG1 Z-0.7 F10.\nG1 X0.6\nG0 Z1.\nM30\n", self.setup)
        self.assertAlmostEqual(a["min_z"], -17.78, places=2)
        self.assertEqual(status_of(a, "NC-004"), "fail")              # 0.7 in is deeper than the 15 mm limit

    def test_missing_end_spindle_and_feed_are_caught(self):
        a = analyze("G21 G90 G54\nG0 X10 Y0 Z5\nG1 Z-3\nG1 X12 F100\n", self.setup)
        for cid in ("NC-001", "NC-007", "NC-008"):
            self.assertEqual(status_of(a, cid), "fail", cid)

    def test_arc_extents_and_incremental_moves(self):
        # G91 X5 moves to X17.5; the counter-clockwise arc to (12.5, -5) about (12.5, 0) goes the long way through +Y and -X
        a = analyze("G21 G90 G54\nT1 M6\nS5000 M3\nG0 X12.5 Y0 Z2\nG1 Z-2 F200\nG91 G1 X5\nG90 G3 X12.5 Y-5 I-5 J0\nG0 Z10\nM30\n", self.setup)
        self.assertAlmostEqual(a["cut_extents"]["max"][0], 17.5, places=1)
        self.assertAlmostEqual(a["cut_extents"]["max"][1], 5.0, places=1)
        self.assertAlmostEqual(a["cut_extents"]["min"][0], 7.5, places=1)
        cw = analyze("G21 G90 G54\nT1 M6\nS5000 M3\nG0 X17.5 Y0 Z2\nG1 Z-2 F200\nG2 X12.5 Y-5 I-5 J0\nG0 Z10\nM30\n", self.setup)
        self.assertAlmostEqual(cw["cut_extents"]["max"][1], 0.0, places=1)    # clockwise is the short quarter

    def test_drill_cycle_depth(self):
        a = analyze("G21 G90 G54\nT3 M6\nS3000 M3\nG0 X10 Y20 Z5\nG81 X10 Y20 Z-16 R2 F100\nX15 Y20\nG80\nM30\n", self.setup)
        self.assertAlmostEqual(a["min_z"], -16.0)
        self.assertEqual(status_of(a, "NC-004"), "fail")

    def test_no_room_to_regrasp(self):
        a = analyze("G21 G90 G54\nT1 M6\nS5000 M3\nG0 X10 Y-58 Z2\nG1 Z-4 F200\nG1 Y58\nG0 Z10\nM30\n", self.setup)
        self.assertEqual(status_of(a, "NC-010"), "fail")


class ScheduleTests(unittest.TestCase):
    def test_weekly_window_crosses_midnight_and_merges(self):
        w = [{"kind": "weekly", "days": "4", "start_time": "18:00", "end_time": "06:00"},                # Friday night
             {"kind": "weekly", "days": "5", "start_time": "00:00", "end_time": "12:00"}]               # Saturday morning
        fri = datetime(2026, 9, 25, 12, 0)
        spans = S.expand(w, fri, fri + timedelta(days=2))
        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0][0], spans[0][1]), (datetime(2026, 9, 25, 18), datetime(2026, 9, 26, 12)))

    def test_runs_only_start_where_they_fit(self):
        w = [{"kind": "once", "start": "2026-09-28T12:00:00", "end": "2026-09-28T12:30:00"},
             {"kind": "once", "start": "2026-09-28T18:00:00", "end": "2026-09-28T23:00:00"}]
        q = [{"id": 1, "est_duration_s": 1200}, {"id": 2, "est_duration_s": 3600}]
        p = S.project(q, w, datetime(2026, 9, 28, 8))
        self.assertEqual(p[1]["start"], "2026-09-28T12:00:00")
        self.assertEqual(p[2]["start"], "2026-09-28T18:00:00")          # 10 minutes left at lunch is not enough
        self.assertIsNone(S.project([{"id": 3, "est_duration_s": 10 * 3600}], w, datetime(2026, 9, 28, 8))[3]["start"])


class ShopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.app = ShopApp(self.dir, background=False)
        self.app.save_settings(sim_speed=1000)

    def tearDown(self):
        self.app.close()
        for t in list(self.app._threads.values()):
            t.join(30)
        self.app.store.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def wait(self, rid):
        t = self.app._threads.get(rid)
        if t:
            t.join(120)
        return self.app.run_detail(rid)

    def ready_set(self):
        app = self.app
        jid = app.create_jaw_set("Hex fitting OP1", "HX-100")
        for side in ("left", "right"):
            nid = app.add_nc(jid, side, f"x_{side}.nc", (NC / f"hex-fitting-op1_{side}.nc").read_bytes())
            app.review_nc(nid, "approved", "tester")
        for s in (0, 1):
            app.set_rack(s, "blank")
        return jid

    def window_now(self):
        now = datetime.now()
        self.app.save_downtime(kind="once", start=S.iso(now - timedelta(minutes=5)), end=S.iso(now + timedelta(hours=3)), label="test")

    def test_failed_program_cannot_be_approved_and_hotfolder_import(self):
        app = self.app
        jid = app.create_jaw_set("Cam plate OP2")
        inbox = app.inbox_dir()
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "cam-plate-op2_left.nc").write_bytes((NC / "cam-plate-op2_left.nc").read_bytes())
        (inbox / "cam-plate-op2.nc").write_text(GOOD)                     # no side in the name
        imported = app.scan_inbox()
        self.assertEqual(len(imported), 1)
        self.assertIn("cam-plate-op2.nc", app.unmatched)
        nc = app.latest_nc(jid)["left"]
        self.assertEqual((nc["source"], nc["check_status"]), ("hotfolder", "fail"))
        with self.assertRaises(ValueError):
            app.review_nc(nc["id"], "approved", "tester")
        self.assertTrue((inbox / "imported").exists())
        out = app.outbox_dir() / "cam-plate-op2"
        self.assertTrue((out / "jaw_setup.json").exists() and (out / "blank_top_face.dxf").exists())
        self.assertEqual(app.stage(app.store.get("jaw_sets", jid))["key"], "cam")    # right program still missing

    def test_production_job_queues_jaws_and_auto_run_waits_for_a_window(self):
        app = self.app
        jid = self.ready_set()
        app.save_job(name="WO-1", need_by=(datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"), jaw_set_id=jid)
        self.assertEqual(len(app.queue()), 1)
        self.assertIsNone(app.tick())                                    # no downtime window: nothing starts
        self.window_now()
        rid = app.tick()
        r = self.wait(rid)
        self.assertEqual((r["status"], r["state"]), ("complete", "COMPLETE"))
        self.assertTrue(r["replay"])
        clock = app.run_clock(rid)                                       # the live 3D view ends on the last event
        self.assertEqual((clock["status"], clock["sim_t"]), ("complete", r["sim_duration_s"]))
        rack = {x["slot"]: x for x in app.rack()}
        self.assertEqual([(rack[s]["content"], rack[s]["side"]) for s in (0, 1)], [("finished", "left"), ("finished", "right")])
        self.assertEqual(app.stage(app.store.get("jaw_sets", jid))["key"], "made")
        app.collect(jid, "Shelf B3")
        self.assertEqual(app.store.get("jaw_sets", jid)["location"], "Shelf B3")
        self.assertEqual(app.rack()[0]["content"], "empty")
        self.assertFalse(app.list_jobs()[0]["at_risk"])

    def test_safe_stop_blocks_auto_run_until_recovered(self):
        app = self.app
        jid = self.ready_set()
        self.window_now()
        rid = app.queue_run(jid, fault="clamp_disagreement")
        app.start_run(rid, manual=True)
        r = self.wait(rid)
        self.assertEqual(r["status"], "safe_stop")
        self.assertEqual(r["fault"]["cause"], "clamp_disagreement")
        app.queue_run(jid)
        self.assertIsNone(app.tick())                                    # stopped run blocks auto mode
        with self.assertRaises(ValueError):
            app.recover_run(rid, "tester", {"left": "blank_in_rack"})     # every jaw must be confirmed
        app.recover_run(rid, "tester", {"left": "blank_in_rack", "right": "blank_in_rack"})
        self.assertEqual(app.store.get("runs", rid)["status"], "recovered")
        self.assertIsNotNone(app.tick())                                 # auto mode resumes with a new run

    def test_manual_start_outside_window_needs_confirmation(self):
        app = self.app
        jid = self.ready_set()
        rid = app.queue_run(jid)
        with self.assertRaises(PermissionError):
            app.start_run(rid, manual=True)
        app.start_run(rid, manual=True, confirm_outside_window=True)
        self.assertEqual(self.wait(rid)["status"], "complete")

    def test_not_ready_without_blanks_or_approval(self):
        app = self.app
        jid = app.create_jaw_set("Shared", program_mode="shared")
        js = app.store.get("jaw_sets", jid)
        self.assertEqual(app.readiness(js), ["no NC program for the jaws", "needs 2 blanks in the rack (0 loaded)"])
        rid = app.queue_run(jid)
        with self.assertRaises(ValueError):
            app.start_run(rid, confirm_outside_window=True)


class ServerTests(unittest.TestCase):
    def test_api_and_static_pages(self):
        from softjaw.shop.server import make_server
        d = tempfile.mkdtemp()
        srv, app = make_server("127.0.0.1", 0, d, background=False)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(path, method="GET", body=None, raw=None):
            data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                with e:
                    return e.code, e.read()
        try:
            self.assertEqual(call("/")[0], 200)
            self.assertIn(b"Soft Jaw Cell", call("/index.html")[1])
            self.assertEqual(call("/../softjaw/__init__.py")[0], 404)
            code, body = call("/api/jaw-sets", "POST", {"name": "Test set"})
            self.assertEqual(code, 201)
            jid = json.loads(body)["id"]
            code, body = call(f"/api/jaw-sets/{jid}/nc?side=left&filename=t.nc", "POST", raw=GOOD.encode())
            self.assertEqual((code, json.loads(body)["check_status"]), (201, "pass"))
            self.assertEqual(call(f"/api/jaw-sets/{jid}/nc?side=middle&filename=t.nc", "POST", raw=b"M30")[0], 400)
            status = json.loads(call("/api/status")[1])
            self.assertEqual(len(status["rack"]), 6)
            self.assertEqual(call("/api/nope")[0], 404)
            code, body = call("/sim/cell-plan.js")                       # idle 3D view: built from the current config
            self.assertEqual(code, 200)
            self.assertIn(b"cell-at-rest", body)
            self.assertIn(b"Soft Jaw Cell Simulator", call("/sim/")[1])
        finally:
            srv.shutdown()
            srv.server_close()
            app.close()
            app.store.db.close()
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
