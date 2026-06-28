"""
backup_controller.py — FleetPilot Universal Backup Server Integration

Supports the following backup server types:

  TYPE          PROTOCOL        USE CASE
  ─────────────────────────────────────────────────────────────────────────
  pbs           REST API        Proxmox Backup Server (HTTPS, API token)
  duplicati     REST API        Duplicati (HTTP, password/token, port 8200)
  restic        REST API        Restic REST-Server (HTTP, basic auth)
  borgwarehouse  REST API       BorgWarehouse (HTTP, Bearer token)
  bacula        SSH + bconsole  Bacula Community (SSH to Director)
  urbackup      REST API        UrBackup Server (HTTP, user/pass)
  ssh_generic   SSH             Any backup tool via SSH (restic, borg, etc.)

Architecture:
  FleetPilot (Unraid) ──HTTP/SSH──▶ Backup Server ──▶ Job status / snapshots

Database: DATA_DIR/backup_controller.db
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# ── Encryption helpers ────────────────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet
    _SECRET = os.environ.get("SECRET_KEY", "").encode()
    if len(_SECRET) >= 32:
        import base64
        _FKEY = Fernet(base64.urlsafe_b64encode(_SECRET[:32]))
        def _encrypt(s: str) -> str:
            return _FKEY.encrypt(s.encode()).decode()
        def _decrypt(s: str) -> str:
            return _FKEY.decrypt(s.encode()).decode()
    else:
        raise ValueError("key too short")
except Exception:
    def _encrypt(s: str) -> str: return s
    def _decrypt(s: str) -> str: return s

# ── Server type registry ──────────────────────────────────────────────────────

SERVER_TYPES: Dict[str, Dict] = {
    "pbs": {
        "label": "Proxmox Backup Server",
        "icon": "🟠",
        "description": "Proxmox Backup Server — REST API over HTTPS. Monitors datastores, backup jobs, tasks, and snapshots.",
        "default_port": 8007,
        "auth": "api_token",  # PBSAPIToken: USER@REALM!TOKENID=SECRET
        "protocol": "https",
        "docs_url": "https://pbs.proxmox.com/docs/api-viewer/",
    },
    "duplicati": {
        "label": "Duplicati",
        "icon": "🔵",
        "description": "Duplicati backup client — REST API on port 8200. Monitors backup jobs, triggers runs, views logs.",
        "default_port": 8200,
        "auth": "password",
        "protocol": "http",
        "docs_url": "https://docs.duplicati.com/",
    },
    "restic": {
        "label": "Restic REST-Server",
        "icon": "🟢",
        "description": "Restic REST-Server — HTTP backend for restic. Lists repositories and snapshots.",
        "default_port": 8000,
        "auth": "basic",
        "protocol": "http",
        "docs_url": "https://github.com/restic/rest-server",
    },
    "borgwarehouse": {
        "label": "BorgWarehouse",
        "icon": "🟣",
        "description": "BorgWarehouse — Web UI for BorgBackup. REST API with Bearer token. Lists repositories and status.",
        "default_port": 3000,
        "auth": "bearer",
        "protocol": "http",
        "docs_url": "https://borgwarehouse.com/docs/developer-manual/api/",
    },
    "urbackup": {
        "label": "UrBackup",
        "icon": "🔴",
        "description": "UrBackup Server — REST API with session-based auth. Monitors clients, backup jobs, and file/image backups.",
        "default_port": 55414,
        "auth": "userpass",
        "protocol": "http",
        "docs_url": "https://www.urbackup.org/",
    },
    "bacula": {
        "label": "Bacula (bconsole via SSH)",
        "icon": "⚫",
        "description": "Bacula Community — SSH to Director host, runs bconsole commands. Lists jobs, volumes, and clients.",
        "default_port": 22,
        "auth": "ssh",
        "protocol": "ssh",
        "docs_url": "https://www.bacula.org/",
    },
    "ssh_generic": {
        "label": "Generic SSH Backup",
        "icon": "⚙",
        "description": "Any backup tool accessible via SSH (restic CLI, borg CLI, rsync, etc.). Run custom status commands.",
        "default_port": 22,
        "auth": "ssh",
        "protocol": "ssh",
        "docs_url": "",
    },
}

# ── SSH helper ────────────────────────────────────────────────────────────────

def _ssh_run(host: str, port: int, username: str, password: str,
             ssh_key: str, command: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a command on a remote host via SSH. Returns (returncode, stdout, stderr)."""
    try:
        import paramiko
    except ImportError:
        return 1, "", "paramiko not installed"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs: Dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": timeout,
            "banner_timeout": 30,
            "auth_timeout": 20,
        }
        if ssh_key:
            import io
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(ssh_key))
            connect_kwargs["pkey"] = pkey
            connect_kwargs["look_for_keys"] = False
        elif password:
            connect_kwargs["password"] = password
            connect_kwargs["look_for_keys"] = False
        client.connect(**connect_kwargs)
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err
    except Exception as e:
        return 1, "", str(e)
    finally:
        client.close()

# ── Database ──────────────────────────────────────────────────────────────────

_DB_PATH: Optional[Path] = None
_db_lock = threading.Lock()


def init_db(data_dir: str) -> None:
    global _DB_PATH
    _DB_PATH = Path(data_dir) / "backup_controller.db"
    with _db_lock:
        conn = sqlite3.connect(str(_DB_PATH))
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS backup_servers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                server_type TEXT NOT NULL,
                host        TEXT NOT NULL,
                port        INTEGER NOT NULL DEFAULT 8007,
                protocol    TEXT NOT NULL DEFAULT 'https',
                username    TEXT,
                password    TEXT,
                api_token   TEXT,
                ssh_key     TEXT,
                verify_ssl  INTEGER NOT NULL DEFAULT 0,
                use_sudo    INTEGER NOT NULL DEFAULT 0,
                notes       TEXT,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                last_poll   TEXT,
                last_status TEXT DEFAULT 'unknown'
            );
            CREATE TABLE IF NOT EXISTS _bc_migrations(name TEXT PRIMARY KEY);

            CREATE TABLE IF NOT EXISTS backup_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id   INTEGER NOT NULL,
                job_id      TEXT,
                job_name    TEXT,
                job_type    TEXT,
                status      TEXT,
                last_run    TEXT,
                next_run    TEXT,
                duration_s  INTEGER,
                size_bytes  INTEGER,
                files_count INTEGER,
                error_msg   TEXT,
                raw_json    TEXT,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES backup_servers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS backup_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id   INTEGER NOT NULL,
                repo        TEXT,
                snapshot_id TEXT,
                hostname    TEXT,
                timestamp   TEXT,
                size_bytes  INTEGER,
                tags        TEXT,
                raw_json    TEXT,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES backup_servers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS backup_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id   INTEGER NOT NULL,
                ts          TEXT NOT NULL DEFAULT (datetime('now')),
                jobs_ok     INTEGER DEFAULT 0,
                jobs_warn   INTEGER DEFAULT 0,
                jobs_error  INTEGER DEFAULT 0,
                jobs_total  INTEGER DEFAULT 0,
                FOREIGN KEY (server_id) REFERENCES backup_servers(id) ON DELETE CASCADE
            );
        """)
        conn.commit()
        # Migration: add use_sudo if missing
        try:
            conn.execute("ALTER TABLE backup_servers ADD COLUMN use_sudo INTEGER NOT NULL DEFAULT 0")
            conn.execute("INSERT OR IGNORE INTO _bc_migrations VALUES ('add_use_sudo')")
            conn.commit()
        except Exception:
            pass
        conn.close()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

# ── CRUD ──────────────────────────────────────────────────────────────────────

def add_server(name: str, server_type: str, host: str, port: int,
               protocol: str, username: str = "", password: str = "",
               api_token: str = "", ssh_key: str = "",
               verify_ssl: bool = False, use_sudo: bool = False, notes: str = "") -> int:
    with _db_lock:
        conn = _db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO backup_servers
              (name, server_type, host, port, protocol, username, password,
               api_token, ssh_key, verify_ssl, use_sudo, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (name, server_type, host, port, protocol,
              username,
              _encrypt(password) if password else "",
              _encrypt(api_token) if api_token else "",
              _encrypt(ssh_key) if ssh_key else "",
              int(verify_ssl), int(use_sudo), notes))
        conn.commit()
        new_id = c.lastrowid
        conn.close()
    return new_id


def update_server(server_id: int, **kwargs) -> None:
    allowed = {"name", "server_type", "host", "port", "protocol", "username",
               "password", "api_token", "ssh_key", "verify_ssl", "use_sudo", "notes", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if "password" in updates and updates["password"]:
        updates["password"] = _encrypt(updates["password"])
    if "api_token" in updates and updates["api_token"]:
        updates["api_token"] = _encrypt(updates["api_token"])
    if "ssh_key" in updates and updates["ssh_key"]:
        updates["ssh_key"] = _encrypt(updates["ssh_key"])
    if not updates:
        return
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [server_id]
    with _db_lock:
        conn = _db()
        conn.execute(f"UPDATE backup_servers SET {set_clause} WHERE id=?", values)
        conn.commit()
        conn.close()


def delete_server(server_id: int) -> None:
    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_servers WHERE id=?", (server_id,))
        conn.commit()
        conn.close()


def get_server(server_id: int) -> Optional[Dict]:
    conn = _db()
    row = conn.execute("SELECT * FROM backup_servers WHERE id=?", (server_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["password"] = _decrypt(d["password"]) if d.get("password") else ""
    d["api_token"] = _decrypt(d["api_token"]) if d.get("api_token") else ""
    d["ssh_key"] = _decrypt(d["ssh_key"]) if d.get("ssh_key") else ""
    return d


def list_servers() -> List[Dict]:
    conn = _db()
    rows = conn.execute("SELECT * FROM backup_servers ORDER BY name").fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d.pop("password", None)
        d.pop("api_token", None)
        d.pop("ssh_key", None)
        result.append(d)
    return result


def get_jobs(server_id: int) -> List[Dict]:
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM backup_jobs WHERE server_id=? ORDER BY last_run DESC",
        (server_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshots(server_id: int, limit: int = 50) -> List[Dict]:
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM backup_snapshots WHERE server_id=? ORDER BY timestamp DESC LIMIT ?",
        (server_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_history(server_id: int, hours: int = 24) -> List[Dict]:
    conn = _db()
    rows = conn.execute(
        """SELECT * FROM backup_history WHERE server_id=?
           AND ts >= datetime('now', ?)
           ORDER BY ts ASC""",
        (server_id, f"-{hours} hours")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Polling ───────────────────────────────────────────────────────────────────

_poll_threads: Dict[int, threading.Thread] = {}
_poll_stop: Dict[int, threading.Event] = {}
POLL_INTERVAL = 120  # seconds


def start_polling(server_id: int) -> None:
    if server_id in _poll_threads and _poll_threads[server_id].is_alive():
        return
    stop_ev = threading.Event()
    _poll_stop[server_id] = stop_ev
    t = threading.Thread(target=_poll_loop, args=(server_id, stop_ev), daemon=True)
    _poll_threads[server_id] = t
    t.start()


def stop_polling(server_id: int) -> None:
    if server_id in _poll_stop:
        _poll_stop[server_id].set()


def start_all_polling() -> None:
    if _DB_PATH is None:
        return
    conn = _db()
    rows = conn.execute("SELECT id FROM backup_servers WHERE enabled=1").fetchall()
    conn.close()
    for row in rows:
        start_polling(row["id"])


def _poll_loop(server_id: int, stop_ev: threading.Event) -> None:
    time.sleep(5)
    while not stop_ev.is_set():
        try:
            poll_server(server_id)
        except Exception as e:
            logger.warning(f"[backup] poll error server {server_id}: {e}")
        stop_ev.wait(POLL_INTERVAL)


def poll_server(server_id: int) -> Dict:
    """Poll a backup server and update the database. Returns status dict."""
    srv = get_server(server_id)
    if not srv:
        return {"ok": False, "error": "Server not found"}

    stype = srv["server_type"]
    try:
        if stype == "pbs":
            result = _poll_pbs(srv)
        elif stype == "duplicati":
            result = _poll_duplicati(srv)
        elif stype == "restic":
            result = _poll_restic(srv)
        elif stype == "borgwarehouse":
            result = _poll_borgwarehouse(srv)
        elif stype == "urbackup":
            result = _poll_urbackup(srv)
        elif stype == "bacula":
            result = _poll_bacula(srv)
        elif stype == "ssh_generic":
            result = _poll_ssh_generic(srv)
        else:
            result = {"ok": False, "error": f"Unknown server type: {stype}"}
    except Exception as e:
        result = {"ok": False, "error": str(e)}

    # Update last_poll and last_status
    status_str = "ok" if result.get("ok") else "error"
    with _db_lock:
        conn = _db()
        conn.execute(
            "UPDATE backup_servers SET last_poll=datetime('now'), last_status=? WHERE id=?",
            (status_str, server_id)
        )
        conn.commit()
        conn.close()

    return result

# ── PBS ───────────────────────────────────────────────────────────────────────

def _pbs_session(srv: Dict) -> requests.Session:
    sess = requests.Session()
    sess.verify = bool(srv.get("verify_ssl"))
    token = srv.get("api_token", "")
    if token:
        # Format: USER@REALM!TOKENID=SECRET
        if "=" in token:
            token_id, secret = token.split("=", 1)
            sess.headers["Authorization"] = f"PBSAPIToken={token_id}:{secret}"
        else:
            sess.headers["Authorization"] = f"PBSAPIToken={token}"
    elif srv.get("username") and srv.get("password"):
        # Password auth — get ticket
        base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
        try:
            r = sess.post(f"{base}/api2/json/access/ticket",
                          data={"username": srv["username"], "password": srv["password"]},
                          timeout=10)
            if r.ok:
                data = r.json().get("data", {})
                sess.headers["CSRFPreventionToken"] = data.get("CSRFPreventionToken", "")
                sess.cookies.set("PBSAuthCookie", data.get("ticket", ""))
        except Exception:
            pass
    return sess


def _poll_pbs(srv: Dict) -> Dict:
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}/api2/json"
    sess = _pbs_session(srv)
    jobs_ok = jobs_warn = jobs_error = 0

    # Get datastores
    try:
        r = sess.get(f"{base}/nodes/localhost/storage", timeout=15)
        datastores = r.json().get("data", []) if r.ok else []
    except Exception:
        datastores = []

    # Get tasks (recent backup tasks)
    try:
        r = sess.get(f"{base}/nodes/localhost/tasks",
                     params={"limit": 50, "typefilter": "backup"},
                     timeout=15)
        tasks = r.json().get("data", []) if r.ok else []
    except Exception:
        tasks = []

    # Get backup jobs config
    try:
        r = sess.get(f"{base}/config/sync", timeout=15)
        sync_jobs = r.json().get("data", []) if r.ok else []
    except Exception:
        sync_jobs = []

    # Get backup schedules
    try:
        r = sess.get(f"{base}/config/backup", timeout=15)
        backup_jobs_cfg = r.json().get("data", []) if r.ok else []
    except Exception:
        backup_jobs_cfg = []

    # Store jobs from tasks
    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_jobs WHERE server_id=?", (srv["id"],))
        for task in tasks[:30]:
            status = task.get("status", "")
            if status == "OK":
                jobs_ok += 1
                st = "ok"
            elif "error" in status.lower() or "failed" in status.lower():
                jobs_error += 1
                st = "error"
            else:
                jobs_warn += 1
                st = "warning"
            conn.execute("""
                INSERT INTO backup_jobs
                  (server_id, job_id, job_name, job_type, status, last_run,
                   duration_s, error_msg, raw_json)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                srv["id"],
                task.get("upid", ""),
                task.get("id", task.get("upid", "")[:20]),
                task.get("type", "backup"),
                st,
                _epoch_to_iso(task.get("starttime")),
                task.get("duration"),
                task.get("status") if st != "ok" else None,
                json.dumps(task),
            ))

        # Store snapshots from datastores
        conn.execute("DELETE FROM backup_snapshots WHERE server_id=?", (srv["id"],))
        for ds in datastores:
            ds_id = ds.get("storage", "")
            try:
                r2 = sess.get(f"{base}/nodes/localhost/storage/{ds_id}/snapshots",
                              timeout=15)
                snaps = r2.json().get("data", []) if r2.ok else []
                for snap in snaps[:20]:
                    conn.execute("""
                        INSERT INTO backup_snapshots
                          (server_id, repo, snapshot_id, hostname, timestamp,
                           size_bytes, tags, raw_json)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (
                        srv["id"], ds_id,
                        snap.get("backup-id", ""),
                        snap.get("backup-id", ""),
                        _epoch_to_iso(snap.get("backup-time")),
                        snap.get("size"),
                        snap.get("backup-type", ""),
                        json.dumps(snap),
                    ))
            except Exception:
                pass

        # History
        conn.execute("""
            INSERT INTO backup_history
              (server_id, jobs_ok, jobs_warn, jobs_error, jobs_total)
            VALUES (?,?,?,?,?)
        """, (srv["id"], jobs_ok, jobs_warn, jobs_error, jobs_ok + jobs_warn + jobs_error))
        conn.commit()
        conn.close()

    return {"ok": True, "jobs_ok": jobs_ok, "jobs_warn": jobs_warn, "jobs_error": jobs_error}

# ── Duplicati ─────────────────────────────────────────────────────────────────

def _duplicati_auth(srv: Dict) -> Optional[str]:
    """Get a Duplicati auth token. Returns token string or None."""
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
    password = srv.get("password", "")
    if not password:
        return None
    try:
        # Get nonce
        r = requests.get(f"{base}/api/v1/auth/issignin", timeout=10, verify=False)
        if not r.ok:
            return None
        nonce_data = r.json()
        nonce = nonce_data.get("Nonce", "")
        salt = nonce_data.get("Salt", "")
        # Hash password
        import hashlib, base64
        salted = base64.b64decode(salt) + password.encode()
        pwd_hash = base64.b64encode(hashlib.sha256(salted).digest()).decode()
        nonce_bytes = base64.b64decode(nonce)
        nonced = nonce_bytes + base64.b64decode(pwd_hash)
        final_hash = base64.b64encode(hashlib.sha256(nonced).digest()).decode()
        # Sign in
        r2 = requests.post(f"{base}/api/v1/auth/signin",
                           json={"Password": final_hash},
                           timeout=10, verify=False)
        if r2.ok:
            return r2.json().get("Token")
    except Exception as e:
        logger.debug(f"Duplicati auth error: {e}")
    return None


def _poll_duplicati(srv: Dict) -> Dict:
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
    token = srv.get("api_token") or _duplicati_auth(srv)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    jobs_ok = jobs_warn = jobs_error = 0

    try:
        r = requests.get(f"{base}/api/v1/backups",
                         headers=headers, timeout=15, verify=False)
        backups = r.json() if r.ok else []
    except Exception as e:
        return {"ok": False, "error": str(e)}

    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_jobs WHERE server_id=?", (srv["id"],))
        for bk in backups:
            bk_id = str(bk.get("Backup", {}).get("ID", ""))
            bk_name = bk.get("Backup", {}).get("Name", "")
            last_result = bk.get("Backup", {}).get("Metadata", {}).get("LastBackupDate", "")
            last_duration = bk.get("Backup", {}).get("Metadata", {}).get("LastBackupDuration", "")
            last_size = bk.get("Backup", {}).get("Metadata", {}).get("SourceFilesSize", 0)
            last_files = bk.get("Backup", {}).get("Metadata", {}).get("SourceFilesCount", 0)

            # Get last result
            try:
                r2 = requests.get(f"{base}/api/v1/backup/{bk_id}/filesets",
                                  headers=headers, timeout=10, verify=False)
                filesets = r2.json() if r2.ok else []
                last_status = "ok" if filesets else "warning"
                if last_status == "ok":
                    jobs_ok += 1
                else:
                    jobs_warn += 1
            except Exception:
                last_status = "unknown"
                jobs_warn += 1

            conn.execute("""
                INSERT INTO backup_jobs
                  (server_id, job_id, job_name, job_type, status, last_run,
                   duration_s, size_bytes, files_count, raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                srv["id"], bk_id, bk_name, "backup",
                last_status, last_result,
                _duration_to_seconds(last_duration),
                last_size, last_files,
                json.dumps(bk),
            ))

        conn.execute("""
            INSERT INTO backup_history
              (server_id, jobs_ok, jobs_warn, jobs_error, jobs_total)
            VALUES (?,?,?,?,?)
        """, (srv["id"], jobs_ok, jobs_warn, jobs_error, jobs_ok + jobs_warn + jobs_error))
        conn.commit()
        conn.close()

    return {"ok": True, "jobs_ok": jobs_ok, "jobs_warn": jobs_warn, "jobs_error": jobs_error}


def trigger_duplicati_backup(srv: Dict, backup_id: str) -> Dict:
    """Trigger a Duplicati backup job."""
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
    token = srv.get("api_token") or _duplicati_auth(srv)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(f"{base}/api/v1/backup/{backup_id}/run",
                          headers=headers, timeout=15, verify=False)
        return {"ok": r.ok, "status_code": r.status_code, "message": r.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Restic REST-Server ────────────────────────────────────────────────────────

def _poll_restic(srv: Dict) -> Dict:
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
    auth = None
    if srv.get("username") and srv.get("password"):
        auth = (srv["username"], srv["password"])

    jobs_ok = jobs_warn = 0

    try:
        # List repos (top-level directories)
        r = requests.get(f"{base}/", auth=auth, timeout=15, verify=False)
        if not r.ok:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:100]}"}
        repos = r.json() if r.headers.get("content-type", "").startswith("application/json") else []
    except Exception as e:
        return {"ok": False, "error": str(e)}

    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_snapshots WHERE server_id=?", (srv["id"],))
        for repo in repos:
            repo_name = repo if isinstance(repo, str) else repo.get("name", "")
            try:
                r2 = requests.get(f"{base}/{repo_name}/snapshots/",
                                  auth=auth, timeout=15, verify=False)
                snaps = r2.json() if r2.ok else []
                jobs_ok += 1
                for snap in snaps[-10:]:
                    conn.execute("""
                        INSERT INTO backup_snapshots
                          (server_id, repo, snapshot_id, hostname, timestamp,
                           size_bytes, tags, raw_json)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (
                        srv["id"], repo_name,
                        snap.get("id", "")[:16],
                        snap.get("hostname", ""),
                        snap.get("time", ""),
                        None,
                        ",".join(snap.get("tags", [])) if snap.get("tags") else "",
                        json.dumps(snap),
                    ))
            except Exception:
                jobs_warn += 1

        conn.execute("""
            INSERT INTO backup_history
              (server_id, jobs_ok, jobs_warn, jobs_error, jobs_total)
            VALUES (?,?,?,?,?)
        """, (srv["id"], jobs_ok, jobs_warn, 0, jobs_ok + jobs_warn))
        conn.commit()
        conn.close()

    return {"ok": True, "repos": len(repos), "jobs_ok": jobs_ok}

# ── BorgWarehouse ─────────────────────────────────────────────────────────────

def _poll_borgwarehouse(srv: Dict) -> Dict:
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
    token = srv.get("api_token", "")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        r = requests.get(f"{base}/api/v1/repositories",
                         headers=headers, timeout=15, verify=False)
        if not r.ok:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:100]}"}
        repos = r.json().get("repoList", [])
    except Exception as e:
        return {"ok": False, "error": str(e)}

    jobs_ok = jobs_warn = jobs_error = 0
    now_ts = int(time.time())

    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_jobs WHERE server_id=?", (srv["id"],))
        conn.execute("DELETE FROM backup_snapshots WHERE server_id=?", (srv["id"],))
        for repo in repos:
            alias = repo.get("alias", repo.get("repositoryName", ""))
            last_save = repo.get("lastSave", 0)
            alert_threshold = repo.get("alert", 0)
            storage_used = repo.get("storageUsed", 0)
            storage_size = repo.get("storageSize", 0)

            # Determine status
            if alert_threshold and last_save:
                age = now_ts - last_save
                if age > alert_threshold:
                    st = "warning"
                    jobs_warn += 1
                else:
                    st = "ok"
                    jobs_ok += 1
            elif last_save:
                st = "ok"
                jobs_ok += 1
            else:
                st = "warning"
                jobs_warn += 1

            conn.execute("""
                INSERT INTO backup_jobs
                  (server_id, job_id, job_name, job_type, status, last_run,
                   size_bytes, raw_json)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                srv["id"],
                repo.get("repositoryName", ""),
                alias, "borg",
                st,
                _epoch_to_iso(last_save) if last_save else None,
                storage_used,
                json.dumps(repo),
            ))

        conn.execute("""
            INSERT INTO backup_history
              (server_id, jobs_ok, jobs_warn, jobs_error, jobs_total)
            VALUES (?,?,?,?,?)
        """, (srv["id"], jobs_ok, jobs_warn, jobs_error, jobs_ok + jobs_warn + jobs_error))
        conn.commit()
        conn.close()

    return {"ok": True, "repos": len(repos), "jobs_ok": jobs_ok, "jobs_warn": jobs_warn}

# ── UrBackup ──────────────────────────────────────────────────────────────────

def _urbackup_login(srv: Dict) -> Optional[str]:
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
    try:
        r = requests.get(f"{base}/x?a=login",
                         params={"username": srv.get("username", "admin"),
                                 "password": srv.get("password", "")},
                         timeout=10, verify=False)
        if r.ok:
            data = r.json()
            if data.get("success"):
                return r.cookies.get("URBACKUP_SESSIONID") or data.get("session")
    except Exception:
        pass
    return None


def _poll_urbackup(srv: Dict) -> Dict:
    base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
    session = _urbackup_login(srv)
    params = {}
    if session:
        params["ses"] = session

    jobs_ok = jobs_warn = jobs_error = 0

    try:
        r = requests.get(f"{base}/x", params={**params, "a": "status"}, timeout=15, verify=False)
        if not r.ok:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        data = r.json()
        clients = data.get("clients", [])
    except Exception as e:
        return {"ok": False, "error": str(e)}

    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_jobs WHERE server_id=?", (srv["id"],))
        for client in clients:
            cname = client.get("name", "")
            last_filebackup = client.get("lastbackup", 0)
            last_imagebackup = client.get("lastbackup_image", 0)
            file_ok = client.get("file_ok", False)
            image_ok = client.get("image_ok", False)

            # File backup job
            if last_filebackup:
                st = "ok" if file_ok else "warning"
                if st == "ok":
                    jobs_ok += 1
                else:
                    jobs_warn += 1
                conn.execute("""
                    INSERT INTO backup_jobs
                      (server_id, job_id, job_name, job_type, status, last_run, raw_json)
                    VALUES (?,?,?,?,?,?,?)
                """, (
                    srv["id"], f"{cname}_file", f"{cname} (file)", "file",
                    st, _epoch_to_iso(last_filebackup), json.dumps(client),
                ))

            # Image backup job
            if last_imagebackup:
                st = "ok" if image_ok else "warning"
                if st == "ok":
                    jobs_ok += 1
                else:
                    jobs_warn += 1
                conn.execute("""
                    INSERT INTO backup_jobs
                      (server_id, job_id, job_name, job_type, status, last_run, raw_json)
                    VALUES (?,?,?,?,?,?,?)
                """, (
                    srv["id"], f"{cname}_image", f"{cname} (image)", "image",
                    st, _epoch_to_iso(last_imagebackup), json.dumps(client),
                ))

        conn.execute("""
            INSERT INTO backup_history
              (server_id, jobs_ok, jobs_warn, jobs_error, jobs_total)
            VALUES (?,?,?,?,?)
        """, (srv["id"], jobs_ok, jobs_warn, jobs_error, jobs_ok + jobs_warn + jobs_error))
        conn.commit()
        conn.close()

    return {"ok": True, "clients": len(clients), "jobs_ok": jobs_ok, "jobs_warn": jobs_warn}

# ── Bacula ────────────────────────────────────────────────────────────────────

def _poll_bacula(srv: Dict) -> Dict:
    # Run bconsole commands via SSH
    is_root = srv.get("username", "root") == "root"
    use_sudo = bool(srv.get("use_sudo", 0))
    sudo = "" if (is_root or not use_sudo) else "sudo "
    cmd = (
        f"echo -e 'status director\\nquit' | {sudo}bconsole 2>&1 | head -60 ; "
        "echo '---JOBS---' ; "
        f"echo -e 'list jobs last=20\\nquit' | {sudo}bconsole 2>&1 | head -80"
    )
    rc, out, err = _ssh_run(
        srv["host"], srv["port"], srv.get("username", "root"),
        srv.get("password", ""), srv.get("ssh_key", ""), cmd, timeout=30
    )
    if rc != 0 and not out:
        return {"ok": False, "error": err or "bconsole failed"}

    jobs_ok = jobs_warn = jobs_error = 0
    lines = out.split("\n")
    in_jobs = False
    job_rows = []

    for line in lines:
        if "---JOBS---" in line:
            in_jobs = True
            continue
        if in_jobs and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 6 and parts[0].isdigit():
                job_rows.append(parts)

    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_jobs WHERE server_id=?", (srv["id"],))
        for row in job_rows[:30]:
            try:
                job_id = row[0]
                job_name = row[1] if len(row) > 1 else ""
                start_time = row[3] if len(row) > 3 else ""
                job_status_raw = row[5] if len(row) > 5 else ""
                if job_status_raw in ("T", "R"):
                    st = "ok"
                    jobs_ok += 1
                elif job_status_raw in ("W",):
                    st = "warning"
                    jobs_warn += 1
                else:
                    st = "error"
                    jobs_error += 1
                conn.execute("""
                    INSERT INTO backup_jobs
                      (server_id, job_id, job_name, job_type, status, last_run, raw_json)
                    VALUES (?,?,?,?,?,?,?)
                """, (srv["id"], job_id, job_name, "bacula", st, start_time, json.dumps(row)))
            except Exception:
                pass

        conn.execute("""
            INSERT INTO backup_history
              (server_id, jobs_ok, jobs_warn, jobs_error, jobs_total)
            VALUES (?,?,?,?,?)
        """, (srv["id"], jobs_ok, jobs_warn, jobs_error, jobs_ok + jobs_warn + jobs_error))
        conn.commit()
        conn.close()

    return {"ok": True, "jobs_ok": jobs_ok, "jobs_warn": jobs_warn, "jobs_error": jobs_error}

# ── SSH Generic ───────────────────────────────────────────────────────────────

def _poll_ssh_generic(srv: Dict) -> Dict:
    """Run a configurable status command via SSH and parse output."""
    # Default: try to detect restic/borg/rsync and run appropriate status
    cmd = srv.get("notes", "") or (
        "which restic >/dev/null 2>&1 && restic snapshots --json 2>/dev/null | python3 -c \"import json,sys; snaps=json.load(sys.stdin); print(f'SNAPSHOTS:{len(snaps)}')\" ; "
        "which borg >/dev/null 2>&1 && borg list 2>/dev/null | wc -l | xargs -I{} echo 'BORG_ARCHIVES:{}' ; "
        "df -h / 2>/dev/null | tail -1"
    )
    rc, out, err = _ssh_run(
        srv["host"], srv["port"], srv.get("username", "root"),
        srv.get("password", ""), srv.get("ssh_key", ""), cmd, timeout=30
    )

    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM backup_jobs WHERE server_id=?", (srv["id"],))
        conn.execute("""
            INSERT INTO backup_jobs
              (server_id, job_id, job_name, job_type, status, last_run, raw_json)
            VALUES (?,?,?,?,?,datetime('now'),?)
        """, (
            srv["id"], "ssh_status", "SSH Status Check", "ssh",
            "ok" if rc == 0 else "warning",
            json.dumps({"stdout": out[:2000], "stderr": err[:500], "rc": rc}),
        ))
        conn.execute("""
            INSERT INTO backup_history
              (server_id, jobs_ok, jobs_warn, jobs_error, jobs_total)
            VALUES (?,?,?,?,?)
        """, (srv["id"], 1 if rc == 0 else 0, 0 if rc == 0 else 1, 0, 1))
        conn.commit()
        conn.close()

    return {"ok": rc == 0, "output": out[:1000]}

# ── Connection test ───────────────────────────────────────────────────────────

def test_connection(server_id: int) -> Dict:
    """Quick connectivity test without full poll."""
    srv = get_server(server_id)
    if not srv:
        return {"ok": False, "error": "Server not found"}
    stype = srv["server_type"]
    try:
        if stype in ("bacula", "ssh_generic"):
            rc, out, err = _ssh_run(
                srv["host"], srv["port"], srv.get("username", "root"),
                srv.get("password", ""), srv.get("ssh_key", ""),
                "echo 'FleetPilot connection test OK'", timeout=10
            )
            return {"ok": rc == 0, "message": out.strip() or err.strip()}
        else:
            base = f"{srv['protocol']}://{srv['host']}:{srv['port']}"
            if stype == "pbs":
                url = f"{base}/api2/json/version"
                sess = _pbs_session(srv)
                r = sess.get(url, timeout=10)
            elif stype == "duplicati":
                url = f"{base}/api/v1/serverstate"
                r = requests.get(url, timeout=10, verify=False)
            elif stype == "restic":
                url = f"{base}/"
                auth = (srv.get("username"), srv.get("password")) if srv.get("username") else None
                r = requests.get(url, auth=auth, timeout=10, verify=False)
            elif stype == "borgwarehouse":
                url = f"{base}/api/v1/version"
                r = requests.get(url, timeout=10, verify=False)
            elif stype == "urbackup":
                url = f"{base}/x?a=login"
                r = requests.get(url, timeout=10, verify=False)
            else:
                return {"ok": False, "error": "Unknown type"}
            return {
                "ok": r.ok,
                "status_code": r.status_code,
                "message": f"HTTP {r.status_code}",
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Trigger backup ────────────────────────────────────────────────────────────

def trigger_backup(server_id: int, job_id: str = "") -> Dict:
    """Trigger a backup job on the server."""
    srv = get_server(server_id)
    if not srv:
        return {"ok": False, "error": "Server not found"}
    stype = srv["server_type"]
    if stype == "duplicati":
        return trigger_duplicati_backup(srv, job_id)
    elif stype == "pbs":
        base = f"{srv['protocol']}://{srv['host']}:{srv['port']}/api2/json"
        sess = _pbs_session(srv)
        try:
            r = sess.post(f"{base}/nodes/localhost/backup", json={"job-id": job_id}, timeout=15)
            return {"ok": r.ok, "message": r.text[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    elif stype in ("bacula", "ssh_generic"):
        cmd = f"echo -e 'run job={job_id} yes\\nquit' | bconsole 2>&1" if stype == "bacula" else job_id
        rc, out, err = _ssh_run(
            srv["host"], srv["port"], srv.get("username", "root"),
            srv.get("password", ""), srv.get("ssh_key", ""), cmd, timeout=30
        )
        return {"ok": rc == 0, "output": out[:500]}
    return {"ok": False, "error": f"Trigger not supported for {stype}"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _epoch_to_iso(epoch) -> Optional[str]:
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(epoch)


def _duration_to_seconds(duration_str: str) -> Optional[int]:
    if not duration_str:
        return None
    try:
        # Format: "00:01:23" or "PT1M23S"
        if ":" in duration_str:
            parts = duration_str.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
        if m:
            h, mi, s = m.group(1), m.group(2), m.group(3)
            return int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)
    except Exception:
        pass
    return None


def format_bytes(b: Optional[int]) -> str:
    if b is None:
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
