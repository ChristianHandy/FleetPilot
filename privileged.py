# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""How FleetPilot runs its root helpers (disk actions, self-update, proxy apply).

install.sh copies them root-owned to /usr/local/lib/fleetpilot and lets the
unprivileged service user run exactly these through one sudo rule. Installs that
run FleetPilot itself as root, such as the community-scripts.org LXC container,
have no such copies or rule; there the helpers shipped in scripts/ run directly.
"""
import os

INSTALLED_DIR = '/usr/local/lib/fleetpilot'
BUNDLED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
APP_DIR = os.path.dirname(os.path.abspath(__file__))


def command(name, *args):
    """Return the argv that runs helper ``name`` (disk-action, update, proxy-apply)."""
    installed = os.path.join(INSTALLED_DIR, name)
    if os.path.exists(installed) or os.geteuid() != 0:
        return ['sudo', '-n', installed, *args]
    bundled = os.path.join(BUNDLED_DIR, f'fleetpilot-{name}')
    with open(bundled, encoding='utf-8') as fh:
        interpreter = fh.readline()[2:].split()   # the helper's own shebang line
    return [*interpreter, bundled, *args]


def is_git_checkout():
    """True when FleetPilot was installed from git (install.sh), not from a release tarball."""
    return os.path.isdir(os.path.join(APP_DIR, '.git'))
