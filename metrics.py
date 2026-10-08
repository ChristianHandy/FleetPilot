"""
metrics.py — Prometheus text exposition for FleetPilot.

Served at /metrics (token protected, see app.py). Everything here is read
from data FleetPilot already collects; nothing triggers SSH or polling.
"""
import time
from datetime import datetime, timezone


def _escape(value) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class _Writer:
    def __init__(self):
        self.lines = []
        self._declared = set()

    def metric(self, name, mtype, help_text, value, **labels):
        if value is None:
            return
        if name not in self._declared:
            self.lines.append(f"# HELP {name} {help_text}")
            self.lines.append(f"# TYPE {name} {mtype}")
            self._declared.add(name)
        label_text = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
        self.lines.append(f"{name}{{{label_text}}} {float(value):g}" if labels else f"{name} {float(value):g}")

    def text(self):
        return "\n".join(self.lines) + "\n"


def _age_seconds(timestamp):
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - dt.timestamp())
    except ValueError:
        return None


def render(release, hosts, smart_manager, system_monitor, disktool_core=None):
    """Return the metrics page as Prometheus text format."""
    w = _Writer()
    w.metric("fleetpilot_info", "gauge", "FleetPilot build information.", 1,
             version=release.get("version", "unknown"))

    # Hosts
    w.metric("fleetpilot_hosts", "gauge", "Configured hosts.", len(hosts))
    for name, host in hosts.items():
        w.metric("fleetpilot_host_last_update_age_seconds", "gauge",
                 "Seconds since FleetPilot last updated the host.",
                 _age_seconds(host.get("last_update")), host=name)
        w.metric("fleetpilot_host_last_seen_age_seconds", "gauge",
                 "Seconds since the host was last seen.",
                 _age_seconds(host.get("last_seen")), host=name)

    # SMART
    try:
        summary = smart_manager.get_health_summary()
        for health, count in (summary.get("counts") or {}).items():
            w.metric("fleetpilot_smart_disks", "gauge", "Disks by latest SMART health.", count, health=health)
        w.metric("fleetpilot_smart_alerts_open", "gauge", "Unacknowledged SMART alerts.",
                 summary.get("active_alerts", 0))
        for disk in smart_manager.get_all_disks():
            labels = dict(source=disk.get("source") or "", device=disk.get("device") or "",
                          model=disk.get("model") or "", serial=disk.get("serial") or "")
            w.metric("fleetpilot_smart_disk_temperature_celsius", "gauge",
                     "Latest SMART temperature.", disk.get("temp"), **labels)
            w.metric("fleetpilot_smart_disk_power_on_hours", "counter",
                     "Latest SMART power-on hours.", disk.get("poh"), **labels)
            w.metric("fleetpilot_smart_disk_healthy", "gauge",
                     "1 if the latest SMART health is GOOD, else 0.",
                     1 if disk.get("health") == "GOOD" else 0 if disk.get("health") else None, **labels)
    except Exception:
        w.metric("fleetpilot_scrape_error", "gauge", "A collector failed during this scrape.", 1, collector="smart")

    # FleetPilot host itself
    try:
        latest = system_monitor.get_latest() or {}
        w.metric("fleetpilot_server_cpu_percent", "gauge", "CPU use of the FleetPilot server.", latest.get("cpu_pct"))
        w.metric("fleetpilot_server_memory_percent", "gauge", "Memory use of the FleetPilot server.", latest.get("ram_pct"))
    except Exception:
        w.metric("fleetpilot_scrape_error", "gauge", "A collector failed during this scrape.", 1, collector="system")

    # Disk Tools
    if disktool_core is not None:
        try:
            running = sum(1 for t in disktool_core.list_task_history(limit=200)
                          if str(dict(t).get("status", "")).upper() in ("RUNNING", "QUEUED", "PENDING"))
            w.metric("fleetpilot_disk_tasks_running", "gauge", "Disk Tools tasks queued or running.", running)
            w.metric("fleetpilot_disk_auto_mode", "gauge", "1 if Disk Tools auto mode is on.",
                     1 if disktool_core.auto_enabled else 0)
        except Exception:
            w.metric("fleetpilot_scrape_error", "gauge", "A collector failed during this scrape.", 1, collector="disktools")

    return w.text()
