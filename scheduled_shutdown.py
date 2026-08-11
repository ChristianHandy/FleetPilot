"""
scheduled_shutdown.py — Scheduled power-off for remote hosts via SSH.

Stores schedules in DATA_DIR/scheduled_shutdown.db.
A background thread checks every minute whether any schedule is due and
executes the shutdown command via SSH.
"""

import sqlite3
import threading
import time
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

import paramiko

logger = logging.getLogger(__name__)

_DB_FILE: Optional[Path] = None
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_running = False

DAYS_OF_WEEK = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def _get_db():
    conn = sqlite3.connect(str(_DB_FILE), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: str):
    global _DB_FILE
    _DB_FILE = Path(data_dir) / 'scheduled_shutdown.db'
    with _get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                host        TEXT NOT NULL,
                port        INTEGER DEFAULT 22,
                username    TEXT DEFAULT 'root',
                password    TEXT,
                ssh_key     TEXT,
                shutdown_time TEXT NOT NULL,
                days        TEXT NOT NULL DEFAULT '["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]',
                enabled     INTEGER DEFAULT 1,
                warn_minutes INTEGER DEFAULT 5,
                action      TEXT DEFAULT 'shutdown',
                last_run    TEXT,
                last_status TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS shutdown_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER,
                host        TEXT,
                action      TEXT,
                status      TEXT,
                message     TEXT,
                ts          TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    logger.info('scheduled_shutdown: DB initialised at %s', _DB_FILE)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def list_schedules() -> List[Dict]:
    with _get_db() as conn:
        rows = conn.execute('SELECT * FROM schedules ORDER BY shutdown_time').fetchall()
    return [dict(r) for r in rows]


def get_schedule(sid: int) -> Optional[Dict]:
    with _get_db() as conn:
        row = conn.execute('SELECT * FROM schedules WHERE id=?', (sid,)).fetchone()
    return dict(row) if row else None


def add_schedule(name, host, port, username, password, ssh_key,
                 shutdown_time, days, enabled, warn_minutes, action) -> int:
    days_json = json.dumps(days) if isinstance(days, list) else days
    with _get_db() as conn:
        cur = conn.execute(
            '''INSERT INTO schedules
               (name,host,port,username,password,ssh_key,shutdown_time,days,enabled,warn_minutes,action)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (name, host, port, username, password, ssh_key,
             shutdown_time, days_json, int(enabled), warn_minutes, action)
        )
        conn.commit()
        return cur.lastrowid


def update_schedule(sid, **kwargs):
    if 'days' in kwargs and isinstance(kwargs['days'], list):
        kwargs['days'] = json.dumps(kwargs['days'])
    sets = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [sid]
    with _get_db() as conn:
        conn.execute(f'UPDATE schedules SET {sets} WHERE id=?', vals)
        conn.commit()


def delete_schedule(sid: int):
    with _get_db() as conn:
        conn.execute('DELETE FROM schedules WHERE id=?', (sid,))
        conn.execute('DELETE FROM shutdown_log WHERE schedule_id=?', (sid,))
        conn.commit()


def get_log(sid: int = None, limit: int = 50) -> List[Dict]:
    with _get_db() as conn:
        if sid:
            rows = conn.execute(
                'SELECT * FROM shutdown_log WHERE schedule_id=? ORDER BY ts DESC LIMIT ?',
                (sid, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM shutdown_log ORDER BY ts DESC LIMIT ?', (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


# ── Execution ─────────────────────────────────────────────────────────────────

def _execute_action(schedule: Dict) -> tuple:
    """SSH into host and run shutdown/reboot/suspend command."""
    host = schedule['host']
    port = schedule.get('port', 22)
    user = schedule.get('username', 'root')
    pwd  = schedule.get('password', '')
    key  = schedule.get('ssh_key', '')
    action = schedule.get('action', 'shutdown')

    cmd_map = {
        'shutdown':  'shutdown -h now',
        'reboot':    'shutdown -r now',
        'suspend':   'systemctl suspend',
        'hibernate': 'systemctl hibernate',
    }
    cmd = cmd_map.get(action, 'shutdown -h now')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())  # nosec B507
    try:
        connect_kwargs = dict(hostname=host, port=port, username=user, timeout=15)
        if key:
            connect_kwargs['key_filename'] = key
        elif pwd:
            connect_kwargs['password'] = pwd
        client.connect(**connect_kwargs)
        _, stdout, stderr = client.exec_command(cmd, timeout=10)
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        client.close()
        return True, f'Command: {cmd} | out: {out} | err: {err}'
    except Exception as e:
        return False, str(e)
    finally:
        client.close()


def _log_run(schedule_id, host, action, status, message):
    with _get_db() as conn:
        conn.execute(
            'INSERT INTO shutdown_log (schedule_id,host,action,status,message) VALUES (?,?,?,?,?)',
            (schedule_id, host, action, status, message)
        )
        conn.execute(
            'UPDATE schedules SET last_run=?, last_status=? WHERE id=?',
            (datetime.now().strftime('%Y-%m-%d %H:%M'), status, schedule_id)
        )
        conn.commit()


# ── Background thread ─────────────────────────────────────────────────────────

def _scheduler_loop():
    global _running
    logger.info('scheduled_shutdown: background thread started')
    # Track which schedules already fired this minute
    fired: Dict[int, str] = {}  # id -> "YYYY-MM-DD HH:MM"

    while _running:
        try:
            now = datetime.now()
            current_minute = now.strftime('%Y-%m-%d %H:%M')
            current_time   = now.strftime('%H:%M')
            current_day    = DAYS_OF_WEEK[now.weekday()]

            schedules = list_schedules()
            for s in schedules:
                if not s['enabled']:
                    continue
                if s['shutdown_time'] != current_time:
                    continue
                try:
                    days = json.loads(s['days']) if isinstance(s['days'], str) else s['days']
                except Exception:
                    days = DAYS_OF_WEEK
                if current_day not in days:
                    continue
                # Already fired this minute?
                if fired.get(s['id']) == current_minute:
                    continue

                logger.info('scheduled_shutdown: firing %s → %s (%s)',
                            s['name'], s['host'], s['action'])
                fired[s['id']] = current_minute
                ok, msg = _execute_action(s)
                status = 'success' if ok else 'error'
                _log_run(s['id'], s['host'], s['action'], status, msg)
                logger.info('scheduled_shutdown: %s %s — %s', s['host'], status, msg[:120])

        except Exception as e:
            logger.error('scheduled_shutdown loop error: %s', e)

        time.sleep(30)  # check every 30 seconds


def start_polling():
    global _thread, _running
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_scheduler_loop, daemon=True, name='shutdown-scheduler')
    _thread.start()


def stop_polling():
    global _running
    _running = False
