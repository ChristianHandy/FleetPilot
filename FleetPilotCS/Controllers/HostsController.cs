using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using FleetPilot.Data;
using FleetPilot.Models;
using FleetPilot.Services;

namespace FleetPilot.Controllers;

[ApiController]
[Route("api/hosts")]
[Authorize]
public class HostsController : ControllerBase
{
    private readonly AppDbContext _db;
    private readonly SshService _ssh;

    public HostsController(AppDbContext db, SshService ssh)
    {
        _db = db;
        _ssh = ssh;
    }

    [HttpGet]
    public async Task<IActionResult> GetAll()
    {
        var hosts = await _db.Hosts.ToListAsync();
        return Ok(hosts.Select(h => new
        {
            h.Id, h.Name, h.Address, h.User, h.Port, h.Group, h.Location,
            h.Environment, h.Criticality, h.Tags, h.Description, h.Notes,
            h.Mac, h.CustomImage, h.IsOnline, h.LastSeen, h.LastUpdate, h.CreatedAt
        }));
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> Get(int id)
    {
        var host = await _db.Hosts.FindAsync(id);
        if (host == null) return NotFound();
        return Ok(host);
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] ServerHost host)
    {
        host.CreatedAt = DateTime.UtcNow;
        _db.Hosts.Add(host);
        await _db.SaveChangesAsync();
        return CreatedAtAction(nameof(Get), new { id = host.Id }, host);
    }

    [HttpPut("{id}")]
    public async Task<IActionResult> Update(int id, [FromBody] ServerHost host)
    {
        if (id != host.Id) return BadRequest();
        _db.Entry(host).State = EntityState.Modified;
        await _db.SaveChangesAsync();
        return Ok(host);
    }

    [HttpDelete("{id}")]
    public async Task<IActionResult> Delete(int id)
    {
        var host = await _db.Hosts.FindAsync(id);
        if (host == null) return NotFound();
        _db.Hosts.Remove(host);
        await _db.SaveChangesAsync();
        return Ok(new { success = true });
    }

    [HttpGet("{id}/status")]
    public async Task<IActionResult> CheckStatus(int id)
    {
        var host = await _db.Hosts.FindAsync(id);
        if (host == null) return NotFound();
        var online = await _ssh.IsOnlineAsync(host);
        host.IsOnline = online;
        host.LastSeen = online ? DateTime.UtcNow : host.LastSeen;
        await _db.SaveChangesAsync();
        return Ok(new { online, lastSeen = host.LastSeen });
    }

    [HttpPost("{id}/execute")]
    public async Task<IActionResult> Execute(int id, [FromBody] ExecuteRequest req)
    {
        var host = await _db.Hosts.FindAsync(id);
        if (host == null) return NotFound();
        var result = await _ssh.ExecuteAsync(host, req.Command, req.TimeoutSeconds);
        return Ok(new { result.Success, result.Output, result.Error, result.ExitCode });
    }

    [HttpGet("{id}/system-info")]
    public async Task<IActionResult> GetSystemInfo(int id)
    {
        var host = await _db.Hosts.FindAsync(id);
        if (host == null) return NotFound();
        var result = await _ssh.ExecuteAsync(host,
            "uname -a && echo '---' && cat /etc/os-release | head -5 && echo '---' && " +
            "uptime && echo '---' && free -m | head -2 && echo '---' && df -h / | tail -1", 10);
        return Ok(new { result.Success, result.Output, result.Error });
    }

    [HttpPost("{id}/update")]
    public async Task<IActionResult> UpdateSystem(int id)
    {
        var host = await _db.Hosts.FindAsync(id);
        if (host == null) return NotFound();
        var result = await _ssh.ExecuteAsync(host,
            "DEBIAN_FRONTEND=noninteractive apt-get update -q && apt-get upgrade -y 2>&1 | tail -20", 300);
        return Ok(new { result.Success, result.Output, result.Error });
    }
}

public record ExecuteRequest(string Command, int TimeoutSeconds = 30);
