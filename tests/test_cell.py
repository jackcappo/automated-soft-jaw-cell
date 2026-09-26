import json
import shutil
import subprocess
import unittest
from pathlib import Path

import numpy as np
from softjaw import cellplan as C, export, jawgen, simplan
from softjaw.kinematics import Arm
from softjaw.orchestrator import FAULTS, Orchestrator, PhysicalCommandPathDisabled
from softjaw.profiles import ROOT, load_json


class KinematicsTests(unittest.TestCase):
    def setUp(self):
        self.arm = Arm(load_json("config/robots/rebot-b601-dm.json"), [0, 0, 0])

    def test_reach_matches_published_value(self):
        rng = np.random.default_rng(0)
        d = max(np.linalg.norm(self.arm.tcp(q)[:3, 3] - self.arm.frames(q)[2][:3, 3])
                for q in rng.uniform(self.arm.lower, self.arm.upper, (4000, 6)))
        self.assertAlmostEqual(d, 767, delta=20)

    def test_ik_round_trip(self):
        for tgt in ([350, 0, -100], [450, 0, 0], [300, 150, 50]):
            r = self.arm.ik(tgt, (0, 0, -1), (1, 0, 0))
            self.assertTrue(r["ok"], r)
            self.assertLess(np.linalg.norm(self.arm.tcp(r["q"])[:3, 3] - tgt), 0.5)


class PlanAndOrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        export.write_package(jawgen.generate(str(ROOT / "config/jobs/hex_fitting.json")))
        cls.job, cls.cell, cls.plan, cls.scen = simplan.build(str(ROOT / "output/hex_fitting/manifest.json"))

    def test_plan_is_reachable_and_collision_free(self):
        self.assertEqual(self.plan["issues"], [])
        self.assertIn("home", self.plan["outside_waypoints"])

    def test_nominal_cycle_returns_both_jaws(self):
        r = self.scen["nominal"]
        self.assertEqual(r["final_state"], "COMPLETE")
        self.assertEqual(r["inventory"], {"left": "rack:0:finished", "right": "rack:1:finished"})

    def test_every_fault_safe_stops_and_stays_stopped(self):
        for fault in FAULTS:
            with self.subTest(fault):
                r = self.scen[fault]
                self.assertEqual(r["final_state"], "SAFE_STOP")
                f = next(e for e in r["events"] if e["type"] == "fault")
                self.assertEqual(f["cause"], fault)
                self.assertFalse([e for e in r["events"] if e["seq"] > f["seq"] and e["type"] == "command"])

    def test_recovery_is_explicit_and_never_resumes(self):
        o = Orchestrator(self.job, self.plan, {"lost_grip": True})
        o.run()
        with self.assertRaises(RuntimeError):
            o.operator_recover("op", {})                     # jaw location still unknown
        o.operator_recover("op", {"left": "rack:0"})
        self.assertEqual(o.state, "IDLE")
        with self.assertRaises(RuntimeError):
            o.run()                                          # needs a fresh, explicit run

    def test_replay_is_deterministic(self):
        a = Orchestrator(self.job, self.plan).run()["events"]
        self.assertEqual(a, self.scen["nominal"]["events"])

    def test_no_physical_command_path(self):
        with self.assertRaises(PhysicalCommandPathDisabled):
            Orchestrator(self.job, self.plan, physical=True)

    def test_blocked_jaws_never_run(self):
        job = dict(self.job, release_status="blocked")
        r = Orchestrator(job, self.plan).run()
        self.assertEqual(r["final_state"], "SAFE_STOP")
        self.assertFalse([e for e in r["events"] if e["type"] == "command"])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_browser_kinematics_match_python(self):
        simplan.export_js(self.job, self.cell, self.plan, self.scen)
        js = """const K=require(process.argv[1]);const fs=require('fs');const s=fs.readFileSync(process.argv[2],'utf8');
const p=JSON.parse(s.slice(s.indexOf('=')+1).trim().replace(/;$/,''));const o={};
for(const [n,q] of Object.entries(p.joints.left)){const f=K.frames(p.robot,q);const T=f[f.length-1];o[n]=[T[3],T[7],T[11],T[0],T[4],T[8]];}
console.log(JSON.stringify(o));"""
        out = subprocess.run(["node", "-e", js, str(ROOT / "sim-web/kinematics.js"), str(ROOT / "sim-web/cell-plan.js")],
                             capture_output=True, text=True, check=True).stdout
        for name, v in json.loads(out).items():
            T = self.cell.arm.tcp(np.array(self.plan["jaws"]["left"]["joints"][name]))
            self.assertLess(np.abs(np.concatenate([T[:3, 3], T[:3, 0]]) - v).max(), 1e-6)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_simulator_replays_every_scenario(self):
        simplan.export_js(self.job, self.cell, self.plan, self.scen)
        r = subprocess.run(["node", str(ROOT / "tools/sim_smoke_test.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
