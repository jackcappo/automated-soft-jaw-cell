"""Versioned data profiles (CFG-001, CFG-002).

Fit-critical numbers are stored as {"value": x, "status": s}. Status is one of
published / measured / verified / estimated / assumed. Anything assumed or
estimated is tracked so a job can be generated for review but is blocked from
production release (CFG-003).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUSTED = {"published", "measured", "verified"}


def load_json(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["_path"] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    data["_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return data


class Tracker:
    """Reads values out of profiles and remembers which ones are unverified."""

    def __init__(self):
        self.unverified: list[dict] = []

    def get(self, profile: dict, *keys, default=None):
        node = profile
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                if default is not None:
                    return default
                raise KeyError(f"{profile.get('_path', profile.get('id'))}: missing {'.'.join(keys)}")
            node = node[k]
        if isinstance(node, dict) and "value" in node:
            status = node.get("status", "unspecified")
            if status not in TRUSTED:
                self.unverified.append({"profile": profile.get("_path", profile.get("id")),
                                        "field": ".".join(keys), "value": node["value"], "status": status})
            return node["value"]
        return node


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
