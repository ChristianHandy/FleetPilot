"""
Email configuration management for FleetPilot.
Handles email settings for scheduled reports and notifications.

Settings live in DATA_DIR/email_settings.json (mode 0600). The SMTP password
is stored encrypted and is never sent back to the browser.
"""
import json
import os
import shutil

import secret_box

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_box = secret_box.SecretBox("sha256")

DEFAULTS = {
    "email_enabled": False,
    "smtp_server": "",
    "smtp_port": 587,
    "smtp_use_tls": True,
    "smtp_username": "",
    "smtp_password": "",
    "sender_email": "",
    "recipient_emails": [],
    "report_enabled": False,
    "report_interval": "weekly",
    "error_notifications_enabled": True,
    "smart_alerts_enabled": True,
}


def _config_path():
    data_dir = os.environ.get("FLEETPILOT_DATA_DIR", os.path.join(_APP_DIR, "data"))
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "email_settings.json")
    # Older versions wrote the file relative to the working directory.
    for legacy in (os.path.join(_APP_DIR, "email_settings.json"), os.path.abspath("email_settings.json")):
        if legacy != path and os.path.exists(legacy) and not os.path.exists(path):
            shutil.move(legacy, path)
    return path


def load_email_settings():
    """Load email settings; the returned dict has the SMTP password decrypted."""
    settings = dict(DEFAULTS)
    try:
        with open(_config_path(), "r") as f:
            settings.update(json.load(f))
    except (OSError, ValueError):
        pass
    settings["smtp_password"] = _box.decrypt(settings.get("smtp_password") or "")
    return settings


def save_email_settings(settings):
    """Save email settings, encrypting the SMTP password."""
    stored = dict(settings)
    if stored.get("smtp_password"):
        stored["smtp_password"] = _box.encrypt(stored["smtp_password"])
    path = _config_path()
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(stored, f, indent=2)
    os.replace(path + ".tmp", path)


def get_email_enabled():
    """Check if email notifications are enabled"""
    return load_email_settings().get("email_enabled", False)


def get_report_enabled():
    """Check if scheduled reports are enabled"""
    settings = load_email_settings()
    return settings.get("email_enabled", False) and settings.get("report_enabled", False)


def get_error_notifications_enabled():
    """Check if error notifications are enabled"""
    settings = load_email_settings()
    return settings.get("email_enabled", False) and settings.get("error_notifications_enabled", False)


def get_smart_alerts_enabled():
    """Check if SMART disk alerts should be emailed"""
    settings = load_email_settings()
    return settings.get("email_enabled", False) and settings.get("smart_alerts_enabled", True)
