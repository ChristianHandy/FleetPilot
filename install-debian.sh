#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Kept for old links and guides: FleetPilot now has one installer for Debian,
# Ubuntu and Raspberry Pi OS. See install.sh and docs/installation.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$HERE/install.sh" ]]; then
    exec bash "$HERE/install.sh" "$@"
fi
echo "install.sh was not found next to this script. Clone the repository and run it:" >&2
echo "  git clone https://github.com/ChristianHandy/FleetPilot.git && sudo bash FleetPilot/install.sh" >&2
exit 1
