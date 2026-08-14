"""Authoritative FleetPilot release metadata.

Keep this module dependency-free so the web interface, health checks, deployment
scripts, and future clients all report the same semantic application version.
"""

VERSION = "1.1.0"
TAG = f"v{VERSION}"
DISPLAY_NAME = f"FleetPilot {TAG}"


def release_metadata() -> dict[str, str]:
    """Return safe, public release metadata for templates and health checks."""
    return {
        "version": VERSION,
        "tag": TAG,
        "display_name": DISPLAY_NAME,
    }
