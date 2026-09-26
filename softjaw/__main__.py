"""Command line:  python -m softjaw <command>

  parts                    regenerate examples/parts/*.stl and config/jobs/*.json
  jaws  [JOB ...] [--all]  generate + validate soft jaws, write the CAM package to output/
  plan  [--slots L R]      robot reach / collision study for the cell layout
  sim   [--job NAME]       plan + run the orchestrator scenarios, write sim-web/cell-plan.js
  bundle [OUT]             one-file simulator page (embeds sim-web/assets/machine.stl if present)
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

from .profiles import ROOT


def cmd_jaws(args):
    from . import export, jawgen
    jobs = sorted(glob.glob(str(ROOT / "config/jobs/*.json"))) if args.all or not args.jobs else \
        [j if j.endswith(".json") else str(ROOT / f"config/jobs/{j}.json") for j in args.jobs]
    bad = 0
    for jp in jobs:
        t = time.time()
        r = jawgen.generate(jp)
        pkg = export.write_package(r)
        expected = json.loads(Path(jp).read_text()).get("expected_status")
        flag = "" if expected in (None, r.status) else f"  (expected {expected})"
        bad += bool(flag)
        print(f"{Path(jp).stem:18s} {r.status:22s} {time.time() - t:5.1f}s -> {Path(pkg['directory']).relative_to(ROOT)}{flag}")
        for c in r.checks:
            if c.status == "fail":
                print(f"    FAIL {c.id} {c.jaw or ''} {c.requirement}: {c.message or c.measured} -> {c.suggestion}")
    return 1 if bad else 0


def cmd_plan(args):
    from . import cellplan as C
    cell = C.build_cell()
    issues = 0
    for side, slot in (("left", args.slots[0]), ("right", args.slots[1])):
        p = C.plan_jaw(cell, slot)
        issues += len(p["issues"])
        print(f"{side} jaw, rack slot {slot}: {len(p['issues'])} issues, robot motion {p['cycle_motion_s']} s")
        for i in p["issues"]:
            print("   ", i)
    print(f"reach margin: the vise could sit {C.reach_margin()} mm further into the machine")
    un = {(u['profile'], u['field']) for u in cell.tracker.unverified}
    print(f"{len(un)} layout values are assumed/estimated; measure them before trusting the result")
    return 1 if issues else 0


def cmd_sim(args):
    from . import simplan
    manifest = ROOT / "output" / args.job / "manifest.json"
    if not manifest.exists():
        sys.exit(f"{manifest} not found; run: python -m softjaw jaws {args.job}")
    job, cell, plan, scen = simplan.build(str(manifest), {"left": args.slots[0], "right": args.slots[1]})
    path = simplan.export_js(job, cell, plan, scen)
    for name, r in scen.items():
        print(f"{name:20s} {r['final_state']:10s} {r['sim_time_s']:8.1f} s")
    print(f"wrote {path.relative_to(ROOT)}; serve with: cd sim-web && python -m http.server 8070")
    return 1 if plan["issues"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m softjaw", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("parts")
    j = sub.add_parser("jaws"); j.add_argument("jobs", nargs="*"); j.add_argument("--all", action="store_true")
    p = sub.add_parser("plan"); p.add_argument("--slots", nargs=2, type=int, default=[0, 1])
    s = sub.add_parser("sim"); s.add_argument("--job", default="hex_fitting"); s.add_argument("--slots", nargs=2, type=int, default=[0, 1])
    b = sub.add_parser("bundle"); b.add_argument("out", nargs="?", default=str(ROOT / "output" / "soft-jaw-cell-sim.html"))
    a = ap.parse_args(argv)
    if a.cmd == "parts":
        sys.path.insert(0, str(ROOT / "tools"))
        import make_examples
        make_examples.main()
        return 0
    if a.cmd == "bundle":
        sys.path.insert(0, str(ROOT / "tools"))
        import bundle_sim
        print(bundle_sim.bundle(a.out))
        return 0
    return {"jaws": cmd_jaws, "plan": cmd_plan, "sim": cmd_sim}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
