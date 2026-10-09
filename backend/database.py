"""
ChronoForge — SQLite persistence layer.

Tables
------
schedules       : one row per saved timetable version
schedule_items  : rows belonging to a schedule (period/start/end/label/tone)
system_logs     : activity / audit log
configuration   : simple key-value settings store (ESP32 IP, port, etc.)
"""

import sqlite3
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chronoforge.db")

_lock = threading.RLock()  # reentrant: some functions call other locked functions internally

DEFAULT_CONFIG = {
    "esp32_host": "192.168.1.100",
    "esp32_port": "80",
    "esp32_timeout_seconds": "3",
    "bell_test_duration_seconds": "2",
    "mock_mode": "true",  # default to mock mode until a real ESP32 is configured
}


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't already exist and seed default config."""
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                source_filename TEXT,
                created_at TEXT NOT NULL,
                dispatched_at TEXT,
                status TEXT NOT NULL DEFAULT 'draft'  -- draft | active | archived
            );

            CREATE TABLE IF NOT EXISTS schedule_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                label TEXT NOT NULL,
                tone TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',  -- info | warning | error | success
                event TEXT NOT NULL,
                details TEXT
            );

            CREATE TABLE IF NOT EXISTS configuration (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        for key, value in DEFAULT_CONFIG.items():
            conn.execute(
                "INSERT OR IGNORE INTO configuration (key, value) VALUES (?, ?)",
                (key, value),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_config() -> Dict[str, str]:
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT key, value FROM configuration").fetchall()
        return {r["key"]: r["value"] for r in rows}


def update_config(updates: Dict[str, str]) -> Dict[str, str]:
    with _lock, _connect() as conn:
        for key, value in updates.items():
            conn.execute(
                "INSERT INTO configuration (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
        conn.commit()
        rows = conn.execute("SELECT key, value FROM configuration").fetchall()
        return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def add_log(event: str, details: str = "", level: str = "info") -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO system_logs (timestamp, level, event, details) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), level, event, details),
        )
        conn.commit()


def get_logs(limit: int = 100) -> List[Dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM system_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

def create_schedule(items: List[Dict], source_filename: Optional[str] = None,
                     status: str = "draft") -> Dict:
    """
    Insert a new schedule version + its items.
    The previous 'active' schedule (if any) is archived, not deleted.
    """
    with _lock, _connect() as conn:
        row = conn.execute("SELECT MAX(version) AS v FROM schedules").fetchone()
        next_version = (row["v"] or 0) + 1

        if status == "active":
            conn.execute(
                "UPDATE schedules SET status = 'archived' WHERE status = 'active'"
            )

        cur = conn.execute(
            "INSERT INTO schedules (version, source_filename, created_at, status) "
            "VALUES (?, ?, ?, ?)",
            (next_version, source_filename, datetime.now().isoformat(timespec="seconds"), status),
        )
        schedule_id = cur.lastrowid

        for idx, item in enumerate(items):
            conn.execute(
                "INSERT INTO schedule_items (schedule_id, period, start, end, label, tone, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (schedule_id, str(item.get("period", "")), item["start"], item["end"],
                 item.get("label", ""), item.get("tone", "Short Ring"), idx),
            )
        conn.commit()
        return get_schedule_by_id(schedule_id)


def get_schedule_by_id(schedule_id: int) -> Optional[Dict]:
    with _lock, _connect() as conn:
        srow = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if not srow:
            return None
        items = conn.execute(
            "SELECT * FROM schedule_items WHERE schedule_id = ? ORDER BY sort_order ASC",
            (schedule_id,),
        ).fetchall()
        result = dict(srow)
        result["items"] = [dict(i) for i in items]
        return result


def get_active_schedule() -> Optional[Dict]:
    with _lock, _connect() as conn:
        srow = conn.execute(
            "SELECT * FROM schedules WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not srow:
            # fall back to the most recent draft so the UI has something to show
            srow = conn.execute(
                "SELECT * FROM schedules ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not srow:
            return None
        items = conn.execute(
            "SELECT * FROM schedule_items WHERE schedule_id = ? ORDER BY sort_order ASC",
            (srow["id"],),
        ).fetchall()
        result = dict(srow)
        result["items"] = [dict(i) for i in items]
        return result


def list_schedules(limit: int = 25) -> List[Dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def mark_schedule_dispatched(schedule_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute("UPDATE schedules SET status = 'archived' WHERE status = 'active'")
        conn.execute(
            "UPDATE schedules SET status = 'active', dispatched_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), schedule_id),
        )
        conn.commit()


def update_schedule_items(schedule_id: int, items: List[Dict]) -> Dict:
    """Replace the item rows of an existing (draft) schedule."""
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM schedule_items WHERE schedule_id = ?", (schedule_id,))
        for idx, item in enumerate(items):
            conn.execute(
                "INSERT INTO schedule_items (schedule_id, period, start, end, label, tone, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (schedule_id, str(item.get("period", "")), item["start"], item["end"],
                 item.get("label", ""), item.get("tone", "Short Ring"), idx),
            )
        conn.commit()
        return get_schedule_by_id(schedule_id)
