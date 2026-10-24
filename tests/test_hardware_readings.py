# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
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


def test_hw_monitor_scripts_run_on_a_linux_host():
    """The collector is sent to each host as a script; a syntax error there marks every host unreachable."""
    import ast
    import subprocess
    import sys

    import hw_monitor
    ast.parse(hw_monitor.FAN_DETECT_SCRIPT)
    out = subprocess.run([sys.executable, "-"], input=hw_monitor.COLLECT_SCRIPT, capture_output=True,
                         text=True, timeout=60, check=True).stdout
    data = json.loads(out)
    assert data["ram_total_mb"] > 0 and data["cpu_cores"] >= 1 and "ts" in data


def test_fan_controller_and_hw_monitor_use_logging_not_print(tmp_path, monkeypatch, caplog, capsys):
    """fan_controller.py and hw_monitor.py use logging.getLogger(__name__) instead of print() (#160)."""
    import ast
    import logging
    from pathlib import Path
    import hw_monitor

    class _StopPoll(Exception):
        pass

    def _raise_db_down(*_a, **_kw):
        raise RuntimeError("db down")

    def _stop_sleep(_s):
        raise _StopPoll()

    def _raise_ssh(_dev):
        raise OSError("ssh unreachable")

    root = Path(__file__).resolve().parent.parent
    assert isinstance(fan_controller.logger, logging.Logger)
    assert fan_controller.logger.name == "fan_controller"
    assert isinstance(hw_monitor.logger, logging.Logger)
    assert hw_monitor.logger.name == "hw_monitor"

    for filename in ("fan_controller.py", "hw_monitor.py"):
        source = (root / filename).read_text(encoding="utf-8")
        assert "print(" not in source, filename
        tree = ast.parse(source)
        print_calls = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        assert print_calls == [], filename

    ast.parse(fan_controller._ARCTIC_READ_SCRIPT)
    ast.parse(fan_controller._ARCTIC_SET_SCRIPT)

    # Malformed hosts.json logs via hw_monitor.logger instead of warnings.warn or print()
    (tmp_path / "hosts.json").write_text("{invalid json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="hw_monitor"):
        hw_monitor._auto_import_from_hosts(str(tmp_path))
    assert capsys.readouterr().out == ""
    assert any("Auto-import from hosts.json failed" in rec.getMessage() for rec in caplog.records)

    # Poll loop error logs via hw_monitor.logger instead of print()
    caplog.clear()
    monkeypatch.setattr(hw_monitor, "get_db", _raise_db_down)
    monkeypatch.setattr(hw_monitor, "_poll_interval", lambda: 1)
    monkeypatch.setattr(hw_monitor.time, "sleep", _stop_sleep)
    with caplog.at_level(logging.WARNING, logger="hw_monitor"):
        try:
            hw_monitor._polling_loop()
        except _StopPoll:
            pass
    assert capsys.readouterr().out == ""
    assert any("Poll error: db down" in rec.getMessage() for rec in caplog.records)

    # fan_controller fetch, setter, test_connection, store_sample, and poll_all errors log via logger
    caplog.clear()
    monkeypatch.setattr(fan_controller, "_ssh_connect", _raise_ssh)
    with caplog.at_level(logging.WARNING, logger="fan_controller"):
        for ctype in ("lm_sensors", "ipmi", "nbfc", "liquidctl", "pwm_sysfs", "rpi_gpio_fan", "arctic_usb"):
            fres = fan_controller.fetch_status(
                {"name": "node-01", "host": "192.0.2.10", "controller_type": ctype},
            )
            assert not fres["ok"]
        for ctype in ("lm_sensors", "ipmi", "nbfc", "liquidctl", "pwm_sysfs", "arctic_usb"):
            res = fan_controller.set_fan_speed(
                {"name": "node-01", "host": "192.0.2.10", "controller_type": ctype},
                "pwm1",
                50,
            )
            assert not res["ok"]
        monkeypatch.setattr(
            fan_controller,
            "get_device",
            lambda _id: {"id": _id, "name": "node-01", "host": "192.0.2.10", "controller_type": "lm_sensors"},
        )
        conn_res = fan_controller.test_connection(1)
        assert not conn_res["ok"]

        monkeypatch.setattr(fan_controller, "_get_db", _raise_db_down)
        fan_controller._store_sample(1, {})

        monkeypatch.setattr(fan_controller, "_poll_running", True)
        monkeypatch.setattr(fan_controller, "list_devices", _raise_db_down)
        monkeypatch.setattr(fan_controller.time, "sleep", _stop_sleep)
        try:
            fan_controller._poll_all()
        except _StopPoll:
            pass

    assert capsys.readouterr().out == ""
    messages = [rec.getMessage() for rec in caplog.records]
    for ctype in ("lm_sensors", "ipmi", "nbfc", "liquidctl", "pwm_sysfs", "rpi_gpio_fan", "arctic_usb"):
        assert any(f"{ctype} fetch error for node-01" in m for m in messages), ctype
    for ctype in ("lm_sensors", "ipmi", "nbfc", "liquidctl", "pwm_sysfs", "arctic_usb"):
        assert any(f"{ctype} set error for node-01" in m for m in messages), ctype
    assert any("test_connection error for node-01" in m for m in messages)
    assert any("store_sample error: db down" in m for m in messages)
    assert any("poll_all error: db down" in m for m in messages)

