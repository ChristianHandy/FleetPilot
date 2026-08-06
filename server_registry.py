"""
server_registry.py — Central Server Registry for FleetPilot

This module provides a single source of truth for all configured servers.
When a server is added anywhere in FleetPilot (Update Manager, HW Monitor,
Fan Control, Backup, VM Controller, etc.), it is automatically available
in all other modules.

Usage:
    from server_registry import get_registry
    reg = get_registry(data_dir)

    # List all servers
    servers = reg.list_servers()

    # Get a server by ID or name
    srv = reg.get_server(id=1)
    srv = reg.get_server(name="pve03")

    # Add or update a server
    reg.upsert_server(name="pve03", host="192.168.1.52", user="root",
                      password="secret", port=22, tags=["proxmox"])

    # Register a module's use of a server
    reg.register_module(server_id=1, module="hw_monitor", module_id=3)

    # Get all servers registered for a module
    servers = reg.get_servers_for_module("hw_monitor")
"""

import sqlite3
import json
import os
import threading
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

_instances: Dict[str, "ServerRegistry"] = {}
_lock = threading.Lock()


def get_registry(data_dir: str) -> "ServerRegistry":
    """Get or create the singleton registry for a given data directory."""
    with _lock:
        if data_dir not in _instances:
            _instances[data_dir] = ServerRegistry(data_dir)
        return _instances[data_dir]


class ServerRegistry:
    """Central registry for all servers configured in FleetPilot."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS servers (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        host        TEXT NOT NULL,
        port        INTEGER DEFAULT 22,
        user        TEXT DEFAULT 'root',
        password    TEXT DEFAULT '',
        ssh_key     TEXT DEFAULT '',
        os_type     TEXT DEFAULT 'linux',
        description TEXT DEFAULT '',
        location    TEXT DEFAULT '',
        environment TEXT DEFAULT 'Production',
        criticality TEXT DEFAULT 'Medium',
        tags        TEXT DEFAULT '[]',
        mac         TEXT DEFAULT '',
        notes       TEXT DEFAULT '',
        online      INTEGER DEFAULT 0,
        last_seen   TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS server_modules (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id   INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
        module      TEXT NOT NULL,
        module_id   INTEGER,
        enabled     INTEGER DEFAULT 1,
        config      TEXT DEFAULT '{}',
        UNIQUE(server_id, module)
    );

    CREATE INDEX IF NOT EXISTS idx_servers_host ON servers(host);
    CREATE INDEX IF NOT EXISTS idx_server_modules_module ON server_modules(module);
    """

    def __init__(self, data_dir: str):
        self._db_path = os.path.join(data_dir, "server_registry.db")
        self._local = threading.local()
        self._init_db()
        logger.info(f"[ServerRegistry] Initialized at {self._db_path}")

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def upsert_server(self, name: str, host: str, **kwargs) -> int:
        """Add or update a server. Returns the server ID."""
        tags = kwargs.pop('tags', [])
        if isinstance(tags, list):
            tags = json.dumps(tags)

        now = datetime.utcnow().isoformat()
        conn = self._conn()

        existing = conn.execute(
            "SELECT id FROM servers WHERE name=? OR host=?", (name, host)
        ).fetchone()

        if existing:
            sid = existing['id']
            fields = {k: v for k, v in kwargs.items()
                      if k in ('port','user','password','ssh_key','os_type',
                               'description','location','environment','criticality',
                               'mac','notes','online','last_seen')}
            fields['tags'] = tags
            fields['updated_at'] = now
            if 'name' not in fields:
                fields['name'] = name
            if 'host' not in fields:
                fields['host'] = host
            sets = ', '.join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE servers SET {sets} WHERE id=?",
                         list(fields.values()) + [sid])
        else:
            conn.execute("""
                INSERT INTO servers
                    (name, host, port, user, password, ssh_key, os_type,
                     description, location, environment, criticality, tags,
                     mac, notes, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                name, host,
                kwargs.get('port', 22),
                kwargs.get('user', 'root'),
                kwargs.get('password', ''),
                kwargs.get('ssh_key', ''),
                kwargs.get('os_type', 'linux'),
                kwargs.get('description', ''),
                kwargs.get('location', ''),
                kwargs.get('environment', 'Production'),
                kwargs.get('criticality', 'Medium'),
                tags,
                kwargs.get('mac', ''),
                kwargs.get('notes', ''),
                now, now
            ))
            sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.commit()
        logger.info(f"[ServerRegistry] Upserted server '{name}' (id={sid})")
        return sid

    def get_server(self, id: int = None, name: str = None,
                   host: str = None) -> Optional[Dict]:
        """Get a server by id, name, or host."""
        conn = self._conn()
        if id is not None:
            row = conn.execute("SELECT * FROM servers WHERE id=?", (id,)).fetchone()
        elif name is not None:
            row = conn.execute("SELECT * FROM servers WHERE name=?", (name,)).fetchone()
        elif host is not None:
            row = conn.execute("SELECT * FROM servers WHERE host=?", (host,)).fetchone()
        else:
            return None
        return self._row_to_dict(row) if row else None

    def list_servers(self, module: str = None, online_only: bool = False) -> List[Dict]:
        """List all servers, optionally filtered by module or online status."""
        conn = self._conn()
        if module:
            rows = conn.execute("""
                SELECT s.* FROM servers s
                JOIN server_modules sm ON sm.server_id = s.id
                WHERE sm.module=? AND sm.enabled=1
                ORDER BY s.name
            """, (module,)).fetchall()
        elif online_only:
            rows = conn.execute(
                "SELECT * FROM servers WHERE online=1 ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM servers ORDER BY name").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_server(self, id: int):
        """Delete a server and all its module registrations."""
        conn = self._conn()
        conn.execute("DELETE FROM servers WHERE id=?", (id,))
        conn.commit()
        logger.info(f"[ServerRegistry] Deleted server id={id}")

    def update_online_status(self, id: int, online: bool):
        """Update the online status and last_seen timestamp."""
        conn = self._conn()
        conn.execute(
            "UPDATE servers SET online=?, last_seen=? WHERE id=?",
            (1 if online else 0, datetime.utcnow().isoformat(), id)
        )
        conn.commit()

    # ── Module Registration ────────────────────────────────────────────────────

    def register_module(self, server_id: int, module: str,
                        module_id: int = None, config: dict = None):
        """Register that a module is using a server."""
        conn = self._conn()
        conn.execute("""
            INSERT INTO server_modules (server_id, module, module_id, config)
            VALUES (?,?,?,?)
            ON CONFLICT(server_id, module) DO UPDATE SET
                module_id=excluded.module_id,
                config=excluded.config,
                enabled=1
        """, (server_id, module, module_id, json.dumps(config or {})))
        conn.commit()

    def unregister_module(self, server_id: int, module: str):
        """Remove a module registration for a server."""
        conn = self._conn()
        conn.execute(
            "DELETE FROM server_modules WHERE server_id=? AND module=?",
            (server_id, module)
        )
        conn.commit()

    def get_modules_for_server(self, server_id: int) -> List[Dict]:
        """Get all modules registered for a server."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM server_modules WHERE server_id=? AND enabled=1",
            (server_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_servers_for_module(self, module: str) -> List[Dict]:
        """Get all servers registered for a specific module."""
        return self.list_servers(module=module)

    # ── Import from existing configs ──────────────────────────────────────────

    def import_from_hosts_json(self, hosts_json_path: str) -> int:
        """Import servers from the legacy hosts.json file."""
        if not os.path.exists(hosts_json_path):
            return 0
        try:
            with open(hosts_json_path) as f:
                hosts = json.load(f)
        except Exception as e:
            logger.error(f"[ServerRegistry] Failed to read hosts.json: {e}")
            return 0

        count = 0
        for name, data in hosts.items():
            try:
                self.upsert_server(
                    name=name,
                    host=data.get('host', ''),
                    port=int(data.get('port', 22)),
                    user=data.get('user', 'root'),
                    ssh_key=data.get('ssh_key', ''),
                    description=data.get('description', ''),
                    location=data.get('location', ''),
                    environment=data.get('environment', 'Production'),
                    criticality=data.get('criticality', 'Medium'),
                    tags=data.get('tags', []),
                    mac=data.get('mac', ''),
                    notes=data.get('notes', ''),
                    os_type='linux',
                )
                self.register_module(
                    server_id=self.get_server(name=name)['id'],
                    module='update_manager'
                )
                count += 1
            except Exception as e:
                logger.warning(f"[ServerRegistry] Failed to import host '{name}': {e}")

        logger.info(f"[ServerRegistry] Imported {count} servers from hosts.json")
        return count

    def import_from_hw_monitor_db(self, hw_db_path: str) -> int:
        """Import servers from hw_monitor.db."""
        if not os.path.exists(hw_db_path):
            return 0
        try:
            conn = sqlite3.connect(hw_db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM servers").fetchall()
            conn.close()
        except Exception as e:
            logger.error(f"[ServerRegistry] Failed to read hw_monitor.db: {e}")
            return 0

        count = 0
        for row in rows:
            try:
                sid = self.upsert_server(
                    name=row['name'],
                    host=row['host'],
                    port=int(row.get('port') or 22),
                    user=row.get('username') or row.get('user') or 'root',
                    password=row.get('password') or '',
                    ssh_key=row.get('ssh_key') or '',
                    os_type='linux',
                )
                self.register_module(sid, 'hw_monitor', module_id=row['id'])
                count += 1
            except Exception as e:
                logger.warning(f"[ServerRegistry] Failed to import hw_monitor server: {e}")

        logger.info(f"[ServerRegistry] Imported {count} servers from hw_monitor.db")
        return count

    def import_from_fan_controller_db(self, fan_db_path: str) -> int:
        """Import servers from fan_controller.db."""
        if not os.path.exists(fan_db_path):
            return 0
        try:
            conn = sqlite3.connect(fan_db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM fc_devices").fetchall()
            conn.close()
        except Exception as e:
            logger.error(f"[ServerRegistry] Failed to read fan_controller.db: {e}")
            return 0

        count = 0
        for row in rows:
            try:
                sid = self.upsert_server(
                    name=row['name'],
                    host=row['host'],
                    port=int(row.get('port') or 22),
                    user=row.get('username') or 'root',
                    password=row.get('password') or '',
                    ssh_key=row.get('ssh_key') or '',
                    os_type='linux',
                )
                self.register_module(sid, 'fan_control', module_id=row['id'])
                count += 1
            except Exception as e:
                logger.warning(f"[ServerRegistry] Failed to import fan_controller server: {e}")

        logger.info(f"[ServerRegistry] Imported {count} servers from fan_controller.db")
        return count

    def import_from_backup_db(self, backup_db_path: str) -> int:
        """Import servers from backup_controller.db."""
        if not os.path.exists(backup_db_path):
            return 0
        try:
            conn = sqlite3.connect(backup_db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM bc_servers").fetchall()
            conn.close()
        except Exception as e:
            logger.error(f"[ServerRegistry] Failed to read backup_controller.db: {e}")
            return 0

        count = 0
        for row in rows:
            try:
                host = row.get('host') or row.get('url') or ''
                # Strip protocol from URL if needed
                if '://' in host:
                    host = host.split('://', 1)[1].split('/')[0].split(':')[0]
                sid = self.upsert_server(
                    name=row['name'],
                    host=host,
                    port=int(row.get('port') or 22),
                    user=row.get('username') or row.get('user') or 'root',
                    password=row.get('password') or '',
                    ssh_key=row.get('ssh_key') or '',
                    os_type='linux',
                )
                self.register_module(sid, 'backup', module_id=row['id'])
                count += 1
            except Exception as e:
                logger.warning(f"[ServerRegistry] Failed to import backup server: {e}")

        logger.info(f"[ServerRegistry] Imported {count} servers from backup_controller.db")
        return count

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _row_to_dict(self, row) -> Dict:
        d = dict(row)
        try:
            d['tags'] = json.loads(d.get('tags') or '[]')
        except Exception:
            d['tags'] = []
        return d

    def to_hosts_json_format(self) -> Dict:
        """Convert registry to hosts.json format for backward compatibility."""
        result = {}
        for srv in self.list_servers():
            result[srv['name']] = {
                'host': srv['host'],
                'port': srv['port'],
                'user': srv['user'],
                'mac': srv.get('mac', ''),
                'description': srv.get('description', ''),
                'notes': srv.get('notes', ''),
                'group': '',
                'location': srv.get('location', ''),
                'environment': srv.get('environment', 'Production'),
                'criticality': srv.get('criticality', 'Medium'),
                'tags': srv.get('tags', []),
                'ssh_key': srv.get('ssh_key', ''),
                'os_profiles': [],
            }
        return result

    def stats(self) -> Dict:
        """Return registry statistics."""
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
        online = conn.execute("SELECT COUNT(*) FROM servers WHERE online=1").fetchone()[0]
        modules = conn.execute(
            "SELECT module, COUNT(*) as cnt FROM server_modules GROUP BY module"
        ).fetchall()
        return {
            'total_servers': total,
            'online_servers': online,
            'modules': {r['module']: r['cnt'] for r in modules},
        }
