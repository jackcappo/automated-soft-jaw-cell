"""Cell orchestrator (CTL-001..006, SIM-002, SIM-006, SIM-007).

One state machine drives either simulated adapters (this file) or, later,
physical adapters behind the same interface. Physical adapters are disabled
in this build: constructing one raises PhysicalCommandPathDisabled.

Time is simulated and deterministic, so the same job + fault plan always
produces the same event log (replay requirement in PRD section 14).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

STATES = [
    "IDLE", "JOB_VALIDATED", "PICK_BLANK", "VERIFY_GRIP", "REQUEST_LOAD", "DOOR_OPEN_CONFIRMED", "LOAD_BLANK",
    "FIXTURE_CLAMPED_CONFIRMED", "ROBOT_CLEAR_CONFIRMED", "DOOR_CLOSED_CONFIRMED", "CNC_CYCLE", "CYCLE_COMPLETE",
    "SPINDLE_ZERO_CONFIRMED", "DOOR_OPEN_CONFIRMED", "UNCLAMP", "PICK_FINISHED_JAW", "RETURN_TO_RACK", "COMPLETE",
    "SAFE_STOP",
]

FAULTS = {
    "lost_grip": "gripper possession sensor drops after the blank is picked",
    "occupied_slot": "the return slot is found occupied",
    "door_disagreement": "door commanded open but the door-open sensor never confirms",
    "clamp_disagreement": "vise commanded closed but the clamp sensor reports open",
    "cnc_alarm": "CNC raises an alarm during the cycle",
    "timeout": "CNC never reports cycle complete",
    "comms_loss": "robot adapter stops responding during a move",
    "spindle_not_stopped": "spindle-stopped signal missing when the robot wants to enter",
}


class PhysicalCommandPathDisabled(RuntimeError):
    pass


class SafeStop(Exception):
    def __init__(self, cause, detail=""):
        super().__init__(cause)
        self.cause, self.detail = cause, detail


class CommsLost(Exception):
    pass


# ---------------------------------------------------------------- sim world

@dataclass
class World:
    """Ground truth shared by the fake adapters."""
    t: float = 0.0
    robot_at: str = "home"
    holding: str | None = None
    door_open: bool = False
    spindle_running: bool = False
    axes_at_exchange: bool = False
    clamped: bool = False
    vise_holds: str | None = None
    cycle_done: bool = False
    alarm: bool = False
    rack: dict = field(default_factory=dict)          # slot -> jaw id or None
    faults: dict = field(default_factory=dict)        # fault -> trigger detail
    moves: dict = field(default_factory=dict)         # (from,to) -> seconds, from the motion plan
    outside: set = field(default_factory=set)         # waypoints verified (by FK) outside the machine


class FakeRobot:
    def __init__(self, w: World, log):
        self.w, self.log = w, log

    def move(self, to):
        if self.w.robot_at == to:
            return                                     # already there: nothing to command
        key = (self.w.robot_at, to)
        if key not in self.w.moves:
            raise SafeStop("unplanned_motion", f"no verified path {key[0]} -> {to}")
        if self.w.faults.get("comms_loss") == to:
            raise CommsLost(f"robot stopped acknowledging during move to {to}")
        self.log("command", device="robot", action="move", frm=self.w.robot_at, to=to)
        self.w.t += self.w.moves[key]
        self.w.robot_at = to
        self.log("ack", device="robot", action="move", at=to)

    def grip(self, close: bool, target=None):
        self.log("command", device="gripper", action="close" if close else "open")
        self.w.t += 0.6
        self.w.holding = target if close else None
        if close and self.w.faults.get("lost_grip") and self.w.holding and self.w.holding.endswith("blank"):
            self.w.holding = None                      # part slipped
            self.w.faults.pop("lost_grip")
        self.log("ack", device="gripper", holding=self.w.holding)

    def sensor_holding(self):
        return self.w.holding is not None

    def outside_machine(self):
        return self.w.robot_at in self.w.outside


class FakeCnc:
    def __init__(self, w: World, log, program_id):
        self.w, self.log, self.program_id = w, log, program_id

    def request_exchange(self):
        self.log("command", device="cnc", action="goto_exchange_pose")
        self.w.t += 4.0
        if self.w.faults.get("spindle_not_stopped"):
            self.w.spindle_running = True
        self.w.axes_at_exchange = True

    def door(self, open_):
        self.log("command", device="cnc", action="door_open" if open_ else "door_close")
        self.w.t += 3.0
        if open_ and self.w.faults.get("door_disagreement"):
            return                                     # door jammed, sensor never changes
        self.w.door_open = open_

    def cycle_start(self, program_id):
        self.log("command", device="cnc", action="cycle_start", program_id=program_id)
        if program_id != self.program_id:
            raise SafeStop("program_mismatch", f"{program_id} != loaded {self.program_id}")
        self.w.spindle_running, self.w.axes_at_exchange, self.w.cycle_done = True, False, False

    def run_cycle(self, seconds):
        if self.w.faults.get("cnc_alarm"):
            self.w.t += seconds / 3
            self.w.alarm, self.w.spindle_running = True, False
            return
        if self.w.faults.get("timeout"):
            self.w.t += seconds                        # expected time passes, completion never arrives
            return
        self.w.t += seconds
        self.w.spindle_running, self.w.cycle_done = False, True
        self.w.vise_holds = self.w.vise_holds.replace("blank", "finished") if self.w.vise_holds else None


class FakeVise:
    def __init__(self, w: World, log):
        self.w, self.log = w, log

    def clamp(self, close):
        self.log("command", device="vise", action="clamp" if close else "unclamp")
        self.w.t += 1.5
        if close and self.w.faults.get("clamp_disagreement"):
            return
        self.w.clamped = close


# ---------------------------------------------------------------- orchestrator

class Orchestrator:
    TIMEOUT = {"door": 10.0, "clamp": 5.0, "exchange": 20.0}

    def __init__(self, job: dict, plan: dict, faults: dict | None = None, physical: bool = False):
        if physical:
            raise PhysicalCommandPathDisabled("no physical robot or CNC command path exists in this build (PRD section 14)")
        self.job, self.plan = job, plan
        self.events, self.state, self.seq, self.jaw = [], "IDLE", 0, None
        self.run_permission = True
        self.w = World(faults=dict(faults or {}))
        slots = job["slots"]
        self.w.rack = {s: f"{side}_blank" for side, s in slots.items()}
        self.inventory = {f"{side}": f"rack:{s}" for side, s in slots.items()}
        for side, s in slots.items():
            for seg in plan["jaws"][side]["segments"]:
                self.w.moves[(seg["from"], seg["to"])] = seg["duration_s"]
        self.w.outside = set(plan["outside_waypoints"])
        self.robot, self.vise = FakeRobot(self.w, self.log), FakeVise(self.w, self.log)
        self.cnc = FakeCnc(self.w, self.log, job["program_id"])

    # ------------------------------------------------------------ logging
    def log(self, kind, **data):
        self.seq += 1
        w = self.w
        snap = {"robot_at": w.robot_at, "holding": w.holding, "door_open": w.door_open, "spindle": w.spindle_running,
                "clamped": w.clamped, "vise_holds": w.vise_holds, "alarm": w.alarm, "rack": {str(k): v for k, v in w.rack.items()}}
        self.events.append({"seq": self.seq, "t": round(w.t, 2), "type": kind, "state": self.state,
                            "jaw": self.jaw, **data, "world": snap})

    def enter(self, state, jaw=None):
        if jaw:
            self.jaw = jaw
        self.log("transition", frm=self.state, to=state)
        self.state = state

    def expect(self, cond, cause, detail, timeout=0.0):
        """Wait for a sensor condition; any disagreement or timeout is a SAFE_STOP."""
        if not cond():
            self.w.t += timeout
            if not cond():
                raise SafeStop(cause, detail)
        self.log("confirm", check=cause)

    # ------------------------------------------------------------ guards
    def guard_robot_entry(self):                                   # CTL-005
        self.expect(lambda: not self.w.spindle_running, "spindle_not_stopped", "spindle running at robot entry", self.TIMEOUT["exchange"])
        self.expect(lambda: self.w.axes_at_exchange, "axes_not_at_exchange", "axes not at exchange pose", self.TIMEOUT["exchange"])
        self.expect(lambda: self.w.door_open, "door_disagreement", "door-open not confirmed", self.TIMEOUT["door"])

    def guard_cycle_start(self):                                   # CTL-004
        self.expect(self.robot.outside_machine, "robot_not_clear", "robot inside protected volume")
        self.expect(lambda: not self.w.door_open, "door_disagreement", "door-closed not confirmed", self.TIMEOUT["door"])
        self.expect(lambda: self.w.clamped, "clamp_disagreement", "fixture clamp not confirmed", self.TIMEOUT["clamp"])

    # ------------------------------------------------------------ run
    def run(self):
        if not self.run_permission:
            raise RuntimeError("run permission removed by SAFE_STOP; operator recovery required")
        try:
            self._run()
        except CommsLost as e:
            self._safe_stop("comms_loss", str(e))
        except SafeStop as e:
            self._safe_stop(e.cause, e.detail)
        return self.result()

    def _run(self):
        job = self.job
        self.enter("JOB_VALIDATED")
        if job["release_status"] == "blocked":
            raise SafeStop("job_blocked", "jaw design failed validation")
        self.log("confirm", check="job validated", release_status=job["release_status"], program_id=job["program_id"])
        for side in ("left", "right"):
            slot = job["slots"][side]
            blank, finished = f"{side}_blank", f"{side}_finished"

            self.enter("PICK_BLANK", side)
            for wp in ("rack_above", "rack_grasp"):
                self.robot.move(wp)
            self.robot.grip(True, blank)
            self.w.rack[slot] = None
            self.inventory[side] = "gripper"
            self.robot.move("rack_above")

            self.enter("VERIFY_GRIP", side)
            self.expect(self.robot.sensor_holding, "lost_grip", "gripper possession sensor false after pick")

            self.enter("REQUEST_LOAD", side)
            self.cnc.request_exchange()
            self.vise.clamp(False)

            self.enter("DOOR_OPEN_CONFIRMED", side)
            self.cnc.door(True)
            self.guard_robot_entry()

            self.enter("LOAD_BLANK", side)
            for wp in ("home", "door_transit", "vise_above", "vise_place"):
                self.robot.move(wp)
                self.expect(self.robot.sensor_holding, "lost_grip", f"payload lost moving to {wp}")

            self.enter("FIXTURE_CLAMPED_CONFIRMED", side)
            self.vise.clamp(True)
            self.expect(lambda: self.w.clamped, "clamp_disagreement", "clamp sensor did not confirm", self.TIMEOUT["clamp"])
            self.robot.grip(False)
            self.w.vise_holds = blank
            self.inventory[side] = "vise"

            self.enter("ROBOT_CLEAR_CONFIRMED", side)
            for wp in ("vise_above", "door_transit", "home"):
                self.robot.move(wp)
            self.expect(self.robot.outside_machine, "robot_not_clear", "robot not confirmed outside")

            self.enter("DOOR_CLOSED_CONFIRMED", side)
            self.cnc.door(False)

            program = job.get("programs", {}).get(side, job["program_id"])
            cycle_s = job.get("cycle_times", {}).get(side, job["cycle_time_s"])
            if program != self.cnc.program_id:                     # per-side programs: load this jaw's program
                self.log("command", device="cnc", action="load_program", program_id=program)
                self.cnc.program_id = program
            self.enter("CNC_CYCLE", side)
            self.guard_cycle_start()
            self.cnc.cycle_start(program)
            self.cnc.run_cycle(cycle_s)

            self.enter("CYCLE_COMPLETE", side)
            self.expect(lambda: not self.w.alarm, "cnc_alarm", "CNC alarm active")
            self.expect(lambda: self.w.cycle_done, "timeout", "cycle complete not received", cycle_s * 0.5)

            self.enter("SPINDLE_ZERO_CONFIRMED", side)
            self.cnc.request_exchange()
            self.expect(lambda: not self.w.spindle_running, "spindle_not_stopped", "spindle still running", self.TIMEOUT["exchange"])

            self.enter("DOOR_OPEN_CONFIRMED", side)
            self.cnc.door(True)
            self.guard_robot_entry()

            self.enter("UNCLAMP", side)
            for wp in ("home", "door_transit", "vise_above_finished", "vise_grasp_finished"):
                self.robot.move(wp)
            self.robot.grip(True, finished)
            self.vise.clamp(False)
            self.expect(lambda: not self.w.clamped, "clamp_disagreement", "vise did not open", self.TIMEOUT["clamp"])

            self.enter("PICK_FINISHED_JAW", side)
            self.expect(self.robot.sensor_holding, "lost_grip", "finished jaw not in gripper")
            self.w.vise_holds = None
            self.inventory[side] = "gripper"
            self.robot.move("vise_above_finished")

            self.enter("RETURN_TO_RACK", side)
            if self.w.faults.get("occupied_slot"):
                self.w.rack[slot] = "unexpected_object"
            for wp in ("door_transit", "home", "rack_above_finished"):
                self.robot.move(wp)
            self.expect(lambda: self.w.rack[slot] is None, "occupied_slot", f"rack slot {slot} occupied")
            self.robot.move("rack_place_finished")
            self.robot.grip(False)
            self.w.rack[slot] = finished
            self.inventory[side] = f"rack:{slot}:finished"
            for wp in ("rack_above_finished", "home"):
                self.robot.move(wp)
        self.cnc.door(False)
        self.enter("COMPLETE")

    def _safe_stop(self, cause, detail):
        self.log("fault", cause=cause, detail=detail)
        for side, loc in self.inventory.items():   # CTL-006: anything in motion is now unknown
            if loc == "gripper":
                self.inventory[side] = "unknown"
        self.enter("SAFE_STOP")
        self.run_permission = False

    def operator_recover(self, operator: str, inventory_confirmed: dict):
        """CTL-003: explicit recovery. Never resumes the interrupted motion."""
        if self.state != "SAFE_STOP":
            raise RuntimeError("recovery only applies in SAFE_STOP")
        if any(v == "unknown" for v in {**self.inventory, **inventory_confirmed}.values()):
            raise RuntimeError("every jaw location must be confirmed by the operator")
        self.inventory.update(inventory_confirmed)
        self.log("recovery", operator=operator, inventory=dict(self.inventory))
        self.enter("IDLE")
        self.run_permission = False     # a new, explicit run request is still required

    def result(self):
        return {"final_state": self.state, "sim_time_s": round(self.w.t, 2), "inventory": dict(self.inventory),
                "rack": dict(self.w.rack), "events": self.events}


def build_job(manifest: dict, slots=None, cycle_time_s=240.0):
    """Cell job from a jaw manifest. Simulation accepts provisional jaws; blocked jaws never run."""
    return {"job_id": manifest["job_id"], "release_status": manifest["release_status"],
            "program_id": "O" + manifest["job_id"].upper().replace("-", "")[:8],
            "slots": slots or {"left": 0, "right": 1}, "cycle_time_s": cycle_time_s,
            "grasp_y": {s: manifest["jaws"][s]["robot"]["finger_grasp_y_wcs"] for s in ("left", "right")}}
