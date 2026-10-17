# Managing Windows PCs and servers

FleetPilot manages Windows machines over OpenSSH, like Linux hosts. Nothing else has to be installed on them. FleetPilot itself runs on Linux (a VM, an LXC container or a Raspberry Pi).

## Supported Windows versions

Every Windows release that Microsoft still services, as of October 2026. FleetPilot shows each host's release and support status, and the update log warns before support ends.

| Release | Editions | Build | Microsoft support ends |
|---|---|---|---|
| Windows 11 26H2 | Home, Pro | 26300 | 2028-10-10 |
| | Enterprise, Education | 26300 | 2029-10-09 |
| Windows 11 26H1 (only on new Arm devices) | Home, Pro | 28000 | 2028-03-14 |
| | Enterprise, Education | 28000 | 2029-03-13 |
| Windows 11 25H2 | Home, Pro | 26200 | 2027-10-12 |
| | Enterprise, Education | 26200 | 2028-10-10 |
| Windows 11 24H2 | Enterprise, Education | 26100 | 2027-10-12 |
| Windows 11 23H2 | Enterprise, Education | 22631 | 2026-11-10 |
| Windows 11 Enterprise LTSC 2024 | Enterprise LTSC | 26100 | 2029-10-09 |
| | IoT Enterprise LTSC | 26100 | 2034-10-10 |
| Windows 10 Enterprise LTSC 2021 | Enterprise LTSC | 19044 | 2027-01-12 |
| | IoT Enterprise LTSC | 19044 | 2032-01-13 |
| Windows 10 Enterprise LTSC 2019 | Enterprise LTSC, IoT Enterprise LTSC | 17763 | 2029-01-09 |
| Windows 10 22H2 | all, with Extended Security Updates (ESU) | 19045 | ESU for organisations until 2028-10-10 |
| Windows Server 2025 | Standard, Datacenter (Desktop Experience or Server Core) | 26100 | 2034-10-10 |
| Windows Server 2022 | Standard, Datacenter (Desktop Experience or Server Core) | 20348 | 2031-10-14 |
| Windows Server 2019 | Standard, Datacenter (Desktop Experience or Server Core) | 17763 | 2029-01-09 |
| Windows Server 2016 | Standard, Datacenter (Desktop Experience or Server Core) | 14393 | 2027-01-12 |

Older releases still work as far as their tools allow. FleetPilot marks them **Support ended**:
- Windows 11 24H2 Home and Pro, Windows 10 22H2 without ESU and Windows 10 LTSB 2016 ended in October 2025 or October 2026.
- Windows Server 23H2 (Annual Channel) ended in October 2025.

The dates come from Microsoft's lifecycle pages and are kept in [`windows_host.py`](windows_host.py).

## What works

| Feature | How it works on Windows |
|---|---|
| **OS detection** | **Detect OS** on the host shows the exact release, for example *Windows 11 Enterprise LTSC 2024* or *Windows Server 2022 Standard (Server Core)*. It also shows the build and the support status. |
| **Windows updates** | Through the Windows Update Agent that every release includes:<ul><li>It follows WSUS or Windows Update for Business policies.</li><li>It works on Server Core and LTSC, and needs no PowerShell Gallery module.</li><li>Windows does not let an SSH session install updates, so FleetPilot runs the installation once as SYSTEM through a scheduled task. It shows the progress live and removes the task afterwards.</li><li>FleetPilot never restarts the machine; it tells you when a restart is needed.</li></ul> |
| **Application updates** | **Full update** also runs `winget upgrade --all` where winget is installed: Windows 10/11 through the App Installer. LTSC and Server usually have no winget, which is reported and is not an error. **Repository-only update** installs Windows updates only. |
| **Shut down** | `shutdown /s /t 30`, so logged-in users get a 30-second warning. |
| **Wake-on-LAN** | As for any host with a MAC address. Enable it in the firmware and the network adapter's power settings. |
| **Hardware overview** | CPU, memory modules, mainboard and BIOS, GPUs, network adapters and disks, read through CIM. |
| **SMART** | With [smartmontools for Windows](https://www.smartmontools.org/wiki/Download#InstalltheWindowspackage) installed, FleetPilot reads disk health like on Linux. Without it, the hardware overview still shows each disk's health status. |
| **Vulnerability scan** | Not for Windows: there is no package-level vulnerability data. Keep Windows Update running; FleetPilot installs the missing updates. |

All commands are PowerShell 5.1 scripts sent as `-EncodedCommand`. They work whether the OpenSSH default shell is `cmd.exe` or PowerShell, and nothing from a form reaches the command line.

## Setting up a Windows machine

### 1. OpenSSH server

**Windows 10 1809 and later, Windows 11, LTSC 2019/2021/2024, Server 2019/2022:** in PowerShell as administrator:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
```

**Windows Server 2025** includes the OpenSSH server; only enable it:

```powershell
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
```

**Windows Server 2016 and Windows 10 LTSB 2016** have no built-in OpenSSH. Install [Win32-OpenSSH from Microsoft's GitHub releases](https://github.com/PowerShell/Win32-OpenSSH/releases) (MSI package).

On **Windows 10, Windows 11 and Windows Server 2025**, the firewall rule `OpenSSH-Server-In-TCP` allows port 22 only for **Private** networks, and Windows puts a newly connected network into the **Public** profile, so FleetPilot's connection times out. (Seen on Windows 11 LTSC 2024 and Server 2025; Server 2016–2022 worked without a change.) Either mark the network as private or allow SSH from FleetPilot's network:

```powershell
Get-NetConnectionProfile                                    # NetworkCategory: Public or Private
Set-NetConnectionProfile -InterfaceAlias Ethernet -NetworkCategory Private
# or keep it public and allow SSH only from the local network:
Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -Profile Any -RemoteAddress LocalSubnet
```

### 2. An administrator account

FleetPilot needs an account in the local **Administrators** group: installing updates and shutting down require it. A dedicated local account is a good choice, for example `fleetpilot`.

### 3. SSH key (recommended)

After adding the host (step 4), use **Install SSH key** on it and enter the account's password once. FleetPilot puts its key where Windows OpenSSH reads it: for administrators that is `C:\ProgramData\ssh\administrators_authorized_keys` (readable only by Administrators and SYSTEM), not the `.ssh` folder in the profile.

To do it by hand instead:

```powershell
Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value 'ssh-ed25519 AAAA... fleetpilot'
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F'
```

A password works too: enter it when you add the host.

### 4. Add the host in FleetPilot

1. **Hosts → Add host**, with the address, the account and the port (22).
2. Open the host and click **Detect OS**: FleetPilot shows the Windows release and its support status.
3. Run **Repository-only update** (Windows updates only) or **Full update** (Windows updates and winget).

## What FleetPilot leaves on the machine

| Where | What | When |
|---|---|---|
| `C:\ProgramData\FleetPilot\` | `update.ps1`, `update.log` and `update.json` of the last update | Overwritten by the next update. Only SYSTEM and Administrators can write here, because the script runs as SYSTEM. |
| Task Scheduler | *FleetPilot Windows Update* | Only while an update runs |

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| *Could not prepare Windows Update … The SSH account must be an administrator* | The account is not in the local Administrators group, or (with UAC) it is a domain account without administrator rights on this machine. |
| *Windows Update: 0x8024402C* or similar | The machine cannot reach Windows Update or its WSUS server. Check the proxy and the WSUS address. |
| The update runs for a long time without output | Large cumulative updates download and install silently, and slow disks make that take hours. FleetPilot waits up to 2 hours and then stops waiting, but never stops Windows: the installation continues as SYSTEM. Run the update again later; FleetPilot follows the running installation and shows its result. |
| *winget is not installed on this system* | Normal on LTSC and Server: only Windows updates are installed. |
| Detect OS shows "Linux" | The SSH login lands in WSL or another shell without `powershell.exe`. Set the OpenSSH default shell back to `cmd.exe` or PowerShell. |
| Connecting times out, although `sshd` is running (Windows 10/11, Server 2025) | The firewall rule for SSH covers only Private networks, and the network is Public. See [step 1](#1-openssh-server). |
| *the SSH server closed the connection without answering*, or most connections fail with *Connection reset* | The SSH server is too busy to answer, typically while Windows installs updates. With OpenSSH 10.0 for Windows, each login that times out this way can leave an `sshd-auth.exe` process behind; we found 88 of them on a Windows 11 test machine. From 10 waiting processes on, `sshd` turns away more and more new connections ("drop connection … Maxstartups" in the *OpenSSH/Operational* event log), even after memory is free again. Check with `(Get-Process sshd-auth).Count` and clear them with `Get-Process sshd-auth \| Stop-Process -Force`, run from the console or from any SSH session that gets through. Sessions that are already signed in are not affected. When no connection gets through any more, `ssh -v` from FleetPilot's machine shows *banner line 0: Exceeded MaxStartups*; then only `Restart-Service sshd` on the console or a restart of Windows helps (seen on Server 2025). |
| Server 2016 updates are slow | Server 2016's cumulative updates are large and install slowly; that is normal. |
