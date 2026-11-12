# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Version Manager Module
Handles checking for new dashboard versions from GitHub and managing update notifications.
"""

import json
import logging
import os
import re
import subprocess
import requests
from addon_loader import fire_app_hook
from datetime import datetime, timedelta
from fleetpilot_version import TAG

try:
    from packaging.version import InvalidVersion as _InvalidVersion
    from packaging.version import Version as _packaging_version
except ImportError:  # packaging is not a runtime dependency of FleetPilot
    _packaging_version = None
    _InvalidVersion = ValueError

# Get logger for this module
logger = logging.getLogger(__name__)

# In the data directory: the code directory is read-only for the service.
VERSION_CHECK_FILE = os.path.join(
    os.environ.get("FLEETPILOT_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
    "version_check.json")
GITHUB_REPO = "ChristianHandy/fleetpilot"
GITHUB_API_BASE = "https://api.github.com"


def get_current_version() -> str:
    """Return the authoritative semantic FleetPilot release version."""
    return TAG


_PRERELEASE_RANKS = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2,
                     "pre": 2, "preview": 2}


def _version_key(text):
    """Sort key for a dotted version with an optional pre-release suffix.

    Fallback for environments without `packaging`. A final release sorts
    after its own pre-releases: 1.8.0-beta.2 < 1.8.0 < 1.8.1.
    """
    match = re.match(r"^(\d+(?:\.\d+)*)(?:[-.]?([a-zA-Z]+)[-.]?(\d+)?)?$", text)
    if not match:
        return None
    numbers = tuple(int(part) for part in match.group(1).split("."))
    numbers += (0,) * max(0, 4 - len(numbers))
    label = (match.group(2) or "").lower()
    if not label:
        return numbers, 3, 0
    return numbers, _PRERELEASE_RANKS.get(label, 2), int(match.group(3) or 0)


def _is_newer_version(candidate, current) -> bool:
    """True when `candidate` (a release tag or version) is newer than `current`.

    Both may carry a leading "v" ("v1.8.0"). Anything unparsable is not an
    update.
    """
    candidate = (candidate or "").strip().lstrip("vV")
    current = (current or "").strip().lstrip("vV")
    if not candidate or not current:
        return False
    if _packaging_version is not None:
        try:
            return _packaging_version(candidate) > _packaging_version(current)
        except _InvalidVersion:
            return False
    candidate_key = _version_key(candidate)
    current_key = _version_key(current)
    if candidate_key is None or current_key is None:
        return False
    return candidate_key > current_key


def load_version_data():
    """Load version check data from file"""
    try:
        if os.path.exists(VERSION_CHECK_FILE):
            with open(VERSION_CHECK_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "last_check": None,
        "current_version": None,
        "latest_version": None,
        "update_available": False,
        "update_type": None,  # "release" or "commit"
        "update_url": None,
        "update_description": None,
        "notification_dismissed": False,
        "last_notified": None
    }

def save_version_data(data):
    """Save version check data to file"""
    with open(VERSION_CHECK_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_current_commit_sha():
    """Get the current commit SHA of the local repository"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None

def sanitize_branch_name(branch):
    """
    Security: Validate and sanitize git branch names to prevent command injection.
    Only allows alphanumeric characters, hyphens, underscores, and dots in branch segments,
    with forward slashes as path separators for hierarchical branch names.
    Branch names must start with alphanumeric characters to prevent flag injection.
    Branch names are limited to 255 characters.
    """
    if not branch or not isinstance(branch, str):
        raise ValueError("Branch name cannot be empty or non-string")
    
    # Additional safety check: prevent absolute paths
    if branch.startswith('/'):
        raise ValueError("Branch name contains invalid characters or format")
    
    # Only allow safe characters for branch names with reasonable length limit
    # Pattern requires alphanumeric start to prevent flag injection (e.g., -rf)
    # Allows dots for version tags (e.g., release/v1.2.3) but prevents path traversal
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*(?:/[a-zA-Z0-9][a-zA-Z0-9._-]*)*$', branch):
        raise ValueError("Branch name contains invalid characters or format")
    
    # Additional safety check: prevent path traversal attempts
    # Check for .. (consecutive dots), /./ patterns, and trailing dots
    if '..' in branch or re.search(r'/\./', branch) or branch.endswith('.'):
        raise ValueError("Branch name contains invalid path traversal patterns")
    
    # Additional safety check: limit total length
    if len(branch) > 255:
        raise ValueError("Branch name exceeds maximum length of 255 characters")
    
    return branch

def get_current_branch():
    """Get the current git branch"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            # Sanitize the branch name before returning
            try:
                return sanitize_branch_name(branch)
            except ValueError as e:
                # Log failed sanitization for security monitoring
                logger.warning(f"Branch name sanitization failed, falling back to 'main': {e}")
                return "main"
    except Exception as e:
        logger.error(f"Error getting current branch: {e}")
    return "main"

def _notify_new_version(data, previous_version):
    """
    Announce a new version through the plugin ``notification`` hook.

    Only fires when the version actually changed. The check runs every 24 h,
    so firing unconditionally would make every plugin that forwards to Slack
    or mail repeat the same "new version" message every single day.
    """
    if previous_version == data.get("latest_version"):
        return
    fire_app_hook("notification_hook", "new_version_available", {
        "type": data.get("update_type"),
        "version": data.get("latest_version"),
        "description": data.get("update_description"),
        "url": data.get("update_url"),
    })


def check_for_updates():
    """
    Check GitHub for new versions (releases or commits).
    Returns updated version data.
    """
    data = load_version_data()
    from constants import offline_mode
    if offline_mode():
        return data  # no internet access allowed
    current_sha = get_current_commit_sha()
    branch = get_current_branch()
    previous_version = data.get("latest_version")
    
    data["current_version"] = current_sha
    data["last_check"] = datetime.now().isoformat()
    
    try:
        # First, check for latest release
        release_url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(release_url, timeout=10)
        
        if response.status_code == 200:
            release = response.json()
            tag_name = release.get("tag_name", "")

            # Compare versions, not commits: target_commitish is the branch
            # the release targets ("main"), never a commit SHA, so comparing
            # it with the running commit reported an update on every check.
            if _is_newer_version(tag_name, get_current_version()):
                data["update_available"] = True
                data["update_type"] = "release"
                data["latest_version"] = tag_name
                data["update_url"] = release.get("html_url")
                data["update_description"] = release.get("name", "New release available")
                if previous_version != tag_name:
                    # A genuinely new version re-arms the banner; the same
                    # version keeps the user's dismissal.
                    data["notification_dismissed"] = False
                save_version_data(data)
                _notify_new_version(data, previous_version)
                return data
        
        # If no newer release, check for latest commit on current branch
        commit_url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/commits/{branch}"
        response = requests.get(commit_url, timeout=10)
        
        if response.status_code == 200:
            commit = response.json()
            latest_sha = commit.get("sha", "")
            
            if latest_sha and current_sha and latest_sha != current_sha:
                data["update_available"] = True
                data["update_type"] = "commit"
                data["latest_version"] = latest_sha[:7]  # Short SHA
                data["update_url"] = commit.get("html_url")
                commit_msg = commit.get("commit", {}).get("message", "").split("\n")[0]
                data["update_description"] = f"New commit: {commit_msg}"
                if previous_version != data["latest_version"]:
                    data["notification_dismissed"] = False
                save_version_data(data)
                _notify_new_version(data, previous_version)
                return data
            else:
                # No update available
                data["update_available"] = False
                data["update_type"] = None
                
    except Exception as e:
        # Log error but don't crash
        print(f"Error checking for updates: {e}")
    
    save_version_data(data)
    return data

def should_check_for_updates(check_interval_hours=24):
    """
    Determine if we should check for updates based on last check time.
    Default: check every 24 hours.
    """
    data = load_version_data()
    last_check = data.get("last_check")
    
    if not last_check:
        return True
    
    try:
        last_check_dt = datetime.fromisoformat(last_check)
        if datetime.now() - last_check_dt > timedelta(hours=check_interval_hours):
            return True
    except Exception:
        return True
    
    return False

def dismiss_notification():
    """Mark the current update notification as dismissed"""
    data = load_version_data()
    data["notification_dismissed"] = True
    data["last_notified"] = datetime.now().isoformat()
    save_version_data(data)

def get_update_notification():
    """
    Get update notification data if an update is available and not dismissed.
    Returns None if no notification should be shown.
    """
    data = load_version_data()
    
    if data.get("update_available") and not data.get("notification_dismissed"):
        return {
            "type": data.get("update_type"),
            "version": data.get("latest_version"),
            "description": data.get("update_description"),
            "url": data.get("update_url")
        }
    
    return None
