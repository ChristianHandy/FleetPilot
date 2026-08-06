using FleetPilot.Data;
using FleetPilot.Models;
using Microsoft.EntityFrameworkCore;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FleetPilot.Services;

public class LiveMetrics
{
    public double? CpuTemp { get; set; }
    public double? CpuUsage { get; set; }
    public double? GpuTemp { get; set; }
    public double? GpuUsage { get; set; }
    public string? GpuVendor { get; set; }
    public long? RamUsedMb { get; set; }
    public long? RamTotalMb { get; set; }
    public double? NetRxKbps { get; set; }
    public double? NetTxKbps { get; set; }
    public double? DiskReadKbps { get; set; }
    public double? DiskWriteKbps { get; set; }
    public List<FanData> Fans { get; set; } = new();
    public bool IsOnline { get; set; }
    public string? Error { get; set; }
}

public class FanData
{
    public string Name { get; set; } = "";
    public double? Rpm { get; set; }
    public double? DutyCycle { get; set; }
    public double? Temp { get; set; }
}

public class HwMonitorService : BackgroundService
{
    private readonly IServiceProvider _services;
    private readonly SshService _ssh;
    private readonly ILogger<HwMonitorService> _logger;
    private readonly Dictionary<int, LiveMetrics> _liveCache = new();
    private readonly Dictionary<int, string> _logCache = new();

    // Stress test script
    private const string StressScript = @"#!/usr/bin/env python3
import subprocess, time, os, sys, json, re, datetime, threading, signal

LOG_DIR = '/root/hw_stress_test'
LOG_FILE = LOG_DIR + '/stress_test.log'
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg, level='INFO'):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] [{level}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def get_cpu_temp():
    try:
        r = subprocess.run(['sensors','-j'], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            temps = []
            for chip, data in d.items():
                for feat, vals in data.items():
                    if isinstance(vals, dict):
                        for k, v in vals.items():
                            if 'temp' in k.lower() and 'input' in k.lower() and isinstance(v, (int,float)):
                                if v > 5: temps.append(v)
            return max(temps) if temps else None
    except: pass
    return None

running = True
def handle_signal(sig, frame):
    global running
    running = False
    log('Test gestoppt', 'INFO')
    sys.exit(0)
signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

log('Hardware Stress Test gestartet (PID: ' + str(os.getpid()) + ')')

def monitor():
    while running:
        t = get_cpu_temp()
        mem = open('/proc/meminfo').readlines()
        md = {l.split(':')[0]: int(l.split()[1]) for l in mem if ':' in l}
        ram = (md.get('MemTotal',0) - md.get('MemAvailable',0)) // 1024
        msg = f'[MONITOR] CPU: {t:.1f}C' if t else '[MONITOR] CPU: N/A'
        msg += f' | RAM: {ram}MB'
        if t and t > 95:
            log(f'CRITICAL: CPU {t}C - stopping!', 'CRITICAL')
            global running; running = False; return
        log(msg)
        time.sleep(10)

threading.Thread(target=monitor, daemon=True).start()

iteration = 0
while running:
    iteration += 1
    log(f'=== ITERATION {iteration} ===', 'TEST')
    cpus = os.cpu_count() or 4
    try:
        subprocess.run(['stress-ng','--cpu',str(cpus),'--timeout','60s','--quiet'],
            capture_output=True, timeout=90)
        log('CPU test OK', 'TEST')
    except: log('CPU test skipped', 'WARN')
    if not running: break
    try:
        subprocess.run(['stress-ng','--vm','2','--vm-bytes','512M','--timeout','60s','--quiet'],
            capture_output=True, timeout=90)
        log('RAM test OK', 'TEST')
    except: log('RAM test skipped', 'WARN')
    log(f'=== ITERATION {iteration} DONE ===', 'TEST')
    for _ in range(30):
        if not running: break
        time.sleep(1)

log('Test beendet.')
";

    public HwMonitorService(IServiceProvider services, SshService ssh, ILogger<HwMonitorService> logger)
    {
        _services = services;
        _ssh = ssh;
        _logger = logger;
    }

    public LiveMetrics? GetLiveMetrics(int serverId)
        => _liveCache.TryGetValue(serverId, out var m) ? m : null;

    public string GetLog(int serverId)
        => _logCache.TryGetValue(serverId, out var l) ? l : "";

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            using var scope = _services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
            var servers = await db.HwServers.ToListAsync(stoppingToken);

            var tasks = servers.Select(s => PollServerAsync(s));
            await Task.WhenAll(tasks);

            await Task.Delay(TimeSpan.FromSeconds(8), stoppingToken);
        }
    }

    private async Task PollServerAsync(HwServer server)
    {
        var collectScript = @"
import json, subprocess, re, os, glob

def get_temp():
    try:
        r = subprocess.run(['sensors','-j'], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            temps = []
            for chip, data in d.items():
                for feat, vals in data.items():
                    if isinstance(vals, dict):
                        for k, v in vals.items():
                            if 'temp' in k.lower() and 'input' in k.lower() and isinstance(v,(int,float)):
                                if v > 5: temps.append(v)
            return max(temps) if temps else None
    except: pass
    return None

def get_gpu():
    # NVIDIA
    try:
        r = subprocess.run(['nvidia-smi','--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total','--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            parts = r.stdout.strip().split(',')
            return {'temp': float(parts[0]), 'usage': float(parts[1].strip().replace('%','')), 'vendor': 'nvidia',
                    'vram_used': int(parts[2].strip()), 'vram_total': int(parts[3].strip())}
    except: pass
    # AMD sysfs
    try:
        for hwmon in glob.glob('/sys/class/hwmon/hwmon*'):
            name = open(hwmon+'/name').read().strip() if os.path.exists(hwmon+'/name') else ''
            if name in ('amdgpu','radeon'):
                for tf in glob.glob(hwmon+'/temp*_input'):
                    raw = int(open(tf).read().strip())
                    t = raw / 1000.0
                    if t > 5: return {'temp': t, 'usage': None, 'vendor': 'amd', 'vram_used': None, 'vram_total': None}
    except: pass
    return None

def get_net():
    try:
        lines = open('/proc/net/dev').readlines()
        rx = tx = 0
        for l in lines[2:]:
            parts = l.split()
            if parts[0] not in ('lo:',):
                rx += int(parts[1]); tx += int(parts[9])
        return rx, tx
    except: return 0, 0

def get_disk_io():
    try:
        lines = open('/proc/diskstats').readlines()
        r = w = 0
        for l in lines:
            parts = l.split()
            if len(parts) >= 14 and parts[2].startswith(('sd','nvme','vd')):
                r += int(parts[5]); w += int(parts[9])
        return r * 512, w * 512
    except: return 0, 0

def get_fans():
    fans = []
    try:
        r = subprocess.run(['sensors','-j'], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            for chip, data in d.items():
                for feat, vals in data.items():
                    if isinstance(vals, dict):
                        for k, v in vals.items():
                            if 'fan' in k.lower() and 'input' in k.lower() and isinstance(v,(int,float)):
                                fans.append({'name': f'{chip}/{feat}', 'rpm': v})
    except: pass
    return fans

import time
mem = open('/proc/meminfo').readlines()
md = {l.split(':')[0]: int(l.split()[1]) for l in mem if ':' in l}
ram_used = (md.get('MemTotal',0) - md.get('MemAvailable',0)) // 1024
ram_total = md.get('MemTotal',0) // 1024

rx1, tx1 = get_net()
dr1, dw1 = get_disk_io()
time.sleep(1)
rx2, tx2 = get_net()
dr2, dw2 = get_disk_io()

cpu_stat1 = open('/proc/stat').readline().split()
time.sleep(0.5)
cpu_stat2 = open('/proc/stat').readline().split()
idle1 = int(cpu_stat1[4]); total1 = sum(int(x) for x in cpu_stat1[1:])
idle2 = int(cpu_stat2[4]); total2 = sum(int(x) for x in cpu_stat2[1:])
cpu_pct = 100.0 * (1 - (idle2-idle1)/(total2-total1)) if total2 != total1 else 0

result = {
    'cpu_temp': get_temp(),
    'cpu_usage': round(cpu_pct, 1),
    'gpu': get_gpu(),
    'ram_used_mb': ram_used,
    'ram_total_mb': ram_total,
    'net_rx_kbps': round((rx2-rx1)/1024, 1),
    'net_tx_kbps': round((tx2-tx1)/1024, 1),
    'disk_read_kbps': round((dr2-dr1)/1024, 1),
    'disk_write_kbps': round((dw2-dw1)/1024, 1),
    'fans': get_fans(),
    'stress_running': bool(__import__('subprocess').run(['pgrep','-f','hw_stress_test.py'],capture_output=True).returncode == 0)
}
print(json.dumps(result))
";
        try
        {
            var result = await _ssh.ExecuteAsync(
                server.Address, server.Port, server.SshUser,
                server.SshPassword, server.SshKey,
                $"python3 -c {ShellEscape(collectScript)}", 15);

            if (result.Success && !string.IsNullOrEmpty(result.Output))
            {
                var json = JObject.Parse(result.Output.Trim());
                var gpu = json["gpu"] as JObject;
                var metrics = new LiveMetrics
                {
                    IsOnline = true,
                    CpuTemp = json["cpu_temp"]?.Value<double?>(),
                    CpuUsage = json["cpu_usage"]?.Value<double?>(),
                    GpuTemp = gpu?["temp"]?.Value<double?>(),
                    GpuUsage = gpu?["usage"]?.Value<double?>(),
                    GpuVendor = gpu?["vendor"]?.ToString(),
                    RamUsedMb = json["ram_used_mb"]?.Value<long?>(),
                    RamTotalMb = json["ram_total_mb"]?.Value<long?>(),
                    NetRxKbps = json["net_rx_kbps"]?.Value<double?>(),
                    NetTxKbps = json["net_tx_kbps"]?.Value<double?>(),
                    DiskReadKbps = json["disk_read_kbps"]?.Value<double?>(),
                    DiskWriteKbps = json["disk_write_kbps"]?.Value<double?>(),
                    Fans = (json["fans"] as JArray)?.Select(f => new FanData
                    {
                        Name = f["name"]?.ToString() ?? "",
                        Rpm = f["rpm"]?.Value<double?>()
                    }).ToList() ?? new()
                };
                _liveCache[server.Id] = metrics;

                // Save to DB periodically (every ~5 polls = 40s)
                if (DateTime.UtcNow.Second % 40 < 8)
                {
                    using var scope = _services.CreateScope();
                    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
                    db.HwMetrics.Add(new HwMetric
                    {
                        ServerId = server.Id,
                        CpuTemp = metrics.CpuTemp,
                        CpuUsage = metrics.CpuUsage,
                        GpuTemp = metrics.GpuTemp,
                        GpuUsage = metrics.GpuUsage,
                        GpuVendor = metrics.GpuVendor,
                        RamUsedMb = metrics.RamUsedMb,
                        RamTotalMb = metrics.RamTotalMb,
                        NetRxKbps = metrics.NetRxKbps,
                        NetTxKbps = metrics.NetTxKbps,
                        DiskReadKbps = metrics.DiskReadKbps,
                        DiskWriteKbps = metrics.DiskWriteKbps,
                        FanData = JsonConvert.SerializeObject(metrics.Fans)
                    });
                    await db.SaveChangesAsync();
                    // Cleanup old metrics (keep 24h)
                    var cutoff = DateTime.UtcNow.AddHours(-24);
                    await db.HwMetrics
                        .Where(m => m.ServerId == server.Id && m.RecordedAt < cutoff)
                        .ExecuteDeleteAsync();
                }
            }
            else
            {
                _liveCache[server.Id] = new LiveMetrics { IsOnline = false, Error = result.Error };
            }

            // Fetch stress test log
            var logResult = await _ssh.ExecuteAsync(
                server.Address, server.Port, server.SshUser,
                server.SshPassword, server.SshKey,
                "tail -50 /root/hw_stress_test/stress_test.log 2>/dev/null || echo 'No log'", 5);
            _logCache[server.Id] = logResult.Output;
        }
        catch (Exception ex)
        {
            _liveCache[server.Id] = new LiveMetrics { IsOnline = false, Error = ex.Message };
        }
    }

    public async Task<bool> StartStressTestAsync(HwServer server)
    {
        // Upload script
        var upload = await _ssh.UploadFileAsync(
            server.Address, server.Port, server.SshUser,
            server.SshPassword, server.SshKey,
            "/root/hw_stress_test.py", StressScript);
        if (upload.StartsWith("ERROR")) return false;

        var result = await _ssh.ExecuteAsync(
            server.Address, server.Port, server.SshUser,
            server.SshPassword, server.SshKey,
            "pkill -f hw_stress_test.py 2>/dev/null; sleep 1; " +
            "mkdir -p /root/hw_stress_test && " +
            "nohup python3 /root/hw_stress_test.py > /root/hw_stress_test/stress_test.log 2>&1 &", 10);
        return result.ExitCode == 0;
    }

    public async Task<bool> StopStressTestAsync(HwServer server)
    {
        var result = await _ssh.ExecuteAsync(
            server.Address, server.Port, server.SshUser,
            server.SshPassword, server.SshKey,
            "pkill -f hw_stress_test.py 2>/dev/null; echo stopped", 5);
        return true;
    }

    public async Task<string> InstallDependenciesAsync(HwServer server)
    {
        var result = await _ssh.ExecuteAsync(
            server.Address, server.Port, server.SshUser,
            server.SshPassword, server.SshKey,
            "DEBIAN_FRONTEND=noninteractive apt-get install -y stress-ng fio lm-sensors fancontrol i2c-tools 2>&1 | tail -10",
            120);
        return result.Output + result.Error;
    }

    private static string ShellEscape(string s)
    {
        // Wrap in single quotes, escape single quotes inside
        return "'" + s.Replace("'", "'\\''") + "'";
    }
}
