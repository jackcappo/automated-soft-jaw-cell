"""SQLite storage for the shop app. One connection shared across threads behind a lock."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jaw_sets (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, part_number TEXT DEFAULT '',
  description TEXT DEFAULT '', program_mode TEXT DEFAULT 'per_side',      -- per_side | shared
  location TEXT DEFAULT '', made_count INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, jaw_set_id INTEGER NOT NULL, side TEXT DEFAULT 'both', filename TEXT, stored TEXT,
  sha256 TEXT, size INTEGER, uploaded_at TEXT);
CREATE TABLE IF NOT EXISTS nc_programs (
  id INTEGER PRIMARY KEY, jaw_set_id INTEGER NOT NULL, side TEXT NOT NULL, filename TEXT, stored TEXT, sha256 TEXT,
  program_number TEXT, source TEXT, uploaded_at TEXT, analysis TEXT, check_status TEXT,
  review_status TEXT DEFAULT 'pending', reviewed_by TEXT, reviewed_at TEXT, review_note TEXT);
CREATE TABLE IF NOT EXISTS production_jobs (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, part_number TEXT DEFAULT '', customer TEXT DEFAULT '',
  quantity INTEGER, need_by TEXT, jaw_set_id INTEGER, status TEXT DEFAULT 'planned', notes TEXT DEFAULT '',
  created_at TEXT);
CREATE TABLE IF NOT EXISTS downtime (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, start TEXT, end TEXT, days TEXT, start_time TEXT, end_time TEXT,
  label TEXT DEFAULT '', enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, jaw_set_id INTEGER NOT NULL, status TEXT NOT NULL, trigger TEXT, need_by TEXT,
  priority INTEGER DEFAULT 0, fault TEXT, slots TEXT, programs TEXT, created_at TEXT, started_at TEXT, finished_at TEXT,
  est_duration_s REAL, sim_duration_s REAL, state TEXT, jaw TEXT, progress REAL DEFAULT 0, result TEXT, error TEXT,
  world TEXT, recovered_by TEXT, note TEXT DEFAULT '', sim_t REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS run_events (run_id INTEGER, seq INTEGER, t REAL, type TEXT, state TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS run_events_run ON run_events (run_id, seq);
CREATE TABLE IF NOT EXISTS rack (slot INTEGER PRIMARY KEY, content TEXT DEFAULT 'empty', jaw_set_id INTEGER, side TEXT,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, at TEXT, kind TEXT, message TEXT, jaw_set_id INTEGER,
  run_id INTEGER);
"""

JSON_COLS = {"analysis", "slots", "programs", "result", "world", "data"}


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class Store:
    def __init__(self, path: Path, rack_slots: int = 6):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            cols = {r[1] for r in self.db.execute("PRAGMA table_info(runs)")}
            if "sim_t" not in cols:                     # added after the first release of the schema
                self.db.execute("ALTER TABLE runs ADD COLUMN sim_t REAL DEFAULT 0")
            for s in range(rack_slots):
                self.db.execute("INSERT OR IGNORE INTO rack (slot, content, updated_at) VALUES (?, 'empty', ?)", (s, now_iso()))
            self.db.commit()

    @staticmethod
    def _row(r):
        if r is None:
            return None
        d = dict(r)
        for k in JSON_COLS & d.keys():
            if d[k]:
                d[k] = json.loads(d[k])
        return d

    def all(self, sql, args=()):
        with self.lock:
            return [self._row(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            return self._row(self.db.execute(sql, args).fetchone())

    def run(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    def insert(self, table, **cols):
        cols = {k: json.dumps(v) if k in JSON_COLS and v is not None else v for k, v in cols.items()}
        return self.run(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))

    def update(self, table, row_id, key="id", **cols):
        if not cols:
            return
        cols = {k: json.dumps(v) if k in JSON_COLS and v is not None else v for k, v in cols.items()}
        self.run(f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in cols)} WHERE {key} = ?", (*cols.values(), row_id))

    def get(self, table, row_id, key="id"):
        return self.one(f"SELECT * FROM {table} WHERE {key} = ?", (row_id,))

    def setting(self, key, default=None):
        r = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(r["value"]) if r else default

    def set_setting(self, key, value):
        self.run("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))

    def log(self, kind, message, jaw_set_id=None, run_id=None):
        self.insert("activity", at=now_iso(), kind=kind, message=message, jaw_set_id=jaw_set_id, run_id=run_id)
