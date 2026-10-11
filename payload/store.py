"""
Local database (SQLite). Migrations are append-only, so any app version can
open data written by an older one, and updates never rewrite existing rows.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

MIGRATIONS = [
    # 1 — the original web version (crew hail findings + crew-drawn areas). Old databases open as-is.
    """
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, lat REAL NOT NULL, lng REAL NOT NULL, size_in REAL NOT NULL,
        obs_date TEXT, hood TEXT, address TEXT, notes TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS hoods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, size_in REAL NOT NULL, geojson TEXT NOT NULL, created TEXT);
    """,
    # 2 — weather module: places, territories, inspection candidates, alerts, notices, crew sign-offs, settings
    """
    CREATE TABLE IF NOT EXISTS places (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK (kind IN ('job', 'property')),
        name TEXT NOT NULL, address TEXT, lat REAL NOT NULL, lng REAL NOT NULL,
        precision TEXT, located_by TEXT, tz TEXT, notes TEXT, created TEXT,
        nws_zone TEXT, nws_county TEXT, nws_fire_zone TEXT, zones_checked TEXT,
        roof_system TEXT, product TEXT, phase TEXT, work_date TEXT,
        duration_h REAL, dryin_h REAL, site_checks TEXT, rules TEXT);
    CREATE TABLE IF NOT EXISTS territories (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, geojson TEXT NOT NULL, created TEXT);
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
        event_key TEXT NOT NULL, event_label TEXT, tier INTEGER,
        reasons TEXT NOT NULL, evidence TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'not_contacted', rep TEXT, notes TEXT, created TEXT, updated TEXT,
        UNIQUE (place_id, event_key));
    CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY, status TEXT, data TEXT NOT NULL, first_seen TEXT, last_seen TEXT);
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, dedupe_key TEXT NOT NULL UNIQUE, kind TEXT,
        title TEXT, body TEXT, created TEXT, read INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
        work_date TEXT NOT NULL, outlook TEXT, reviewer TEXT NOT NULL, decision TEXT, note TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS acks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
        work_date TEXT NOT NULL, crew_member TEXT NOT NULL, created TEXT);
    CREATE TABLE IF NOT EXISTS outlook_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
        work_date TEXT NOT NULL, status TEXT NOT NULL, summary TEXT, observed_at TEXT);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
]

CANDIDATE_STATUSES = [("not_contacted", "Not contacted"), ("scheduled", "Scheduled"),
                      ("inspected", "Inspected"), ("completed", "Completed")]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self.conn() as c:
            have = c.execute("PRAGMA user_version").fetchone()[0]
            for number, sql in enumerate(MIGRATIONS[have:], start=have + 1):
                c.executescript(sql)
                c.execute(f"PRAGMA user_version = {number}")

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def _all(self, sql, args=()):
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        rows = self._all(sql, args)
        return rows[0] if rows else None

    def _run(self, sql, args=()):
        with self.conn() as c:
            cur = c.execute(sql, args)
            return cur.lastrowid, cur.rowcount

    def schema(self) -> int:
        with self.conn() as c:
            return c.execute("PRAGMA user_version").fetchone()[0]

    # ---------------- settings ----------------
    def setting(self, key, default=None):
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return default
        try:
            value = json.loads(row["value"])
        except ValueError:
            return default
        return {**default, **value} if isinstance(default, dict) and isinstance(value, dict) else value

    def set_setting(self, key, value):
        self._run("INSERT INTO settings (key, value) VALUES (?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    # ---------------- crew inspection findings (evidence kind: inspection) ----------------
    def findings(self):
        return self._all("SELECT * FROM reports ORDER BY obs_date DESC, id DESC")

    def add_finding(self, lat, lng, size_in, obs_date, hood, address, notes):
        self._run("INSERT INTO reports (lat,lng,size_in,obs_date,hood,address,notes,created) VALUES (?,?,?,?,?,?,?,?)",
                  (lat, lng, size_in, obs_date, hood, address, notes, now_iso()))

    def delete_finding(self, rid):
        self._run("DELETE FROM reports WHERE id=?", (rid,))

    def areas(self):
        return self._all("SELECT * FROM hoods ORDER BY id DESC")

    def add_area(self, name, size_in, geometry):
        self._run("INSERT INTO hoods (name,size_in,geojson,created) VALUES (?,?,?,?)",
                  (name, size_in, json.dumps(geometry), now_iso()))

    def delete_area(self, aid):
        self._run("DELETE FROM hoods WHERE id=?", (aid,))

    # ---------------- places and territories ----------------
    def places(self, kind=None):
        if kind:
            return self._all("SELECT * FROM places WHERE kind=? ORDER BY name COLLATE NOCASE", (kind,))
        return self._all("SELECT * FROM places ORDER BY kind, name COLLATE NOCASE")

    def place(self, pid):
        return self._one("SELECT * FROM places WHERE id=?", (pid,))

    def add_place(self, kind, name, address, lat, lng, precision, located_by, notes=""):
        rid, _ = self._run("INSERT INTO places (kind,name,address,lat,lng,precision,located_by,notes,created) "
                           "VALUES (?,?,?,?,?,?,?,?,?)",
                           (kind, name, address, lat, lng, precision, located_by, notes, now_iso()))
        return rid

    def set_place_tz(self, pid, tz):
        self._run("UPDATE places SET tz=? WHERE id=?", (tz, pid))

    def set_place_codes(self, pid, zone, county, fire_zone, tz):
        self._run("UPDATE places SET nws_zone=?, nws_county=?, nws_fire_zone=?, tz=COALESCE(?, tz), zones_checked=? "
                  "WHERE id=?", (zone, county, fire_zone, tz, now_iso(), pid))

    def places_needing_codes(self, max_age_days=30):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        return self._all("SELECT * FROM places WHERE zones_checked IS NULL OR zones_checked < ?", (cutoff,))

    def update_job(self, pid, roof_system, product, phase, work_date, duration_h, dryin_h, site_checks, rules: dict):
        self._run("UPDATE places SET roof_system=?, product=?, phase=?, work_date=?, duration_h=?, dryin_h=?, "
                  "site_checks=?, rules=? WHERE id=?",
                  (roof_system, product, phase, work_date, duration_h, dryin_h, site_checks,
                   json.dumps({k: v for k, v in rules.items() if v is not None}), pid))

    # ---------------- outlook change log (what changed, and what was known when) ----------------
    def log_outlook(self, pid, work_date, status, summary):
        """Record a job's outlook only when it changes. Returns the previous entry if it changed."""
        prev = self._one("SELECT * FROM outlook_log WHERE place_id=? AND work_date=? ORDER BY id DESC LIMIT 1",
                         (pid, work_date))
        if prev is None or prev["status"] != status:
            self._run("INSERT INTO outlook_log (place_id,work_date,status,summary,observed_at) VALUES (?,?,?,?,?)",
                      (pid, work_date, status, summary, now_iso()))
            return prev
        return None

    def outlook_history(self, pid, work_date, limit=6):
        return self._all("SELECT * FROM outlook_log WHERE place_id=? AND work_date=? ORDER BY id DESC LIMIT ?",
                         (pid, work_date, limit))

    def delete_place(self, pid):
        self._run("DELETE FROM places WHERE id=?", (pid,))

    def territories(self):
        return self._all("SELECT * FROM territories ORDER BY name COLLATE NOCASE")

    def add_territory(self, name, geometry):
        self._run("INSERT INTO territories (name,geojson,created) VALUES (?,?,?)",
                  (name, json.dumps(geometry), now_iso()))

    def delete_territory(self, tid):
        self._run("DELETE FROM territories WHERE id=?", (tid,))

    # ---------------- inspection candidates ----------------
    def upsert_candidate(self, place_id, event_key, event_label, tier, reasons, evidence, demo) -> bool:
        """Adding the same place for the same event twice refreshes the evidence
        snapshot but never duplicates the candidate or resets its status."""
        with self.conn() as c:
            exists = c.execute("SELECT 1 FROM candidates WHERE place_id=? AND event_key=?",
                               (place_id, event_key)).fetchone()
            c.execute(
                "INSERT INTO candidates (place_id,event_key,event_label,tier,reasons,evidence,demo,created,updated) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(place_id, event_key) DO UPDATE SET "
                "tier=excluded.tier, reasons=excluded.reasons, evidence=excluded.evidence, updated=excluded.updated",
                (place_id, event_key, event_label, tier, json.dumps(reasons), json.dumps(evidence),
                 1 if demo else 0, now_iso(), now_iso()))
        return exists is None

    def candidates(self, status=None):
        sql = ("SELECT c.*, p.name AS place_name, p.kind AS place_kind, p.address AS place_address, "
               "p.lat AS place_lat, p.lng AS place_lng, p.precision AS place_precision, p.tz AS place_tz "
               "FROM candidates c JOIN places p ON p.id = c.place_id")
        rows = self._all(sql + (" WHERE c.status=?" if status else "") +
                         " ORDER BY COALESCE(c.tier, 9), c.updated DESC", (status,) if status else ())
        for r in rows:
            r["reasons"], r["evidence"] = json.loads(r["reasons"]), json.loads(r["evidence"])
        return rows

    def candidate(self, cid):
        rows = [r for r in self.candidates() if r["id"] == cid]
        return rows[0] if rows else None

    def update_candidate(self, cid, status, rep, notes):
        if status not in dict(CANDIDATE_STATUSES):
            raise ValueError("unknown status")
        self._run("UPDATE candidates SET status=?, rep=?, notes=?, updated=? WHERE id=?",
                  (status, rep, notes, now_iso(), cid))

    def delete_candidate(self, cid):
        self._run("DELETE FROM candidates WHERE id=?", (cid,))

    # ---------------- official alerts (reconciled records) ----------------
    def load_alerts(self) -> dict:
        return {r["id"]: json.loads(r["data"]) for r in self._all("SELECT id, data FROM alerts")}

    def save_alerts(self, records: dict):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with self.conn() as c:
            for aid, rec in records.items():
                c.execute("INSERT INTO alerts (id,status,data,first_seen,last_seen) VALUES (?,?,?,?,?) "
                          "ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data, "
                          "last_seen=excluded.last_seen",
                          (aid, rec.get("status"), json.dumps(rec), rec.get("first_seen"), rec.get("last_seen")))
            c.execute("DELETE FROM alerts WHERE status != 'active' AND last_seen < ?", (cutoff,))

    # ---------------- notices (deduplicated storm matches) ----------------
    def add_notice(self, dedupe_key, kind, title, body) -> bool:
        _, n = self._run("INSERT OR IGNORE INTO notices (dedupe_key,kind,title,body,created) VALUES (?,?,?,?,?)",
                         (dedupe_key, kind, title, body, now_iso()))
        return n == 1

    def notices(self, limit=30):
        return self._all("SELECT * FROM notices ORDER BY id DESC LIMIT ?", (limit,))

    def unread_notices(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM notices WHERE read=0")["n"]

    def mark_notices_read(self):
        self._run("UPDATE notices SET read=1 WHERE read=0")

    # ---------------- crew outlook sign-offs ----------------
    def add_review(self, place_id, work_date, outlook, reviewer, decision, note):
        self._run("INSERT INTO reviews (place_id,work_date,outlook,reviewer,decision,note,created) "
                  "VALUES (?,?,?,?,?,?,?)", (place_id, work_date, outlook, reviewer, decision, note, now_iso()))

    def add_ack(self, place_id, work_date, crew_member):
        self._run("INSERT INTO acks (place_id,work_date,crew_member,created) VALUES (?,?,?,?)",
                  (place_id, work_date, crew_member, now_iso()))

    def signoffs(self, place_id, work_date):
        return (self._all("SELECT * FROM reviews WHERE place_id=? AND work_date=? ORDER BY id DESC", (place_id, work_date)),
                self._all("SELECT * FROM acks WHERE place_id=? AND work_date=? ORDER BY id DESC", (place_id, work_date)))

    def counts(self) -> dict:
        with self.conn() as c:
            q = lambda t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
            return {"findings": q("reports"), "areas": q("hoods"), "places": q("places"),
                    "territories": q("territories"), "candidates": q("candidates")}
