# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Linux distributions are recognised by ID and ID_LIKE and get their own package manager's command."""
import pytest

import linux_distro as ld
import updater


def os_release(distro, like='', variant='', pretty=''):
    text = f'ID={distro}\n'
    if like:
        text += f'ID_LIKE="{like}"\n'
    if variant:
        text += f'VARIANT_ID={variant}\n'
    if pretty:
        text += f'PRETTY_NAME="{pretty}"\n'
    return ld.parse_os_release(text)


# (ID, ID_LIKE) as the distributions ship them, and the family FleetPilot must pick.
CASES = [
    ('debian', '', 'apt'), ('ubuntu', 'debian', 'apt'), ('linuxmint', 'ubuntu debian', 'apt'),
    ('pop', 'ubuntu debian', 'apt'), ('raspbian', 'debian', 'apt'), ('kali', 'debian', 'apt'),
    ('zorin', 'ubuntu', 'apt'), ('devuan', '', 'apt'),
    ('fedora', '', 'dnf'), ('rhel', 'fedora', 'dnf'), ('rocky', 'rhel centos fedora', 'dnf'),
    ('almalinux', 'rhel centos fedora', 'dnf'), ('ol', 'fedora', 'dnf'), ('amzn', 'fedora', 'dnf'),
    ('centos', 'rhel fedora', 'dnf'),
    ('opensuse-leap', 'suse opensuse', 'zypper'), ('opensuse-tumbleweed', 'opensuse suse', 'zypper'),
    ('sles', 'suse', 'zypper'),
    ('arch', '', 'pacman'), ('manjaro', 'arch', 'pacman'), ('endeavouros', 'arch', 'pacman'),
    ('cachyos', 'arch', 'pacman'),
    ('alpine', '', 'apk'), ('void', '', 'xbps'), ('solus', '', 'eopkg'), ('clear-linux-os', '', 'swupd'),
    # A derivative FleetPilot has never heard of still works through ID_LIKE.
    ('some-new-distro', 'ubuntu debian', 'apt'),
]


@pytest.mark.parametrize('distro,like,family', CASES)
def test_every_distribution_gets_its_package_manager(distro, like, family):
    info = os_release(distro, like)
    assert ld.identify(info) == (family, distro)
    for repo_only in (False, True):
        for root in (False, True):
            cmd, desc = ld.update_command(info, repo_only=repo_only, run_as_root=root)
            assert ('$SUDO ' in cmd and cmd.startswith(ld.ELEVATE)) is not root
            assert desc


def test_commands_per_family():
    cmd = lambda d, like='', root=False, **k: ld.update_command(os_release(d, like), run_as_root=root, **k)[0]  # noqa: E731
    assert 'env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 dist-upgrade -y' in cmd('linuxmint', 'ubuntu debian')
    assert 'dist-upgrade' not in cmd('debian', repo_only=True)
    rocky = cmd('rocky', 'rhel centos fedora')
    assert 'dnf -y upgrade --refresh' in rocky and 'yum -y upgrade' in rocky   # yum on CentOS 7 / Amazon Linux 2
    assert 'noscripts' not in rocky + cmd('fedora', repo_only=True)          # skipping scriptlets breaks kernels
    assert 'zypper --non-interactive dist-upgrade' in cmd('opensuse-tumbleweed', 'opensuse suse')
    assert 'zypper --non-interactive update' in cmd('opensuse-leap', 'suse opensuse', repo_only=True)
    assert 'done; pacman -Sy --needed --noconfirm archlinux-keyring && pacman -Syu' in cmd('arch', root=True)
    assert 'pacman -Sy --needed --noconfirm manjaro-keyring && ' in cmd('manjaro', 'arch', root=True)
    assert cmd('cachyos', 'arch', root=True).endswith('done; pacman -Syu --noconfirm')
    assert '[ -e /var/lib/pacman/db.lck ]' in cmd('arch')
    assert 'pgrep -x dnf' in rocky and rocky.index('pgrep') < rocky.index('dnf -y upgrade')
    assert cmd('alpine') == ld.ELEVATE + '; $SUDO apk --wait 600 update && $SUDO apk --wait 600 upgrade --available'
    assert cmd('void', root=True) == 'xbps-install -Syu xbps && xbps-install -yu'


def test_declarative_and_unknown_systems_are_explained():
    with pytest.raises(ValueError, match='nixos-rebuild'):
        ld.update_command(os_release('nixos', pretty='NixOS 24.05 (Uakari)'))
    with pytest.raises(ValueError, match='rpm-ostree'):
        ld.update_command(os_release('fedora', variant='silverblue'))
    with pytest.raises(ValueError, match=r'Unsupported distribution: Gentoo Linux \(ID=gentoo\)'):
        ld.update_command(os_release('gentoo', pretty='Gentoo Linux'))


def test_os_release_parsing():
    info = ld.parse_os_release('# comment\nNAME="Rocky Linux"\nID="rocky"\nID_LIKE="rhel centos fedora"\n'
                               "VERSION_ID='9.4'\n\nPRETTY_NAME=\"Rocky Linux 9.4 (Blue Onyx)\"\n")
    assert info == {'NAME': 'Rocky Linux', 'ID': 'rocky', 'ID_LIKE': 'rhel centos fedora', 'VERSION_ID': '9.4',
                    'PRETTY_NAME': 'Rocky Linux 9.4 (Blue Onyx)'}


def test_updater_uses_id_like_and_names_the_family():
    info = os_release('linuxmint', 'ubuntu debian', pretty='Linux Mint 22')
    cmd, _ = updater.get_update_command('linuxmint', os_release=info)
    assert 'apt-get' in cmd
    assert updater._distro_name(info) == 'Linux Mint 22 (apt)'
    assert 'rocky' in updater.SUPPORTED_DISTRIBUTIONS and 'windows' in updater.SUPPORTED_DISTRIBUTIONS


def test_terminal_codes_are_stripped_from_update_output():
    import ssh_helper
    # Captured from zypper on openSUSE and from sudo on Arch Linux (systemd OSC 3008 markers).
    assert ssh_helper.plain_text("\x1b[22;27;39;49mNothing to do.\x1b[0m\r\n") == 'Nothing to do.'
    arch = ("\x1b]3008;start=cf4b;user=fpadmin;hostname=fp-test-arch\x1b\\:: Starting full system upgrade..."
            "\x1b[?25h\x1b]3008;end=cf4b\x1b\\")
    assert ssh_helper.plain_text(arch) == ':: Starting full system upgrade...'
    assert ssh_helper.plain_text('0% [Working]\r100% [Done]\n') == '100% [Done]'
    # apk saves and restores the cursor (ESC 7 / ESC 8) around its progress text.
    assert ssh_helper.plain_text('\x1b7[syncing disks...]\x1b8OK: 206 packages\n') == '[syncing disks...]OK: 206 packages'


def test_dnf_runs_once_more_after_colliding_with_another_dnf():
    # Rocky 9: cloud-init runs "dnf makecache" then "dnf upgrade"; FleetPilot's dnf started in between and
    # failed with "rpm exception: package not installed". A second run after waiting succeeds.
    cmd, _ = ld.update_command(os_release('rocky', 'rhel centos fedora'))
    assert cmd.count('dnf -y upgrade --refresh') == 2 and "trying once more" in cmd


@pytest.mark.parametrize('distro,like,expected', [
    ('ubuntu', 'debian', '/var/run/reboot-required'), ('rocky', 'rhel fedora', 'needs-restarting -r'),
    ('opensuse-leap', 'suse', 'zypper needs-rebooting'), ('arch', '', '/usr/lib/modules/$(uname -r)'),
    ('alpine', '', '/lib/modules/$(uname -r)'),
])
def test_restart_checks(distro, like, expected):
    cmd = ld.reboot_check_command(os_release(distro, like), run_as_root=True)
    assert expected in cmd and ld.REBOOT_MARKER in cmd
    assert ld.reboot_check_command(os_release('solus')) is None


def test_restart_check_scripts_run_in_a_real_shell(tmp_path):
    import shutil
    import subprocess
    if not shutil.which('sh'):
        pytest.skip('no sh')
    # On this machine the running kernel's modules exist, so the kernel check stays quiet; all scripts must
    # parse and exit 0 whatever they find.
    for family_os in (os_release('arch'), os_release('ubuntu', 'debian'), os_release('rocky', 'rhel')):
        cmd = ld.reboot_check_command(family_os, run_as_root=True)
        result = subprocess.run(['sh', '-c', cmd], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (cmd, result.stderr)
