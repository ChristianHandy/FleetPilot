using Microsoft.EntityFrameworkCore;
using FleetPilot.Models;

namespace FleetPilot.Data;

public class AppDbContext : DbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

    public DbSet<User> Users => Set<User>();
    public DbSet<ServerHost> Hosts => Set<ServerHost>();
    public DbSet<VmEndpoint> VmEndpoints => Set<VmEndpoint>();
    public DbSet<VmSnapshot> VmSnapshots => Set<VmSnapshot>();
    public DbSet<StorageEndpoint> StorageEndpoints => Set<StorageEndpoint>();
    public DbSet<SmartDisk> SmartDisks => Set<SmartDisk>();
    public DbSet<FanController> FanControllers => Set<FanController>();
    public DbSet<FanReading> FanReadings => Set<FanReading>();
    public DbSet<BackupServer> BackupServers => Set<BackupServer>();
    public DbSet<BackupJob> BackupJobs => Set<BackupJob>();
    public DbSet<HwServer> HwServers => Set<HwServer>();
    public DbSet<HwMetric> HwMetrics => Set<HwMetric>();
    public DbSet<HwAlert> HwAlerts => Set<HwAlert>();
    public DbSet<SystemMetric> SystemMetrics => Set<SystemMetric>();
    public DbSet<CommanderDevice> CommanderDevices => Set<CommanderDevice>();
    public DbSet<EmailConfig> EmailConfigs => Set<EmailConfig>();
    public DbSet<AuditLog> AuditLogs => Set<AuditLog>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        // Indexes for performance
        modelBuilder.Entity<VmSnapshot>()
            .HasIndex(v => new { v.EndpointId, v.RecordedAt });
        modelBuilder.Entity<HwMetric>()
            .HasIndex(h => new { h.ServerId, h.RecordedAt });
        modelBuilder.Entity<SystemMetric>()
            .HasIndex(s => new { s.HostId, s.RecordedAt });
        modelBuilder.Entity<FanReading>()
            .HasIndex(f => new { f.ControllerId, f.RecordedAt });
        modelBuilder.Entity<AuditLog>()
            .HasIndex(a => a.CreatedAt);
        modelBuilder.Entity<User>()
            .HasIndex(u => u.Username).IsUnique();
    }
}
