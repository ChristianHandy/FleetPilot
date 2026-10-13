# FleetPilot demo

Published at **https://christianhandy.github.io/FleetPilot/** by `.github/workflows/pages.yml` on every push to `main`.

| Path | What it is | Built by |
|------|------------|----------|
| `/` | **Live demo**: the real FleetPilot, running in the visitor's browser against an emulated homelab | `demo/build_live.py` |
| `/tour/` | Static tour: pre-rendered pages, buttons do nothing (for old browsers and slow connections) | `demo/build_site.py` |

## How the live demo works

```
index.html + shell.js ──► worker.js: Pyodide (Python in WebAssembly)
        ▲                      └─ FleetPilot (app.py, unchanged) + demo/live/lab
        │ postMessage
sw.js (service worker): every request below app/<lab-id>/ goes to the page above, not to a server
```

- **FleetPilot itself is unchanged.** `demo/live/lab/runtime.py` replaces what a browser does not have before FleetPilot is imported:
  - **Threads.** Background work runs right after the request; the polling loops become one round per lab tick.
  - **Sockets, HTTP** (`urllib` and `requests`), **SSH** (`ssh_helper.create_client`), **subprocess**, **SMTP** and **psutil**.
- **The emulated homelab:**
  - **`demo/live/lab/machines.py`** holds Linux and Windows machines with disks, packages, sensors and PWM fans. They answer the shell commands FleetPilot sends (`apt-get`, `smartctl`, `lsblk`, `sensors -j`, the hardware collector scripts, `shutdown`, ...) in the real tools' output format.
  - **`demo/live/lab/services.py`** holds the HTTP APIs: Proxmox VE, Proxmox Backup Server, TrueNAS, FRITZ! TR-064 (SOAP) and OPNsense, plus OpenWrt over SSH.
  - **`demo/live/lab/inventory.py`** lists the devices; every address is from RFC 5737.
- **`demo/live/lab/seed.py`** configures FleetPilot the way a user would: hosts, routers, Proxmox, TrueNAS, the backup server, fans, ntfy and e-mail.
  - Everything shown afterwards is read from the emulated devices by FleetPilot's own code.
  - E-mails and ntfy messages land in the lab's **Outbox**, and Wake-on-LAN magic packets wake the machine with that MAC.
- **`demo/live/lab/osv.py`** handles the vulnerability scan. At build time it asks the real OSV.dev about exactly the package versions in the lab and ships those records, and the lab answers FleetPilot's OSV requests from them. The CVEs shown are therefore real, with no request leaving the browser.
- **The "Virtual lab" panel** lets visitors switch devices off, let a disk fail, publish updates or put a CPU under load, then watch FleetPilot react.
- **Dependencies:** pure-Python packages are downloaded with the hashes from `requirements-lock.txt`. Compiled ones (cryptography, bcrypt, ...) come from the Pyodide distribution (jsDelivr, pinned version).

`test_demo_lab.py` boots the lab in CPython and runs the suggested actions, so a change to FleetPilot that breaks the demo fails the tests.

## Run it locally

```bash
python demo/build_live.py && python demo/build_site.py
mkdir -p /tmp/fp-demo && ln -sfn "$PWD/demo/site" /tmp/fp-demo/FleetPilot
python -m http.server 8000 --directory /tmp/fp-demo     # open http://localhost:8000/FleetPilot/
```

Service workers need `localhost` or HTTPS.
