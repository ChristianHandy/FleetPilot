"""
account_security.py — server-side sessions, personal API tokens and security settings.

Sessions: every sign-in gets a random session id that lives in the signed
cookie; the server keeps only its SHA-256 hash.  A session is valid while its
row exists, is not revoked and has been used within the idle timeout, so users
and admins can end sessions on other devices.

API tokens: ``fp_`` + 43 random characters, shown once and stored as a hash.
A token acts as its owner, limited to the JSON API and, for ``read`` tokens,
to GET requests.

Settings live in DATA_DIR/security_settings.json and are cached by mtime.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import threading
import time

import user_management

TOKEN_PREFIX = 'fp_'
TOKEN_SCOPES = ('read', 'write')
TOUCH_INTERVAL = 60            # seconds between last_seen writes for one session
ABSOLUTE_SESSION_DAYS = 30     # rows older than this are pruned

DEFAULT_SETTINGS = {
    'require_2fa_admins': False,
    'idle_minutes': 120,        # 0 turns the idle timeout off
    'reauth_minutes': 10,       # how long a password confirmation unlocks sensitive actions
    'ip_allowlist': [],         # CIDRs; empty means every address may connect
    'audit_retention_days': 365,
    'max_token_days': 365,      # 0 allows tokens that never expire
}

_settings_cache = {'mtime': None, 'value': None}
_settings_lock = threading.Lock()


def _data_dir():
    return os.environ.get('FLEETPILOT_DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))


def _settings_path():
    return os.path.join(_data_dir(), 'security_settings.json')


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def init_db():
    with user_management.get_user_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS user_sessions(
          id         TEXT PRIMARY KEY,           -- sha256 of the session id in the cookie
          user_id    INTEGER NOT NULL,
          created_at REAL NOT NULL,
          last_seen  REAL NOT NULL,
          ip         TEXT NOT NULL DEFAULT '',
          user_agent TEXT NOT NULL DEFAULT '',
          method     TEXT NOT NULL DEFAULT 'password',
          revoked    INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);

        CREATE TABLE IF NOT EXISTS api_tokens(
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id      INTEGER NOT NULL,
          name         TEXT NOT NULL,
          prefix       TEXT NOT NULL,
          token_hash   TEXT NOT NULL UNIQUE,
          scope        TEXT NOT NULL DEFAULT 'read',
          created_at   REAL NOT NULL,
          expires_at   REAL,
          last_used_at REAL,
          last_used_ip TEXT NOT NULL DEFAULT '',
          revoked      INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);
        """)


# ── Settings ──────────────────────────────────────────────────────────────────

def clean_allowlist(entries):
    """Parse CIDR/IP strings. Returns (networks as strings, list of invalid entries)."""
    good, bad = [], []
    for raw in entries:
        entry = raw.strip()
        if not entry:
            continue
        try:
            good.append(str(ipaddress.ip_network(entry, strict=False)))
        except ValueError:
            bad.append(entry)
    return good, bad


def get_settings() -> dict:
    path = _settings_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return dict(DEFAULT_SETTINGS)
    with _settings_lock:
        if _settings_cache['mtime'] != mtime:
            try:
                with open(path) as fh:
                    stored = json.load(fh)
            except (OSError, ValueError):
                stored = {}
            value = dict(DEFAULT_SETTINGS)
            value.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
            _settings_cache.update(mtime=mtime, value=value)
        return dict(_settings_cache['value'])


def save_settings(changes: dict) -> dict:
    value = get_settings()
    value.update({k: v for k, v in changes.items() if k in DEFAULT_SETTINGS})
    value['require_2fa_admins'] = bool(value['require_2fa_admins'])
    for key, low, high in (('idle_minutes', 0, 1440), ('reauth_minutes', 1, 120),
                           ('audit_retention_days', 30, 3650), ('max_token_days', 0, 3650)):
        try:
            value[key] = max(low, min(int(value[key]), high))
        except (TypeError, ValueError):
            value[key] = DEFAULT_SETTINGS[key]
    value['ip_allowlist'], _ = clean_allowlist(value.get('ip_allowlist') or [])
    path = _settings_path()
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(value, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    with _settings_lock:
        _settings_cache['mtime'] = None
    return value


def ip_allowed(ip: str, allowlist=None) -> bool:
    """True if ``ip`` may use FleetPilot. Loopback is always allowed so the host can recover."""
    allowlist = get_settings()['ip_allowlist'] if allowlist is None else allowlist
    if not allowlist:
        return True
    try:
        addr = ipaddress.ip_address((ip or '').split('%', 1)[0])
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    if getattr(addr, 'ipv4_mapped', None):
        addr = addr.ipv4_mapped
    for net in allowlist:
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(user_id: int, ip: str = '', user_agent: str = '', method: str = 'password') -> str:
    sid = secrets.token_urlsafe(32)
    now = time.time()
    with user_management.get_user_db() as db:
        db.execute('DELETE FROM user_sessions WHERE created_at < ? OR revoked = 1 AND last_seen < ?',
                   (now - ABSOLUTE_SESSION_DAYS * 86400, now - 7 * 86400))
        db.execute('INSERT INTO user_sessions(id, user_id, created_at, last_seen, ip, user_agent, method) '
                   'VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (_hash(sid), user_id, now, now, (ip or '')[:64], (user_agent or '')[:300], method[:40]))
    return sid


def check_session(sid: str, user_id: int, ip: str = '') -> bool:
    """Validate a session id and record activity. Ends the session if it idled out."""
    if not sid:
        return False
    now = time.time()
    key = _hash(sid)
    with user_management.get_user_db() as db:
        row = db.execute('SELECT user_id, last_seen, revoked FROM user_sessions WHERE id = ?', (key,)).fetchone()
        if not row or row['revoked'] or row['user_id'] != user_id:
            return False
        idle = get_settings()['idle_minutes']
        if idle and now - row['last_seen'] > idle * 60:
            db.execute('UPDATE user_sessions SET revoked = 1 WHERE id = ?', (key,))
            return False
        if now - row['last_seen'] > TOUCH_INTERVAL:
            db.execute('UPDATE user_sessions SET last_seen = ?, ip = ? WHERE id = ?', (now, (ip or '')[:64], key))
    return True


def session_key(sid: str) -> str:
    return _hash(sid) if sid else ''


def list_sessions(user_id=None, include_ended=False):
    idle = get_settings()['idle_minutes']
    cutoff = time.time() - idle * 60 if idle else 0
    sql = ('SELECT s.*, u.username FROM user_sessions s JOIN users u ON u.id = s.user_id '
           'WHERE (? OR (s.revoked = 0 AND s.last_seen >= ?))')
    args = [1 if include_ended else 0, cutoff]
    if user_id is not None:
        sql += ' AND s.user_id = ?'
        args.append(user_id)
    with user_management.get_user_db() as db:
        return [dict(r) for r in db.execute(sql + ' ORDER BY s.last_seen DESC', args)]


def revoke_session(key: str, user_id=None) -> bool:
    sql, args = 'UPDATE user_sessions SET revoked = 1 WHERE id = ?', [key]
    if user_id is not None:
        sql += ' AND user_id = ?'
        args.append(user_id)
    with user_management.get_user_db() as db:
        return db.execute(sql, args).rowcount > 0


def revoke_user_sessions(user_id: int, keep_sid: str = '') -> int:
    with user_management.get_user_db() as db:
        return db.execute('UPDATE user_sessions SET revoked = 1 WHERE user_id = ? AND id != ? AND revoked = 0',
                          (user_id, session_key(keep_sid))).rowcount


def last_activity_by_user() -> dict:
    with user_management.get_user_db() as db:
        return {r['user_id']: r['seen'] for r in
                db.execute('SELECT user_id, MAX(last_seen) AS seen FROM user_sessions GROUP BY user_id')}


# ── API tokens ────────────────────────────────────────────────────────────────

def create_token(user_id: int, name: str, scope: str = 'read', days: int = 90):
    """Create a token. Returns (raw token, row id). The raw token is never stored."""
    if scope not in TOKEN_SCOPES:
        raise ValueError('Unknown token scope')
    name = (name or '').strip()[:64]
    if not name:
        raise ValueError('Give the token a name so you can recognise it later.')
    limit = get_settings()['max_token_days']
    days = int(days or 0)
    if limit and (days <= 0 or days > limit):
        raise ValueError(f'Tokens must expire within {limit} days.')
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = time.time()
    with user_management.get_user_db() as db:
        cur = db.execute('INSERT INTO api_tokens(user_id, name, prefix, token_hash, scope, created_at, expires_at) '
                         'VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (user_id, name, raw[:10], _hash(raw), scope, now, now + days * 86400 if days > 0 else None))
        return raw, cur.lastrowid


def verify_token(raw: str, ip: str = ''):
    """Return the token row (with username) for a valid token, else None."""
    if not raw or not raw.startswith(TOKEN_PREFIX) or len(raw) > 100:
        return None
    now = time.time()
    with user_management.get_user_db() as db:
        row = db.execute('SELECT t.*, u.username, u.active FROM api_tokens t JOIN users u ON u.id = t.user_id '
                         'WHERE t.token_hash = ?', (_hash(raw),)).fetchone()
        if not row or row['revoked'] or not row['active'] or (row['expires_at'] and row['expires_at'] < now):
            return None
        if not row['last_used_at'] or now - row['last_used_at'] > TOUCH_INTERVAL:
            db.execute('UPDATE api_tokens SET last_used_at = ?, last_used_ip = ? WHERE id = ?',
                       (now, (ip or '')[:64], row['id']))
        return dict(row)


def list_tokens(user_id=None):
    sql = ('SELECT t.id, t.user_id, t.name, t.prefix, t.scope, t.created_at, t.expires_at, t.last_used_at, '
           't.last_used_ip, t.revoked, u.username FROM api_tokens t JOIN users u ON u.id = t.user_id')
    args = []
    if user_id is not None:
        sql += ' WHERE t.user_id = ?'
        args.append(user_id)
    now = time.time()
    with user_management.get_user_db() as db:
        rows = [dict(r) for r in db.execute(sql + ' ORDER BY t.created_at DESC', args)]
    for r in rows:
        r['expired'] = bool(r['expires_at'] and r['expires_at'] < now)
    return rows


def revoke_token(token_id: int, user_id=None) -> bool:
    sql, args = 'UPDATE api_tokens SET revoked = 1 WHERE id = ?', [token_id]
    if user_id is not None:
        sql += ' AND user_id = ?'
        args.append(user_id)
    with user_management.get_user_db() as db:
        return db.execute(sql, args).rowcount > 0
