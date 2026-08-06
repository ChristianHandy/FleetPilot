using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using FleetPilot.Data;
using FleetPilot.Models;
using FleetPilot.Services;

namespace FleetPilot.Controllers;

[ApiController]
[Route("api/vm")]
[Authorize]
public class VmController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly ProxmoxService _proxmox;

    public VmController(AppDbContext db, ProxmoxService proxmox)
    {
        _db = db;
        _proxmox = proxmox;
    }

    // ── Endpoints ─────────────────────────────────────────────────────────────
    [HttpGet("endpoints")]
    public async Task<IActionResult> GetEndpoints()
        => Ok(await _db.VmEndpoints.Select(e => new
        {
            e.Id, e.Name, e.Address, e.Port, e.Type, e.Node, e.CreatedAt
        }).ToListAsync());

    [HttpPost("endpoints")]
    public async Task<IActionResult> AddEndpoint([FromBody] VmEndpoint ep)
    {
        ep.CreatedAt = DateTime.UtcNow;
        _db.VmEndpoints.Add(ep);
        await _db.SaveChangesAsync();
        return Ok(ep);
    }

    [HttpPut("endpoints/{id}")]
    public async Task<IActionResult> UpdateEndpoint(int id, [FromBody] VmEndpoint ep)
    {
        if (id != ep.Id) return BadRequest();
        _db.Entry(ep).State = EntityState.Modified;
        await _db.SaveChangesAsync();
        return Ok(ep);
    }

    [HttpDelete("endpoints/{id}")]
    public async Task<IActionResult> DeleteEndpoint(int id)
    {
        var ep = await _db.VmEndpoints.FindAsync(id);
        if (ep == null) return NotFound();
        _db.VmEndpoints.Remove(ep);
        await _db.SaveChangesAsync();
        return Ok(new { success = true });
    }

    // ── VMs ───────────────────────────────────────────────────────────────────
    [HttpGet("endpoints/{id}/vms")]
    public async Task<IActionResult> GetVms(int id)
    {
        var ep = await _db.VmEndpoints.FindAsync(id);
        if (ep == null) return NotFound();
        var vms = await _proxmox.GetVmsAsync(ep);
        return Ok(vms);
    }

    [HttpGet("endpoints/{id}/nodes")]
    public async Task<IActionResult> GetNodes(int id)
    {
        var ep = await _db.VmEndpoints.FindAsync(id);
        if (ep == null) return NotFound();
        var nodes = await _proxmox.GetNodesAsync(ep);
        return Ok(nodes);
    }

    [HttpPost("endpoints/{id}/vms/{node}/{vmId}/{type}/action")]
    public async Task<IActionResult> VmAction(int id, string node, string vmId, string type,
        [FromBody] VmActionRequest req)
    {
        var ep = await _db.VmEndpoints.FindAsync(id);
        if (ep == null) return NotFound();
        var ok = await _proxmox.VmActionAsync(ep, node, vmId, type, req.Action);
        return ok ? Ok(new { success = true }) : BadRequest(new { error = "Action failed" });
    }

    [HttpGet("all")]
    public async Task<IActionResult> GetAllVms()
    {
        var endpoints = await _db.VmEndpoints.ToListAsync();
        var result = new List<object>();
        var tasks = endpoints.Select(async ep =>
        {
            var vms = await _proxmox.GetVmsAsync(ep);
            return new { endpoint = new { ep.Id, ep.Name }, vms };
        });
        var all = await Task.WhenAll(tasks);
        return Ok(all);
    }
}

[ApiController]
[Route("api/hw")]
[Authorize]
public class HwMonitorController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly HwMonitorService _hwService;

    public HwMonitorController(AppDbContext db, HwMonitorService hwService)
    {
        _db = db;
        _hwService = hwService;
    }

    [HttpGet("servers")]
    public async Task<IActionResult> GetServers()
    {
        var servers = await _db.HwServers.ToListAsync();
        return Ok(servers.Select(s => new
        {
            s.Id, s.Name, s.Address, s.Port, s.SshUser, s.StressTestRunning,
            s.LastSeen, s.CreatedAt,
            metrics = _hwService.GetLiveMetrics(s.Id)
        }));
    }

    [HttpPost("servers")]
    public async Task<IActionResult> AddServer([FromBody] HwServer server)
    {
        server.CreatedAt = DateTime.UtcNow;
        _db.HwServers.Add(server);
        await _db.SaveChangesAsync();
        return Ok(server);
    }

    [HttpPut("servers/{id}")]
    public async Task<IActionResult> UpdateServer(int id, [FromBody] HwServer server)
    {
        if (id != server.Id) return BadRequest();
        _db.Entry(server).State = EntityState.Modified;
        await _db.SaveChangesAsync();
        return Ok(server);
    }

    [HttpDelete("servers/{id}")]
    public async Task<IActionResult> DeleteServer(int id)
    {
        var server = await _db.HwServers.FindAsync(id);
        if (server == null) return NotFound();
        _db.HwServers.Remove(server);
        await _db.SaveChangesAsync();
        return Ok(new { success = true });
    }

    [HttpGet("servers/{id}/live")]
    public IActionResult GetLive(int id)
    {
        var metrics = _hwService.GetLiveMetrics(id);
        return Ok(metrics ?? new LiveMetrics { IsOnline = false });
    }

    [HttpGet("servers/{id}/log")]
    public IActionResult GetLog(int id)
        => Ok(new { log = _hwService.GetLog(id) });

    [HttpGet("servers/{id}/history")]
    public async Task<IActionResult> GetHistory(int id, [FromQuery] int hours = 2)
    {
        var cutoff = DateTime.UtcNow.AddHours(-hours);
        var metrics = await _db.HwMetrics
            .Where(m => m.ServerId == id && m.RecordedAt >= cutoff)
            .OrderBy(m => m.RecordedAt)
            .Select(m => new
            {
                m.RecordedAt, m.CpuTemp, m.CpuUsage, m.GpuTemp,
                m.RamUsedMb, m.RamTotalMb, m.NetRxKbps, m.NetTxKbps
            })
            .ToListAsync();
        return Ok(metrics);
    }

    [HttpPost("servers/{id}/stress/start")]
    public async Task<IActionResult> StartStress(int id)
    {
        var server = await _db.HwServers.FindAsync(id);
        if (server == null) return NotFound();
        var ok = await _hwService.StartStressTestAsync(server);
        if (ok) { server.StressTestRunning = true; await _db.SaveChangesAsync(); }
        return ok ? Ok(new { success = true }) : BadRequest(new { error = "Failed to start" });
    }

    [HttpPost("servers/{id}/stress/stop")]
    public async Task<IActionResult> StopStress(int id)
    {
        var server = await _db.HwServers.FindAsync(id);
        if (server == null) return NotFound();
        await _hwService.StopStressTestAsync(server);
        server.StressTestRunning = false;
        await _db.SaveChangesAsync();
        return Ok(new { success = true });
    }

    [HttpPost("servers/{id}/install")]
    public async Task<IActionResult> InstallDeps(int id)
    {
        var server = await _db.HwServers.FindAsync(id);
        if (server == null) return NotFound();
        var output = await _hwService.InstallDependenciesAsync(server);
        return Ok(new { output });
    }

    [HttpGet("servers/{id}/alerts")]
    public async Task<IActionResult> GetAlerts(int id)
    {
        var alerts = await _db.HwAlerts
            .Where(a => a.ServerId == id && !a.Acknowledged)
            .OrderByDescending(a => a.CreatedAt)
            .ToListAsync();
        return Ok(alerts);
    }

    [HttpPost("alerts/{alertId}/ack")]
    public async Task<IActionResult> AckAlert(int alertId, [FromBody] AckAlertRequest req)
    {
        var alert = await _db.HwAlerts.FindAsync(alertId);
        if (alert == null) return NotFound();
        alert.Acknowledged = true;
        alert.AckNote = req.Note;
        alert.AcknowledgedAt = DateTime.UtcNow;
        await _db.SaveChangesAsync();
        return Ok(new { success = true });
    }
}
