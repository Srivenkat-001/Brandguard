"""SQLite persistence: brand profiles, detections (with analyst status) and scan runs."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .detect import Detection
from .profile import BrandProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
    name TEXT PRIMARY KEY, profile_json TEXT NOT NULL, base_dir TEXT DEFAULT '.', updated REAL);
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT, brand TEXT, kind TEXT, source TEXT, platform TEXT, ref TEXT,
    title TEXT, url TEXT, score INTEGER, level TEXT, reasons_json TEXT, evidence_json TEXT,
    status TEXT DEFAULT 'new', first_seen REAL, last_seen REAL,
    UNIQUE (brand, kind, platform, ref));
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, brand TEXT, started REAL, summary_json TEXT, sources_json TEXT);
"""


class Store:
    def __init__(self, path: str | Path = "brandguard.db"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------- brands
    def save_brand(self, b: BrandProfile) -> None:
        self.db.execute("INSERT INTO brands(name, profile_json, base_dir, updated) VALUES(?,?,?,?) "
                        "ON CONFLICT(name) DO UPDATE SET profile_json=excluded.profile_json, "
                        "base_dir=excluded.base_dir, updated=excluded.updated",
                        (b.name, json.dumps(b.to_dict()), b.base_dir, time.time()))
        self.db.commit()

    def list_brands(self) -> list[str]:
        return [r["name"] for r in self.db.execute("SELECT name FROM brands ORDER BY name")]

    def load_brand(self, name: str) -> BrandProfile | None:
        r = self.db.execute("SELECT * FROM brands WHERE name=?", (name,)).fetchone()
        return BrandProfile.from_dict(json.loads(r["profile_json"]), r["base_dir"]) if r else None

    # --------------------------------------------------------- detections
    def upsert_detection(self, brand: str, d: Detection) -> bool:
        """Insert or refresh a detection. Returns True if it is new. Analyst status is preserved."""
        now = time.time()
        row = self.db.execute("SELECT id FROM detections WHERE brand=? AND kind=? AND platform=? AND ref=?",
                              (brand, d.kind, d.platform, d.ref)).fetchone()
        payload = (d.source, d.title, d.url, d.score, d.level,
                   json.dumps(d.reasons), json.dumps(d.evidence), now)
        if row:
            self.db.execute("UPDATE detections SET source=?, title=?, url=?, score=?, level=?, "
                            "reasons_json=?, evidence_json=?, last_seen=? WHERE id=?", (*payload, row["id"]))
            self.db.commit()
            return False
        self.db.execute("INSERT INTO detections(brand, kind, platform, ref, source, title, url, score, level, "
                        "reasons_json, evidence_json, last_seen, first_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (brand, d.kind, d.platform, d.ref, *payload, now))
        self.db.commit()
        return True

    def detections(self, brand: str, kind: str | None = None, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM detections WHERE brand=?", [brand]
        if kind:
            q += " AND kind=?"; args.append(kind)
        if status:
            q += " AND status=?"; args.append(status)
        out = []
        for r in self.db.execute(q + " ORDER BY score DESC, id", args):
            d = dict(r)
            d["reasons"] = json.loads(d.pop("reasons_json"))
            d["evidence"] = json.loads(d.pop("evidence_json"))
            out.append(d)
        return out

    def set_status(self, det_id: int, status: str) -> None:
        self.db.execute("UPDATE detections SET status=? WHERE id=?", (status, det_id))
        self.db.commit()

    def clear_detections(self, brand: str) -> None:
        self.db.execute("DELETE FROM detections WHERE brand=?", (brand,))
        self.db.commit()

    # ---------------------------------------------------------- scan runs
    def log_run(self, brand: str, summary: dict, sources: list[dict]) -> None:
        self.db.execute("INSERT INTO scan_runs(brand, started, summary_json, sources_json) VALUES(?,?,?,?)",
                        (brand, time.time(), json.dumps(summary), json.dumps(sources)))
        self.db.commit()

    def last_run(self, brand: str) -> dict | None:
        r = self.db.execute("SELECT * FROM scan_runs WHERE brand=? ORDER BY id DESC LIMIT 1", (brand,)).fetchone()
        if not r:
            return None
        return {"started": r["started"], "summary": json.loads(r["summary_json"]),
                "sources": json.loads(r["sources_json"])}
