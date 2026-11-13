# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""disktool_core: device-name validation against a fake /sys/block, the
operations table on a throwaway database, format-target protection with
mocked inspection commands, VALIDATION_SUMMARY parsing with a mocked
helper, and the auto mode worker's device decisions with fake disk lists.

Nothing here touches a real disk: subprocess and the privileged helper are
replaced, and block-device presence comes from a stubbed listing.
"""
import subprocess
from types import SimpleNamespace

import pytest

import disktool_core as dc


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "DB_FILE", None)
    dc.init_db(str(tmp_path))
    return tmp_path


@pytest.fixture
def present(monkeypatch):
    """Control which block devices the machine 'has'."""
    devices = ["sda", "sdb", "nvme0n1", "mmcblk0"]
    monkeypatch.setattr(dc, "_present_block_devices", lambda: list(devices))
    return devices


def _type_map(monkeypatch, types):
    """Fake the lsblk TYPE lookup used by validate_format_target."""
    def fake_output(cmd):
        if cmd[0] == "lsblk":
            return types[cmd[-1].removeprefix("/dev/")]
        raise AssertionError(f"unexpected command: {cmd}")
    monkeypatch.setattr(dc, "_command_output", fake_output)


# ── sanitize_device_name ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["sda", "nvme0n1", "mmcblk0", "sda-1_x", "a" * 255])
def test_sanitize_accepts_plain_device_names(name):
    assert dc.sanitize_device_name(name) == name


@pytest.mark.parametrize("name", [
    "", None, 42, "/dev/sda", "sda/../etc", "..", "sda 1", "sda;id",
    "sda|x", "sda/b", "a" * 256, "sda\nreboot",
])
def test_sanitize_rejects_paths_and_metacharacters(name):
    with pytest.raises(ValueError):
        dc.sanitize_device_name(name)


# ── local_block_device ──────────────────────────────────────────────────────

def test_local_block_device_returns_present_disks(present):
    for name in ("sda", "nvme0n1", "mmcblk0"):
        assert dc.local_block_device(name) == name


def test_local_block_device_rejects_partitions_and_unknown(present):
    # /sys/block lists whole disks, so a partition name never matches.
    with pytest.raises(ValueError, match="No disk named sda1"):
        dc.local_block_device("sda1")
    with pytest.raises(ValueError, match="No disk named sdz"):
        dc.local_block_device("sdz")


def test_local_block_device_rejects_paths_before_lookup(present):
    with pytest.raises(ValueError, match="Invalid device name"):
        dc.local_block_device("/dev/sda")


def test_local_block_device_with_no_devices_present(monkeypatch):
    monkeypatch.setattr(dc, "_present_block_devices", lambda: [])
    with pytest.raises(ValueError, match="No disk named sda"):
        dc.local_block_device("sda")


# ── operations table ────────────────────────────────────────────────────────

def test_log_op_creates_a_running_record(db):
    op_id = dc.log_op("sdb", "QUICK_WIPE_FORMAT_EXT4")
    assert isinstance(op_id, int) and op_id >= 1
    row = dc.get_task_record(op_id)
    assert row["device"] == "sdb"
    assert row["action"] == "QUICK_WIPE_FORMAT_EXT4"
    assert row["status"] == "RUNNING"
    assert row["progress"] == 0
    assert row["details"] == "Task queued on the FleetPilot server."
    assert row["started_ts"] is not None
    assert row["finished_ts"] is None


def test_log_op_truncates_long_details(db):
    op_id = dc.log_op("sdb", "SMART_SHORT", "x" * 6000)
    assert len(dc.get_task_record(op_id)["details"]) == 5000


def test_update_op_progress_and_details(db):
    op_id = dc.log_op("sdb", "FORMAT")
    dc.update_op(op_id, progress=55, details="half way")
    row = dc.get_task_record(op_id)
    assert row["progress"] == 55
    assert row["details"] == "half way"
    assert row["status"] == "RUNNING"
    assert row["finished_ts"] is None


def test_update_op_terminal_status_stamps_finished(db):
    op_id = dc.log_op("sdb", "FORMAT")
    dc.update_op(op_id, status="OK", progress=100)
    row = dc.get_task_record(op_id)
    assert row["status"] == "OK"
    assert row["finished_ts"] is not None


def test_update_op_truncates_details_and_noops_without_fields(db):
    op_id = dc.log_op("sdb", "FORMAT", "before")
    dc.update_op(op_id, details="y" * 6000)
    assert len(dc.get_task_record(op_id)["details"]) == 5000
    dc.update_op(op_id)  # nothing to change: must not raise or alter the row
    row = dc.get_task_record(op_id)
    assert row["status"] == "RUNNING"
    assert len(row["details"]) == 5000


def test_list_task_history_newest_first_with_clamped_limit(db):
    ids = [dc.log_op("sdb", f"OP{i}") for i in range(3)]
    history = dc.list_task_history()
    assert [row["id"] for row in history] == sorted(ids, reverse=True)
    assert [row["id"] for row in dc.list_task_history(limit=2)] == sorted(ids, reverse=True)[:2]
    assert len(dc.list_task_history(limit=0)) == 1  # clamped to at least 1


def test_get_task_record_and_status_for_unknown_id(db):
    assert dc.get_task_record(999999) is None
    assert dc.get_task_status(999999) == (None, None, None, None, None, None)
    assert dc.get_task_action(999999) is None


def test_get_task_status_and_action(db):
    op_id = dc.log_op("sdb", "SMART_LONG")
    dc.update_op(op_id, progress=30)
    status, progress, details, started, finished, note = dc.get_task_status(op_id)
    assert (status, progress) == ("RUNNING", 30)
    assert details == "Task queued on the FleetPilot server."
    assert started is not None and finished is None
    assert "closing the browser" in note
    assert dc.get_task_action(op_id) == "SMART_LONG"


def test_recover_interrupted_tasks(db):
    running = dc.log_op("sdb", "FORMAT", "started")
    done = dc.log_op("sdb", "SMART_SHORT")
    dc.update_op(done, status="OK")
    dc.recover_interrupted_tasks()
    row = dc.get_task_record(running)
    assert row["status"] == "INTERRUPTED"
    assert row["finished_ts"] is not None
    assert "Interrupted because FleetPilot restarted." in row["details"]
    assert dc.get_task_record(done)["status"] == "OK"


# ── protected_system_disks / validate_format_target ─────────────────────────

def _fake_mounts(monkeypatch, sources, parents):
    def fake_output(cmd):
        if cmd[0] == "findmnt":
            result = sources[cmd[-1]]
            if isinstance(result, Exception):
                raise result
            return result
        if cmd[0] == "lsblk":
            return parents[cmd[-1]]
        raise AssertionError(f"unexpected command: {cmd}")
    monkeypatch.setattr(dc, "_command_output", fake_output)


def test_protected_system_disks_resolves_partition_parents(monkeypatch):
    _fake_mounts(
        monkeypatch,
        sources={"/": "/dev/sda2", "/boot": "/dev/nvme0n1p1",
                 "/boot/firmware": RuntimeError("no such mount")},
        parents={"/dev/sda2": "sda", "/dev/nvme0n1p1": "nvme0n1"},
    )
    assert dc.protected_system_disks() == {"sda", "nvme0n1"}


def test_protected_system_disks_skips_non_device_sources(monkeypatch):
    _fake_mounts(
        monkeypatch,
        sources={"/": "tmpfs", "/boot": "/dev/sdb1", "/boot/firmware": "overlay"},
        parents={"/dev/sdb1": ""},  # no parent: the device itself is protected
    )
    assert dc.protected_system_disks() == {"sdb1"}


def test_protected_system_disks_swallows_command_failures(monkeypatch):
    _fake_mounts(monkeypatch,
                 sources={m: RuntimeError("findmnt failed")
                          for m in ("/", "/boot", "/boot/firmware")},
                 parents={})
    assert dc.protected_system_disks() == set()


def test_validate_format_target_refuses_protected_disk(present, monkeypatch):
    monkeypatch.setattr(dc, "protected_system_disks", lambda: {"sda"})
    _type_map(monkeypatch, {"sda": "disk"})
    with pytest.raises(ValueError, match="protected"):
        dc.validate_format_target("sda")


def test_validate_format_target_refuses_partitions(present, monkeypatch):
    monkeypatch.setattr(dc, "protected_system_disks", lambda: set())
    _type_map(monkeypatch, {"sdb": "part"})
    with pytest.raises(ValueError, match="not a whole physical disk"):
        dc.validate_format_target("sdb")


def test_validate_format_target_accepts_plain_disk(present, monkeypatch):
    monkeypatch.setattr(dc, "protected_system_disks", lambda: set())
    _type_map(monkeypatch, {"sdb": "disk"})
    assert dc.validate_format_target("sdb") == "sdb"


# ── start_format / format_worker / start_smart ──────────────────────────────

class _FakeThread:
    instances = []

    def __init__(self, target=None, args=(), daemon=None, name=None):
        self.target, self.args, self.name = target, args, name
        self.started = False
        _FakeThread.instances.append(self)

    def start(self):
        self.started = True


def _stub_format_path(monkeypatch):
    """Make validate_format_target pass for sdb without touching hardware."""
    monkeypatch.setattr(dc, "_present_block_devices", lambda: ["sdb"])
    monkeypatch.setattr(dc, "protected_system_disks", lambda: set())
    _type_map(monkeypatch, {"sdb": "disk"})


def test_start_format_queues_one_task_per_filesystem(db, monkeypatch):
    _stub_format_path(monkeypatch)
    _FakeThread.instances = []
    monkeypatch.setattr(dc, "threading", SimpleNamespace(Thread=_FakeThread))
    for fs in sorted(dc.FORMAT_FILESYSTEMS):
        op_id = dc.start_format("sdb", fs, "quick")
        row = dc.get_task_record(op_id)
        assert row["action"] == f"QUICK_WIPE_FORMAT_{fs.upper()}"
        assert row["status"] == "RUNNING"
        thread = _FakeThread.instances[-1]
        assert thread.target is dc.format_worker
        assert thread.args == ("sdb", fs, "quick", op_id)
        assert thread.started
    assert len(dc.list_task_history()) == len(dc.FORMAT_FILESYSTEMS)


def test_start_format_rejects_bad_filesystem_and_wipe_mode(db, monkeypatch):
    _stub_format_path(monkeypatch)
    with pytest.raises(ValueError, match="Unsupported filesystem"):
        dc.start_format("sdb", "ntfs", "quick")
    with pytest.raises(ValueError, match="Unsupported wipe mode"):
        dc.start_format("sdb", "ext4", "slow")
    assert dc.list_task_history() == []  # nothing was queued


def _stub_helper(monkeypatch, result):
    """Replace the privileged helper and subprocess for format_worker."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return result

    monkeypatch.setattr(dc, "privileged",
                        SimpleNamespace(command=lambda *a: ["fake-disk-action", *a]))
    monkeypatch.setattr(dc, "subprocess", SimpleNamespace(
        run=fake_run, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
    return calls


def test_format_worker_success_marks_op_ok(db, monkeypatch):
    _stub_format_path(monkeypatch)
    calls = _stub_helper(monkeypatch, SimpleNamespace(returncode=0, stdout="helper ok"))
    op_id = dc.log_op("sdb", "QUICK_WIPE_FORMAT_EXT4")
    dc.format_worker("sdb", "ext4", "quick", op_id)
    row = dc.get_task_record(op_id)
    assert (row["status"], row["progress"], row["details"]) == ("OK", 100, "helper ok")
    assert calls == [["fake-disk-action", "disk-action", "quick", "ext4", "sdb"]]


def test_format_worker_helper_failure_marks_op_fail(db, monkeypatch):
    _stub_format_path(monkeypatch)
    _stub_helper(monkeypatch, SimpleNamespace(returncode=1, stdout="boom"))
    op_id = dc.log_op("sdb", "QUICK_WIPE_FORMAT_XFS")
    dc.format_worker("sdb", "xfs", "quick", op_id)
    row = dc.get_task_record(op_id)
    assert (row["status"], row["progress"], row["details"]) == ("FAIL", 0, "boom")


def test_format_worker_rejects_bad_filesystem_before_running(db, monkeypatch):
    _stub_format_path(monkeypatch)
    calls = _stub_helper(monkeypatch, SimpleNamespace(returncode=0, stdout=""))
    op_id = dc.log_op("sdb", "FORMAT")
    dc.format_worker("sdb", "ntfs", "quick", op_id)
    row = dc.get_task_record(op_id)
    assert row["status"] == "FAIL"
    assert "Unsupported filesystem type" in row["details"]
    assert calls == []  # the helper never ran


def test_start_smart_runs_smartctl_and_logs(db, present, monkeypatch):
    commands = []
    monkeypatch.setattr(dc, "run", lambda cmd: commands.append(cmd) or "")
    dc.start_smart("sdb", "short")
    assert commands == [["smartctl", "-t", "short", "/dev/sdb"]]
    history = dc.list_task_history()
    assert [row["action"] for row in history] == ["SMART_SHORT"]
    with pytest.raises(ValueError, match="Invalid SMART mode"):
        dc.start_smart("sdb", "medium")


# ── validate_blocks: parsing the helper output ──────────────────────────────

def _stub_validation(monkeypatch, stdout, returncode=0):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout)
    monkeypatch.setattr(dc, "privileged",
                        SimpleNamespace(command=lambda *a: ["fake-disk-action", *a]))
    monkeypatch.setattr(dc, "subprocess", SimpleNamespace(
        run=fake_run, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))


def test_validate_blocks_parses_summary_and_bad_samples(present, monkeypatch):
    _stub_validation(monkeypatch, (
        "reading samples…\n"
        "BAD_SAMPLE 3\n"
        "VALIDATION_SUMMARY samples=8 bytes=32768 bad=2 size=123456789\n"
        "BAD_SAMPLE 7\n"
    ))
    blocks, bad, summary = dc.validate_blocks("sdb")
    assert blocks == list(range(8))
    assert bad == [3, 7]
    assert summary == {
        "device_size_bytes": 123456789,
        "sample_count": 8,
        "sample_bytes": 32768,
        "bad_count": 2,
        "method": "Read-only 4 KiB samples evenly distributed across the device",
    }


def test_validate_blocks_with_no_bad_samples(present, monkeypatch):
    _stub_validation(monkeypatch,
                     "VALIDATION_SUMMARY samples=4 bytes=16384 bad=0 size=999\n")
    blocks, bad, summary = dc.validate_blocks("sdb")
    assert blocks == [0, 1, 2, 3]
    assert bad == []
    assert summary["bad_count"] == 0


def test_validate_blocks_rejects_inconsistent_counts(present, monkeypatch):
    _stub_validation(monkeypatch, (
        "BAD_SAMPLE 3\n"
        "VALIDATION_SUMMARY samples=8 bytes=32768 bad=2 size=123456789\n"
    ))
    with pytest.raises(RuntimeError, match="inconsistent"):
        dc.validate_blocks("sdb")


def test_validate_blocks_rejects_missing_summary(present, monkeypatch):
    _stub_validation(monkeypatch, "BAD_SAMPLE 3\nall done\n")
    with pytest.raises(RuntimeError, match="no summary"):
        dc.validate_blocks("sdb")


def test_validate_blocks_helper_failure_raises_output(present, monkeypatch):
    _stub_validation(monkeypatch, "helper died", returncode=3)
    with pytest.raises(RuntimeError, match="helper died"):
        dc.validate_blocks("sdb")


# ── auto mode: sync_disks decisions with fake device lists ──────────────────

FAKE_DISKS = [
    {"name": "mmcblk0", "model": "Builtin", "size": "32G"},
    {"name": "nvme0n1", "model": "System NVMe", "size": "512G"},
    {"name": "sdb", "model": "USB SSD", "size": "1T"},
    {"name": "sdc", "model": "USB HDD", "size": "2T"},
]


def _stub_disk_scan(monkeypatch):
    monkeypatch.setattr(dc, "ls_disks", lambda: [dict(d) for d in FAKE_DISKS])
    monkeypatch.setattr(dc, "get_serial", lambda dev: f"SER-{dev}")


def test_sync_disks_records_all_devices_without_auto_work(db, monkeypatch):
    _stub_disk_scan(monkeypatch)
    monkeypatch.setattr(dc, "auto_enabled", False)
    started = []
    monkeypatch.setattr(dc, "start_format", lambda *a: started.append(("format", a)))
    monkeypatch.setattr(dc, "start_smart", lambda *a: started.append(("smart", a)))
    dc.sync_disks()
    assert started == []  # auto mode off: inventory only
    names = {d["device"] for d in dc.get_disk_list()}
    assert names == {"mmcblk0", "nvme0n1", "sdb", "sdc"}


def test_sync_disks_auto_mode_skips_system_and_nvme(db, monkeypatch):
    _stub_disk_scan(monkeypatch)
    monkeypatch.setattr(dc, "auto_enabled", True)
    formatted, smarted = [], []
    monkeypatch.setattr(dc, "start_format", lambda dev, fs, mode: formatted.append((dev, fs, mode)))
    monkeypatch.setattr(dc, "start_smart", lambda dev, mode: smarted.append((dev, mode)))
    dc.sync_disks()
    # mmcblk0 is AUTO_SKIP_DEVICE and nvme* is skipped as a system drive;
    # only the two new plain disks get auto work, in scan order.
    assert formatted == [("sdb", "ext4", "quick"), ("sdc", "ext4", "quick")]
    assert smarted == [("sdb", "short"), ("sdc", "short")]


def test_sync_disks_auto_mode_logs_skips_when_a_start_fails(db, monkeypatch):
    _stub_disk_scan(monkeypatch)
    monkeypatch.setattr(dc, "auto_enabled", True)

    def flaky_format(dev, fs, mode):
        if dev == "sdc":
            raise ValueError("protected")

    monkeypatch.setattr(dc, "start_format", flaky_format)
    monkeypatch.setattr(dc, "start_smart", lambda dev, mode: None)
    dc.sync_disks()
    skipped = [row for row in dc.list_task_history() if row["action"] == "AUTO_MODE_SKIPPED"]
    assert [row["device"] for row in skipped] == ["sdc"]
    assert "did not process /dev/sdc" in skipped[0]["details"]


def test_set_auto_mode_takes_a_baseline_before_enabling(db, monkeypatch):
    seen = []
    monkeypatch.setattr(dc, "sync_disks", lambda: seen.append(dc.auto_enabled))
    monkeypatch.setattr(dc, "auto_enabled", False)
    assert dc.set_auto_mode(True) is True
    assert seen == [False]  # baseline ran while auto mode was still off
    assert dc.set_auto_mode(True) is True
    assert seen == [False]  # already on: no second baseline
    assert dc.set_auto_mode(False) is False
    assert dc.auto_enabled is False
