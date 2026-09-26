"""Machine downtime windows and fitting queued cell runs into them.

A downtime window is time the Haas is not needed for production, so the cell may use it.
Windows are one-off (start/end) or weekly (days + clock times, may cross midnight). Times
are the shop PC's local time, stored as ISO strings.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

FMT = "%Y-%m-%dT%H:%M:%S"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def iso(d: datetime) -> str:
    return d.strftime(FMT)


def expand(windows: list[dict], start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
    """All enabled windows overlapping [start, end), clipped and merged, in time order."""
    out = []
    for w in windows:
        if not w.get("enabled", 1):
            continue
        if w["kind"] == "once":
            s, e = parse(w["start"]), parse(w["end"])
            if e > start and s < end:
                out.append((max(s, start), min(e, end), w.get("label") or ""))
            continue
        days = {int(d) for d in str(w["days"]).split(",") if d.strip() != ""}
        t0, t1 = time.fromisoformat(w["start_time"]), time.fromisoformat(w["end_time"])
        d = (start - timedelta(days=1)).date()
        while d <= end.date():
            if d.weekday() in days:
                s = datetime.combine(d, t0)
                e = datetime.combine(d if t1 > t0 else d + timedelta(days=1), t1)
                if e > start and s < end:
                    out.append((max(s, start), min(e, end), w.get("label") or ""))
            d += timedelta(days=1)
    out.sort()
    merged = []
    for s, e, label in out:
        if merged and s <= merged[-1][1]:
            ps, pe, pl = merged[-1]
            merged[-1] = (ps, max(pe, e), pl if pl == label or not label else f"{pl} + {label}" if pl else label)
        else:
            merged.append((s, e, label))
    return merged


def current_window(windows, now: datetime):
    for s, e, label in expand(windows, now, now + timedelta(days=2)):
        if s <= now < e:
            return s, e, label
    return None


def project(queue: list[dict], windows: list[dict], now: datetime, busy_until: datetime | None = None,
            horizon_days: int = 14) -> dict:
    """Earliest start for each queued run (in queue order), each needing est_duration_s inside one window."""
    spans = expand(windows, now, now + timedelta(days=horizon_days))
    cursor = max(now, busy_until) if busy_until else now
    out = {}
    for run in queue:
        need = timedelta(seconds=float(run.get("est_duration_s") or 900))
        start = None
        for s, e, _ in spans:
            t = max(s, cursor)
            if t + need <= e:
                start = t
                break
        out[run["id"]] = {"start": iso(start) if start else None, "end": iso(start + need) if start else None}
        if start:
            cursor = start + need
    return out


def describe(w: dict) -> str:
    if w["kind"] == "once":
        s, e = parse(w["start"]), parse(w["end"])
        return f"{s:%a %d %b %H:%M} - {e:%a %d %b %H:%M}"
    days = [DAYS[int(d)] for d in str(w["days"]).split(",") if d.strip() != ""]
    return f"{', '.join(days) or 'no days'} {w['start_time']}-{w['end_time']}"
