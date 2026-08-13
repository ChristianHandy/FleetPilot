"""FleetPilot audit logging.

Stores a concise, append-only record of security-relevant state changes without
recording request bodies, passwords, SSH keys, tokens, or command output.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _data_dir() -> Path:
    path = Path(os.environ.get("FLEETPILOT_DATA_DIR", Path(__file__).parent / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = _data_dir() / "audit_log.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                actor_id INTEGER,
                actor TEXT NOT NULL DEFAULT 'anonymous',
                event_type TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL,
                remote_addr TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at
              ON audit_events(occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_events_actor
              ON audit_events(actor);
            CREATE INDEX IF NOT EXISTS idx_audit_events_event_type
              ON audit_events(event_type);
            """
        )


def record_event(
    *,
    actor_id: int | None,
    actor: str | None,
    event_type: str,
    target: str = "",
    outcome: str = "success",
    remote_addr: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record an auditable event.

    Metadata is intentionally whitelisted by the caller and truncated before it
    is persisted.  Never pass form data or secrets here.
    """
    safe_event = str(event_type)[:120]
    safe_target = str(target)[:300]
    safe_outcome = str(outcome)[:40]
    safe_actor = str(actor or "anonymous")[:120]
    safe_addr = str(remote_addr or "")[:80]
    try:
        payload = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))[:2000]
    except (TypeError, ValueError):
        payload = "{}"
    with _connect() as db:
        db.execute(
            """INSERT INTO audit_events
               (occurred_at, actor_id, actor, event_type, target, outcome, remote_addr, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                actor_id,
                safe_actor,
                safe_event,
                safe_target,
                safe_outcome,
                safe_addr,
                payload,
            ),
        )


def list_events(limit: int = 100) -> Iterable[sqlite3.Row]:
    limit = max(1, min(int(limit), 500))
    with _connect() as db:
        return db.execute(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def health() -> dict[str, Any]:
    with _connect() as db:
        count = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        latest = db.execute(
            "SELECT occurred_at FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {"events": count, "latest": latest[0] if latest else None, "path": str(DB_PATH)}
