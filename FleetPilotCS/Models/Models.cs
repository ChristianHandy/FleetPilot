using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace FleetPilot.Models;

// ── Authentication ────────────────────────────────────────────────────────────
public class User
{
    public int Id { get; set; }
    [Required] public string Username { get; set; } = "";
    [Required] public string PasswordHash { get; set; } = "";
    public string Role { get; set; } = "admin"; // admin, operator, viewer
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? LastLogin { get; set; }
}

// ── Hosts ─────────────────────────────────────────────────────────────────────
public class ServerHost
{
    public int Id { get; set; }
    [Required] public string Name { get; set; } = "";
    public string Address { get; set; } = "";
    public string User { get; set; } = "root";
    public int Port { get; set; } = 22;
    public string? Password { get; set; }
    public string? SshKey { get; set; }
    public string? Mac { get; set; }
    public string? Description { get; set; }
    public string? Notes { get; set; }
    public string? Group { get; set; }
    public string? Location { get; set; }
    public string Environment { get; set; } = "Production";
    public string Criticality { get; set; } = "Medium";
    public string? Tags { get; set; } // JSON array
    public string? CustomImage { get; set; }
    public DateTime? LastSeen { get; set; }
    public DateTime? LastUpdate { get; set; }
    public bool IsOnline { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// ── VM Controllers (Proxmox) ──────────────────────────────────────────────────
public class VmEndpoint
{
    public int Id { get; set; }
    [Required] public string Name { get; set; } = "";
    [Required] public string Address { get; set; } = "";
    public int Port { get; set; } = 8006;
    public string? Username { get; set; }
    public string? Password { get; set; }
    public string? ApiToken { get; set; }
    public string Type { get; set; } = "proxmox"; // proxmox, esxi
    public bool VerifySsl { get; set; } = false;
    public string? Node { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class VmSnapshot
{
    public int Id { get; set; }
    public int EndpointId { get; set; }
    public string VmId { get; set; } = "";
    public string VmName { get; set; } = "";
    public string Status { get; set; } = "";
    public int Cpus { get; set; }
    public long MaxMem { get; set; }
    public long Mem { get; set; }
    public long Disk { get; set; }
    public double Uptime { get; set; }
    public string Type { get; set; } = "qemu"; // qemu, lxc
    public string Node { get; set; } = "";
    public string? Tags { get; set; }
    public DateTime RecordedAt { get; set; } = DateTime.UtcNow;
}

// ── Storage Controllers ───────────────────────────────────────────────────────
public class StorageEndpoint
{
    public int Id { get; set; }
    [Required] public string Name { get; set; } = "";
    [Required] public string Address { get; set; } = "";
    public int Port { get; set; } = 8006;
    public string? Username { get; set; }
    public string? Password { get; set; }
    public string? ApiToken { get; set; }
    public string Type { get; set; } = "proxmox"; // proxmox, truenas, unraid
    public bool VerifySsl { get; set; } = false;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// ── SMART Disk Monitoring ─────────────────────────────────────────────────────
public class SmartDisk
{
    public int Id { get; set; }
    public int HostId { get; set; }
    public string DevicePath { get; set; } = "";
    public string? Model { get; set; }
    public string? Serial { get; set; }
    public string? Firmware { get; set; }
    public long? CapacityBytes { get; set; }
    public string? SmartStatus { get; set; } // PASSED, FAILED, UNKNOWN
    public int? Temperature { get; set; }
    public long? PowerOnHours { get; set; }
    public int? ReallocatedSectors { get; set; }
    public int? PendingSectors { get; set; }
    public int? UncorrectableSectors { get; set; }
    public string? RawJson { get; set; }
    public DateTime LastPolled { get; set; } = DateTime.UtcNow;
}

// ── Fan Controllers ───────────────────────────────────────────────────────────
public class FanController
{
    public int Id { get; set; }
    [Required] public string Name { get; set; } = "";
    public int HostId { get; set; }
    public string ControllerType { get; set; } = "lm_sensors"; // lm_sensors, ipmi, liquidctl, pwm_sysfs, nbfc
    public string? MatchString { get; set; } // for liquidctl
    public bool DirectAccess { get; set; } = false;
    public string? RawData { get; set; } // JSON
    public DateTime? LastPolled { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class FanReading
{
    public int Id { get; set; }
    public int ControllerId { get; set; }
    public string ChannelName { get; set; } = "";
    public double? Rpm { get; set; }
    public double? DutyCycle { get; set; }
    public double? Temperature { get; set; }
    public DateTime RecordedAt { get; set; } = DateTime.UtcNow;
}

// ── Backup Controllers ────────────────────────────────────────────────────────
public class BackupServer
{
    public int Id { get; set; }
    [Required] public string Name { get; set; } = "";
    [Required] public string Address { get; set; } = "";
    public int Port { get; set; } = 443;
    public string Type { get; set; } = "pbs"; // pbs, duplicati, restic, borgwarehouse, urbackup, bacula, ssh_generic
    public string? Username { get; set; }
    public string? Password { get; set; }
    public string? ApiToken { get; set; }
    public bool VerifySsl { get; set; } = false;
    public string? SshKey { get; set; }
    public string? CustomCommand { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class BackupJob
{
    public int Id { get; set; }
    public int ServerId { get; set; }
    public string JobId { get; set; } = "";
    public string? JobName { get; set; }
    public string Status { get; set; } = "unknown";
    public DateTime? LastRun { get; set; }
    public DateTime? NextRun { get; set; }
    public long? SizeBytes { get; set; }
    public string? RawJson { get; set; }
    public DateTime RecordedAt { get; set; } = DateTime.UtcNow;
}

// ── HW Monitor / Stress Tests ─────────────────────────────────────────────────
public class HwServer
{
    public int Id { get; set; }
    [Required] public string Name { get; set; } = "";
    [Required] public string Address { get; set; } = "";
    public int Port { get; set; } = 22;
    public string SshUser { get; set; } = "root";
    public string? SshPassword { get; set; }
    public string? SshKey { get; set; }
    public bool StressTestRunning { get; set; } = false;
    public string? LastStatus { get; set; }
    public DateTime? LastSeen { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class HwMetric
{
    public int Id { get; set; }
    public int ServerId { get; set; }
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
    public string? FanData { get; set; } // JSON
    public DateTime RecordedAt { get; set; } = DateTime.UtcNow;
}

public class HwAlert
{
    public int Id { get; set; }
    public int ServerId { get; set; }
    public string AlertType { get; set; } = "";
    public string Message { get; set; } = "";
    public bool Acknowledged { get; set; } = false;
    public string? AckNote { get; set; }
    public DateTime? AcknowledgedAt { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// ── System Monitor ────────────────────────────────────────────────────────────
public class SystemMetric
{
    public int Id { get; set; }
    public int HostId { get; set; }
    public double? CpuPercent { get; set; }
    public double? MemPercent { get; set; }
    public long? MemUsedMb { get; set; }
    public long? MemTotalMb { get; set; }
    public double? DiskPercent { get; set; }
    public long? DiskUsedGb { get; set; }
    public long? DiskTotalGb { get; set; }
    public double? LoadAvg1 { get; set; }
    public double? LoadAvg5 { get; set; }
    public double? LoadAvg15 { get; set; }
    public long? UptimeSeconds { get; set; }
    public string? TopProcesses { get; set; } // JSON
    public DateTime RecordedAt { get; set; } = DateTime.UtcNow;
}

// ── Corsair Commander Pro ─────────────────────────────────────────────────────
public class CommanderDevice
{
    public int Id { get; set; }
    [Required] public string Name { get; set; } = "";
    public int HostId { get; set; }
    public string? MatchString { get; set; }
    public bool DirectAccess { get; set; } = false;
    public string? RawData { get; set; }
    public DateTime? LastPolled { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// ── Email Config ──────────────────────────────────────────────────────────────
public class EmailConfig
{
    public int Id { get; set; }
    public string SmtpHost { get; set; } = "";
    public int SmtpPort { get; set; } = 587;
    public string? SmtpUser { get; set; }
    public string? SmtpPassword { get; set; }
    public bool UseTls { get; set; } = true;
    public string? FromAddress { get; set; }
    public string? ToAddress { get; set; }
    public bool Enabled { get; set; } = false;
}

// ── Audit Log ─────────────────────────────────────────────────────────────────
public class AuditLog
{
    public int Id { get; set; }
    public int? UserId { get; set; }
    public string Action { get; set; } = "";
    public string? Target { get; set; }
    public string? Details { get; set; }
    public string? IpAddress { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

// ── DTOs (Data Transfer Objects) ──────────────────────────────────────────────
public record LoginRequest(string Username, string Password);
public record LoginResponse(string Token, string Username, string Role, DateTime Expires);
public record ApiResponse<T>(bool Success, T? Data, string? Error = null);
public record HostStatusDto(int Id, string Name, string Address, bool IsOnline, DateTime? LastSeen);
public record VmActionRequest(string Action); // start, stop, reboot, suspend, resume
public record FanSetRequest(string Channel, int DutyCycle);
public record StressTestAction(string Action); // start, stop
public record AckAlertRequest(int AlertId, string? Note);
