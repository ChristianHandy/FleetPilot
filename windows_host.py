# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows PCs and servers reached through OpenSSH.

Supports every Windows release Microsoft still services (see LIFECYCLE): Windows 10
and 11 (Home, Pro, Enterprise, Education, IoT), the LTSC/LTSB releases 2016, 2019,
2021 and 2024, and Windows Server 2016, 2019, 2022 and 2025 with or without the
Desktop Experience.

* Commands are PowerShell 5.1 scripts sent as ``-EncodedCommand``, so they work
  whether the OpenSSH default shell is cmd.exe or PowerShell and nothing needs quoting.
* Updates use the Windows Update Agent that every release includes: no module from
  the PowerShell Gallery, works with WSUS and on Server Core and LTSC. Windows does
  not let a remote (SSH) session download or install updates, so that part runs as a
  one-off scheduled task under SYSTEM and FleetPilot follows its log.
"""
import base64
import json
import re
from datetime import date
from typing import Dict, Optional

POWERSHELL = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand '
WORK_DIR = r'C:\ProgramData\FleetPilot'
RESULT_MARKER = '@@fp:result '


# Console output is in the OEM code page by default (850 on German Windows: "ü" is byte 0x81). UTF-8 without a BOM
# keeps update titles and adapter names intact and leaves the first line ("windows") unprefixed.
UTF8_OUTPUT = '[Console]::OutputEncoding = New-Object Text.UTF8Encoding'


def ps(script: str) -> str:
    """A command line that runs ``script`` in Windows PowerShell from cmd.exe or PowerShell, writing UTF-8."""
    first, newline, rest = script.partition('\n')
    if first.startswith('# fleetpilot:'):      # keep the marker line first (the demo lab dispatches on it)
        script = f'{first}\n{UTF8_OUTPUT}\n{rest}'
    else:
        script = f'{UTF8_OUTPUT}\n{script}'
    return POWERSHELL + base64.b64encode(script.encode('utf-16-le')).decode('ascii')


# Prints "windows" on Windows; on other systems powershell.exe does not exist.
DETECT_COMMAND = ps("# fleetpilot:detect\n'windows'")

INFO_SCRIPT = r"""# fleetpilot:windows-info
$ErrorActionPreference = 'Stop'
$k = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$os = Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{
  caption = $os.Caption; edition = $k.EditionID; display_version = $k.DisplayVersion; release_id = $k.ReleaseId
  build = [int]$k.CurrentBuildNumber; ubr = [int]$k.UBR; installation = $k.InstallationType
  arch = $os.OSArchitecture; hostname = $env:COMPUTERNAME; last_boot = $os.LastBootUpTime.ToString('o')
} | ConvertTo-Json -Compress
"""
INFO_COMMAND = ps(INFO_SCRIPT)

SHUTDOWN_COMMAND = 'shutdown /s /t 30 /c "FleetPilot shutdown"'
REBOOT_COMMAND = 'shutdown /r /t 30 /c "FleetPilot restart"'

# ── Versions and support ─────────────────────────────────────────────────────
# End of servicing from Microsoft's lifecycle pages, checked October 2026. Windows
# 10/11 feature updates: (version, end for Home/Pro, end for Enterprise/Education).
CLIENT = {
    28000: ('26H1', date(2028, 3, 14), date(2029, 3, 13)),   # new Arm devices only
    26300: ('26H2', date(2028, 10, 10), date(2029, 10, 9)),
    26200: ('25H2', date(2027, 10, 12), date(2028, 10, 10)),
    26100: ('24H2', date(2026, 10, 13), date(2027, 10, 12)),
    22631: ('23H2', date(2025, 11, 11), date(2026, 11, 10)),
    22621: ('22H2', date(2024, 10, 8), date(2025, 10, 14)),
    22000: ('21H2', date(2023, 10, 10), date(2024, 10, 8)),
    19045: ('22H2', date(2025, 10, 14), date(2025, 10, 14)),
    19044: ('21H2', date(2022, 6, 13), date(2023, 6, 13)),
}
# Long-Term Servicing Channel: (name, end, end for the IoT edition).
LTSC = {
    26100: ('LTSC 2024', date(2029, 10, 9), date(2034, 10, 10)),
    19044: ('LTSC 2021', date(2027, 1, 12), date(2032, 1, 13)),
    17763: ('LTSC 2019', date(2029, 1, 9), date(2029, 1, 9)),
    14393: ('LTSB 2016', date(2026, 10, 13), date(2026, 10, 13)),
}
# Windows Server: (release, end of extended support).
SERVER = {
    26100: ('2025', date(2034, 10, 10)),
    25398: ('23H2', date(2025, 10, 24)),       # Annual Channel
    20348: ('2022', date(2031, 10, 14)),
    17763: ('2019', date(2029, 1, 9)),
    14393: ('2016', date(2027, 1, 12)),
}
# Windows 10 22H2 continues with Extended Security Updates (a paid licence for organisations).
ESU_END = date(2028, 10, 10)
CONSUMER_EDITIONS = ('Core', 'CoreN', 'CoreSingleLanguage', 'CoreCountrySpecific', 'Professional', 'ProfessionalN',
                     'ProfessionalWorkstation', 'ProfessionalWorkstationN', 'ProfessionalEducation',
                     'ProfessionalEducationN')
SOON_DAYS = 180


def parse_info(output: str) -> Dict:
    """The JSON printed by INFO_SCRIPT, with the release identified (see identify)."""
    start = output.find('{')
    if start < 0:
        raise ValueError('The host did not report its Windows version.')
    return identify(json.loads(output[start:output.rfind('}') + 1]))


def identify(info: Dict, today: Optional[date] = None) -> Dict:
    """Name, channel and support status of a Windows installation from INFO_SCRIPT's fields."""
    today = today or date.today()
    build = int(info.get('build') or 0)
    edition = str(info.get('edition') or '')
    installation = str(info.get('installation') or '')
    caption = str(info.get('caption') or 'Windows').replace('Microsoft ', '').strip()
    server = installation.lower().startswith('server') or edition.startswith('Server')
    ltsc = not server and re.fullmatch(r'(IoT)?EnterpriseS[NK]?(Eval)?', edition) is not None   # LTSC/LTSB editions, also evaluations
    iot = edition.startswith('IoT')
    # Windows 11 still writes "Windows 10" into the registry; the build tells them apart.
    if not server and build >= 22000:
        caption = caption.replace('Windows 10', 'Windows 11')

    release, end, channel, note = '', None, 'General Availability', ''
    if server:
        channel = 'Annual Channel' if build == 25398 else 'Long-Term Servicing Channel'
        if build in SERVER:
            release, end = SERVER[build]
    elif ltsc:
        channel = 'Long-Term Servicing Channel'
        if build in LTSC:
            release, end_ent, end_iot = LTSC[build]
            end = end_iot if iot else end_ent
    elif build in CLIENT:
        release, end_consumer, end_enterprise = CLIENT[build]
        end = end_consumer if edition in CONSUMER_EDITIONS else end_enterprise
        if build == 19045:
            note = f'Security updates only with Extended Security Updates (organisations: until {ESU_END.isoformat()}).'
    release = release or str(info.get('display_version') or info.get('release_id') or '')

    if end is None:
        status = 'unknown'
    elif end < today:
        status = 'ended'
    elif (end - today).days <= SOON_DAYS:
        status = 'ending'
    else:
        status = 'supported'
    # Append the release unless the caption already names it ("... LTSC Evaluation" + "LTSC 2024" -> "... 2024").
    missing = ' '.join(word for word in release.split() if word not in caption.split())
    name = f'{caption} {missing}' if missing else caption
    if installation == 'Server Core':
        name += ' (Server Core)'
    return {
        'name': name, 'caption': caption, 'release': release, 'edition': edition, 'build': build,
        'ubr': int(info.get('ubr') or 0), 'version': f'10.0.{build}.{int(info.get("ubr") or 0)}',
        'kind': 'server' if server else 'client', 'ltsc': ltsc or server, 'iot': iot,
        'core': installation == 'Server Core', 'channel': channel, 'arch': info.get('arch', ''),
        'hostname': info.get('hostname', ''), 'last_boot': info.get('last_boot', ''),
        'support_end': end.isoformat() if end else None, 'support_status': status, 'support_note': note,
    }


# ── Updates ──────────────────────────────────────────────────────────────────
# Runs as SYSTEM in a scheduled task (see RUNNER_SCRIPT). Mode "check" lists the
# missing updates, "install" also downloads and installs them. Never restarts.
UPDATE_WORKER = r"""# fleetpilot:windows-update
param([string]$Mode = 'check', [string]$Dir = 'C:\ProgramData\FleetPilot')
$ErrorActionPreference = 'Stop'
function Log([string]$m) { Add-Content -Path (Join-Path $Dir 'update.log') -Value $m -Encoding UTF8 }
$result = [ordered]@{ ok = $false; mode = $Mode; updates = @(); installed = 0; failed = 0; reboot = $false; error = $null }
try {
  $session = New-Object -ComObject Microsoft.Update.Session
  $session.ClientApplicationID = 'FleetPilot'
  Log 'Searching for updates...'
  $found = $session.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0 and Type='Software'").Updates
  $todo = New-Object -ComObject Microsoft.Update.UpdateColl
  $list = @()
  foreach ($u in $found) {
    $cats = @($u.Categories | ForEach-Object { $_.Name })
    $list += [ordered]@{ title = $u.Title; kb = (@($u.KBArticleIDs) -join ','); severity = [string]$u.MsrcSeverity
                         security = ($cats -contains 'Security Updates'); size = [int64]$u.MaxDownloadSize }
    if (-not $u.InstallationBehavior.CanRequestUserInput) {
      if (-not $u.EulaAccepted) { $u.AcceptEula() }
      [void]$todo.Add($u)
    }
  }
  $result.updates = $list
  Log ("Found {0} update(s)." -f $list.Count)
  foreach ($item in $list) { Log ("  " + $item.title) }
  if ($Mode -eq 'install' -and $todo.Count -gt 0) {
    Log 'Downloading...'
    $downloader = $session.CreateUpdateDownloader(); $downloader.Updates = $todo; [void]$downloader.Download()
    Log 'Installing...'
    $installer = $session.CreateUpdateInstaller(); $installer.Updates = $todo
    $outcome = $installer.Install()
    $names = @('not started', 'in progress', 'installed', 'installed with errors', 'failed', 'aborted')
    for ($i = 0; $i -lt $todo.Count; $i++) {
      $code = $outcome.GetUpdateResult($i).ResultCode
      if ($code -eq 2 -or $code -eq 3) { $result.installed++ } else { $result.failed++ }
      Log ("{0}: {1}" -f $todo.Item($i).Title, $names[$code])
    }
    $result.reboot = [bool]$outcome.RebootRequired
    $result.ok = ($result.failed -eq 0)
  } else {
    $result.ok = $true
  }
  if ((Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
      (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')) {
    $result.reboot = $true
  }
} catch {
  $result.error = $_.Exception.Message
  Log ('Error: ' + $_.Exception.Message)
}
$result | ConvertTo-Json -Depth 4 -Compress | Set-Content -Path (Join-Path $Dir 'update.json') -Encoding UTF8
"""

# Runs update.ps1 (uploaded by upload_commands) once as SYSTEM, printing its log as it
# grows and finally RESULT_MARKER plus the JSON result. Needs an administrator account.
RUNNER_SCRIPT = r"""# fleetpilot:run-as-system
$ErrorActionPreference = 'Stop'
$dir = 'C:\ProgramData\FleetPilot'
$script = Join-Path $dir 'update.ps1'; $log = Join-Path $dir 'update.log'; $json = Join-Path $dir 'update.json'
$b64 = Join-Path $dir 'update.b64'
$task = 'FleetPilot Windows Update'
# A run whose SSH session was lost keeps going as SYSTEM: follow it instead of starting a second one.
if ((Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue).State -eq 'Running') {
  Write-Output 'A Windows Update started earlier by FleetPilot is still running; following it.'
  Remove-Item $b64 -ErrorAction SilentlyContinue
} else {
  [IO.File]::WriteAllBytes($script, [Convert]::FromBase64String([IO.File]::ReadAllText($b64)))
  Remove-Item $b64, $log, $json -ErrorAction SilentlyContinue
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Mode __MODE__ -Dir "{1}"' -f $script, $dir)
  $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes __MINUTES__)
  Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings -Force | Out-Null
}
try {
  if ((Get-ScheduledTask -TaskName $task).State -ne 'Running') { Start-ScheduledTask -TaskName $task }
  $shown = 0; $deadline = (Get-Date).AddMinutes(__MINUTES__)
  while ($true) {
    Start-Sleep -Seconds 3
    if (Test-Path $log) {
      $lines = @(Get-Content -Path $log -Encoding UTF8)
      for ($i = $shown; $i -lt $lines.Count; $i++) { Write-Output $lines[$i] }
      $shown = $lines.Count
    }
    if (Test-Path $json) { break }
    if ((Get-Date) -gt $deadline) { Stop-ScheduledTask -TaskName $task; throw 'Windows Update did not finish in time.' }
    if ((Get-ScheduledTask -TaskName $task).State -eq 'Ready' -and -not (Test-Path $json)) {
      Start-Sleep -Seconds 3
      if (-not (Test-Path $json)) { throw 'Windows Update stopped without a result.' }
    }
  }
  Write-Output ('__MARKER__' + (Get-Content -Path $json -Raw -Encoding UTF8).Trim())
} finally {
  Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
}
"""


def upload_commands(script: str, chunk: int = 1800) -> list:
    """Commands that store ``script`` as update.ps1's base64 in WORK_DIR, a few KB per command.

    The first one creates WORK_DIR so that only SYSTEM and Administrators can write to it,
    because the script then runs as SYSTEM.
    """
    data = base64.b64encode(b'\xef\xbb\xbf' + script.encode('utf-8')).decode('ascii')
    parts = [data[i:i + chunk] for i in range(0, len(data), chunk)]
    first = (f"$d = '{WORK_DIR}'; New-Item -ItemType Directory -Force -Path $d | Out-Null; "
             "& icacls.exe $d /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null; "
             f"[IO.File]::WriteAllText((Join-Path $d 'update.b64'), '{parts[0]}')")
    rest = [f"[IO.File]::AppendAllText((Join-Path '{WORK_DIR}' 'update.b64'), '{p}')" for p in parts[1:]]
    return [ps('# fleetpilot:upload\n' + c) for c in [first] + rest]


def update_command(install: bool, minutes: int = 120) -> str:
    """Runner command line; run upload_commands(UPDATE_WORKER) first."""
    script = (RUNNER_SCRIPT.replace('__MODE__', 'install' if install else 'check')
              .replace('__MINUTES__', str(int(minutes))).replace('__MARKER__', RESULT_MARKER))
    return ps(script)


def parse_result(line: str) -> Optional[Dict]:
    """The JSON result from the runner's last line, or None for an ordinary log line."""
    line = line.strip().lstrip('\ufeff')
    if not line.startswith(RESULT_MARKER):
        return None
    result = json.loads(line[len(RESULT_MARKER):].lstrip('\ufeff'))
    result['updates'] = result.get('updates') or []
    if isinstance(result['updates'], dict):     # ConvertTo-Json writes a single item as an object
        result['updates'] = [result['updates']]
    return result


# winget upgrades the installed applications. Windows 10/11 have it through the App
# Installer; LTSC and Server editions usually do not, and that is not an error.
WINGET_COMMAND = ps("""# fleetpilot:winget
if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
  winget.exe upgrade --all --silent --accept-source-agreements --accept-package-agreements --disable-interactivity
} else {
  'winget is not installed on this system (usual for LTSC and Windows Server); applications were not updated.'
}
""")


# ── Hardware inventory (same fields as hw_info's Linux collector) ─────────────
HW_SCRIPT = r"""# fleetpilot:windows-hw
$ErrorActionPreference = 'SilentlyContinue'
$os = Get-CimInstance Win32_OperatingSystem; $cs = Get-CimInstance Win32_ComputerSystem
$cpu = @(Get-CimInstance Win32_Processor); $bb = Get-CimInstance Win32_BaseBoard; $bios = Get-CimInstance Win32_BIOS
$up = (Get-Date) - $os.LastBootUpTime; $total = [int64]$os.TotalVisibleMemorySize; $free = [int64]$os.FreePhysicalMemory
$ram = Get-CimInstance Win32_PhysicalMemory | ForEach-Object { ('{0} GB {1} MHz {2} {3}' -f ($_.Capacity / 1GB), $_.Speed, $_.Manufacturer, $_.PartNumber -replace '  MHz').Trim() }
$info = [ordered]@{
  platform = 'windows'; os = $os.Caption -replace '^Microsoft ', ''; kernel = $os.Version; hostname = $env:COMPUTERNAME
  uptime = '{0}d {1}h {2}m' -f $up.Days, $up.Hours, $up.Minutes; arch = $os.OSArchitecture
  cpu = [ordered]@{ model = "$($cpu[0].Name)".Trim(); cores = ($cpu | Measure-Object NumberOfCores -Sum).Sum
    threads = ($cpu | Measure-Object NumberOfLogicalProcessors -Sum).Sum; freq_mhz = $cpu[0].CurrentClockSpeed
    max_freq_mhz = $cpu[0].MaxClockSpeed; usage_pct = "$($cpu[0].LoadPercentage)" }
  memory = [ordered]@{ total_kb = "$total"; free_kb = "$free"; used_kb = "$($total - $free)"
    used_pct = "$([math]::Round(($total - $free) * 100 / [math]::Max($total, 1), 1))"; slots_raw = ($ram -join "`n") }
  motherboard = [ordered]@{ manufacturer = $bb.Manufacturer; product = $bb.Product; version = $bb.Version
    bios_vendor = $bios.Manufacturer; bios_version = $bios.SMBIOSBIOSVersion; bios_date = '{0:MM\/dd\/yyyy}' -f $bios.ReleaseDate }
  gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object { [ordered]@{ vendor = $_.AdapterCompatibility
    name = $_.Name; driver = $_.DriverVersion; vram_total_mb = "$([math]::Round($_.AdapterRAM / 1MB))" } })
  network = @(Get-NetAdapter -Physical | ForEach-Object {
    $ips = @(Get-NetIPAddress -InterfaceIndex $_.ifIndex)
    [ordered]@{ name = $_.Name; mac = $_.MacAddress -replace '-', ':'; speed_mbps = "$([math]::Round($_.Speed / 1e6))"
      state = "$($_.Status)".ToLower(); driver = $_.InterfaceDescription
      ipv4 = (($ips | Where-Object AddressFamily -eq 'IPv4').IPAddress -join ', ')
      ipv6 = (($ips | Where-Object { $_.AddressFamily -eq 'IPv6' -and $_.IPAddress -notlike 'fe80*' }).IPAddress -join ', ') } })
  disks = @(Get-PhysicalDisk | ForEach-Object { [ordered]@{ name = "PhysicalDrive$($_.DeviceId)"
    size = '{0:N0} GB' -f ($_.Size / 1GB); model = $_.FriendlyName; serial = "$($_.SerialNumber)".Trim()
    transport = "$($_.BusType)"; rotational = ("$($_.MediaType)" -eq 'HDD'); health = "$($_.HealthStatus)"
    type = $(if ("$($_.BusType)" -eq 'NVMe') { 'NVMe' } else { "$($_.MediaType)" -replace 'Unspecified' }) } })
  virtualization = $(if ($cs.Model -match 'Virtual|VMware|KVM|QEMU|Standard PC') { $cs.Model } else { 'bare-metal' })
}
$info | ConvertTo-Json -Depth 4 -Compress
"""
HW_COMMAND = ps(HW_SCRIPT)


# ── SMART through smartmontools for Windows ──────────────────────────────────
# smartctl.exe is usually not on the PATH; this finds it and lists the disks it sees.
SMARTCTL_SCAN_COMMAND = ps(r"""# fleetpilot:smartctl-scan
$exe = (Get-Command smartctl.exe -ErrorAction SilentlyContinue).Source
if (-not $exe) { $exe = @("$env:ProgramFiles\smartmontools\bin\smartctl.exe", "${env:ProgramFiles(x86)}\smartmontools\bin\smartctl.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1 }
if ($exe) { "SMARTCTL=$exe"; & $exe --scan }
""")
_SMARTCTL_PATH = re.compile(r'[A-Za-z]:\\[A-Za-z0-9 _().\\-]{1,200}\\smartctl\.exe')
_SCAN_DEVICE = re.compile(r'^/dev/([a-z]{2,4}[a-z0-9]{0,4})\b')


def parse_smartctl_scan(output: str):
    """(path of smartctl.exe or None, [disk names such as "sda" or "nvme0"]) from SMARTCTL_SCAN_COMMAND."""
    path, devices = None, []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('SMARTCTL='):
            candidate = line[len('SMARTCTL='):]
            path = candidate if _SMARTCTL_PATH.fullmatch(candidate) else None
        else:
            m = _SCAN_DEVICE.match(line)
            if m and m.group(1) not in devices:
                devices.append(m.group(1))
    return path, (devices if path else [])


def smartctl_command(path: str, option: str, device: str) -> str:
    """Runs smartctl.exe (a path from parse_smartctl_scan) for one disk; option is -a or -i."""
    if option not in ('-a', '-i') or not _SMARTCTL_PATH.fullmatch(path or '') \
            or not re.fullmatch(r'[a-z]{2,4}[a-z0-9]{0,4}', device):
        raise ValueError('Invalid smartctl call')
    return ps(f"# fleetpilot:smartctl\n& '{path}' {option} /dev/{device}")


# ── SSH key installation ─────────────────────────────────────────────────────
_PUBLIC_KEY = re.compile(r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}( [A-Za-z0-9@._-]{1,100})?')


def install_key_command(public_key: str) -> str:
    """Adds an OpenSSH public key where Windows OpenSSH reads it.

    Members of Administrators: C:\\ProgramData\\ssh\\administrators_authorized_keys, readable
    only by Administrators and SYSTEM (sshd ignores the file otherwise). Other accounts:
    .ssh\\authorized_keys in the profile. Prints "installed:<file>".
    """
    key = public_key.strip()
    if not _PUBLIC_KEY.fullmatch(key):
        raise ValueError('That is not an OpenSSH public key.')
    return ps(f"""# fleetpilot:install-key
$ErrorActionPreference = 'Stop'
$key = '{key}'
$admin = @([Security.Principal.WindowsIdentity]::GetCurrent().Groups | ForEach-Object {{ $_.Value }}) -contains 'S-1-5-32-544'
if ($admin) {{ $file = Join-Path $env:ProgramData 'ssh\\administrators_authorized_keys' }}
else {{ $dir = Join-Path $env:USERPROFILE '.ssh'; New-Item -ItemType Directory -Force -Path $dir | Out-Null; $file = Join-Path $dir 'authorized_keys' }}
if (-not (Test-Path $file) -or -not (Select-String -Path $file -SimpleMatch $key -Quiet)) {{ Add-Content -Path $file -Value $key -Encoding ASCII }}
if ($admin) {{ & icacls.exe $file /inheritance:r /grant '*S-1-5-32-544:F' '*S-1-5-18:F' | Out-Null }}
'installed:' + $file
""")
