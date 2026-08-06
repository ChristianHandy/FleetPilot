using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using FleetPilot.Data;
using FleetPilot.Models;
using FleetPilot.Services;

namespace FleetPilot.Controllers;

[ApiController]
[Route("api/fans")]
[Authorize]
public class FansController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly SshService _ssh;

    public FansController(AppDbContext db, SshService ssh)
    {
        _db = db;
        _ssh = ssh;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll()
        => Ok(await _db.FanControllers.ToListAsync());

    [HttpPost]
    public async Task<IActionResult> Add([FromBody] FanController fc)
    {
        fc.CreatedAt = DateTime.UtcNow;
        _db.FanControllers.Add(fc);
        await _db.SaveChangesAsync();
        return Ok(fc);
    }

    [HttpPut("{id}")]
    public async Task<IActionResult> Update(int id, [FromBody] FanController fc)
    {
        if (id != fc.Id) return BadRequest();
        _db.Entry(fc).State = EntityState.Modified;
        await _db.SaveChangesAsync();
        return Ok(fc);
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        var fc = await _db.FanControllers.FindAsync(id);
        if (fc == null) return NotFound();
        _db.FanControllers.Remove(fc);
        await _db.SaveChangesAsync();
        return Ok(new { success = true });
    }

    [HttpGet("{id}/readings")]
    public async Task<IActionResult> GetReadings(int id, [FromQuery] int hours = 2)
    {
        var cutoff = DateTime.UtcNow.AddHours(-hours);
        var readings = await _db.FanReadings
            .Where(r => r.ControllerId == id && r.RecordedAt >= cutoff)
            .OrderBy(r => r.RecordedAt)
            .ToListAsync();
        return Ok(readings);
    }

    [HttpPost("{id}/set")]
    public async Task<IActionResult> SetFan(int id, [FromBody] FanSetRequest req)
    {
        var fc = await _db.FanControllers.FindAsync(id);
        if (fc == null) return NotFound();
        var host = await _db.Hosts.FindAsync(fc.HostId);
        if (host == null) return NotFound("Host not found");

        string cmd = fc.ControllerType switch
        {
            "pwm_sysfs" => $"echo {req.DutyCycle * 255 / 100} > /sys/class/hwmon/{req.Channel}/pwm1",
            "ipmi" => $"ipmitool raw 0x30 0x30 0x02 0xff {req.DutyCycle:X2}",
            "liquidctl" => $"liquidctl --match '{fc.MatchString}' set {req.Channel} speed {req.DutyCycle}",
            _ => $"fancontrol set {req.Channel} {req.DutyCycle}"
        };

        var result = await _ssh.ExecuteAsync(host, cmd, 10);
        return result.Success
            ? Ok(new { success = true })
            : BadRequest(new { error = result.Error });
    }

    [HttpGet("{id}/detect")]
    public async Task<IActionResult> DetectChannels(int id)
    {
        var fc = await _db.FanControllers.FindAsync(id);
        if (fc == null) return NotFound();
        var host = await _db.Hosts.FindAsync(fc.HostId);
        if (host == null) return NotFound("Host not found");

        var result = await _ssh.ExecuteAsync(host,
            "sensors -j 2>/dev/null | python3 -c \"" +
            "import json,sys; d=json.load(sys.stdin); " +
            "fans=[{'chip':c,'feature':f,'channel':k,'rpm':v} " +
            "for c,data in d.items() for f,vals in data.items() if isinstance(vals,dict) " +
            "for k,v in vals.items() if 'fan' in k.lower() and 'input' in k.lower()]; " +
            "print(json.dumps(fans))\"", 10);

        return Ok(new { success = result.Success, channels = result.Output, error = result.Error });
    }

    [HttpPost("{id}/install")]
    public async Task<IActionResult> Install(int id)
    {
        var fc = await _db.FanControllers.FindAsync(id);
        if (fc == null) return NotFound();
        var host = await _db.Hosts.FindAsync(fc.HostId);
        if (host == null) return NotFound("Host not found");

        string installCmd = fc.ControllerType switch
        {
            "ipmi" => "apt-get install -y ipmitool",
            "liquidctl" => "pip3 install liquidctl",
            "nbfc" => "apt-get install -y nbfc-linux",
            _ => "apt-get install -y lm-sensors fancontrol"
        };

        var result = await _ssh.ExecuteAsync(host,
            $"DEBIAN_FRONTEND=noninteractive {installCmd} 2>&1 | tail -10", 120);
        return Ok(new { result.Success, result.Output, result.Error });
    }
}

[ApiController]
[Route("api/backup")]
[Authorize]
public class BackupController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly SshService _ssh;
    private readonly IHttpClientFactory _http;

    public BackupController(AppDbContext db, SshService ssh, IHttpClientFactory http)
    {
        _db = db;
        _ssh = ssh;
        _http = http;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll()
        => Ok(await _db.BackupServers.ToListAsync());

    [HttpPost]
    public async Task<IActionResult> Add([FromBody] BackupServer bs)
    {
        bs.CreatedAt = DateTime.UtcNow;
        _db.BackupServers.Add(bs);
        await _db.SaveChangesAsync();
        return Ok(bs);
    }

    [HttpPut("{id}")]
    public async Task<IActionResult> Update(int id, [FromBody] BackupServer bs)
    {
        if (id != bs.Id) return BadRequest();
        _db.Entry(bs).State = EntityState.Modified;
        await _db.SaveChangesAsync();
        return Ok(bs);
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        var bs = await _db.BackupServers.FindAsync(id);
        if (bs == null) return NotFound();
        _db.BackupServers.Remove(bs);
        await _db.SaveChangesAsync();
        return Ok(new { success = true });
    }

    [HttpGet("{id}/jobs")]
    public async Task<IActionResult> GetJobs(int id)
    {
        var jobs = await _db.BackupJobs
            .Where(j => j.ServerId == id)
            .OrderByDescending(j => j.RecordedAt)
            .Take(50)
            .ToListAsync();
        return Ok(jobs);
    }

    [HttpPost("{id}/test")]
    public async Task<IActionResult> Test(int id)
    {
        var bs = await _db.BackupServers.FindAsync(id);
        if (bs == null) return NotFound();
        // Simple connectivity test
        try
        {
            var client = _http.CreateClient();
            client.Timeout = TimeSpan.FromSeconds(5);
            var resp = await client.GetAsync($"https://{bs.Address}:{bs.Port}/api2/json/version");
            return Ok(new { success = resp.IsSuccessStatusCode, status = (int)resp.StatusCode });
        }
        catch (Exception ex)
        {
            return Ok(new { success = false, error = ex.Message });
        }
    }
}

[ApiController]
[Route("api/smart")]
[Authorize]
public class SmartController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly SshService _ssh;

    public SmartController(AppDbContext db, SshService ssh)
    {
        _db = db;
        _ssh = ssh;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll()
        => Ok(await _db.SmartDisks.ToListAsync());

    [HttpGet("host/{hostId}")]
    public async Task<IActionResult> GetByHost(int hostId)
        => Ok(await _db.SmartDisks.Where(d => d.HostId == hostId).ToListAsync());

    [HttpPost("host/{hostId}/scan")]
    public async Task<IActionResult> Scan(int hostId)
    {
        var host = await _db.Hosts.FindAsync(hostId);
        if (host == null) return NotFound();

        var result = await _ssh.ExecuteAsync(host,
            "lsblk -d -o NAME,SIZE,MODEL,SERIAL,TYPE --json 2>/dev/null || " +
            "ls /dev/sd* /dev/nvme* 2>/dev/null | head -20", 10);

        // Run smartctl on each disk
        var disks = new List<object>();
        var diskResult = await _ssh.ExecuteAsync(host,
            "for d in $(lsblk -d -o NAME --noheadings 2>/dev/null | grep -E '^(sd|nvme|vd)'); do " +
            "echo \"DISK:$d\"; smartctl -a /dev/$d --json 2>/dev/null | head -100; echo 'ENDDISK'; done", 30);

        return Ok(new { success = result.Success, output = diskResult.Output });
    }

    [HttpPost("host/{hostId}/poll")]
    public async Task<IActionResult> Poll(int hostId)
    {
        var host = await _db.Hosts.FindAsync(hostId);
        if (host == null) return NotFound();

        var result = await _ssh.ExecuteAsync(host,
            "smartctl --scan 2>/dev/null | awk '{print $1}' | while read d; do " +
            "echo \"==$d==\"; smartctl -A $d 2>/dev/null | grep -E 'Temperature|Reallocated|Pending|Uncorrectable|Power_On'; " +
            "done", 30);

        return Ok(new { result.Success, result.Output });
    }
}

[ApiController]
[Route("api/dashboard")]
[Authorize]
public class DashboardController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly SshService _ssh;

    public DashboardController(AppDbContext db, SshService ssh)
    {
        _db = db;
        _ssh = ssh;
    }

    [HttpGet("summary")]
    public async Task<IActionResult> GetSummary()
    {
        var hosts = await _db.Hosts.CountAsync();
        var onlineHosts = await _db.Hosts.CountAsync(h => h.IsOnline);
        var vmEndpoints = await _db.VmEndpoints.CountAsync();
        var backupServers = await _db.BackupServers.CountAsync();
        var hwServers = await _db.HwServers.CountAsync();
        var activeAlerts = await _db.HwAlerts.CountAsync(a => !a.Acknowledged);
        var fanControllers = await _db.FanControllers.CountAsync();

        return Ok(new
        {
            hosts = new { total = hosts, online = onlineHosts, offline = hosts - onlineHosts },
            vmEndpoints,
            backupServers,
            hwServers,
            activeAlerts,
            fanControllers,
            lastUpdated = DateTime.UtcNow
        });
    }

    [HttpGet("recent-activity")]
    public async Task<IActionResult> GetRecentActivity()
    {
        var logs = await _db.AuditLogs
            .OrderByDescending(l => l.CreatedAt)
            .Take(20)
            .ToListAsync();
        return Ok(logs);
    }
}
