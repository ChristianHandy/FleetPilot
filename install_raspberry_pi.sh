#!/usr/bin/env bash
# Kept for old links and guides: FleetPilot now has one installer for Debian,
# Ubuntu and Raspberry Pi OS. See install.sh and docs/installation.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$HERE/install.sh" ]]; then
    exec bash "$HERE/install.sh" "$@"
fi
exec bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh)"
