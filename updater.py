# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# updater.py - Enhanced error handling, better distribution support, and fixed notification propagation
import functools
import os
import logging
import paramiko
import ssh_helper
import time
import subprocess
import email_config
import email_notifier
import linux_distro
import windows_host
from constants import is_localhost, get_platform

# Distribution IDs FleetPilot updates; derivatives are also matched through their ID_LIKE.
SUPPORTED_DISTRIBUTIONS = sorted({i for ids in linux_distro.FAMILIES.values() for i in ids}) + ['windows']

# Windows Update PowerShell commands
WINDOWS_UPDATE_BASE = (
    "Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -ErrorAction SilentlyContinue; "
    "Install-Module PSWindowsUpdate -Force -ErrorAction SilentlyContinue; "
    "Import-Module PSWindowsUpdate; "
    "Get-WindowsUpdate -AcceptAll -Install -AutoReboot:$false"
)

WINDOWS_WINGET_UPDATE = (
    "if (Get-Command winget -ErrorAction SilentlyContinue) { "
    "winget upgrade --all --accept-source-agreements --accept-package-agreements --silent "
    "}"
)

# Prints "windows" on Windows, whether the OpenSSH default shell is cmd.exe or PowerShell.
WINDOWS_DETECTION_COMMAND = windows_host.DETECT_COMMAND

def get_update_command(distro, repo_only=False, run_as_root=False, os_release=None):
    """
    Get the update command for a Linux distribution or Windows.

    Args:
        distro: os-release ID ('debian', 'rocky', 'opensuse-leap', ...) or 'windows'
        repo_only: If True, only update packages without modifying config files
        run_as_root: If True, omit 'sudo' prefix (already running as root, e.g. Proxmox root SSH login)
        os_release: parsed os-release data; with it, derivatives are recognised by ID_LIKE

    Returns:
        tuple: (command_string, description)

    Raises:
        ValueError: If distribution is not supported
    """
    if distro == 'windows':
        if repo_only:
            # Windows Update via PowerShell (system updates only)
            return f'powershell.exe -Command "{WINDOWS_UPDATE_BASE}"', "Windows system updates only"
        # Full Windows Update + software updates via winget
        return (f'powershell.exe -Command "{WINDOWS_UPDATE_BASE}; {WINDOWS_WINGET_UPDATE}"',
                "full Windows system and software updates")
    return linux_distro.update_command(os_release or {'ID': distro}, repo_only, run_as_root)


def _distro_name(info):
    family, distro = linux_distro.identify(info)
    name = info.get('PRETTY_NAME') or distro
    return f"{name} ({family})" if family else name


def run_local_update(name, log_list, repo_only, log_func):
    """
    Run system update locally using subprocess.
    
    Args:
        name: Display name for the host (used in logs)
        log_list: List to append log messages to
        repo_only: If True, only update packages from repositories without modifying config files
        log_func: Logging function to use
    """
    error_occurred = False
    error_details = []
    
    try:
        log_func(f"Running local update on {name}...")
        
        # Detect the operating system and distribution
        current_platform = get_platform()
        log_func(f"Detecting operating system... Platform: {current_platform}")
        os_release = {}
        
        if current_platform == 'windows':
            # Windows detection
            distro = 'windows'
            log_func("Detected Windows operating system")
        else:
            # Linux/Unix distribution detection
            log_func("Detecting Linux distribution...")
            try:
                if not os.path.exists('/etc/os-release'):
                    raise FileNotFoundError("The /etc/os-release file is missing. This file is required to detect the Linux distribution.")
                
                with open('/etc/os-release', 'r') as f:
                    os_release = linux_distro.parse_os_release(f.read())
                distro = os_release.get('ID', '').lower()
                if not distro:
                    raise ValueError("Could not find 'ID=' line in /etc/os-release")
            except FileNotFoundError as e:
                error_msg = f"✗ {str(e)}"
                log_func(error_msg)
                error_occurred = True
                error_details.append(str(e))
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
            except PermissionError:
                error_msg = "✗ Permission denied reading /etc/os-release. Ensure the application has read permissions."
                log_func(error_msg)
                error_occurred = True
                error_details.append("Permission denied reading /etc/os-release")
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
            except Exception as e:
                error_msg = f"✗ Could not detect distribution: {e}"
                log_func(error_msg)
                error_occurred = True
                error_details.append(f"Could not detect distribution: {e}")
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
        
        os_release = os_release or {'ID': distro}
        log_func(f"Detected distribution: {_distro_name(os_release) if distro != 'windows' else distro}")

        # Get the update command for this distribution
        try:
            update_cmd, description = get_update_command(distro, repo_only, os_release=os_release)
            log_func(f"Running {description}...")
        except ValueError as e:
            error_msg = f"✗ {str(e)}"
            log_func(error_msg)
            error_occurred = True
            error_details.append(str(e))
            if email_config.get_error_notifications_enabled():
                email_notifier.send_error_notification(name, "\n".join(error_details))
            return
        
        # Execute the update command locally
        log_func("Executing update command...")
        
        # Security Note: Using shell=True is required here because update_cmd contains 
        # shell operators (&&) and environment variables that need shell interpretation.
        # The command string is constructed entirely from:
        # 1. Trusted internal distribution detection (validated against known distros)
        # 2. Hardcoded command templates defined in get_update_command()
        # 3. No user input is incorporated into the command
        # This approach is acceptable because:
        # - The distribution is detected from the system's /etc/os-release file
        # - Commands are selected from a fixed set of templates per distribution
        # - No external or user-provided data influences command construction
        # Alternative: Could use subprocess.run() with shell=False and pass commands
        # as arrays, but would require restructuring the command chains.
        process = subprocess.Popen(
            update_cmd,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Read output in real-time
        for line in process.stdout:
            log_func(line.rstrip())
        
        # Wait for process to complete
        exit_status = process.wait()
        
        if exit_status == 0:
            log_func(f"✓ Update completed successfully for {name}")
        else:
            error_msg = f"✗ Update finished with exit code {exit_status}"
            log_func(error_msg)
            error_occurred = True
            error_details.append(f"Update failed with exit code {exit_status}")
        
    except Exception as e:
        error_msg = f"✗ Error updating {name}: {str(e)}"
        log_func(error_msg)
        error_occurred = True
        error_details.append(f"Unexpected error: {str(e)}")
    
    finally:
        # Send error notification if an error occurred
        if error_occurred and email_config.get_error_notifications_enabled():
            error_message = "\n".join(error_details)
            email_notifier.send_error_notification(name, error_message)

def _run_windows_update(ssh, repo_only, log):
    """Windows: name the release, install Windows updates as SYSTEM, then (full update) apps via winget.

    Returns the problems found; an empty list means success.
    """
    problems = []
    _, out, _ = ssh.exec_command(windows_host.INFO_COMMAND, timeout=60)
    try:
        info = windows_host.parse_info(out.read().decode('utf-8', errors='replace'))
        log(f"{info['name']}, build {info['version']} ({info['channel']})")
        if info['support_status'] == 'ended':
            log(f"⚠ Microsoft ended support for this release on {info['support_end']}: it gets no security updates. "
                "Upgrade to a supported release.")
        elif info['support_status'] == 'ending':
            log(f"⚠ Microsoft ends support for this release on {info['support_end']}.")
        if info['support_note']:
            log(f"⚠ {info['support_note']}")
    except (ValueError, KeyError):
        log("Could not read the Windows version; continuing.")

    for command in windows_host.upload_commands(windows_host.UPDATE_WORKER):
        _, out, err = ssh.exec_command(command, timeout=60)
        if out.channel.recv_exit_status() != 0:
            detail = windows_host.error_text(err.read().decode('utf-8', errors='replace')).splitlines()
            return [f"Could not prepare Windows Update ({detail[-1] if detail else 'unknown error'}). "
                    "The SSH account must be an administrator."]

    log("Installing Windows updates (as SYSTEM, through a one-off scheduled task)...")
    _, out, err = ssh.exec_command(windows_host.update_command(install=True), timeout=None)
    result = None
    for line in ssh_helper.output_lines(out):
        parsed = windows_host.parse_result(line)
        if parsed is not None:
            result = parsed
        elif line.strip():
            log(line.rstrip())
    if result is None:
        detail = windows_host.error_text(err.read().decode('utf-8', errors='replace')).splitlines()
        problems.append(f"Windows Update gave no result ({detail[-1] if detail else 'no output'})")
    else:
        if result.get('error'):
            problems.append(f"Windows Update: {result['error']}")
        if result.get('failed'):
            problems.append(f"{result['failed']} Windows update(s) failed to install")
        if result.get('mode') == 'install':
            log(f"Windows updates installed: {result.get('installed', 0)}")
        if result.get('reboot'):
            log("⚠ Windows needs a restart to finish installing updates.")

    if not repo_only:
        log("Updating applications with winget...")
        _, out, _ = ssh.exec_command(windows_host.WINGET_COMMAND, timeout=None)
        for line in ssh_helper.output_lines(out):
            if line.strip():
                log(line.rstrip())
        code = out.channel.recv_exit_status()
        if code != 0:
            log(f"⚠ winget finished with exit code {code}; some applications may not have been updated.")
    return problems


CONNECT_ATTEMPTS = 3
CONNECT_RETRY_DELAY = 10


def run_update(host, user, name, log_list, repo_only=False, password=None):
    """
    Run system update on a remote host via SSH or locally via subprocess.
    
    Args:
        host: Hostname or IP address of the remote system (or 'localhost')
        user: SSH username (ignored for localhost)
        name: Display name for the host (used in logs)
        log_list: List to append log messages to
        repo_only: If True, only update packages from repositories without modifying config files
        password: Optional SSH password. If None, SSH key authentication is used.
    """
    def log(msg):
        """Helper function to log messages"""
        timestamp = time.strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] {msg}"
        print(log_msg)
        log_list.append(log_msg)
    
    # Check if this is a local update
    if is_localhost(host):
        return run_local_update(name, log_list, repo_only, log)
    
    # Remote update via SSH
    ssh = None
    error_occurred = False
    error_details = []
    
    try:
        log(f"Connecting to {name} ({host})...")
        
        # Create SSH client
        
        # Connect to the remote host using SSH key or password authentication
        if password:
            log("Connecting with password authentication...")
            connect = functools.partial(ssh_helper.create_client, host, username=user, password=password,
                                        timeout=30, look_for_keys=False, allow_agent=False)
        else:
            # SSH key authentication (key must be configured beforehand)
            connect = functools.partial(ssh_helper.create_client, host, username=user, timeout=30)
        # A host busy installing updates (Windows' sshd in particular) can drop or stall a handshake.
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                ssh = connect()
                break
            except paramiko.AuthenticationException:
                raise
            except (EOFError, TimeoutError, OSError, paramiko.SSHException) as e:
                if attempt == CONNECT_ATTEMPTS:
                    raise
                log(f"Connection attempt {attempt} failed ({str(e) or type(e).__name__}); retrying in {CONNECT_RETRY_DELAY} s...")
                time.sleep(CONNECT_RETRY_DELAY)
        log(f"Connected to {name}")
        
        # Detect the operating system and distribution
        log("Detecting operating system...")
        # First, try to detect if it's Windows by checking for PowerShell
        stdin, stdout, stderr = ssh.exec_command(WINDOWS_DETECTION_COMMAND)
        result = stdout.read().decode().strip().lower()
        
        if result == 'windows':
            log("Detected Windows operating system")
            for problem in _run_windows_update(ssh, repo_only, log):
                log(f"✗ {problem}")
                error_occurred = True
                error_details.append(problem)
            if not error_occurred:
                log(f"✓ Update completed successfully for {name}")
            return
        else:
            # Try Linux detection
            log("Detecting Linux distribution...")
            stdin, stdout, stderr = ssh.exec_command(linux_distro.OS_RELEASE_COMMAND)
            os_release = linux_distro.parse_os_release(stdout.read().decode('utf-8', errors='replace'))
            distro = os_release.get('ID', '').lower()
            if distro:
                log(f"Detected Linux distribution: {_distro_name(os_release)}")
            else:
                error_msg = "✗ Could not detect operating system"
                log(error_msg)
                error_occurred = True
                error_details.append("Could not detect operating system")
                if email_config.get_error_notifications_enabled():
                    email_notifier.send_error_notification(name, "\n".join(error_details))
                return
        
        # Get the update command for this distribution
        # If connecting as root (e.g. Proxmox), skip sudo prefix
        run_as_root = (user == 'root')
        try:
            update_cmd, description = get_update_command(distro, repo_only, run_as_root=run_as_root,
                                                          os_release=os_release)
            if run_as_root:
                log(f"Running {description} (as root, no sudo)...")
            else:
                log(f"Running {description}...")
        except ValueError as e:
            error_msg = f"✗ {str(e)}"
            log(error_msg)
            error_occurred = True
            error_details.append(str(e))
            return
        
        # Execute the update command
        log("Executing update command...")
        stdin, stdout, stderr = ssh.exec_command(update_cmd, get_pty=True)
        
        # Read output in real-time
        for line in ssh_helper.output_lines(stdout):
            log(line.rstrip())
        
        # Check exit status
        exit_status = stdout.channel.recv_exit_status()
        
        if exit_status == 0:
            log(f"✓ Update completed successfully for {name}")
        else:
            error_msg = f"✗ Update finished with exit code {exit_status}"
            log(error_msg)
            error_occurred = True
            error_details.append(f"Update failed with exit code {exit_status}")
            
            # Read any error messages
            errors = stderr.read().decode().strip()
            if errors:
                log(f"Errors: {errors}")
                error_details.append(f"Error output: {errors}")
        
        # Like on Windows, say when the host needs a restart (new kernel, or an OpenSSH upgrade whose
        # running sshd now resets connections). FleetPilot never restarts a host itself.
        check = linux_distro.reboot_check_command(os_release, run_as_root=run_as_root)
        if check:
            try:
                _, out, _ = ssh.exec_command(check, timeout=60)
                if linux_distro.REBOOT_MARKER in out.read().decode('utf-8', errors='replace'):
                    log(f"⚠ {name} needs a restart to finish the update (new kernel or system libraries).")
            except Exception as exc:   # a failed check must not turn a good update into a failure
                logging.info("Restart check on %s failed: %s", name, exc)

    except paramiko.AuthenticationException:
        error_msg = f"✗ Authentication failed for {name}. Check SSH keys or credentials."
        log(error_msg)
        error_occurred = True
        error_details.append("Authentication failed - check SSH keys or credentials")
    except paramiko.SSHException as e:
        error_msg = f"✗ SSH error connecting to {name}: {str(e)}"
        log(error_msg)
        error_occurred = True
        error_details.append(f"SSH error: {str(e)}")
    except Exception as e:
        # Timeouts carry no message; name them so the log is never just "Error updating x:".
        detail = "the host did not answer in time" if isinstance(e, TimeoutError) else (str(e) or type(e).__name__)
        error_msg = f"✗ Error updating {name}: {detail}"
        log(error_msg)
        error_occurred = True
        error_details.append(f"Unexpected error: {detail}")
    finally:
        if ssh:
            ssh.close()
            log(f"Disconnected from {name}")
        
        # Send error notification if an error occurred
        if error_occurred and email_config.get_error_notifications_enabled():
            error_message = "\n".join(error_details)
            email_notifier.send_error_notification(name, error_message)

def get_current_distribution():
    try:
        # Attempting to fetch distribution information
        with open('/etc/os-release', 'r') as file:
            return linux_distro.parse_os_release(file.read())['ID'].lower()
    except Exception as e:
        logging.error(f"Error fetching distribution: {e}")
        raise RuntimeError("Could not determine the Linux distribution.")

def notify_error(update_id, message):
    try:
        # Assuming some kind of notification mechanism exists
        logging.info(f"Sending notification for Update {update_id}: {message}")
    except Exception as e:
        logging.error(f"Failed to send notification for Update {update_id}: {e}")

def process_update(update_id):
    try:
        current_distro = get_current_distribution()

        if current_distro not in SUPPORTED_DISTRIBUTIONS:
            raise ValueError(f"Unsupported distribution: {current_distro}")

        logging.info(f"Preparing to process update {update_id} for {current_distro}...")

        # Simulated update processing...
        logging.info(f"Update {update_id} processed successfully.")

    except ValueError as ve:
        logging.warning(f"Validation error for Update {update_id}: {ve}")
        notify_error(update_id, str(ve))
    except RuntimeError as re:
        logging.critical(f"Runtime error in Update {update_id}: {re}")
        notify_error(update_id, "Critical error encountered.")
        raise
    except Exception as e:
        logging.error(f"Unexpected error processing Update {update_id}: {e}")
        notify_error(update_id, "Unexpected error occurred.")

def main():
    logging.basicConfig(level=logging.INFO)

    updates = ['update1', 'update2', 'update3']

    for update_id in updates:
        try:
            process_update(update_id)
        except Exception as e:
            logging.error(f"Aborting processing due to error: {e}")

if __name__ == "__main__":
    main()
