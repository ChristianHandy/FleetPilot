# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for corsair_commander.py: liquidctl status parsing, fan control, and device CRUD."""

import json
import pytest

import corsair_commander


class _FakeChannel:
    def __init__(self, code=0):
        self._code = code

    def recv_exit_status(self):
        return self._code


class _FakeStream:
    def __init__(self, text="", code=0):
        self._data = text.encode("utf-8")
        self.channel = _FakeChannel(code)

    def read(self):
        return self._data


class _FakeSSHClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.commands = []
        self.closed = False

    def exec_command(self, cmd, timeout=30):
        self.commands.append((cmd, timeout))
        if self._responses:
            out, err, code = self._responses.pop(0)
        else:
            out, err, code = "", "", 0
        return None, _FakeStream(out, code), _FakeStream(err, code)

    def close(self):
        self.closed = True


def _sample_device():
    return {
        "name": "rack-commander",
        "host": "192.0.2.55",
        "port": 22,
        "username": "root",
        "password_plain": "test-pw",
        "match_str": "Commander Pro",
        "use_direct": 0,
        "use_sudo": 0,
    }


def test_fetch_status_parses_temperatures_fans_and_voltages(monkeypatch):
    payload = [
        {
            "bus": "hid",
            "description": "Corsair Commander Pro",
            "status": [
                {"key": "Temperature 1", "value": 28.4, "unit": "°C"},
                {"key": "Temperature 2", "value": 34.1, "unit": "°C"},
                {"key": "Fan 1 speed", "value": 1180, "unit": "rpm"},
                {"key": "Fan 2 speed", "value": 920, "unit": "rpm"},
                {"key": "+12V rail", "value": 12.08, "unit": "V"},
                {"key": "+5V rail", "value": 5.02, "unit": "V"},
                {"key": "+3.3V rail", "value": 3.31, "unit": "V"},
            ],
        }
    ]
    client = _FakeSSHClient([("", "", 0), (json.dumps(payload), "", 0)])
    monkeypatch.setattr(
        corsair_commander.ssh_helper, "create_client", lambda **kw: client
    )

    res = corsair_commander.fetch_status(_sample_device())

    assert res["ok"] is True
    assert res["error"] is None
    assert res["device"] == "rack-commander"
    assert res["temperatures"] == [
        {"label": "Temperature 1", "value": 28.4, "unit": "°C"},
        {"label": "Temperature 2", "value": 34.1, "unit": "°C"},
    ]
    assert res["fans"] == [
        {"label": "Fan 1 speed", "rpm": 1180},
        {"label": "Fan 2 speed", "rpm": 920},
    ]
    assert res["voltages"] == [
        {"label": "+12V rail", "value": 12.08, "unit": "V"},
        {"label": "+5V rail", "value": 5.02, "unit": "V"},
        {"label": "+3.3V rail", "value": 3.31, "unit": "V"},
    ]
    assert client.closed is True


@pytest.mark.parametrize(
    ("responses", "ssh_error"),
    [
        pytest.param(
            [("", "", 0), ("{not-valid-json", "", 0)],
            None,
            id="invalid-json",
        ),
        pytest.param(
            [("", "", 0), ("", "", 0), ("", "", 0)],
            None,
            id="empty-output",
        ),
        pytest.param(
            [("", "", 0), ("", "USB device not found", 1)],
            None,
            id="nonzero-exit",
        ),
        pytest.param(
            [],
            OSError("SSH connection refused"),
            id="ssh-error",
        ),
    ],
)
def test_fetch_status_errors_return_ok_false_with_message(
    monkeypatch, responses, ssh_error
):
    if ssh_error is not None:
        def _fail(**kw):
            raise ssh_error

        monkeypatch.setattr(
            corsair_commander.ssh_helper, "create_client", _fail
        )
    else:
        client = _FakeSSHClient(responses)
        monkeypatch.setattr(
            corsair_commander.ssh_helper, "create_client", lambda **kw: client
        )

    res = corsair_commander.fetch_status(_sample_device())

    assert res["ok"] is False
    assert isinstance(res["error"], str) and res["error"]


@pytest.mark.parametrize(
    ("channel", "speed"),
    [
        ("fan0", 50),
        ("fan7", 50),
        ("pump", 50),
        ("", 50),
        ("fan1; reboot", 50),
        ("fan1", -1),
        ("fan1", 101),
        ("fan1", True),
        ("fan1", "50"),
        ("fan1", []),
        ("fan1", [(40, -5)]),
        ("fan1", [(40, 120)]),
        ("fan1", [(-10, 50)]),
    ],
)
def test_set_fan_speed_rejects_bad_channels_and_out_of_range_speeds(
    monkeypatch, channel, speed
):
    def _unexpected_ssh(**kw):
        raise AssertionError("SSH should not be called for invalid input")

    monkeypatch.setattr(
        corsair_commander.ssh_helper, "create_client", _unexpected_ssh
    )

    res = corsair_commander.set_fan_speed(_sample_device(), channel, speed)

    assert res["ok"] is False
    assert isinstance(res["message"], str) and res["message"]


def test_set_fan_speed_builds_expected_commands(monkeypatch):
    client = _FakeSSHClient([("", "", 0), ("", "", 0)])
    monkeypatch.setattr(
        corsair_commander.ssh_helper, "create_client", lambda **kw: client
    )

    dev = _sample_device()
    res_fixed = corsair_commander.set_fan_speed(dev, "fan1", 65)
    assert res_fixed["ok"] is True
    assert (
        client.commands[0][0]
        == "liquidctl --match 'Commander Pro' set fan1 speed 65 --json 2>&1"
    )

    dev_direct = dict(dev, use_direct=1)
    res_profile = corsair_commander.set_fan_speed(
        dev_direct, "sync", [(30, 25), (60, 60), (80, 100)]
    )
    assert res_profile["ok"] is True
    assert (
        client.commands[1][0]
        == "liquidctl --match 'Commander Pro' --direct-access set sync speed 30 25 60 60 80 100 --json 2>&1"
    )


def test_device_crud_in_temp_database(tmp_path, monkeypatch):
    monkeypatch.setattr(corsair_commander, "_DB_FILE", None)
    corsair_commander.init_db(str(tmp_path))

    dev_id = corsair_commander.add_device(
        name="commander-main",
        host="192.0.2.10",
        port=2222,
        username="admin",
        password="secret-password",
        match_str="Commander Pro",
        use_direct=True,
        use_sudo=True,
        notes="rack 1",
    )
    assert isinstance(dev_id, int)

    devices = corsair_commander.list_devices()
    assert len(devices) == 1
    assert devices[0]["id"] == dev_id
    assert devices[0]["name"] == "commander-main"
    assert devices[0]["host"] == "192.0.2.10"
    assert devices[0]["port"] == 2222
    assert devices[0]["use_direct"] == 1
    assert devices[0]["use_sudo"] == 1
    assert "password" not in devices[0]

    fetched = corsair_commander.get_device(dev_id)
    assert fetched is not None
    assert fetched["password_plain"] == "secret-password"

    updated = corsair_commander.update_device(
        dev_id,
        host="192.0.2.20",
        password="updated-password",
        notes="rack 2",
    )
    assert updated is True
    assert corsair_commander.update_device(dev_id, unknown_field="x") is False

    fetched_after = corsair_commander.get_device(dev_id)
    assert fetched_after["host"] == "192.0.2.20"
    assert fetched_after["notes"] == "rack 2"
    assert fetched_after["password_plain"] == "updated-password"

    corsair_commander.delete_device(dev_id)
    assert corsair_commander.list_devices() == []
    assert corsair_commander.get_device(dev_id) is None
