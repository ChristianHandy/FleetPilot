"""FleetPilot audit logging.

Stores a concise, append-only record of security-relevant state changes without
recording request bodies, passwords, SSH keys, tokens, or command output.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
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

# Every event is also written to this logger (journald/syslog), so it can be
# forwarded to a SIEM or a remote log host outside FleetPilot's control.
_siem = logging.getLogger("fleetpilot.audit")

# Hash chain fields, in a fixed order.
_CHAIN_FIELDS = ("occurred_at", "actor_id", "actor", "event_type", "target", "outcome", "remote_addr", "metadata_json")


def _chain_key() -> bytes:
    return hashlib.sha256(b"fleetpilot-audit-chain:" + os.environ.get("SECRET_KEY", "").encode()).digest()


def _entry_hash(prev_hash: str, row) -> str:
    """HMAC-SHA256 over the previous hash and this event; changing or removing any event breaks the chain."""
    canonical = json.dumps([prev_hash] + [row[f] for f in _CHAIN_FIELDS], ensure_ascii=False, separators=(",", ":"))
    return hmac.new(_chain_key(), canonical.encode(), hashlib.sha256).hexdigest()


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
        columns = {r[1] for r in db.execute("PRAGMA table_info(audit_events)")}
        for column in ("prev_hash", "entry_hash"):
            if column not in columns:
                db.execute(f"ALTER TABLE audit_events ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


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
    row = {
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor_id": actor_id, "actor": safe_actor, "event_type": safe_event, "target": safe_target,
        "outcome": safe_outcome, "remote_addr": safe_addr, "metadata_json": payload,
    }
    db = _connect()
    try:
        db.execute("BEGIN IMMEDIATE")  # serialise writers so the chain stays linear
        last = db.execute("SELECT entry_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last[0] if last else ""
        entry_hash = _entry_hash(prev_hash, row)
        db.execute(
            """INSERT INTO audit_events
               (occurred_at, actor_id, actor, event_type, target, outcome, remote_addr, metadata_json,
                prev_hash, entry_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(row[f] for f in _CHAIN_FIELDS) + (prev_hash, entry_hash),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    _siem.info(json.dumps(dict(row, entry_hash=entry_hash), ensure_ascii=False, separators=(",", ":")))


def verify_chain() -> dict[str, Any]:
    """Check that no audit event was changed, inserted or removed.

    The oldest remaining event is trusted as the anchor, because pruning removes
    events from the start. Returns {"ok", "checked", "first_bad_id"}.
    """
    expected_prev = None
    checked = 0
    with _connect() as db:
        for event in db.execute("SELECT * FROM audit_events WHERE entry_hash != '' ORDER BY id"):
            if expected_prev is not None and event["prev_hash"] != expected_prev:
                return {"ok": False, "checked": checked, "first_bad_id": event["id"]}
            if not hmac.compare_digest(event["entry_hash"], _entry_hash(event["prev_hash"], event)):
                return {"ok": False, "checked": checked, "first_bad_id": event["id"]}
            expected_prev = event["entry_hash"]
            checked += 1
    return {"ok": True, "checked": checked, "first_bad_id": None}


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
