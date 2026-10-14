# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The live demo's emulated homelab still works with the current FleetPilot.

The lab replaces threads, sockets and SSH process-wide, so it runs in a separate
Python process. It boots FleetPilot exactly as the browser demo does (demo/live/lab),
then renders the main pages and runs the things the demo suggests to try.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))

SCRIPT = r'''
import html, json, re, sys, urllib.parse
sys.path.insert(0, "demo/live")
from lab import boot, net
P = "/FleetPilot/app/test"
boot.start("https://demo.example", P)
out = {}

def call(method, path, form=None, accept="text/html"):
    path, _, query = path.partition("?")
    headers = {"Accept": accept, "Referer": "https://demo.example" + P + "/hosts"}
    body = b""
    if form is not None:
        page = boot.handle("GET", P + "/hosts", "", {"Accept": "text/html"}, b"")[2].decode()
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        body = urllib.parse.urlencode(dict(form, csrf_token=token)).encode()
        headers.update({"Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": token})
    status, hdrs, data = boot.handle(method, P + path, query, headers, body)
    boot.after_request()
    text = data.decode(errors="replace")
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", "", text))))
    return status, dict(hdrs), text, plain

pages = {}
for path in ["/index", "/hosts", "/routers", "/routers/1", "/smart", "/vm/1", "/storage/1", "/backup/1", "/fans/1",
             "/hw", "/hw_overview", "/scanner", "/monitor", "/system/proxy", "/system/security", "/vulnerabilities"]:
    status, _, text, plain = call("GET", path)
    pages[path] = [status, plain]
out["status"] = {p: v[0] for p, v in pages.items()}
out["vm"] = all(w in pages["/vm/1"][1] for w in ("docker-01", "jellyfin", "k3s-node"))
out["router"] = all(w in pages["/routers/1"][1] for w in ("phone-anna", "203.0.113.47"))
out["storage"] = "tank" in pages["/storage/1"][1]
out["unprefixed"] = sorted(set(re.findall(r'(?:href|src|action)="(/(?!FleetPilot/)[a-z][^"]*)"',
                                          call("GET", "/hosts")[2])))[:5]

call("POST", "/update/docker-01", {})
out["update"] = "Update completed successfully for docker-01" in call("GET", "/progress/docker-01")[3]
out["wol"] = (call("POST", "/hosts/lab-01/wol", {}, "application/json")[0], net.lab.find("lab-01").state)
status, _, text, _ = call("POST", "/vm/1/action", {"node": "pve-02", "vmid": "108", "action": "start",
                                                   "rtype": "qemu"}, "application/json")
out["vm_start"] = json.loads(text).get("ok")
boot.act("nas", "disk")
boot.tick()
out["outbox"] = [m["subject"] for m in net.lab.outbox]
call("POST", "/fans/1/set_fan", {"channel": "pwm1", "mode": "fixed", "speed": "20"}, "application/json")
out["pwm"] = net.lab.find("pve-01").pwm["pwm1"]
import vuln_scanner
out["vuln_targets"] = {t["name"]: t["status"] for t in vuln_scanner.get_targets()}
print("RESULT " + json.dumps(out))
'''


def _run_lab():
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=REPO, capture_output=True, text=True, timeout=300)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, proc.stdout[-3000:] + proc.stderr[-3000:]
    return json.loads(lines[-1][len("RESULT "):])


def test_demo_lab_runs_fleetpilot_against_emulated_devices():
    out = _run_lab()
    assert all(status == 200 for status in out["status"].values()), out["status"]
    assert out["vm"] and out["router"] and out["storage"]
    assert out["unprefixed"] == [], "links the demo's path rewriting missed: %s" % out["unprefixed"]
    assert out["update"]
    assert out["wol"] == [200, "booting"]
    assert out["vm_start"] is True
    assert any("nas:sda" in subject for subject in out["outbox"]), out["outbox"]
    assert out["pwm"] == 51
    targets = out["vuln_targets"]
    assert targets["docker-01"] == "ok" and targets["reverse-proxy on docker-01"] == "ok"
    assert targets["win-desk"] == "unsupported" and targets["OPNsense"] == "ok"
