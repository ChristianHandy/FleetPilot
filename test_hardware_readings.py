"""Readings from Proxmox nodes and lm-sensors are stored under the right names and values."""
import json

import fan_controller
import smart_manager
import vm_controller


def test_proxmox_disks_of_each_node_are_kept_apart(tmp_path, monkeypatch):
    """Both nodes of a cluster have an sda; SMART is asked for by the API's devpath."""
    monkeypatch.setattr(smart_manager, "DB_FILE", None)
    smart_manager.init_db(str(tmp_path))
    asked = []
    monkeypatch.setattr(vm_controller, "get_proxmox_disks", lambda ep, node: [
        {"devpath": "/dev/sda", "model": f"Disk of {node}", "serial": f"SN-{node}", "size": 4 * 10**12}])

    def smart(ep, node, disk):
        asked.append((node, disk))
        return {"health": "PASSED", "attributes": []}
    monkeypatch.setattr(vm_controller, "get_proxmox_disk_smart", smart)

    smart_manager.collect_proxmox_disks(1, "pve-01")
    smart_manager.collect_proxmox_disks(1, "pve-02")

    disks = {d["device"]: d for d in smart_manager.get_all_disks() if d["source"] == "proxmox"}
    assert set(disks) == {"pve-01:sda", "pve-02:sda"}
    assert disks["pve-02:sda"]["serial"] == "SN-pve-02"
    assert asked == [("pve-01", "/dev/sda"), ("pve-02", "/dev/sda")]


def test_lm_sensors_limits_are_not_shown_as_readings(monkeypatch):
    sensors = {
        "coretemp-isa-0000": {"Adapter": "ISA adapter",
                              "Package id 0": {"temp1_input": 48.0, "temp1_max": 84.0, "temp1_crit": 100.0,
                                               "temp1_crit_alarm": 0.0}},
        "nct6798-isa-0290": {"Adapter": "ISA adapter",
                             "fan1": {"fan1_input": 1123.0, "fan1_min": 0.0, "fan1_alarm": 0.0},
                             "in0": {"in0_input": 1.016, "in0_min": 0.0, "in0_max": 1.744}},
    }

    class _Ssh:
        def close(self):
            pass

    monkeypatch.setattr(fan_controller, "_ssh_connect", lambda dev: _Ssh())
    monkeypatch.setattr(fan_controller, "_run_remote", lambda ssh, cmd, timeout=60, stdin_data=None:
                        (json.dumps(sensors), "", 0) if cmd.startswith("sensors") else ("", "", 0))

    result = fan_controller._fetch_lm_sensors({"name": "test", "host": "192.0.2.10", "controller_type": "lm_sensors"})

    assert [t["value"] for t in result["temperatures"]] == [48.0]
    assert [f["rpm"] for f in result["fans"]] == [1123]
    assert [v["value"] for v in result["voltages"]] == [1.016]
