# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux distributions: recognise one from /etc/os-release and build its update command.

A distribution is matched by its ``ID`` first and then by ``ID_LIKE``, so derivatives work
without being listed: Linux Mint and Pop!_OS say ``ID_LIKE="ubuntu debian"``, Rocky Linux says
``ID_LIKE="rhel centos fedora"``, Manjaro says ``ID_LIKE=arch``.
"""
from typing import Dict, Optional, Tuple

# Package-manager families, keyed by the IDs that identify them (ID or any ID_LIKE word).
FAMILIES = {
    'apt': ('debian', 'ubuntu', 'raspbian', 'linuxmint', 'pop', 'elementary', 'zorin', 'kali', 'parrot',
            'devuan', 'mx', 'neon', 'pureos', 'deepin', 'tuxedo'),
    'dnf': ('fedora', 'rhel', 'centos', 'rocky', 'almalinux', 'ol', 'amzn', 'nobara', 'ultramarine',
            'eurolinux', 'navy', 'circle'),
    'zypper': ('opensuse', 'opensuse-leap', 'opensuse-tumbleweed', 'opensuse-slowroll', 'suse', 'sles', 'sled'),
    'pacman': ('arch', 'archarm', 'manjaro', 'manjaro-arm', 'endeavouros', 'garuda', 'artix', 'cachyos'),
    'apk': ('alpine', 'postmarketos'),
    'xbps': ('void',),
    'eopkg': ('solus',),
    'swupd': ('clear-linux-os',),
}
# Rolling openSUSE releases must be updated with "zypper dup"; "update" would leave them inconsistent.
ZYPPER_ROLLING = ('opensuse-tumbleweed', 'opensuse-slowroll')
# Immutable or declarative systems: a package upgrade is the wrong tool, so FleetPilot says so.
NOT_PACKAGE_BASED = {
    'nixos': 'NixOS is configured declaratively; update it with nixos-rebuild (or your flake).',
    'opensuse-microos': 'openSUSE MicroOS updates itself with transactional-update.',
    'fedora-coreos': 'Fedora CoreOS updates itself with Zincati/rpm-ostree.',
    'silverblue': 'Fedora Atomic desktops update with rpm-ostree.',
    'kinoite': 'Fedora Atomic desktops update with rpm-ostree.',
    'flatcar': 'Flatcar Container Linux updates itself.',
    'talos': 'Talos Linux is updated with talosctl.',
}
APT_LOCK_TIMEOUT = 600   # seconds to wait for unattended-upgrades or cloud-init to release the dpkg lock
ELEVATE = 'SUDO=$(command -v sudo || command -v doas || echo sudo)'
OS_RELEASE_COMMAND = 'cat /etc/os-release 2>/dev/null || cat /usr/lib/os-release'


def _wait_while(condition: str) -> str:
    """Shell prefix that waits (up to APT_LOCK_TIMEOUT) while ``condition`` holds."""
    return (f"for _ in $(seq {APT_LOCK_TIMEOUT // 5}); do {condition} || break; "
            f"[ -n \"$fp_waited\" ] || echo 'Waiting for another package manager to finish...'; fp_waited=1; "
            f"sleep 5; done; ")


# Prints REBOOT_MARKER when the system needs a restart to use what was installed (kernel, libc, sshd ...).
REBOOT_MARKER = '@@fp:reboot-required'
_KERNEL_GONE = '[ -d "/lib/modules/$(uname -r)" ] || [ -d "/usr/lib/modules/$(uname -r)" ] || echo {m}'
REBOOT_CHECKS = {
    'apt': '[ -f /var/run/reboot-required ] && echo {m}',
    # needs-restarting -r exits 1 when a reboot is needed (dnf-utils / dnf5 plugin); missing tool: no answer.
    'dnf': ('if command -v needs-restarting >/dev/null 2>&1; then needs-restarting -r >/dev/null 2>&1; '
            'r=$?; else dnf needs-restarting -r >/dev/null 2>&1; r=$?; fi; [ "$r" = 1 ] && echo {m}'),
    'zypper': '{sudo}zypper needs-rebooting >/dev/null 2>&1; [ $? = 102 ] && echo {m}',
    'pacman': _KERNEL_GONE, 'apk': _KERNEL_GONE, 'xbps': _KERNEL_GONE,
}


def reboot_check_command(info: Dict[str, str], run_as_root: bool = False) -> Optional[str]:
    """Shell command that prints REBOOT_MARKER if the system needs a restart, or None if unknown."""
    family, _ = identify(info)
    check = REBOOT_CHECKS.get(family)
    if not check:
        return None
    sudo = '' if run_as_root else '$SUDO '
    cmd = check.format(m=REBOOT_MARKER, sudo=sudo) + '; true'
    return cmd if run_as_root or '$SUDO' not in cmd else f'{ELEVATE}; {cmd}'


def parse_os_release(text: str) -> Dict[str, str]:
    """KEY=value pairs of an os-release file, unquoted."""
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            key, _, value = line.partition('=')
            info[key.strip()] = value.strip().strip('"').strip("'")
    return info


def identify(info: Dict[str, str]) -> Tuple[Optional[str], str]:
    """(package-manager family or None, distribution id) for parsed os-release data."""
    distro = info.get('ID', '').lower()
    variant = info.get('VARIANT_ID', '').lower()
    for special in (distro, variant):
        if special in NOT_PACKAGE_BASED:
            return None, special
    for candidate in [distro] + info.get('ID_LIKE', '').lower().split():
        for family, ids in FAMILIES.items():
            if candidate in ids:
                return family, distro
    return None, distro


def unsupported_message(info: Dict[str, str]) -> str:
    family, distro = identify(info)
    name = info.get('PRETTY_NAME') or info.get('NAME') or distro or 'this system'
    if distro in NOT_PACKAGE_BASED:
        return f"{name}: {NOT_PACKAGE_BASED[distro]}"
    return (f"Unsupported distribution: {name} (ID={distro or '?'}). FleetPilot updates systems that use "
            "apt, dnf/yum, zypper, pacman, apk, xbps, eopkg or swupd.")


def update_command(info: Dict[str, str], repo_only: bool = False, run_as_root: bool = False) -> Tuple[str, str]:
    """(shell command, description) that updates the distribution described by ``info``.

    repo_only installs updates from the configured repositories and keeps changed configuration
    files; a full update also takes distribution-level changes (apt dist-upgrade, zypper dup).
    Raises ValueError for distributions FleetPilot cannot update.
    """
    family, distro = identify(info)
    sudo = '' if run_as_root else '$SUDO '
    cmd, desc = _command(family, distro, info, repo_only, sudo)
    # sudo where it exists, else doas (Alpine's cloud images have only doas). doas takes no VAR=value
    # prefix, hence "env" below.
    return (cmd if run_as_root else f'{ELEVATE}; {cmd}'), desc


def _command(family, distro, info, repo_only, sudo):
    full = 'full system update'
    repo = 'repository-only update (preserving config files)'
    if family == 'apt':
        apt = f"{sudo}env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout={APT_LOCK_TIMEOUT}"
        if repo_only:
            return f"{apt} update && {apt} upgrade -y -o Dpkg::Options::='--force-confold'", repo
        return f"{apt} update && {apt} upgrade -y && {apt} dist-upgrade -y", full
    if family == 'dnf':
        # dnf keeps changed configuration files (new ones become .rpmnew). CentOS 7 / Amazon Linux 2 only have yum.
        # dnf resolves first and takes its lock only for the transaction: started while dnf-automatic or
        # cloud-init is upgrading, it then fails with "rpm exception: package not installed". Wait first.
        # Waiting first is not enough: cloud-init runs "dnf makecache" and then "dnf upgrade", and a run started
        # in between still collides. So after a failure, wait again and run once more: a fresh run re-resolves
        # and finishes what the interrupted transaction left.
        wait = _wait_while('pgrep -x dnf >/dev/null || pgrep -x dnf5 >/dev/null || pgrep -x yum >/dev/null')
        upgrade = (f"if command -v dnf >/dev/null 2>&1; then {sudo}dnf -y upgrade --refresh; "
                   f"else {sudo}yum -y upgrade; fi")
        cmd = (f"{wait}{upgrade} || {{ echo 'The upgrade failed; trying once more...'; sleep 10; "
               f"{wait}{upgrade}; }}")
        return cmd, (repo if repo_only else full)
    if family == 'zypper':
        zypper = f"{sudo}env ZYPP_LOCK_TIMEOUT={APT_LOCK_TIMEOUT} zypper --non-interactive"
        refresh = f"{zypper} refresh"
        if distro in ZYPPER_ROLLING:
            return f"{refresh} && {zypper} dist-upgrade --auto-agree-with-licenses", full
        return f"{refresh} && {zypper} update --auto-agree-with-licenses", (repo if repo_only else full)
    if family == 'pacman':
        # Refresh the keyring first: an outdated one makes "pacman -Syu" fail on signatures.
        keyring = {'arch': 'archlinux-keyring', 'manjaro': 'manjaro-keyring', 'endeavouros': 'endeavouros-keyring',
                   'artix': 'artix-keyring'}.get(distro)
        pre = f"{sudo}pacman -Sy --needed --noconfirm {keyring} && " if keyring else ''
        wait = _wait_while('[ -e /var/lib/pacman/db.lck ]')     # pacman gives up at once on a held lock
        return f"{wait}{pre}{sudo}pacman -Syu --noconfirm", (repo if repo_only else full)
    if family == 'apk':
        apk = f"{sudo}apk --wait {APT_LOCK_TIMEOUT}"
        if repo_only:
            return f"{apk} update && {apk} upgrade", repo
        return f"{apk} update && {apk} upgrade --available", full
    if family == 'xbps':
        # xbps must update itself before it can update the rest.
        return f"{sudo}xbps-install -Syu xbps && {sudo}xbps-install -yu", (repo if repo_only else full)
    if family == 'eopkg':
        return f"{sudo}eopkg upgrade -y", (repo if repo_only else full)
    if family == 'swupd':
        return f"{sudo}swupd update", (repo if repo_only else full)
    raise ValueError(unsupported_message(info))
