"""Build the live demo: FleetPilot running in the browser (Pyodide) against an emulated homelab.

    python demo/build_live.py [OUT]       # default OUT: demo/site/demo

Writes the demo page (demo/live/*), FleetPilot's source and the lab as one zip, and
the pure-Python dependencies as wheels, downloaded with the hashes pinned in
requirements-lock.txt. Compiled packages (cryptography, bcrypt, ...) come from Pyodide.
The lab's vulnerability data is a fresh snapshot of OSV.dev for its package versions.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, "demo", "live")
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(REPO, "demo", "site", "demo")

# Pure-Python packages from requirements-lock.txt that FleetPilot imports in the demo.
# Left out: compiled ones Pyodide provides, server-only ones (gunicorn), and optional
# extras FleetPilot runs without (flask-compress, webauthn, psutil: the lab emulates it).
WHEELS = ["apscheduler", "blinker", "certifi", "charset-normalizer", "click", "flask", "flask-wtf", "idna",
          "invoke", "itsdangerous", "jinja2", "paramiko", "pyotp", "python-dotenv", "requests", "typing-extensions",
          "tzlocal", "urllib3", "werkzeug", "wtforms", "yubico-client"]
APP_DIRS = ["templates", "static", "addons", "hw_monitor", "integrations"]


def locked_requirements():
    """The lock file's entries (with hashes) for the packages in WHEELS."""
    text = open(os.path.join(REPO, "requirements-lock.txt"), encoding="utf-8").read()
    blocks = re.split(r"\n(?=[a-z0-9][a-z0-9_.-]*==)", text)
    wanted = []
    for block in blocks:
        name = block.split("==", 1)[0].strip().lower()
        if name in WHEELS:
            wanted.append("\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#")))
    missing = set(WHEELS) - {b.split("==", 1)[0].strip().lower() for b in wanted}
    if missing:
        sys.exit(f"Not in requirements-lock.txt: {', '.join(sorted(missing))}")
    return "\n".join(wanted) + "\n"


def download_wheels(dest):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as req:
        req.write(locked_requirements())
    try:
        subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--only-binary=:all:",
                        "--platform", "any", "--python-version", "3.13", "--implementation", "py",
                        "--require-hashes", "-r", req.name, "-d", dest], check=True)
    finally:
        os.unlink(req.name)
    return sorted(f for f in os.listdir(dest) if f.endswith(".whl"))


def app_zip():
    """FleetPilot's runtime files plus demo/live/lab, as a zip for Pyodide."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(REPO)):
            if name.endswith(".py") and not name.startswith(("test_", "conftest")):
                zf.write(os.path.join(REPO, name), name)
        for top in APP_DIRS + [os.path.join("demo", "live", "lab")]:
            for root, dirs, files in os.walk(os.path.join(REPO, top)):
                dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "host_images"))
                for f in sorted(files):
                    if not f.endswith((".pyc", ".db")):
                        path = os.path.join(root, f)
                        zf.write(path, os.path.relpath(path, REPO))
    return buf.getvalue()


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "lab", "wheels"))
    for name in ("index.html", "shell.js", "shell.css", "sw.js", "worker.js"):
        shutil.copy(os.path.join(LIVE, name), OUT)
    assets = os.path.join(OUT, "assets")
    shutil.copytree(os.path.join(REPO, "static", "vendor", "bootstrap-icons"), os.path.join(assets, "bootstrap-icons"))
    shutil.copy(os.path.join(REPO, "static", "fleetpilot-logo.svg"), assets)
    shutil.copy(os.path.join(REPO, "docs", "screenshots", "home.png"), os.path.join(assets, "social-preview.png"))

    snapshot = os.path.join(LIVE, "lab", "osv-snapshot.json")
    try:                         # real OSV.dev records for the lab's package versions (see lab/osv.py)
        sys.path.insert(0, LIVE)
        from lab import osv
        print("OSV snapshot: %d package versions with vulnerabilities, %d records" % osv.build_snapshot(snapshot))
    except Exception as exc:
        print(f"OSV snapshot not refreshed ({exc}); the demo's vulnerability scan "
              + ("uses the existing one." if os.path.exists(snapshot) else "finds nothing."))
    data = app_zip()
    zip_name = f"fleetpilot-{hashlib.sha256(data).hexdigest()[:12]}.zip"
    with open(os.path.join(OUT, "lab", zip_name), "wb") as fh:
        fh.write(data)
    wheels = download_wheels(os.path.join(OUT, "lab", "wheels"))
    with open(os.path.join(OUT, "lab", "manifest.json"), "w") as fh:
        json.dump({"app": zip_name, "wheels": wheels}, fh, indent=1)
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    print(f"live demo: {OUT} ({len(data) // 1024} KB app, {len(wheels)} wheels)")


if __name__ == "__main__":
    main()
