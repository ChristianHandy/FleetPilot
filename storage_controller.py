"""
FleetPilot — Storage Controller
=================================
Manages NAS/storage systems: Unraid and TrueNAS (SCALE & CORE).

Supported platforms:
  - Unraid 6.x / 7.x  (Unraid API via JSON plugin or built-in API)
  - TrueNAS SCALE / CORE  (REST API v2.0)

All connections are stored in the SQLite database (storage_controller.db).
"""

import os
import json
import sqlite3
import logging
import urllib.request
import urllib.error
import urllib.parse
import ssl
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger("fleetpilot.storage_controller")

DB_FILE = Path(__file__).parent / "storage_controller.db"

# ── Encryption (same pattern as vm_controller) ────────────────────────────────
try:
    from cryptography.fernet import Fernet
    import base64 as _b64
    import hashlib as _hashlib
    # Use SHA256 of SECRET_KEY — consistent with app.py and all other controllers
    _secret = os.environ.get("SECRET_KEY", "")
    _fernet = Fernet(_b64.urlsafe_b64encode(_hashlib.sha256(_secret.encode()).digest()))
    def _encrypt(s: str) -> str:
        return _fernet.encrypt(s.encode()).decode()
    def _decrypt(s: str) -> str:
        return _fernet.decrypt(s.encode()).decode()
except Exception:
    import base64 as _b64
    def _encrypt(s: str) -> str:
        return _b64.b64encode(s.encode()).decode()
    def _decrypt(s: str) -> str:
        return _b64.b64decode(s.encode()).decode()


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS storage_endpoints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            platform    TEXT NOT NULL,   -- unraid | truenas
            host        TEXT NOT NULL,
            port        INTEGER DEFAULT 443,
            api_key     TEXT NOT NULL,   -- encrypted; for Unraid: API key; for TrueNAS: API key
            verify_ssl  INTEGER DEFAULT 0,
            enabled     INTEGER DEFAULT 1,
            notes       TEXT DEFAULT '',
            added_ts    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS storage_disk_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER,
            disk_id     TEXT,
            disk_name   TEXT,
            model       TEXT,
            serial      TEXT,
            size_gb     REAL,
            temp        INTEGER,
            health      TEXT,
            smart_status TEXT,
            pool        TEXT,
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS storage_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_id INTEGER,
            resource    TEXT,
            action      TEXT,
            status      TEXT,
            message     TEXT,
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)


# ── Endpoint CRUD ─────────────────────────────────────────────────────────────

def add_endpoint(name: str, platform: str, host: str, port: int,
                 api_key: str, verify_ssl: bool = False, notes: str = "") -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO storage_endpoints(name,platform,host,port,api_key,verify_ssl,notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (name, platform, host, port, _encrypt(api_key), 1 if verify_ssl else 0, notes)
        )
        return cur.lastrowid


def list_endpoints() -> List[Dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM storage_endpoints ORDER BY added_ts DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("api_key", None)
        result.append(d)
    return result


def get_endpoint(ep_id: int) -> Optional[Dict]:
    with get_db() as db:
        row = db.execute("SELECT * FROM storage_endpoints WHERE id=?", (ep_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["api_key_plain"] = _decrypt(d["api_key"])
    except Exception:
        d["api_key_plain"] = ""
    return d


def delete_endpoint(ep_id: int):
    with get_db() as db:
        db.execute("DELETE FROM storage_endpoints WHERE id=?", (ep_id,))


def log_event(endpoint_id: int, resource: str, action: str,
              status: str, message: str = ""):
    with get_db() as db:
        db.execute(
            "INSERT INTO storage_events(endpoint_id,resource,action,status,message) "
            "VALUES (?,?,?,?,?)",
            (endpoint_id, resource, action, status, message)
        )


def get_events(limit: int = 100) -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT e.*, ep.name AS endpoint_name, ep.platform "
            "FROM storage_events e LEFT JOIN storage_endpoints ep ON e.endpoint_id=ep.id "
            "ORDER BY e.ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def log_disk_snapshot(endpoint_id: int, disk: Dict):
    """Persist a disk health snapshot for trend tracking."""
    with get_db() as db:
        db.execute(
            "INSERT INTO storage_disk_log"
            "(endpoint_id,disk_id,disk_name,model,serial,size_gb,temp,health,smart_status,pool) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (endpoint_id,
             disk.get("id", ""),
             disk.get("name", ""),
             disk.get("model", ""),
             disk.get("serial", ""),
             disk.get("size_gb"),
             disk.get("temp"),
             disk.get("health", "UNKNOWN"),
             disk.get("smart_status", ""),
             disk.get("pool", ""))
        )


def get_disk_history(endpoint_id: int, disk_id: str, limit: int = 50) -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM storage_disk_log WHERE endpoint_id=? AND disk_id=? "
            "ORDER BY ts DESC LIMIT ?",
            (endpoint_id, disk_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _http(method: str, url: str, headers: Dict = None,
          body: Any = None, verify_ssl: bool = False, timeout: int = 15) -> Dict:
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    data = None
    if body is not None:
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            headers = dict(headers or {})
            headers["Content-Type"] = "application/json"
        else:
            data = body if isinstance(body, bytes) else str(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return {"ok": True, "status": resp.status, "data": json.loads(raw)}
            except json.JSONDecodeError:
                return {"ok": True, "status": resp.status, "data": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": e.code, "error": raw}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# TrueNAS SCALE / CORE Client  (REST API v2.0)
# ══════════════════════════════════════════════════════════════════════════════

class TrueNASClient:
    """TrueNAS SCALE/CORE REST API v2 client."""

    def __init__(self, host: str, port: int, api_key: str,
                 verify_ssl: bool = False):
        self.base = f"https://{host}:{port}/api/v2.0"
        self.verify_ssl = verify_ssl
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: str = "") -> Dict:
        url = f"{self.base}{path}"
        if params:
            url += "?" + params
        return _http("GET", url, headers=self._headers, verify_ssl=self.verify_ssl)

    def _post(self, path: str, body: Any = None) -> Dict:
        return _http("POST", f"{self.base}{path}", headers=self._headers,
                     body=body, verify_ssl=self.verify_ssl)

    def _put(self, path: str, body: Any = None) -> Dict:
        return _http("PUT", f"{self.base}{path}", headers=self._headers,
                     body=body, verify_ssl=self.verify_ssl)

    # ── System ────────────────────────────────────────────────────────────────

    def get_system_info(self) -> Dict:
        r = self._get("/system/info")
        return r["data"] if r["ok"] else {}

    def get_version(self) -> str:
        info = self.get_system_info()
        return info.get("version", "unknown")

    # ── Disks ─────────────────────────────────────────────────────────────────

    def get_disks(self) -> List[Dict]:
        r = self._get("/disk")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    def get_disk_temperatures(self) -> Dict:
        r = self._post("/disk/temperatures", body={"names": []})
        return r["data"] if r["ok"] and isinstance(r["data"], dict) else {}

    def get_disk_smart_results(self, disk_name: str) -> List[Dict]:
        r = self._get(f"/smart/test/results/{disk_name}")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    def start_smart_test(self, disk_name: str, test_type: str = "SHORT") -> Dict:
        """test_type: SHORT | LONG | CONVEYANCE | OFFLINE"""
        return self._post("/smart/test", body={
            "disks": [disk_name],
            "type": test_type
        })

    # ── Storage Pools ─────────────────────────────────────────────────────────

    def get_pools(self) -> List[Dict]:
        r = self._get("/pool")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    def get_pool_status(self, pool_id: int) -> Dict:
        r = self._get(f"/pool/id/{pool_id}/get_instance")
        return r["data"] if r["ok"] else {}

    # ── Datasets / Volumes ────────────────────────────────────────────────────

    def get_datasets(self) -> List[Dict]:
        r = self._get("/pool/dataset")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    # ── Shares ────────────────────────────────────────────────────────────────

    def get_smb_shares(self) -> List[Dict]:
        r = self._get("/sharing/smb")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    def get_nfs_shares(self) -> List[Dict]:
        r = self._get("/sharing/nfs")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    # ── Alerts ────────────────────────────────────────────────────────────────

    def get_alerts(self) -> List[Dict]:
        r = self._get("/alert/list")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    # ── Snapshots ─────────────────────────────────────────────────────────────

    def get_snapshots(self) -> List[Dict]:
        r = self._get("/zfs/snapshot")
        return r["data"] if r["ok"] and isinstance(r["data"], list) else []

    # ── Normalized disk summary ───────────────────────────────────────────────

    def get_disk_summary(self) -> List[Dict]:
        """Return normalized disk dicts for FleetPilot disk manager."""
        disks = self.get_disks()
        temps = self.get_disk_temperatures()
        result = []
        for d in disks:
            name = d.get("name", "")
            size_bytes = d.get("size", 0) or 0
            size_gb = round(size_bytes / 1e9, 1) if size_bytes else None
            temp = temps.get(name)
            health = "UNKNOWN"
            if d.get("hddstandby") == "ALWAYS ON":
                health = "GOOD"
            result.append({
                "id": name,
                "name": name,
                "model": d.get("model", ""),
                "serial": d.get("serial", ""),
                "size_gb": size_gb,
                "temp": temp,
                "health": health,
                "smart_status": d.get("togglesmart", ""),
                "pool": d.get("pool", ""),
                "source": "truenas",
            })
        return result


# ══════════════════════════════════════════════════════════════════════════════
# Unraid Client  (Unraid API via JSON plugin or built-in API)
# ══════════════════════════════════════════════════════════════════════════════

class UnraidClient:
    """
    Unraid API client.

    Unraid 6.12+ ships with a built-in GraphQL API (port 443, /graphql).
    Older versions use the community JSON API plugin.
    We support both; the built-in REST/JSON endpoints are used where possible.
    """

    def __init__(self, host: str, port: int, api_key: str,
                 verify_ssl: bool = False):
        self.host = host
        self.port = port
        self.verify_ssl = verify_ssl
        self._api_key = api_key
        self.base_http = f"http://{host}"   # Unraid typically HTTP on LAN
        self.base_https = f"https://{host}:{port}"

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _get_json(self, path: str, use_https: bool = False) -> Dict:
        base = self.base_https if use_https else self.base_http
        return _http("GET", f"{base}{path}", headers=self._headers(),
                     verify_ssl=self.verify_ssl)

    # ── System info ───────────────────────────────────────────────────────────

    def get_system_info(self) -> Dict:
        """Try /api/system/info (built-in) then fall back to /state/var.ini."""
        r = self._get_json("/api/system/info")
        if r["ok"] and isinstance(r["data"], dict):
            return r["data"]
        # Fallback: parse var.ini (available without auth on LAN)
        r2 = _http("GET", f"{self.base_http}/state/var.ini",
                   verify_ssl=self.verify_ssl)
        if r2["ok"] and isinstance(r2["data"], str):
            info = {}
            for line in r2["data"].splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    info[k.strip()] = v.strip().strip('"')
            return info
        return {}

    # ── Array / Disks ─────────────────────────────────────────────────────────

    def get_array_status(self) -> Dict:
        r = self._get_json("/api/array")
        if r["ok"] and isinstance(r["data"], dict):
            return r["data"]
        # Fallback: /state/array.ini
        r2 = _http("GET", f"{self.base_http}/state/array.ini",
                   verify_ssl=self.verify_ssl)
        if r2["ok"] and isinstance(r2["data"], str):
            info = {}
            for line in r2["data"].splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    info[k.strip()] = v.strip().strip('"')
            return info
        return {}

    def get_disks(self) -> List[Dict]:
        """Return disk list from /api/disks or /state/disks.ini."""
        r = self._get_json("/api/disks")
        if r["ok"] and isinstance(r["data"], list):
            return r["data"]
        # Fallback: parse disks.ini
        r2 = _http("GET", f"{self.base_http}/state/disks.ini",
                   verify_ssl=self.verify_ssl)
        if r2["ok"] and isinstance(r2["data"], str):
            return self._parse_ini_disks(r2["data"])
        return []

    def _parse_ini_disks(self, text: str) -> List[Dict]:
        """Parse Unraid disks.ini into a list of disk dicts."""
        disks = []
        current: Dict = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                if current:
                    disks.append(current)
                    current = {}
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                current[k.strip()] = v.strip().strip('"')
        if current:
            disks.append(current)
        return disks

    def get_shares(self) -> List[Dict]:
        r = self._get_json("/api/shares")
        if r["ok"] and isinstance(r["data"], list):
            return r["data"]
        return []

    def get_docker_containers(self) -> List[Dict]:
        r = self._get_json("/api/docker/containers")
        if r["ok"] and isinstance(r["data"], list):
            return r["data"]
        return []

    def get_vms(self) -> List[Dict]:
        r = self._get_json("/api/vms")
        if r["ok"] and isinstance(r["data"], list):
            return r["data"]
        return []

    def get_notifications(self) -> List[Dict]:
        r = self._get_json("/api/notifications")
        if r["ok"] and isinstance(r["data"], list):
            return r["data"]
        return []

    # ── Normalized disk summary ───────────────────────────────────────────────

    def get_disk_summary(self) -> List[Dict]:
        """Return normalized disk dicts for FleetPilot disk manager."""
        raw = self.get_disks()
        result = []
        for d in raw:
            name = d.get("name", d.get("id", ""))
            # Unraid reports temp in °C as string
            try:
                temp = int(d.get("temp", d.get("diskTemp", 0)) or 0)
            except (ValueError, TypeError):
                temp = None
            # Health from status field
            status_raw = d.get("status", d.get("diskStatus", "")).upper()
            if "DISK_OK" in status_raw or status_raw == "OK":
                health = "GOOD"
            elif "DISK_NP" in status_raw:
                health = "NOT_PRESENT"
            elif "DISK_DSBL" in status_raw:
                health = "DISABLED"
            elif "DISK_INVALID" in status_raw or "ERROR" in status_raw:
                health = "CRITICAL"
            else:
                health = "UNKNOWN"
            # Size
            try:
                size_gb = round(int(d.get("size", d.get("diskSize", 0)) or 0) / 1e9, 1)
            except (ValueError, TypeError):
                size_gb = None
            result.append({
                "id": name,
                "name": name,
                "model": d.get("model", d.get("diskModel", "")),
                "serial": d.get("serial", d.get("id", "")),
                "size_gb": size_gb,
                "temp": temp,
                "health": health,
                "smart_status": d.get("smartStatus", ""),
                "pool": d.get("pool", "array"),
                "source": "unraid",
                "fsType": d.get("fsType", ""),
                "used_gb": None,
            })
        return result


# ── High-level API used by Flask routes ──────────────────────────────────────

def connect(ep_id: int):
    ep = get_endpoint(ep_id)
    if not ep:
        raise ValueError(f"Endpoint {ep_id} not found")
    platform = ep["platform"]
    host = ep["host"]
    port = ep["port"]
    key  = ep["api_key_plain"]
    ssl_ = bool(ep.get("verify_ssl", 0))
    if platform == "truenas":
        return TrueNASClient(host, port, key, ssl_)
    elif platform == "unraid":
        return UnraidClient(host, port, key, ssl_)
    else:
        raise ValueError(f"Unknown platform: {platform}")


def test_connection(ep_id: int) -> Dict:
    try:
        client = connect(ep_id)
        if isinstance(client, TrueNASClient):
            info = client.get_system_info()
            ver = info.get("version", "?")
            return {"ok": True, "message": f"Connected — TrueNAS {ver}"}
        elif isinstance(client, UnraidClient):
            info = client.get_system_info()
            ver = info.get("version", info.get("VERSION", "?"))
            return {"ok": True, "message": f"Connected — Unraid {ver}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def get_storage_overview(ep_id: int) -> Dict:
    """Return a full overview dict for the storage dashboard."""
    ep = get_endpoint(ep_id)
    if not ep:
        return {"error": "Endpoint not found"}
    client = connect(ep_id)
    overview: Dict = {"platform": ep["platform"], "endpoint_name": ep["name"]}
    try:
        if isinstance(client, TrueNASClient):
            overview["system_info"] = client.get_system_info()
            overview["pools"] = client.get_pools()
            overview["disks"] = client.get_disk_summary()
            overview["datasets"] = client.get_datasets()
            overview["smb_shares"] = client.get_smb_shares()
            overview["nfs_shares"] = client.get_nfs_shares()
            overview["alerts"] = client.get_alerts()
        elif isinstance(client, UnraidClient):
            overview["system_info"] = client.get_system_info()
            overview["array"] = client.get_array_status()
            overview["disks"] = client.get_disk_summary()
            overview["shares"] = client.get_shares()
            overview["docker"] = client.get_docker_containers()
            overview["vms"] = client.get_vms()
            overview["alerts"] = client.get_notifications()
    except Exception as exc:
        overview["error"] = str(exc)
    return overview


def poll_and_log_disks(ep_id: int):
    """Fetch current disk state and persist to storage_disk_log for trend tracking."""
    try:
        client = connect(ep_id)
        if isinstance(client, (TrueNASClient, UnraidClient)):
            disks = client.get_disk_summary()
            for d in disks:
                log_disk_snapshot(ep_id, d)
            logger.info("[storage_controller] Logged %d disks for endpoint %d", len(disks), ep_id)
    except Exception as exc:
        logger.error("[storage_controller] Poll failed for endpoint %d: %s", ep_id, exc)
