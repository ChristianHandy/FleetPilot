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


def _filters(actor=None, event_type=None, outcome=None, since=None, search=None):
    where, args = [], []
    if actor:
        where.append("actor = ?")
        args.append(actor)
    if event_type:
        where.append("event_type LIKE ? ESCAPE '\\'")
        args.append(event_type.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if outcome:
        where.append("outcome = ?")
        args.append(outcome)
    if since:
        where.append("occurred_at >= ?")
        args.append(since)
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(target LIKE ? ESCAPE '\\' OR remote_addr LIKE ? ESCAPE '\\' OR actor LIKE ? ESCAPE '\\')")
        args += [like, like, like]
    return (" WHERE " + " AND ".join(where)) if where else "", args


def list_events(limit: int = 100, **filters) -> Iterable[sqlite3.Row]:
    """Newest events first. Filters: actor, event_type (prefix), outcome, since (ISO), search."""
    limit = max(1, min(int(limit), 500))
    where, args = _filters(**filters)
    with _connect() as db:
        return db.execute(
            "SELECT * FROM audit_events" + where + " ORDER BY id DESC LIMIT ?", args + [limit]
        ).fetchall()


def iter_events(**filters):
    """Every matching event, oldest first, for export."""
    where, args = _filters(**filters)
    with _connect() as db:
        yield from db.execute("SELECT * FROM audit_events" + where + " ORDER BY id", args)


def event_types() -> list[str]:
    with _connect() as db:
        return [r[0] for r in db.execute("SELECT DISTINCT event_type FROM audit_events ORDER BY event_type")]


def count_events(**filters) -> int:
    where, args = _filters(**filters)
    with _connect() as db:
        return db.execute("SELECT COUNT(*) FROM audit_events" + where, args).fetchone()[0]


def prune(retention_days: int) -> int:
    """Delete events older than ``retention_days``. Returns the number removed."""
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, int(retention_days)) * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat(timespec="seconds")
    with _connect() as db:
        return db.execute("DELETE FROM audit_events WHERE occurred_at < ?", (cutoff_iso,)).rowcount


def iso_hours_ago(hours: float) -> str:
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - hours * 3600,
                                  timezone.utc).isoformat(timespec="seconds")


def health() -> dict[str, Any]:
    with _connect() as db:
        count = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        latest = db.execute(
            "SELECT occurred_at FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {"events": count, "latest": latest[0] if latest else None, "path": str(DB_PATH)}
