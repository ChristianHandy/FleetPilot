"""
system_monitor.py — FleetPilot System Resource & Temperature Monitor
Collects CPU, RAM, disk, network and temperature metrics every 60 seconds.
Stores history in a SQLite database (DATA_DIR/system_monitor.db).
"""
import os
import sqlite3
import threading
import time
import json
import logging

logger = logging.getLogger(__name__)

# DATA_DIR is injected at init time
_DB_PATH = None
_poll_thread = None
_poll_running = False
_POLL_INTERVAL = 60  # seconds between samples
_RETENTION_DAYS = 30  # keep 30 days of history


# ── Database helpers ──────────────────────────────────────────────────────────

def _get_db():
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: str):
    global _DB_PATH
    _DB_PATH = os.path.join(data_dir, 'system_monitor.db')
    with _get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS monitor_samples (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          INTEGER NOT NULL,
                cpu_pct     REAL,
                cpu_freq    REAL,
                ram_total   INTEGER,
                ram_used    INTEGER,
                ram_pct     REAL,
                swap_total  INTEGER,
                swap_used   INTEGER,
                disk_json   TEXT,
                net_json    TEXT,
                temp_json   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_monitor_ts ON monitor_samples(ts);
        """)
    logger.info("system_monitor DB initialised at %s", _DB_PATH)


def _purge_old():
    cutoff = int(time.time()) - _RETENTION_DAYS * 86400
    with _get_db() as conn:
        conn.execute("DELETE FROM monitor_samples WHERE ts < ?", (cutoff,))


# ── Metric collection ─────────────────────────────────────────────────────────

def _collect():
    """Collect all metrics. Returns a dict or None on failure."""
    try:
        import psutil
    except ImportError:
        return None

    ts = int(time.time())

    # CPU
    cpu_pct = psutil.cpu_percent(interval=1)
    try:
        freq = psutil.cpu_freq()
        cpu_freq = round(freq.current, 1) if freq else None
    except Exception:
        cpu_freq = None

    # RAM
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Disks
    disks = []
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    'device': part.device,
                    'mountpoint': part.mountpoint,
                    'fstype': part.fstype,
                    'total': usage.total,
                    'used': usage.used,
                    'free': usage.free,
                    'pct': usage.percent,
                })
            except PermissionError:
                pass
    except Exception:
        pass

    # Network I/O
    net = {}
    try:
        counters = psutil.net_io_counters(pernic=False)
        net = {
            'bytes_sent': counters.bytes_sent,
            'bytes_recv': counters.bytes_recv,
            'packets_sent': counters.packets_sent,
            'packets_recv': counters.packets_recv,
        }
    except Exception:
        pass

    # Temperatures
    temps = {}
    try:
        raw = psutil.sensors_temperatures()
        for sensor, entries in raw.items():
            temps[sensor] = [
                {'label': e.label or sensor, 'current': e.current,
                 'high': e.high, 'critical': e.critical}
                for e in entries
            ]
    except (AttributeError, Exception):
        pass

    return {
        'ts': ts,
        'cpu_pct': round(cpu_pct, 1),
        'cpu_freq': cpu_freq,
        'ram_total': mem.total,
        'ram_used': mem.used,
        'ram_pct': round(mem.percent, 1),
        'swap_total': swap.total,
        'swap_used': swap.used,
        'disk_json': json.dumps(disks),
        'net_json': json.dumps(net),
        'temp_json': json.dumps(temps),
    }


def _save(sample: dict):
    with _get_db() as conn:
        conn.execute("""
            INSERT INTO monitor_samples
              (ts, cpu_pct, cpu_freq, ram_total, ram_used, ram_pct,
               swap_total, swap_used, disk_json, net_json, temp_json)
            VALUES
              (:ts, :cpu_pct, :cpu_freq, :ram_total, :ram_used, :ram_pct,
               :swap_total, :swap_used, :disk_json, :net_json, :temp_json)
        """, sample)


# ── Background polling thread ─────────────────────────────────────────────────

def _poll_loop():
    global _poll_running
    while _poll_running:
        try:
            sample = _collect()
            if sample:
                _save(sample)
                _purge_old()
        except Exception as exc:
            logger.warning("system_monitor poll error: %s", exc)
        time.sleep(_POLL_INTERVAL)


def start_polling():
    global _poll_thread, _poll_running
    if _poll_thread and _poll_thread.is_alive():
        return
    _poll_running = True
    _poll_thread = threading.Thread(target=_poll_loop, daemon=True, name='sys-monitor')
    _poll_thread.start()
    logger.info("system_monitor polling started (interval=%ds)", _POLL_INTERVAL)


def stop_polling():
    global _poll_running
    _poll_running = False


# ── Query API ─────────────────────────────────────────────────────────────────

def get_latest():
    """Return the most recent sample as a dict, or None."""
    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_samples ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def get_history(hours: int = 24, limit: int = 1440):
    """Return up to `limit` samples from the last `hours` hours."""
    since = int(time.time()) - hours * 3600
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM monitor_samples WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
            (since, limit)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_log(page: int = 1, per_page: int = 100):
    """Return paginated log entries (newest first)."""
    offset = (page - 1) * per_page
    with _get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM monitor_samples").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM monitor_samples ORDER BY ts DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
    return {
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page,
        'items': [_row_to_dict(r) for r in rows],
    }


def _row_to_dict(row) -> dict:
    d = dict(row)
    for field in ('disk_json', 'net_json', 'temp_json'):
        try:
            d[field.replace('_json', '')] = json.loads(d.pop(field) or '{}')
        except Exception:
            d[field.replace('_json', '')] = {}
    return d
