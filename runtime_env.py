"""
runtime_env.py — load configuration before any other FleetPilot module.

Several modules derive encryption keys from SECRET_KEY at import time, so
.env must be loaded and SECRET_KEY must exist before they are imported.
app.py imports this module first.
"""
import os
import secrets

_APP_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    # The repo-root .env (documented `cp .env.example .env` setup) wins; the
    # /opt/fleetpilot/.env path is kept for existing installs.
    for _env_path in (os.path.join(_APP_DIR, '.env'), '/opt/fleetpilot/.env'):
        if os.path.exists(_env_path):
            load_dotenv(_env_path, override=True)
            break
except ImportError:
    pass  # python-dotenv is optional

DATA_DIR = os.environ.get('FLEETPILOT_DATA_DIR', os.path.join(_APP_DIR, 'data'))


# Values from .env.example and old docs; they are public, so never use them as keys.
_PLACEHOLDER_SECRET_KEYS = {'your-secret-key-here', 'change-me', 'changeme'}


def _ensure_secret_key():
    """Use SECRET_KEY from the environment, or a generated key persisted in DATA_DIR."""
    current = os.environ.get('SECRET_KEY', '')
    if current and current not in _PLACEHOLDER_SECRET_KEYS:
        return
    if current:
        # Keep the old value around so credentials encrypted with it can still be read.
        os.environ['FLEETPILOT_LEGACY_SECRET_KEY'] = current
        print('WARNING: SECRET_KEY is the example placeholder; using a generated key instead.')
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, '.secret_key')
    if os.path.exists(path):
        with open(path) as fh:
            key = fh.read().strip()
    else:
        key = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as fh:
            fh.write(key)
        print(f'INFO: SECRET_KEY not set; generated one in {path}')
    os.environ['SECRET_KEY'] = key


def _prepare_data_dir():
    """Create DATA_DIR, keep it private and apply a restore staged by an admin."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
        for name in os.listdir(DATA_DIR):
            path = os.path.join(DATA_DIR, name)
            if os.path.isfile(path) and os.stat(path).st_mode & 0o077:
                os.chmod(path, 0o600)
    except OSError as exc:
        print(f'WARNING: could not tighten permissions on {DATA_DIR}: {exc}')
    import config_backup
    config_backup.apply_pending_restore(DATA_DIR)
    # WAL lets polling threads write while pages read. The mode is stored in the
    # file, so this only does work the first time a database is seen.
    import sqlite3
    for name in os.listdir(DATA_DIR):
        if name.endswith('.db'):
            try:
                con = sqlite3.connect(os.path.join(DATA_DIR, name), timeout=15)
                con.execute('PRAGMA journal_mode=WAL')
                con.close()
            except sqlite3.Error as exc:
                print(f'WARNING: could not enable WAL for {name}: {exc}')


_prepare_data_dir()
_ensure_secret_key()
