"""
FleetPilot — SMART Manager
============================
Extended SMART data logging, health classification, and disk status dashboard.

Features:
  - Full SMART attribute table parsing (all 255 attributes)
  - Health classification: GOOD / WARNING / CRITICAL / FAILED
  - Automatic polling scheduler (background thread)
  - Trend history per disk and attribute
  - Integration with storage_controller (Unraid/TrueNAS remote disks)
  - Integration with vm_controller (Proxmox node disks)
  - Unified disk registry: local + remote disks in one table
"""

import re
import json
import sqlite3
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("fleetpilot.smart_manager")

DB_FILE = Path(__file__).parent / "smart_manager.db"

# ── SMART attribute criticality map ──────────────────────────────────────────
# Attributes that directly indicate imminent failure when RAW_VALUE > threshold
CRITICAL_ATTRS = {
    5:   "Reallocated Sectors Count",
    10:  "Spin Retry Count",
    184: "End-to-End Error",
    187: "Reported Uncorrectable Errors",
    188: "Command Timeout",
    196: "Reallocation Event Count",
    197: "Current Pending Sector Count",
    198: "Uncorrectable Sector Count",
    201: "Soft Read Error Rate",
}

WARNING_ATTRS = {
    1:   "Raw Read Error Rate",
    3:   "Spin-Up Time",
    9:   "Power-On Hours",
    190: "Airflow Temperature",
    194: "Temperature Celsius",
    199: "UDMA CRC Error Count",
}

# Temperature thresholds (°C)
TEMP_WARNING  = 45
TEMP_CRITICAL = 55

# Power-on hours thresholds
POH_WARNING  = 30_000   # ~3.4 years
POH_CRITICAL = 50_000   # ~5.7 years


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        -- Unified disk registry (local + remote)
        CREATE TABLE IF NOT EXISTS disk_registry (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT NOT NULL,   -- local | proxmox | truenas | unraid
            source_id   TEXT,            -- endpoint id for remote sources
            device      TEXT NOT NULL,   -- /dev/sda or disk name
            serial      TEXT,
            model       TEXT,
            size_gb     REAL,
            first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, device)
        );

        -- Full SMART attribute snapshots
        CREATE TABLE IF NOT EXISTS smart_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            disk_id     INTEGER REFERENCES disk_registry(id),
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            health      TEXT DEFAULT 'UNKNOWN',  -- GOOD|WARNING|CRITICAL|FAILED
            overall_status TEXT,                 -- PASSED|FAILED|UNKNOWN
            temp        INTEGER,
            poh         INTEGER,                 -- power-on hours
            reallocated INTEGER,
            pending     INTEGER,
            uncorrectable INTEGER,
            raw_json    TEXT                     -- full attribute JSON
        );

        -- Individual SMART attribute history (for trend charts)
        CREATE TABLE IF NOT EXISTS smart_attributes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER REFERENCES smart_snapshots(id),
            disk_id     INTEGER REFERENCES disk_registry(id),
            attr_id     INTEGER,
            attr_name   TEXT,
            value       INTEGER,
            worst       INTEGER,
            threshold   INTEGER,
            raw_value   INTEGER,
            raw_string  TEXT,
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Disk health alerts
        CREATE TABLE IF NOT EXISTS disk_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            disk_id     INTEGER REFERENCES disk_registry(id),
            level       TEXT,   -- WARNING | CRITICAL | FAILED
            message     TEXT,
            acknowledged INTEGER DEFAULT 0,
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Polling schedule config
        CREATE TABLE IF NOT EXISTS poll_config (
            id              INTEGER PRIMARY KEY DEFAULT 1,
            interval_minutes INTEGER DEFAULT 60,
            enabled         INTEGER DEFAULT 1,
            last_poll       TIMESTAMP
        );
        INSERT OR IGNORE INTO poll_config(id) VALUES(1);
        """)


# ── Disk registry ─────────────────────────────────────────────────────────────

def register_disk(source: str, device: str, serial: str = None,
                  model: str = None, size_gb: float = None,
                  source_id: str = None) -> int:
    """Register or update a disk in the unified registry. Returns disk_id."""
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM disk_registry WHERE source=? AND device=?",
            (source, device)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE disk_registry SET serial=COALESCE(?,serial), model=COALESCE(?,model), "
                "size_gb=COALESCE(?,size_gb), last_seen=CURRENT_TIMESTAMP WHERE id=?",
                (serial, model, size_gb, existing["id"])
            )
            return existing["id"]
        else:
            cur = db.execute(
                "INSERT INTO disk_registry(source,source_id,device,serial,model,size_gb) "
                "VALUES (?,?,?,?,?,?)",
                (source, source_id, device, serial, model, size_gb)
            )
            return cur.lastrowid


def get_all_disks() -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT r.*, "
            "  (SELECT health FROM smart_snapshots WHERE disk_id=r.id ORDER BY ts DESC LIMIT 1) AS health, "
            "  (SELECT temp  FROM smart_snapshots WHERE disk_id=r.id ORDER BY ts DESC LIMIT 1) AS temp, "
            "  (SELECT poh   FROM smart_snapshots WHERE disk_id=r.id ORDER BY ts DESC LIMIT 1) AS poh, "
            "  (SELECT ts    FROM smart_snapshots WHERE disk_id=r.id ORDER BY ts DESC LIMIT 1) AS last_smart "
            "FROM disk_registry r ORDER BY r.source, r.device"
        ).fetchall()
    return [dict(r) for r in rows]


def get_disk_by_id(disk_id: int) -> Optional[Dict]:
    with get_db() as db:
        row = db.execute("SELECT * FROM disk_registry WHERE id=?", (disk_id,)).fetchone()
    return dict(row) if row else None


# ── SMART parsing ─────────────────────────────────────────────────────────────

def parse_smartctl_output(output: str) -> Dict:
    """
    Parse smartctl -a output into a structured dict.
    Returns: {overall_status, temp, poh, reallocated, pending, uncorrectable, attributes:[...]}
    """
    result = {
        "overall_status": "UNKNOWN",
        "temp": None,
        "poh": None,
        "reallocated": 0,
        "pending": 0,
        "uncorrectable": 0,
        "attributes": [],
    }

    # Overall health
    if re.search(r"SMART overall-health self-assessment test result: PASSED", output):
        result["overall_status"] = "PASSED"
    elif re.search(r"SMART overall-health self-assessment test result: FAILED", output):
        result["overall_status"] = "FAILED"

    # Attribute table (ATA)
    # Format: ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
    attr_pattern = re.compile(
        r"^\s*(\d+)\s+([\w_]+)\s+0x[\da-fA-F]+\s+(\d+)\s+(\d+)\s+(\d+)\s+\S+\s+\S+\s+\S+\s+(.+)$",
        re.MULTILINE
    )
    for m in attr_pattern.finditer(output):
        attr_id   = int(m.group(1))
        attr_name = m.group(2)
        value     = int(m.group(3))
        worst     = int(m.group(4))
        threshold = int(m.group(5))
        raw_str   = m.group(6).strip()
        # Parse raw value (first number)
        raw_m = re.match(r"(\d+)", raw_str)
        raw_val = int(raw_m.group(1)) if raw_m else 0

        result["attributes"].append({
            "id": attr_id, "name": attr_name,
            "value": value, "worst": worst,
            "threshold": threshold,
            "raw_value": raw_val, "raw_string": raw_str,
        })

        # Extract key metrics
        if attr_id == 194:
            result["temp"] = raw_val
        elif attr_id == 190 and result["temp"] is None:
            result["temp"] = raw_val
        elif attr_id == 9:
            result["poh"] = raw_val
        elif attr_id == 5:
            result["reallocated"] = raw_val
        elif attr_id == 197:
            result["pending"] = raw_val
        elif attr_id == 198:
            result["uncorrectable"] = raw_val

    # NVMe temperature fallback
    if result["temp"] is None:
        m = re.search(r"Temperature:\s+(\d+)\s+Celsius", output)
        if m:
            result["temp"] = int(m.group(1))

    # NVMe power-on hours fallback
    if result["poh"] is None:
        m = re.search(r"Power On Hours:\s+([\d,]+)", output)
        if m:
            result["poh"] = int(m.group(1).replace(",", ""))

    return result


def classify_health(parsed: Dict) -> str:
    """
    Classify disk health based on parsed SMART data.
    Returns: GOOD | WARNING | CRITICAL | FAILED
    """
    if parsed["overall_status"] == "FAILED":
        return "FAILED"

    # Critical attribute thresholds
    if parsed["reallocated"] > 0:
        return "CRITICAL"
    if parsed["pending"] > 0:
        return "CRITICAL"
    if parsed["uncorrectable"] > 0:
        return "CRITICAL"

    # Temperature
    temp = parsed["temp"]
    if temp is not None:
        if temp >= TEMP_CRITICAL:
            return "CRITICAL"
        if temp >= TEMP_WARNING:
            return "WARNING"

    # Power-on hours
    poh = parsed["poh"]
    if poh is not None:
        if poh >= POH_CRITICAL:
            return "WARNING"

    # Check individual attributes against thresholds
    for attr in parsed["attributes"]:
        if attr["value"] <= attr["threshold"] and attr["threshold"] > 0:
            if attr["id"] in CRITICAL_ATTRS:
                return "CRITICAL"
            if attr["id"] in WARNING_ATTRS:
                return "WARNING"

    return "GOOD"


# ── Local disk SMART collection ───────────────────────────────────────────────

def _run_smartctl(device: str) -> str:
    """Run smartctl -a on a local device and return output."""
    try:
        res = subprocess.run(
            ["smartctl", "-a", f"/dev/{device}"],
            capture_output=True, text=True, timeout=30
        )
        return res.stdout + res.stderr
    except FileNotFoundError:
        return "smartctl not found"
    except Exception as exc:
        return str(exc)


def collect_local_disk(device: str) -> Optional[Dict]:
    """
    Collect SMART data for a local disk, register it, and save snapshot.
    Returns the snapshot dict or None on failure.
    """
    output = _run_smartctl(device)
    parsed = parse_smartctl_output(output)
    health = classify_health(parsed)

    # Get serial/model from smartctl -i
    try:
        info_out = subprocess.run(
            ["smartctl", "-i", f"/dev/{device}"],
            capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        info_out = output

    serial = None
    model  = None
    size_gb = None
    for line in info_out.splitlines():
        if "Serial Number" in line:
            serial = line.split(":", 1)[1].strip()
        elif "Device Model" in line or "Model Number" in line:
            model = line.split(":", 1)[1].strip()
        elif "User Capacity" in line:
            m = re.search(r"([\d,]+)\s+bytes", line)
            if m:
                size_gb = round(int(m.group(1).replace(",", "")) / 1e9, 1)

    disk_id = register_disk("local", device, serial=serial, model=model, size_gb=size_gb)
    snapshot_id = _save_snapshot(disk_id, parsed, health)
    _save_attributes(snapshot_id, disk_id, parsed["attributes"])
    _check_and_alert(disk_id, health, parsed)

    return {
        "disk_id": disk_id,
        "device": device,
        "serial": serial,
        "model": model,
        "health": health,
        "temp": parsed["temp"],
        "poh": parsed["poh"],
        "reallocated": parsed["reallocated"],
        "pending": parsed["pending"],
        "uncorrectable": parsed["uncorrectable"],
        "overall_status": parsed["overall_status"],
        "attributes": parsed["attributes"],
    }


def _save_snapshot(disk_id: int, parsed: Dict, health: str) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO smart_snapshots"
            "(disk_id,health,overall_status,temp,poh,reallocated,pending,uncorrectable,raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (disk_id, health, parsed["overall_status"],
             parsed["temp"], parsed["poh"],
             parsed["reallocated"], parsed["pending"], parsed["uncorrectable"],
             json.dumps(parsed["attributes"]))
        )
        return cur.lastrowid


def _save_attributes(snapshot_id: int, disk_id: int, attributes: List[Dict]):
    with get_db() as db:
        for a in attributes:
            db.execute(
                "INSERT INTO smart_attributes"
                "(snapshot_id,disk_id,attr_id,attr_name,value,worst,threshold,raw_value,raw_string) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (snapshot_id, disk_id, a["id"], a["name"],
                 a["value"], a["worst"], a["threshold"],
                 a["raw_value"], a["raw_string"])
            )


def _check_and_alert(disk_id: int, health: str, parsed: Dict):
    """Create alert entries for WARNING/CRITICAL/FAILED disks."""
    if health == "GOOD":
        return
    messages = []
    if parsed["reallocated"] > 0:
        messages.append(f"Reallocated sectors: {parsed['reallocated']}")
    if parsed["pending"] > 0:
        messages.append(f"Pending sectors: {parsed['pending']}")
    if parsed["uncorrectable"] > 0:
        messages.append(f"Uncorrectable sectors: {parsed['uncorrectable']}")
    if parsed["temp"] and parsed["temp"] >= TEMP_WARNING:
        messages.append(f"Temperature: {parsed['temp']}°C")
    if parsed["overall_status"] == "FAILED":
        messages.append("SMART self-assessment: FAILED")
    if not messages:
        messages.append(f"Health degraded: {health}")
    with get_db() as db:
        db.execute(
            "INSERT INTO disk_alerts(disk_id,level,message) VALUES (?,?,?)",
            (disk_id, health, "; ".join(messages))
        )


# ── SSH-Host disk import ─────────────────────────────────────────────────────

def collect_ssh_host_disks(host_name: str, host_ip: str, user: str,
                           port: int = 22, password: str = None,
                           key_path: str = None) -> List[Dict]:
    """
    Connect to a remote Linux host via SSH, run lsblk + smartctl,
    and import all disks into the SMART registry.
    Returns list of imported disk dicts.
    """
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = dict(hostname=host_ip, username=user, port=port, timeout=10)
        if key_path and Path(key_path).exists():
            connect_kwargs["key_filename"] = key_path
        elif password:
            connect_kwargs["password"] = password
        else:
            # Try default key
            default_key = Path.home() / ".ssh" / "id_rsa"
            if default_key.exists():
                connect_kwargs["key_filename"] = str(default_key)
        ssh.connect(**connect_kwargs)
    except Exception as exc:
        logger.warning("[smart_manager] SSH connect failed for %s (%s): %s", host_name, host_ip, exc)
        return []

    results = []
    try:
        # Discover disks via lsblk
        _, stdout, _ = ssh.exec_command("lsblk -J -d -o NAME,SIZE,MODEL,TYPE 2>/dev/null", timeout=10)
        raw = stdout.read().decode(errors="replace")
        try:
            devices = [d["name"] for d in json.loads(raw).get("blockdevices", [])
                       if d.get("type") == "disk"]
        except Exception:
            devices = []

        for dev in devices:
            try:
                # Get SMART info
                _, so, _ = ssh.exec_command(f"sudo smartctl -a /dev/{dev} 2>/dev/null", timeout=20)
                smart_out = so.read().decode(errors="replace")
                _, si, _ = ssh.exec_command(f"sudo smartctl -i /dev/{dev} 2>/dev/null", timeout=10)
                info_out = si.read().decode(errors="replace")

                serial, model, size_gb = None, None, None
                for line in info_out.splitlines():
                    if "Serial Number" in line:
                        serial = line.split(":", 1)[1].strip()
                    elif "Device Model" in line or "Model Number" in line:
                        model = line.split(":", 1)[1].strip()
                    elif "User Capacity" in line:
                        m = re.search(r"([\d,]+)\s+bytes", line)
                        if m:
                            size_gb = round(int(m.group(1).replace(",", "")) / 1e9, 1)

                # Use host_name as source_id so we know which host this disk belongs to
                disk_id = register_disk(
                    source="ssh_host",
                    device=f"{host_name}:{dev}",
                    serial=serial,
                    model=model,
                    size_gb=size_gb,
                    source_id=host_name
                )

                parsed = parse_smartctl_output(smart_out)
                health = classify_health(parsed)
                snapshot_id = _save_snapshot(disk_id, parsed, health)
                _save_attributes(snapshot_id, disk_id, parsed["attributes"])
                _check_and_alert(disk_id, health, parsed)

                results.append({
                    "disk_id": disk_id,
                    "host": host_name,
                    "device": dev,
                    "serial": serial,
                    "model": model,
                    "health": health,
                    "temp": parsed["temp"],
                    "poh": parsed["poh"],
                })
            except Exception as exc:
                logger.warning("[smart_manager] SSH SMART failed for %s:/dev/%s: %s", host_name, dev, exc)
    finally:
        ssh.close()

    logger.info("[smart_manager] SSH import: %d disk(s) from %s (%s)",
                len(results), host_name, host_ip)
    return results


def collect_all_ssh_hosts() -> List[Dict]:
    """
    Import disks from all configured SSH hosts in hosts.json.
    Skips localhost and hosts without SSH key or password.
    """
    results = []
    try:
        import json as _json
        hosts_file = Path(__file__).parent / "hosts.json"
        if not hosts_file.exists():
            return results
        with open(hosts_file) as f:
            hosts = _json.load(f)
        for name, h in hosts.items():
            ip = h.get("host", "")
            user = h.get("user", "root")
            port = int(h.get("port", 22))
            # Skip localhost
            if ip in ("localhost", "127.0.0.1", "::1", ""):
                continue
            key_path = h.get("ssh_key") or str(Path.home() / ".ssh" / "id_rsa")
            try:
                r = collect_ssh_host_disks(
                    host_name=name, host_ip=ip, user=user,
                    port=port, key_path=key_path
                )
                results.extend(r)
            except Exception as exc:
                logger.warning("[smart_manager] SSH host %s failed: %s", name, exc)
    except Exception as exc:
        logger.error("[smart_manager] collect_all_ssh_hosts error: %s", exc)
    return results


# ── Collect all local disks ───────────────────────────────────────────────────

def collect_all_local_disks() -> List[Dict]:
    """Discover and collect SMART data for all local disks."""
    try:
        import json as _json
        res = subprocess.run(
            ["lsblk", "-J", "-d", "-o", "NAME,SIZE,MODEL,TYPE"],
            capture_output=True, text=True, timeout=10
        )
        data = _json.loads(res.stdout)
        devices = [d["name"] for d in data.get("blockdevices", [])
                   if d.get("type") == "disk"]
    except Exception:
        devices = []

    results = []
    for dev in devices:
        try:
            r = collect_local_disk(dev)
            if r:
                results.append(r)
        except Exception as exc:
            logger.warning("SMART collection failed for %s: %s", dev, exc)
    return results


# ── Remote disk integration ───────────────────────────────────────────────────

def collect_remote_storage_disks(ep_id: int):
    """Collect disk health from a storage_controller endpoint (TrueNAS/Unraid)."""
    try:
        import storage_controller as sc
        client = sc.connect(ep_id)
        ep = sc.get_endpoint(ep_id)
        platform = ep["platform"]
        disks = client.get_disk_summary()
        for d in disks:
            disk_id = register_disk(
                source=platform,
                device=d["name"],
                serial=d.get("serial"),
                model=d.get("model"),
                size_gb=d.get("size_gb"),
                source_id=str(ep_id)
            )
            health_map = {
                "GOOD": "GOOD", "OK": "GOOD",
                "WARNING": "WARNING",
                "CRITICAL": "CRITICAL", "ERROR": "CRITICAL",
                "FAILED": "FAILED",
                "NOT_PRESENT": "UNKNOWN", "DISABLED": "UNKNOWN",
            }
            health = health_map.get(d.get("health", "UNKNOWN").upper(), "UNKNOWN")
            parsed = {
                "overall_status": "PASSED" if health == "GOOD" else "UNKNOWN",
                "temp": d.get("temp"),
                "poh": None,
                "reallocated": 0,
                "pending": 0,
                "uncorrectable": 0,
                "attributes": [],
            }
            _save_snapshot(disk_id, parsed, health)
            sc.log_disk_snapshot(ep_id, d)
        logger.info("[smart_manager] Collected %d remote disks from %s ep %d",
                    len(disks), platform, ep_id)
    except Exception as exc:
        logger.error("[smart_manager] Remote collection failed for ep %d: %s", ep_id, exc)


def collect_proxmox_disks(ep_id: int, node: str):
    """Collect disk SMART data from a Proxmox node."""
    try:
        import vm_controller as vc
        disks = vc.get_proxmox_disks(ep_id, node)
        for d in disks:
            dev_name = d.get("dev", d.get("devpath", "")).lstrip("/dev/")
            if not dev_name:
                continue
            disk_id = register_disk(
                source="proxmox",
                device=dev_name,
                serial=d.get("serial"),
                model=d.get("model"),
                size_gb=round(d.get("size", 0) / 1e9, 1) if d.get("size") else None,
                source_id=str(ep_id)
            )
            # Try to get SMART data from Proxmox API
            smart_data = vc.get_proxmox_disk_smart(ep_id, node, d.get("dev", ""))
            attrs_raw = smart_data.get("attributes", [])
            parsed = {
                "overall_status": smart_data.get("health", "UNKNOWN"),
                "temp": None, "poh": None,
                "reallocated": 0, "pending": 0, "uncorrectable": 0,
                "attributes": [],
            }
            for a in attrs_raw:
                attr_id = a.get("id", 0)
                raw_val = a.get("raw", 0)
                parsed["attributes"].append({
                    "id": attr_id,
                    "name": a.get("name", ""),
                    "value": a.get("value", 0),
                    "worst": a.get("worst", 0),
                    "threshold": a.get("threshold", 0),
                    "raw_value": raw_val,
                    "raw_string": str(raw_val),
                })
                if attr_id == 194:
                    parsed["temp"] = raw_val
                elif attr_id == 9:
                    parsed["poh"] = raw_val
                elif attr_id == 5:
                    parsed["reallocated"] = raw_val
                elif attr_id == 197:
                    parsed["pending"] = raw_val
                elif attr_id == 198:
                    parsed["uncorrectable"] = raw_val
            health = classify_health(parsed)
            snapshot_id = _save_snapshot(disk_id, parsed, health)
            _save_attributes(snapshot_id, disk_id, parsed["attributes"])
    except Exception as exc:
        logger.error("[smart_manager] Proxmox disk collection failed for ep %d: %s", ep_id, exc)


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_disk_snapshots(disk_id: int, limit: int = 50) -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM smart_snapshots WHERE disk_id=? ORDER BY ts DESC LIMIT ?",
            (disk_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_disk_attributes(disk_id: int, attr_id: int = None,
                        limit: int = 100) -> List[Dict]:
    """Get attribute history for a disk, optionally filtered by attribute ID."""
    with get_db() as db:
        if attr_id is not None:
            rows = db.execute(
                "SELECT * FROM smart_attributes WHERE disk_id=? AND attr_id=? "
                "ORDER BY ts DESC LIMIT ?",
                (disk_id, attr_id, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM smart_attributes WHERE disk_id=? "
                "ORDER BY ts DESC LIMIT ?",
                (disk_id, limit)
            ).fetchall()
    return [dict(r) for r in rows]


def get_active_alerts(acknowledged: bool = False) -> List[Dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT a.*, r.device, r.model, r.serial, r.source "
            "FROM disk_alerts a JOIN disk_registry r ON a.disk_id=r.id "
            "WHERE a.acknowledged=? ORDER BY a.ts DESC",
            (1 if acknowledged else 0,)
        ).fetchall()
    return [dict(r) for r in rows]


def acknowledge_alert(alert_id: int):
    with get_db() as db:
        db.execute("UPDATE disk_alerts SET acknowledged=1 WHERE id=?", (alert_id,))


def get_health_summary() -> Dict:
    """Return counts by health status for the dashboard."""
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM disk_registry").fetchone()[0]
        rows = db.execute(
            "SELECT r.id, "
            "  (SELECT health FROM smart_snapshots WHERE disk_id=r.id ORDER BY ts DESC LIMIT 1) AS h "
            "FROM disk_registry r"
        ).fetchall()
    counts = {"GOOD": 0, "WARNING": 0, "CRITICAL": 0, "FAILED": 0, "UNKNOWN": 0}
    for row in rows:
        h = row["h"] or "UNKNOWN"
        counts[h] = counts.get(h, 0) + 1
    active_alerts = len(get_active_alerts())
    return {
        "total": total,
        "counts": counts,
        "active_alerts": active_alerts,
    }


def get_poll_config() -> Dict:
    with get_db() as db:
        row = db.execute("SELECT * FROM poll_config WHERE id=1").fetchone()
    return dict(row) if row else {"interval_minutes": 60, "enabled": 1}


def set_poll_config(interval_minutes: int, enabled: bool):
    with get_db() as db:
        db.execute(
            "UPDATE poll_config SET interval_minutes=?, enabled=? WHERE id=1",
            (interval_minutes, 1 if enabled else 0)
        )


# ── Background polling ────────────────────────────────────────────────────────

_poll_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _poll_worker():
    logger.info("[smart_manager] Poll worker started")
    while not _stop_event.is_set():
        cfg = get_poll_config()
        if cfg.get("enabled", 1):
            logger.info("[smart_manager] Running scheduled SMART poll (all sources)")
            try:
                # 1. Local disks
                collect_all_local_disks()

                # 2. SSH-configured hosts
                try:
                    collect_all_ssh_hosts()
                except Exception as exc:
                    logger.error("[smart_manager] SSH hosts poll error: %s", exc)

                # 3. Proxmox endpoints
                try:
                    import vm_controller as _vc
                    for ep in _vc.list_endpoints():
                        if ep.get("platform") == "proxmox" and ep.get("enabled", 1):
                            try:
                                client = _vc.connect(ep["id"])
                                for node in client.get_nodes():
                                    collect_proxmox_disks(ep["id"], node["node"])
                            except Exception as exc:
                                logger.warning("[smart_manager] Proxmox ep %d poll error: %s", ep["id"], exc)
                except Exception as exc:
                    logger.error("[smart_manager] Proxmox poll error: %s", exc)

                # 4. Storage endpoints (TrueNAS / Unraid)
                try:
                    import storage_controller as _sc
                    for ep in _sc.list_endpoints():
                        if ep.get("enabled", 1):
                            try:
                                collect_remote_storage_disks(ep["id"])
                            except Exception as exc:
                                logger.warning("[smart_manager] Storage ep %d poll error: %s", ep["id"], exc)
                except Exception as exc:
                    logger.error("[smart_manager] Storage poll error: %s", exc)

                # Update last_poll timestamp
                with get_db() as db:
                    db.execute(
                        "UPDATE poll_config SET last_poll=CURRENT_TIMESTAMP WHERE id=1"
                    )
            except Exception as exc:
                logger.error("[smart_manager] Poll error: %s", exc)
        interval = cfg.get("interval_minutes", 60) * 60
        _stop_event.wait(timeout=interval)
    logger.info("[smart_manager] Poll worker stopped")


def start_polling():
    global _poll_thread
    if _poll_thread and _poll_thread.is_alive():
        return
    _stop_event.clear()
    _poll_thread = threading.Thread(target=_poll_worker, daemon=True,
                                    name="smart_poll_worker")
    _poll_thread.start()


def stop_polling():
    _stop_event.set()
