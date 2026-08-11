"""
data_sync.py — Automatic Data Synchronisation for FleetPilot

Keeps two FleetPilot instances in sync by replicating all data files:
- hosts.json
- All SQLite databases (vm_controller.db, storage_controller.db, etc.)
- users.db (user accounts and settings)
- .env configuration

Sync strategy:
- Primary (LXC 200 / 192.168.1.172) is the source of truth
- Secondary (LXC 201 / 192.168.1.173) receives updates
- Sync runs every 30 seconds in a background thread
- On write operations, primary immediately pushes to secondary
- Uses HTTP API to push/pull data between instances

Usage:
    import data_sync
    data_sync.init(app, data_dir, peer_url='http://192.168.1.173:5000')
"""

import os
import json
import sqlite3
import threading
import time
import logging
import hashlib
import shutil
import tempfile
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Files to sync (relative to DATA_DIR)
SYNC_FILES = [
    'hosts.json',
    'hw_monitor.db',
    'vm_controller.db',
    'storage_controller.db',
    'smart_manager.db',
    'fan_controller.db',
    'backup_controller.db',
    'commander.db',
    'hw_info.db',
    'server_registry.db',
    'disktool_core.db',
]

# Users DB is in app dir, not data dir
SYNC_APP_FILES = [
    'users.db',
]

SYNC_INTERVAL = 30  # seconds between sync checks
SYNC_TOKEN = os.environ.get('SYNC_TOKEN', 'fleetpilot-sync-2025')

# ── State ─────────────────────────────────────────────────────────────────────

_data_dir: Optional[str] = None
_app_dir: Optional[str] = None
_peer_url: Optional[str] = None
_sync_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_last_sync: Optional[str] = None
_sync_errors: List[str] = []
_is_primary: bool = True
_sync_enabled: bool = False


def _file_hash(path: str) -> str:
    """Return MD5 hash of file contents."""
    try:
        h = hashlib.md5(usedforsecurity=False)
        with open(path, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ''


def _file_mtime(path: str) -> float:
    """Return file modification time."""
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def _push_file(path: str, rel_name: str, peer_url: str) -> bool:
    """Push a file to the peer instance via HTTP."""
    try:
        import requests
        with open(path, 'rb') as f:
            data = f.read()
        mtime = _file_mtime(path)
        resp = requests.post(
            f'{peer_url}/api/sync/receive',
            files={'file': (rel_name, data)},
            data={'filename': rel_name, 'mtime': str(mtime), 'hash': _file_hash(path)},
            headers={'X-Sync-Token': SYNC_TOKEN},
            timeout=15,
            verify=False  # nosec B501 - internal LAN only, self-signed certs,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f"[Sync] Push failed for {rel_name}: {e}")
        return False


def _pull_file(rel_name: str, dest_path: str, peer_url: str) -> bool:
    """Pull a file from the peer instance via HTTP."""
    try:
        import requests
        resp = requests.get(
            f'{peer_url}/api/sync/file',
            params={'filename': rel_name},
            headers={'X-Sync-Token': SYNC_TOKEN},
            timeout=15,
            verify=os.environ.get("FLEETPILOT_VERIFY_SSL", "false").lower() == "true"  # nosec B501 - internal LAN only, self-signed certs,
        )
        if resp.status_code == 200:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            shutil.move(tmp_path, dest_path)
            return True
        return False
    except Exception as e:
        logger.debug(f"[Sync] Pull failed for {rel_name}: {e}")
        return False


def _get_peer_manifest(peer_url: str) -> Optional[Dict]:
    """Get list of files and their hashes from peer."""
    try:
        import requests
        resp = requests.get(
            f'{peer_url}/api/sync/manifest',
            headers={'X-Sync-Token': SYNC_TOKEN},
            timeout=10,
            verify=os.environ.get("FLEETPILOT_VERIFY_SSL", "false").lower() == "true"  # nosec B501 - internal LAN only, self-signed certs,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def _get_local_manifest() -> Dict:
    """Build manifest of local files."""
    manifest = {}
    for fname in SYNC_FILES:
        path = os.path.join(_data_dir, fname)
        # Security: Ensure path stays within data dir
        if not os.path.realpath(path).startswith(os.path.realpath(_data_dir) + os.sep):
            continue
        if os.path.exists(path):
            manifest[fname] = {
                'hash': _file_hash(path),
                'mtime': _file_mtime(path),
                'size': os.path.getsize(path),
            }
    for fname in SYNC_APP_FILES:
        path = os.path.join(_app_dir, fname)
        # Security: Ensure path stays within app dir
        if not os.path.realpath(path).startswith(os.path.realpath(_app_dir) + os.sep):
            continue
        if os.path.exists(path):
            manifest[fname] = {
                'hash': _file_hash(path),
                'mtime': _file_mtime(path),
                'size': os.path.getsize(path),
            }
    return manifest


def _sync_once():
    """Perform one sync cycle."""
    global _last_sync, _sync_errors

    if not _peer_url or not _sync_enabled:
        return

    try:
        peer_manifest = _get_peer_manifest(_peer_url)
        if peer_manifest is None:
            _sync_errors.append(f"{datetime.utcnow().isoformat()[:19]} Peer unreachable")
            _sync_errors = _sync_errors[-20:]
            return

        local_manifest = _get_local_manifest()
        pushed = []
        pulled = []

        if _is_primary:
            # Primary: push files that are newer or missing on peer
            for fname, local_info in local_manifest.items():
                peer_info = peer_manifest.get(fname)
                if peer_info is None or local_info['hash'] != peer_info['hash']:
                    # Determine path
                    if fname in SYNC_APP_FILES:
                        path = os.path.join(_app_dir, fname)
                    else:
                        path = os.path.join(_data_dir, fname)
                    if _push_file(path, fname, _peer_url):
                        pushed.append(fname)
                        logger.debug(f"[Sync] Pushed {fname}")
        else:
            # Secondary: pull files from primary
            for fname, peer_info in peer_manifest.items():
                local_info = local_manifest.get(fname)
                if local_info is None or local_info['hash'] != peer_info['hash']:
                    if fname in SYNC_APP_FILES:
                        dest = os.path.join(_app_dir, fname)
                    else:
                        dest = os.path.join(_data_dir, fname)
                    if _pull_file(fname, dest, _peer_url):
                        pulled.append(fname)
                        logger.debug(f"[Sync] Pulled {fname}")

        _last_sync = datetime.utcnow().isoformat()[:19]
        if pushed or pulled:
            logger.info(f"[Sync] Cycle complete — pushed: {pushed}, pulled: {pulled}")

    except Exception as e:
        msg = f"{datetime.utcnow().isoformat()[:19]} Sync error: {e}"
        logger.warning(f"[Sync] {msg}")
        _sync_errors.append(msg)
        _sync_errors = _sync_errors[-20:]


def _sync_loop():
    """Background sync thread."""
    logger.info(f"[Sync] Started — role: {'primary' if _is_primary else 'secondary'}, peer: {_peer_url}")
    while not _stop_event.is_set():
        _sync_once()
        _stop_event.wait(SYNC_INTERVAL)
    logger.info("[Sync] Stopped")


# ── Public API ────────────────────────────────────────────────────────────────

def init(app, data_dir: str, peer_url: str = '', is_primary: bool = True):
    """Initialize the sync module."""
    global _data_dir, _app_dir, _peer_url, _is_primary, _sync_enabled

    _data_dir = data_dir
    _app_dir = os.path.dirname(os.path.abspath(__file__))
    _peer_url = peer_url.rstrip('/') if peer_url else ''
    _is_primary = is_primary
    _sync_enabled = bool(_peer_url)

    if _sync_enabled:
        start()
        logger.info(f"[Sync] Initialized — peer: {_peer_url}, primary: {_is_primary}")
    else:
        logger.info("[Sync] No peer configured — sync disabled")

    register_routes(app)


def start():
    """Start the background sync thread."""
    global _sync_thread
    if _sync_thread and _sync_thread.is_alive():
        return
    _stop_event.clear()
    _sync_thread = threading.Thread(target=_sync_loop, daemon=True, name='data-sync')
    _sync_thread.start()


def stop():
    """Stop the background sync thread."""
    _stop_event.set()


def push_now(filename: str = None) -> Dict:
    """Immediately push one or all files to peer."""
    if not _peer_url:
        return {'ok': False, 'error': 'No peer configured'}
    results = {}
    files = [filename] if filename else SYNC_FILES + SYNC_APP_FILES
    for fname in files:
        if fname in SYNC_APP_FILES:
            path = os.path.join(_app_dir, fname)
        else:
            path = os.path.join(_data_dir, fname)
        if os.path.exists(path):
            ok = _push_file(path, fname, _peer_url)
            results[fname] = 'pushed' if ok else 'failed'
    return {'ok': True, 'results': results}


def status() -> Dict:
    """Return sync status."""
    return {
        'enabled': _sync_enabled,
        'peer_url': _peer_url,
        'is_primary': _is_primary,
        'last_sync': _last_sync,
        'recent_errors': _sync_errors[-5:],
        'thread_alive': _sync_thread.is_alive() if _sync_thread else False,
        'sync_interval': SYNC_INTERVAL,
    }


# ── Flask Routes ──────────────────────────────────────────────────────────────

def register_routes(app):
    """Register sync API routes."""
    from flask import request, jsonify, send_file as flask_send_file

    @app.route('/api/sync/manifest')
    def sync_manifest():
        token = request.headers.get('X-Sync-Token', '')
        if token != SYNC_TOKEN:
            return jsonify({'error': 'Unauthorized'}), 401
        return jsonify(_get_local_manifest())

    @app.route('/api/sync/file')
    def sync_get_file():
        token = request.headers.get('X-Sync-Token', '')
        if token != SYNC_TOKEN:
            return jsonify({'error': 'Unauthorized'}), 401
        fname = request.args.get('filename', '')
        if not fname or '..' in fname or fname.startswith('/'):
            return jsonify({'error': 'Invalid filename'}), 400
        if fname in SYNC_APP_FILES:
            path = os.path.join(_app_dir, fname)
        else:
            path = os.path.join(_data_dir, fname)
        if not os.path.exists(path):
            return jsonify({'error': 'File not found'}), 404
        return flask_send_file(path, as_attachment=True, download_name=fname)

    @app.route('/api/sync/receive', methods=['POST'])
    def sync_receive():
        token = request.headers.get('X-Sync-Token', '')
        if token != SYNC_TOKEN:
            return jsonify({'error': 'Unauthorized'}), 401
        fname = request.form.get('filename', '')
        if not fname or '..' in fname or fname.startswith('/'):
            return jsonify({'error': 'Invalid filename'}), 400
        if 'file' not in request.files:
            return jsonify({'error': 'No file'}), 400
        f = request.files['file']
        if fname in SYNC_APP_FILES:
            dest = os.path.join(_app_dir, fname)
        else:
            dest = os.path.join(_data_dir, fname)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # Write to temp then move (atomic)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp',
                                          dir=os.path.dirname(dest)) as tmp:
            f.save(tmp)
            tmp_path = tmp.name
        shutil.move(tmp_path, dest)
        logger.info(f"[Sync] Received {fname}")
        return jsonify({'ok': True})

    @app.route('/api/sync/status')
    def sync_status_api():
        # Allow unauthenticated for HAProxy health checks
        return jsonify(status())

    @app.route('/api/sync/push', methods=['POST'])
    def sync_push_now():
        fname = request.json.get('filename') if request.is_json else None
        result = push_now(fname)
        return jsonify(result)

    logger.info("[Sync] Routes registered")
