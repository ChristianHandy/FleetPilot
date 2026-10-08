"""
config_backup.py — backups of FleetPilot's own data directory.

A backup is a .tar.gz holding a consistent copy of every database (taken with
SQLite's online backup API), the JSON settings files and the generated secret
key, plus a manifest with SHA-256 checksums. Backups contain password hashes,
2FA secrets and encrypted credentials, so they are written with mode 0600 and
only administrators can download them.

Restoring never replaces files under a running app: an uploaded archive is
validated and staged in DATA_DIR/restore_pending, and apply_pending_restore()
moves it into place at the next start, before any module opens a database.
"""
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

BACKUP_DIRNAME = "backups"
PENDING_DIRNAME = "restore_pending"
MANIFEST = "fleetpilot-backup.json"
_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_INCLUDE_EXT = (".db", ".json")
_INCLUDE_NAMES = {".secret_key", ".checkmk_token", "known_hosts"}
_EXCLUDE_NAMES = {"initial_admin_password"}
MAX_RESTORE_BYTES = 512 * 1024 * 1024


def _backup_dir(data_dir):
    path = os.path.join(data_dir, BACKUP_DIRNAME)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _candidates(data_dir):
    for name in sorted(os.listdir(data_dir)):
        path = os.path.join(data_dir, name)
        if not os.path.isfile(path) or name in _EXCLUDE_NAMES or not _NAME_RE.fullmatch(name):
            continue
        if name.endswith(_INCLUDE_EXT) or name in _INCLUDE_NAMES:
            yield name, path


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(data_dir, version="unknown", label="manual"):
    """Write a backup archive into DATA_DIR/backups and return its path."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    label = re.sub(r"[^a-z0-9-]", "", label.lower())[:20] or "manual"
    out_path = os.path.join(_backup_dir(data_dir), f"fleetpilot-{stamp}-{label}.tar.gz")
    files = {}
    with tempfile.TemporaryDirectory(prefix="fp-backup-") as tmp:
        for name, path in _candidates(data_dir):
            dest = os.path.join(tmp, name)
            if name.endswith(".db"):
                src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
                dst = sqlite3.connect(dest)
                try:
                    src.backup(dst)  # consistent even while the app is writing
                finally:
                    dst.close()
                    src.close()
            else:
                shutil.copy2(path, dest)
            files[name] = _sha256(dest)
        manifest = {"format": 1, "fleetpilot_version": version,
                    "created_utc": stamp, "secret_key_from_env": not os.path.exists(os.path.join(data_dir, ".secret_key")),
                    "files": files}
        fd = os.open(out_path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo(MANIFEST)
            info.size, info.mtime, info.mode = len(data), int(time.time()), 0o600
            tar.addfile(info, io.BytesIO(data))
            for name in files:
                tar.add(os.path.join(tmp, name), arcname=name, recursive=False)
        os.replace(out_path + ".tmp", out_path)
    logger.info("Backup written: %s (%d files)", out_path, len(files))
    return out_path


def list_backups(data_dir):
    folder = _backup_dir(data_dir)
    items = []
    for name in sorted(os.listdir(folder), reverse=True):
        if name.endswith(".tar.gz") and _NAME_RE.fullmatch(name):
            st = os.stat(os.path.join(folder, name))
            items.append({"name": name, "size": st.st_size, "mtime": st.st_mtime,
                          "created": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return items


def backup_path(data_dir, name):
    """Return the path of an existing backup, or None for anything else."""
    if not name or not _NAME_RE.fullmatch(name) or not name.endswith(".tar.gz"):
        return None
    path = os.path.join(_backup_dir(data_dir), name)
    return path if os.path.isfile(path) else None


def prune(data_dir, keep=7, label="auto"):
    """Keep the newest ``keep`` automatic backups; manual ones are never pruned."""
    autos = [b["name"] for b in list_backups(data_dir) if b["name"].endswith(f"-{label}.tar.gz")]
    for name in autos[keep:]:
        os.remove(os.path.join(_backup_dir(data_dir), name))


def stage_restore(data_dir, fileobj):
    """Validate an uploaded archive and stage it for the next start. Raises ValueError."""
    pending = os.path.join(data_dir, PENDING_DIRNAME)
    shutil.rmtree(pending, ignore_errors=True)
    os.makedirs(pending, mode=0o700)
    try:
        with tarfile.open(fileobj=fileobj, mode="r:gz") as tar:
            members = tar.getmembers()
            if sum(m.size for m in members) > MAX_RESTORE_BYTES:
                raise ValueError("Archive is too large.")
            names = {m.name for m in members}
            if MANIFEST not in names:
                raise ValueError("This is not a FleetPilot backup (manifest missing).")
            for m in members:
                if not m.isfile() or not _NAME_RE.fullmatch(m.name) or m.name.startswith(".."):
                    raise ValueError(f"Unexpected entry in archive: {m.name!r}")
            manifest = json.load(tar.extractfile(MANIFEST))
            expected = manifest.get("files") or {}
            if set(expected) != names - {MANIFEST}:
                raise ValueError("Archive contents do not match its manifest.")
            for name, digest in expected.items():
                dest = os.path.join(pending, name)
                with tar.extractfile(name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(dest, 0o600)
                if _sha256(dest) != digest:
                    raise ValueError(f"Checksum mismatch for {name}.")
                if name.endswith(".db"):
                    con = sqlite3.connect(dest)
                    try:
                        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError(f"{name} failed the SQLite integrity check.")
                    finally:
                        con.close()
        return manifest
    except (tarfile.TarError, OSError, json.JSONDecodeError) as exc:
        shutil.rmtree(pending, ignore_errors=True)
        raise ValueError(f"Could not read the backup: {exc}") from exc
    except ValueError:
        shutil.rmtree(pending, ignore_errors=True)
        raise


def restore_pending(data_dir):
    return os.path.isdir(os.path.join(data_dir, PENDING_DIRNAME))


def cancel_restore(data_dir):
    shutil.rmtree(os.path.join(data_dir, PENDING_DIRNAME), ignore_errors=True)


def apply_pending_restore(data_dir):
    """Move a staged restore into place. Call before any database is opened."""
    pending = os.path.join(data_dir, PENDING_DIRNAME)
    if not os.path.isdir(pending):
        return False
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    previous = os.path.join(data_dir, f"pre-restore-{stamp}")
    os.makedirs(previous, mode=0o700)
    staged = os.listdir(pending)
    for name in staged:
        for suffix in ("", "-wal", "-shm"):
            current = os.path.join(data_dir, name + suffix)
            if os.path.exists(current):
                shutil.move(current, os.path.join(previous, name + suffix))
        shutil.move(os.path.join(pending, name), os.path.join(data_dir, name))
    os.rmdir(pending)
    print(f"INFO: Restored {len(staged)} files from backup; previous files kept in {previous}")
    return True


_scheduler_started = False


def start_daily_backups(data_dir, version="unknown", keep=7, hour=3):
    """Write an automatic backup once a day (default 03:00 local) and keep ``keep`` of them."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def loop():
        while True:
            now = datetime.now()
            target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            time.sleep(max(60, (target - now).total_seconds()))
            try:
                create_backup(data_dir, version=version, label="auto")
                prune(data_dir, keep=keep, label="auto")
            except Exception as exc:
                logger.error("Automatic backup failed: %s", exc)

    threading.Thread(target=loop, daemon=True, name="fleetpilot-daily-backup").start()
