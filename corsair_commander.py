"""
corsair_commander.py — FleetPilot Corsair Commander Pro Integration
Manages Corsair Commander Pro (and compatible) devices connected to remote
hosts via SSH. Uses `liquidctl` on the remote host to read temperatures,
fan speeds, voltages and to set fan profiles.

Architecture:
  FleetPilot (Unraid) ──SSH──▶ Remote host ──USB──▶ Commander Pro

Requirements on the remote host:
  - liquidctl >= 1.11.1  (pip install liquidctl  or  apt install liquidctl)
  - udev rule or root access so liquidctl can access the USB device
  - SSH access (key or password) from the FleetPilot server

Database: DATA_DIR/corsair_commander.db
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Encryption helpers (same pattern as vm_controller) ───────────────────────
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

# ── Module state ─────────────────────────────────────────────────────────────
_DB_FILE: Optional[Path] = None
_poll_thread: Optional[threading.Thread] = None
_poll_running = False
_POLL_INTERVAL = 30   # seconds between status polls
_RETENTION_DAYS = 30

# ── Database ─────────────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(str(_DB_FILE), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: str):
    global _DB_FILE
    _DB_FILE = Path(data_dir) / "corsair_commander.db"
    with _get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS cc_devices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            host        TEXT NOT NULL,
            port        INTEGER DEFAULT 22,
            username    TEXT NOT NULL DEFAULT 'root',
            password    TEXT NOT NULL DEFAULT '',
            ssh_key     TEXT NOT NULL DEFAULT '',
            match_str   TEXT NOT NULL DEFAULT 'Commander Pro',
            use_direct  INTEGER DEFAULT 0,
            use_sudo    INTEGER DEFAULT 0,
            enabled     INTEGER DEFAULT 1,
            notes       TEXT DEFAULT '',
            added_ts    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS _cc_migrations(name TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS cc_samples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   INTEGER NOT NULL,
            ts          INTEGER NOT NULL,
            status_json TEXT NOT NULL,
            FOREIGN KEY(device_id) REFERENCES cc_devices(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cc_samples_ts ON cc_samples(device_id, ts);
        """)
    # Run migrations
    with _get_db() as db:
        try:
            db.execute("ALTER TABLE cc_devices ADD COLUMN use_sudo INTEGER DEFAULT 0")
            db.execute("INSERT OR IGNORE INTO _cc_migrations VALUES ('add_use_sudo')")
        except Exception:
            pass
    logger.info("corsair_commander DB initialised at %s", _DB_FILE)


# ── Device CRUD ───────────────────────────────────────────────────────────────

def add_device(name: str, host: str, port: int = 22, username: str = "root",
               password: str = "", ssh_key: str = "",
               match_str: str = "Commander Pro", use_direct: bool = False,
               use_sudo: bool = False, notes: str = "") -> int:
    with _get_db() as db:
        cur = db.execute(
            "INSERT INTO cc_devices(name,host,port,username,password,ssh_key,"
            "match_str,use_direct,use_sudo,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name, host, port, username, _encrypt(password), ssh_key,
             match_str, 1 if use_direct else 0, 1 if use_sudo else 0, notes)
        )
        return cur.lastrowid


def list_devices() -> List[Dict]:
    with _get_db() as db:
        rows = db.execute(
            "SELECT * FROM cc_devices ORDER BY added_ts DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("password", None)
        result.append(d)
    return result


def get_device(dev_id: int) -> Optional[Dict]:
    with _get_db() as db:
        row = db.execute(
            "SELECT * FROM cc_devices WHERE id=?", (dev_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["password_plain"] = _decrypt(d["password"])
    except Exception:
        d["password_plain"] = ""
    return d


def update_device(dev_id: int, **kwargs) -> bool:
    allowed = {"name","host","port","username","password","ssh_key",
               "match_str","use_direct","use_sudo","enabled","notes"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if "password" in fields:
        fields["password"] = _encrypt(fields["password"])
    if not fields:
        return False
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with _get_db() as db:
        db.execute(
            f"UPDATE cc_devices SET {set_clause} WHERE id=?",
            list(fields.values()) + [dev_id]
        )
    return True


def delete_device(dev_id: int):
    with _get_db() as db:
        db.execute("DELETE FROM cc_devices WHERE id=?", (dev_id,))


# ── SSH helpers ───────────────────────────────────────────────────────────────

def _ssh_connect(dev: Dict):
    """Open a paramiko SSH connection to the device's host."""
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(
        hostname=dev["host"],
        port=dev.get("port", 22),
        username=dev.get("username", "root"),
        timeout=15,
    )
    pw = dev.get("password_plain") or dev.get("password", "")
    key_path = dev.get("ssh_key", "")
    if key_path and Path(key_path).exists():
        kwargs["key_filename"] = key_path
    elif pw:
        kwargs["password"] = pw
        kwargs["look_for_keys"] = False
        kwargs["allow_agent"] = False
    ssh.connect(**kwargs)
    return ssh


def _run_remote(ssh, cmd: str, timeout: int = 30) -> tuple:
    """Run a command on the remote host; returns (stdout, stderr, exit_code)."""
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return out, err, code


# ── liquidctl helpers ─────────────────────────────────────────────────────────

def _liquidctl_cmd(dev: Dict, subcmd: str) -> str:
    """Build a liquidctl command string for the given device."""
    match = dev.get("match_str", "Commander Pro")
    direct = "--direct-access" if dev.get("use_direct") else ""
    is_root = dev.get("username", "root") == "root"
    use_sudo = bool(dev.get("use_sudo", 0))
    sudo = "" if (is_root or not use_sudo) else "sudo "
    return f"{sudo}liquidctl --match '{match}' {direct} {subcmd} --json 2>/dev/null".strip()


def _parse_liquidctl_json(raw: str) -> List[Dict]:
    """Parse liquidctl --json output. Returns list of device result dicts."""
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return [data]
    except Exception:
        return []


def fetch_status(dev: Dict) -> Dict:
    """
    Connect to the remote host and run `liquidctl status --json`.
    Returns a structured dict:
    {
      "ok": bool,
      "error": str | None,
      "device": str,
      "temperatures": [{"label": str, "value": float, "unit": "°C"}],
      "fans": [{"label": str, "rpm": int}],
      "voltages": [{"label": str, "value": float, "unit": "V"}],
      "raw": [...],   # raw liquidctl JSON
      "ts": int
    }
    """
    result = {
        "ok": False,
        "error": None,
        "device": dev.get("name", ""),
        "temperatures": [],
        "fans": [],
        "voltages": [],
        "raw": [],
        "ts": int(time.time()),
    }
    ssh = None
    try:
        ssh = _ssh_connect(dev)

        # 1. Initialize (needed after boot / resume)
        init_cmd = _liquidctl_cmd(dev, "initialize")
        _run_remote(ssh, init_cmd, timeout=20)

        # 2. Status
        status_cmd = _liquidctl_cmd(dev, "status")
        out, err, code = _run_remote(ssh, status_cmd, timeout=20)

        if not out:
            # Fallback: try without --json flag and parse text output
            status_cmd_text = f"liquidctl --match '{dev.get('match_str','Commander Pro')}' status 2>&1"
            out_text, _, _ = _run_remote(ssh, status_cmd_text, timeout=20)
            result["raw"] = [{"text_output": out_text}]
            _parse_text_status(out_text, result)
        else:
            devices = _parse_liquidctl_json(out)
            result["raw"] = devices
            for device_data in devices:
                _parse_json_status(device_data, result)

        result["ok"] = True

    except Exception as exc:
        result["error"] = str(exc)
        logger.warning("[corsair_commander] fetch_status error for %s: %s",
                       dev.get("name"), exc)
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass

    return result


def _parse_json_status(device_data: Dict, result: Dict):
    """Parse a single device entry from liquidctl --json status output."""
    status_list = device_data.get("status", [])
    for item in status_list:
        key = item.get("key", "")
        value = item.get("value")
        unit = item.get("unit", "")

        if "Temperature" in key or unit == "°C":
            try:
                result["temperatures"].append({
                    "label": key,
                    "value": float(value),
                    "unit": "°C",
                })
            except (TypeError, ValueError):
                pass
        elif "speed" in key.lower() or unit == "rpm":
            try:
                result["fans"].append({
                    "label": key,
                    "rpm": int(float(value)),
                })
            except (TypeError, ValueError):
                pass
        elif "rail" in key.lower() or unit == "V":
            try:
                result["voltages"].append({
                    "label": key,
                    "value": float(value),
                    "unit": "V",
                })
            except (TypeError, ValueError):
                pass


def _parse_text_status(text: str, result: Dict):
    """Fallback: parse plain-text liquidctl status output."""
    for line in text.splitlines():
        line = line.strip().lstrip("├└│").strip()
        if not line or line.startswith("Corsair") or line.startswith("Device"):
            continue
        # Pattern: "Temperature 1     26.4  °C"
        m = re.match(r"(.+?)\s{2,}([\d.]+)\s+(°C|rpm|V|A)", line)
        if m:
            label, val_str, unit = m.group(1).strip(), m.group(2), m.group(3)
            try:
                val = float(val_str)
                if unit == "°C":
                    result["temperatures"].append({"label": label, "value": val, "unit": "°C"})
                elif unit == "rpm":
                    result["fans"].append({"label": label, "rpm": int(val)})
                elif unit == "V":
                    result["voltages"].append({"label": label, "value": val, "unit": "V"})
            except ValueError:
                pass


def set_fan_speed(dev: Dict, channel: str, speed) -> Dict:
    """
    Set fan speed on the Commander Pro.
    speed: int (fixed duty %) or list of (temp, rpm) pairs
    channel: 'fan1'..'fan6' or 'sync'
    Returns {"ok": bool, "message": str}
    """
    result = {"ok": False, "message": ""}
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        match = dev.get("match_str", "Commander Pro")
        direct = "--direct-access" if dev.get("use_direct") else ""

        if isinstance(speed, (int, float)):
            # Fixed duty
            cmd = f"liquidctl --match '{match}' {direct} set {channel} speed {int(speed)} --json 2>&1"
        elif isinstance(speed, list):
            # Temperature profile: [(temp, rpm), ...]
            pairs = " ".join(f"{t} {r}" for t, r in speed)
            cmd = f"liquidctl --match '{match}' {direct} set {channel} speed {pairs} --json 2>&1"
        else:
            result["message"] = "Invalid speed format"
            return result

        out, err, code = _run_remote(ssh, cmd.strip(), timeout=30)
        result["ok"] = (code == 0)
        result["message"] = out or err or ("OK" if code == 0 else "Error")
    except Exception as exc:
        result["message"] = str(exc)
        logger.warning("[corsair_commander] set_fan_speed error for %s: %s",
                       dev.get("name"), exc)
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass
    return result


def test_connection(dev_id: int) -> Dict:
    """Test SSH + liquidctl connectivity for a device."""
    dev = get_device(dev_id)
    if not dev:
        return {"ok": False, "message": "Device not found"}
    ssh = None
    try:
        ssh = _ssh_connect(dev)
        # Check liquidctl is installed
        out, _, code = _run_remote(ssh, "liquidctl --version 2>&1", timeout=10)
        if code != 0:
            return {"ok": False, "message": f"liquidctl not found on remote host: {out}"}
        # List devices
        match = dev.get("match_str", "Commander Pro")
        list_out, _, _ = _run_remote(ssh, f"liquidctl list --json 2>/dev/null", timeout=10)
        devices = _parse_liquidctl_json(list_out)
        found = [d for d in devices if match.lower() in str(d).lower()]
        if not found:
            return {
                "ok": False,
                "message": f"No device matching '{match}' found. Available: {list_out[:200]}"
            }
        return {"ok": True, "message": f"Connected. Found {len(found)} matching device(s). liquidctl {out}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


# ── Background polling ────────────────────────────────────────────────────────

def _save_sample(device_id: int, status: Dict):
    with _get_db() as db:
        db.execute(
            "INSERT INTO cc_samples(device_id, ts, status_json) VALUES (?,?,?)",
            (device_id, status["ts"], json.dumps(status))
        )


def _purge_old():
    cutoff = int(time.time()) - _RETENTION_DAYS * 86400
    with _get_db() as db:
        db.execute("DELETE FROM cc_samples WHERE ts < ?", (cutoff,))


def _poll_loop():
    global _poll_running
    while _poll_running:
        try:
            with _get_db() as db:
                devices = db.execute(
                    "SELECT * FROM cc_devices WHERE enabled=1"
                ).fetchall()
            for row in devices:
                dev = dict(row)
                try:
                    dev["password_plain"] = _decrypt(dev["password"])
                except Exception:
                    dev["password_plain"] = ""
                status = fetch_status(dev)
                _save_sample(dev["id"], status)
            _purge_old()
        except Exception as exc:
            logger.warning("[corsair_commander] poll loop error: %s", exc)
        time.sleep(_POLL_INTERVAL)


def start_polling():
    global _poll_thread, _poll_running
    if _poll_thread and _poll_thread.is_alive():
        return
    _poll_running = True
    _poll_thread = threading.Thread(
        target=_poll_loop, daemon=True, name="corsair-commander-poll"
    )
    _poll_thread.start()
    logger.info("corsair_commander polling started (interval=%ds)", _POLL_INTERVAL)


def stop_polling():
    global _poll_running
    _poll_running = False


# ── Query API ─────────────────────────────────────────────────────────────────

def get_latest(device_id: int) -> Optional[Dict]:
    """Return the most recent sample for a device."""
    with _get_db() as db:
        row = db.execute(
            "SELECT * FROM cc_samples WHERE device_id=? ORDER BY ts DESC LIMIT 1",
            (device_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["status"] = json.loads(d.pop("status_json"))
    except Exception:
        d["status"] = {}
    return d


def get_history(device_id: int, hours: int = 24, limit: int = 1440) -> List[Dict]:
    """Return up to `limit` samples from the last `hours` hours."""
    since = int(time.time()) - hours * 3600
    with _get_db() as db:
        rows = db.execute(
            "SELECT * FROM cc_samples WHERE device_id=? AND ts>=? "
            "ORDER BY ts ASC LIMIT ?",
            (device_id, since, limit)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["status"] = json.loads(d.pop("status_json"))
        except Exception:
            d["status"] = {}
        result.append(d)
    return result


def get_all_latest() -> List[Dict]:
    """Return the latest sample for every enabled device."""
    devices = list_devices()
    result = []
    for dev in devices:
        if not dev.get("enabled"):
            continue
        latest = get_latest(dev["id"])
        result.append({
            "device": dev,
            "latest": latest,
        })
    return result
