#!/usr/bin/env python3
"""
Hardware Monitor & Stress Test Dashboard v2
============================================
- Live-Monitoring: CPU, RAM, Netzwerk, Disk I/O, Temperaturen, Lüfter
- Fan-Control: Lüftergeschwindigkeit per PWM/sysfs steuern
- Stress-Test: Start/Stop/Log für alle Server
- Cluster: Läuft redundant auf pve03 (LXC 200) und pve02 (LXC 201)
"""

from flask import Flask, render_template, jsonify, request, redirect, url_for
import paramiko, threading, time, json, os, re, sqlite3, datetime

app = Flask(__name__)
DB_PATH = "/data/dashboard.db"
POLL_INTERVAL = 8
HIST_INTERVAL = 30

# ─── SSH-Helper ───────────────────────────────────────────────────────────────

def ssh_run(ip, port, user, pw, cmd, timeout=12):
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, port=port, username=user, password=pw,
                  timeout=8, allow_agent=False, look_for_keys=False)
        _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        c.close()
        return True, out
    except Exception as e:
        return False, str(e)

def ssh_run_script(ip, port, user, pw, script_content, timeout=15):
    """Überträgt Skript als Datei und führt es aus — vermeidet Quoting-Probleme."""
    remote_path = f"/tmp/_hw_script_{abs(hash(script_content[:50]))}.py"
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, port=port, username=user, password=pw,
                  timeout=8, allow_agent=False, look_for_keys=False)
        # Datei via SFTP übertragen
        sftp = c.open_sftp()
        with sftp.open(remote_path, 'w') as f:
            f.write(script_content)
        sftp.close()
        # Ausführen
        _, stdout, stderr = c.exec_command(
            f"python3 {remote_path}; rm -f {remote_path}", timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        c.close()
        return True, out
    except Exception as e:
        return False, str(e)

# ─── Datenbank ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs("/data", exist_ok=True)
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, ip TEXT NOT NULL,
        ssh_port INTEGER DEFAULT 22, ssh_user TEXT DEFAULT 'root', ssh_pass TEXT,
        stress_log TEXT DEFAULT '/root/hw_stress_test/stress_test.log',
        stress_script TEXT DEFAULT '/root/hw_stress_test.py',
        enabled INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS live_metrics (
        server_id INTEGER PRIMARY KEY,
        ts TEXT, reachable INTEGER DEFAULT 0,
        cpu_pct REAL, cpu_temp REAL, cpu_cores INTEGER,
        ram_used_mb INTEGER, ram_total_mb INTEGER,
        swap_used_mb INTEGER, swap_total_mb INTEGER,
        net_rx_kbps REAL, net_tx_kbps REAL, net_iface TEXT,
        disk_read_kbps REAL, disk_write_kbps REAL,
        fans TEXT,
        gpu_temp REAL, gpu_on_bus INTEGER,
        stress_running INTEGER DEFAULT 0,
        stress_phase TEXT, stress_failure TEXT,
        stress_log_tail TEXT,
        uptime_s INTEGER
    );
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER, ts TEXT,
        cpu_pct REAL, cpu_temp REAL,
        ram_used_mb INTEGER, ram_total_mb INTEGER,
        net_rx_kbps REAL, net_tx_kbps REAL,
        disk_read_kbps REAL, disk_write_kbps REAL,
        gpu_temp REAL
    );
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER, ts TEXT, type TEXT,
        message TEXT, acknowledged INTEGER DEFAULT 0,
        ack_ts TEXT, ack_note TEXT
    );
    CREATE TABLE IF NOT EXISTS fan_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER, name TEXT,
        hwmon_path TEXT, pwm_channel INTEGER DEFAULT 1,
        mode TEXT DEFAULT 'manual',
        target_pct INTEGER DEFAULT 50,
        temp_source TEXT,
        curve TEXT DEFAULT '[[40,30],[60,60],[80,90],[90,100]]',
        enabled INTEGER DEFAULT 1
    );
    """)
    cur = conn.execute("SELECT COUNT(*) FROM servers")
    if cur.fetchone()[0] == 0:
        for name, ip in [("pve01","192.168.1.90"),("pve02","192.168.1.56"),
                          ("pve03","192.168.1.52"),("pve04","192.168.1.195")]:
            conn.execute("INSERT INTO servers (name,ip,ssh_pass) VALUES (?,?,?)",
                         (name, ip, "lk36po45&%"))
    # DB-Migration: fehlende Spalten ergänzen
    try:
        conn.execute("ALTER TABLE servers ADD COLUMN stress_log TEXT DEFAULT '/root/hw_stress_test/stress_test.log'")
    except: pass
    try:
        conn.execute("ALTER TABLE servers ADD COLUMN stress_script TEXT DEFAULT '/root/hw_stress_test.py'")
    except: pass
    # Fehlende Werte befüllen
    conn.execute("UPDATE servers SET stress_log='/root/hw_stress_test/stress_test.log' WHERE stress_log IS NULL")
    conn.execute("UPDATE servers SET stress_script='/root/hw_stress_test.py' WHERE stress_script IS NULL")
    # last_seen Spalte
    try: conn.execute("ALTER TABLE live_metrics ADD COLUMN last_seen_ts TEXT")
    except: pass
    try: conn.execute("ALTER TABLE live_metrics ADD COLUMN last_cpu_temp REAL")
    except: pass
    try: conn.execute("ALTER TABLE live_metrics ADD COLUMN last_gpu_temp REAL")
    except: pass
    try: conn.execute("ALTER TABLE live_metrics ADD COLUMN last_log TEXT")
    except: pass
    conn.commit(); conn.close()

# ─── Metriken-Sammlung ────────────────────────────────────────────────────────

_net_prev = {}
_disk_prev = {}

COLLECT_SCRIPT = """\
import json, os, time, re, subprocess, glob

d = {}

# CPU %
try:
    with open('/proc/stat') as f: line = f.readline()
    parts = list(map(int, line.split()[1:]))
    idle = parts[3]; total = sum(parts)
    time.sleep(0.3)
    with open('/proc/stat') as f: line = f.readline()
    parts2 = list(map(int, line.split()[1:]))
    idle2 = parts2[3]; total2 = sum(parts2)
    d['cpu_pct'] = round(100*(1-(idle2-idle)/(total2-total)),1)
except: d['cpu_pct'] = None

try: d['cpu_cores'] = os.cpu_count()
except: d['cpu_cores'] = None

# RAM
try:
    mi = {}
    for l in open('/proc/meminfo'):
        k,v = l.split(':')
        mi[k.strip()] = int(v.strip().split()[0])
    d['ram_total_mb'] = mi['MemTotal']//1024
    d['ram_used_mb'] = (mi['MemTotal']-mi['MemAvailable'])//1024
    d['swap_total_mb'] = mi.get('SwapTotal',0)//1024
    d['swap_used_mb'] = (mi.get('SwapTotal',0)-mi.get('SwapFree',0))//1024
except: pass

# Uptime
try: d['uptime_s'] = int(float(open('/proc/uptime').read().split()[0]))
except: d['uptime_s'] = None

# Netzwerk
try:
    for l in open('/proc/net/dev'):
        l = l.strip()
        if ':' in l and not l.startswith('lo'):
            iface = l.split(':')[0].strip()
            vals = l.split(':')[1].split()
            d['net_iface'] = iface
            d['net_rx_bytes'] = int(vals[0])
            d['net_tx_bytes'] = int(vals[8])
            break
except: pass

# Disk I/O
try:
    for l in open('/proc/diskstats'):
        p = l.split()
        if p[2] in ('sda','nvme0n1','vda','sdb'):
            d['disk_read_sectors'] = int(p[5])
            d['disk_write_sectors'] = int(p[9])
            d['disk_dev'] = p[2]
            break
except: pass

# Temperaturen
try:
    r = subprocess.run(['sensors','-j'], capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        sens = json.loads(r.stdout)
        temps = []
        fans = []
        for chip, data in sens.items():
            for feat, vals in data.items():
                if isinstance(vals, dict):
                    for k,v in vals.items():
                        if 'temp' in k.lower() and 'input' in k.lower() and isinstance(v,(int,float)):
                            temps.append(v)
                        if 'fan' in k.lower() and 'input' in k.lower() and isinstance(v,(int,float)):
                            fans.append({'chip':chip,'feature':feat,'rpm':int(v)})
        d['cpu_temp'] = max(temps) if temps else None
        d['fans'] = fans
    else:
        raise Exception('sensors -j failed')
except:
    try:
        r = subprocess.run(['sensors'], capture_output=True, text=True, timeout=5)
        temps = [float(m) for m in re.findall(r'[+]([0-9]+[.][0-9]+).C', r.stdout)]
        d['cpu_temp'] = max(temps) if temps else None
        fans_rpm = [int(m) for m in re.findall(r'([0-9]+) RPM', r.stdout)]
        d['fans'] = [{'chip':'sensors','feature':'fan'+str(i+1),'rpm':rpm} for i,rpm in enumerate(fans_rpm)]
    except: pass

# GPU nvidia
try:
    r = subprocess.run(['nvidia-smi','--query-gpu=temperature.gpu',
                        '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        d['gpu_temp'] = float(r.stdout.strip())
        d['gpu_on_bus'] = True
except: d['gpu_on_bus'] = True

# Stress-Test Log
try:
    log_path = '/root/hw_stress_test/stress_test.log'
    if os.path.exists(log_path):
        lines = open(log_path).readlines()[-40:]
        d['stress_log'] = ''.join(lines)
        d['stress_running'] = any('[MONITOR]' in l or '[TEST]' in l for l in lines[-5:])
        for l in reversed(lines):
            if '[TEST]' in l and 'START' in l:
                m = re.search(r'=== (.+?) START ===', l)
                if m: d['stress_phase'] = m.group(1); break
        for l in reversed(lines):
            if '[CRITICAL]' in l:
                d['stress_failure'] = l.split('[CRITICAL]')[-1].strip(); break
except: pass

d['ts'] = time.time()
print(json.dumps(d))
"""

FAN_DETECT_SCRIPT = """\
import glob, os, json, re

fans = []
for hwmon in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
    name_f = hwmon+'/name'
    name = open(name_f).read().strip() if os.path.exists(name_f) else os.path.basename(hwmon)
    for pwm in sorted(glob.glob(hwmon+'/pwm[0-9]')):
        ch = int(pwm[-1])
        en = hwmon+'/pwm'+str(ch)+'_enable'
        max_f = hwmon+'/pwm'+str(ch)+'_max'
        try:
            fans.append({
                'hwmon': hwmon,
                'name': name,
                'channel': ch,
                'path': pwm,
                'enable_path': en,
                'current': int(open(pwm).read().strip()) if os.path.exists(pwm) else None,
                'max': int(open(max_f).read().strip()) if os.path.exists(max_f) else 255,
                'enable': int(open(en).read().strip()) if os.path.exists(en) else None,
            })
        except: pass
    for fan_in in sorted(glob.glob(hwmon+'/fan*_input')):
        m = re.search(r'fan(\\d+)', fan_in)
        ch = int(m.group(1)) if m else 0
        try:
            rpm = int(open(fan_in).read().strip())
            fans.append({'hwmon': hwmon, 'name': name, 'type': 'rpm', 'channel': ch, 'rpm': rpm, 'path': fan_in})
        except: pass

print(json.dumps(fans))
"""

def collect_metrics(server):
    sid = server["id"]
    ip = server["ip"]; port = server["ssh_port"]
    user = server["ssh_user"]; pw = server["ssh_pass"]

    ok, raw = ssh_run_script(ip, port, user, pw, COLLECT_SCRIPT, timeout=15)
    now = datetime.datetime.now().isoformat()

    conn = get_db()
    if not ok:
        conn.execute("INSERT OR REPLACE INTO live_metrics (server_id,ts,reachable) VALUES (?,?,0)",
                     (sid, now))
        conn.commit(); conn.close(); return

    try:
        data = json.loads(raw)
    except Exception:
        conn.execute("INSERT OR REPLACE INTO live_metrics (server_id,ts,reachable) VALUES (?,?,0)",
                     (sid, now))
        conn.commit(); conn.close(); return

    # Netzwerk-Delta
    net_rx_kbps = net_tx_kbps = None
    if "net_rx_bytes" in data:
        prev = _net_prev.get(sid)
        ts_now = data.get("ts", time.time())
        if prev:
            dt = ts_now - prev[0]
            if dt > 0:
                net_rx_kbps = round((data["net_rx_bytes"] - prev[1]) / dt / 1024, 1)
                net_tx_kbps = round((data["net_tx_bytes"] - prev[2]) / dt / 1024, 1)
        _net_prev[sid] = (ts_now, data["net_rx_bytes"], data["net_tx_bytes"])

    # Disk-Delta
    disk_r_kbps = disk_w_kbps = None
    if "disk_read_sectors" in data:
        prev = _disk_prev.get(sid)
        ts_now = data.get("ts", time.time())
        if prev:
            dt = ts_now - prev[0]
            if dt > 0:
                disk_r_kbps = round((data["disk_read_sectors"] - prev[1]) * 512 / dt / 1024, 1)
                disk_w_kbps = round((data["disk_write_sectors"] - prev[2]) * 512 / dt / 1024, 1)
        _disk_prev[sid] = (ts_now, data["disk_read_sectors"], data["disk_write_sectors"])

    fans_json = json.dumps(data.get("fans", []))
    stress_log = data.get("stress_log", "")[-3000:]

    # Letzte bekannte Werte vor Offline merken
    prev = conn.execute("SELECT cpu_temp,gpu_temp,stress_log_tail,ts FROM live_metrics WHERE server_id=?", (sid,)).fetchone()
    if prev and prev['cpu_temp']:
        conn.execute("UPDATE live_metrics SET last_cpu_temp=?,last_gpu_temp=?,last_log=?,last_seen_ts=? WHERE server_id=?",
            (prev['cpu_temp'], prev['gpu_temp'], prev['stress_log_tail'], prev['ts'], sid))

    conn.execute("""INSERT OR REPLACE INTO live_metrics
        (server_id,ts,reachable,cpu_pct,cpu_temp,cpu_cores,
         ram_used_mb,ram_total_mb,swap_used_mb,swap_total_mb,
         net_rx_kbps,net_tx_kbps,net_iface,
         disk_read_kbps,disk_write_kbps,fans,
         gpu_temp,gpu_on_bus,stress_running,stress_phase,stress_failure,
         stress_log_tail,uptime_s)
        VALUES (?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, now,
         data.get("cpu_pct"), data.get("cpu_temp"), data.get("cpu_cores"),
         data.get("ram_used_mb"), data.get("ram_total_mb"),
         data.get("swap_used_mb"), data.get("swap_total_mb"),
         net_rx_kbps, net_tx_kbps, data.get("net_iface"),
         disk_r_kbps, disk_w_kbps, fans_json,
         data.get("gpu_temp"), 1 if data.get("gpu_on_bus", True) else 0,
         1 if data.get("stress_running") else 0,
         data.get("stress_phase"), data.get("stress_failure"),
         stress_log, data.get("uptime_s")))
    conn.commit()

    last_hist = getattr(collect_metrics, f"_last_hist_{sid}", 0)
    if time.time() - last_hist >= HIST_INTERVAL:
        conn.execute("""INSERT INTO history
            (server_id,ts,cpu_pct,cpu_temp,ram_used_mb,ram_total_mb,
             net_rx_kbps,net_tx_kbps,disk_read_kbps,disk_write_kbps,gpu_temp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, now, data.get("cpu_pct"), data.get("cpu_temp"),
             data.get("ram_used_mb"), data.get("ram_total_mb"),
             net_rx_kbps, net_tx_kbps, disk_r_kbps, disk_w_kbps,
             data.get("gpu_temp")))
        conn.execute("DELETE FROM history WHERE server_id=? AND id NOT IN "
                     "(SELECT id FROM history WHERE server_id=? ORDER BY id DESC LIMIT 2880)",
                     (sid, sid))
        conn.commit()
        setattr(collect_metrics, f"_last_hist_{sid}", time.time())
    conn.close()

def polling_loop():
    while True:
        try:
            conn = get_db()
            servers = [dict(r) for r in conn.execute(
                "SELECT * FROM servers WHERE enabled=1").fetchall()]
            conn.close()
            threads = [threading.Thread(target=collect_metrics, args=(s,), daemon=True)
                       for s in servers]
            for t in threads: t.start()
            for t in threads: t.join(timeout=18)
        except Exception as e:
            print(f"Poll-Fehler: {e}")
        time.sleep(POLL_INTERVAL)

# ─── Fan-Control ──────────────────────────────────────────────────────────────

def set_fan_pwm(ip, port, user, pw, pwm_path, value_pct):
    pwm_val = int(value_pct / 100 * 255)
    enable_path = pwm_path + "_enable"
    cmd = (f"echo 1 > {enable_path} 2>/dev/null || true; "
           f"echo {pwm_val} > {pwm_path} && cat {pwm_path}")
    ok, out = ssh_run(ip, port, user, pw, cmd)
    return ok, out

# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/live")
def api_live():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.id,s.name,s.ip,
               m.ts,m.reachable,m.cpu_pct,m.cpu_temp,m.cpu_cores,
               m.ram_used_mb,m.ram_total_mb,m.swap_used_mb,m.swap_total_mb,
               m.net_rx_kbps,m.net_tx_kbps,m.net_iface,
               m.disk_read_kbps,m.disk_write_kbps,
               m.fans,m.gpu_temp,m.gpu_on_bus,
               m.stress_running,m.stress_phase,m.stress_failure,m.uptime_s
        FROM servers s LEFT JOIN live_metrics m ON s.id=m.server_id
        WHERE s.enabled=1 ORDER BY s.name
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try: d["fans"] = json.loads(d["fans"] or "[]")
        except: d["fans"] = []
        result.append(d)
    return jsonify(result)

@app.route("/api/server/<int:sid>/live")
def api_server_live(sid):
    conn = get_db()
    row = conn.execute("SELECT * FROM live_metrics WHERE server_id=?", (sid,)).fetchone()
    conn.close()
    if not row: return jsonify({})
    d = dict(row)
    try: d["fans"] = json.loads(d["fans"] or "[]")
    except: d["fans"] = []
    return jsonify(d)

@app.route("/api/server/<int:sid>/history")
def api_history(sid):
    limit = int(request.args.get("limit", 240))
    conn = get_db()
    rows = conn.execute("""SELECT ts,cpu_pct,cpu_temp,ram_used_mb,ram_total_mb,
        net_rx_kbps,net_tx_kbps,disk_read_kbps,disk_write_kbps,gpu_temp
        FROM history WHERE server_id=? ORDER BY id DESC LIMIT ?""",
        (sid, limit)).fetchall()
    conn.close()
    return jsonify(list(reversed([dict(r) for r in rows])))

@app.route("/api/server/<int:sid>/log")
def api_log(sid):
    conn = get_db()
    row = conn.execute("SELECT stress_log_tail FROM live_metrics WHERE server_id=?", (sid,)).fetchone()
    conn.close()
    if row and row["stress_log_tail"]:
        return jsonify({"lines": row["stress_log_tail"].splitlines()[-50:]})
    return jsonify({"lines": []})

@app.route("/api/server/<int:sid>/action", methods=["POST"])
def api_action(sid):
    action = request.json.get("action")
    conn = get_db()
    s = dict(conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone())
    conn.close()
    ip, port, user, pw = s["ip"], s["ssh_port"], s["ssh_user"], s["ssh_pass"]
    script = s.get("stress_script", "/root/hw_stress_test.py")
    log = s.get("stress_log", "/root/hw_stress_test/stress_test.log")

    if action == "start":
        cmd = (f"mkdir -p $(dirname {log}); pkill -f hw_stress_test.py 2>/dev/null || true; "
               f"nohup python3 {script} > {log} 2>&1 & echo PID:$!")
        ok, out = ssh_run(ip, port, user, pw, cmd)
    elif action == "stop":
        ok, out = ssh_run(ip, port, user, pw, "pkill -f hw_stress_test.py 2>/dev/null; echo stopped")
    elif action == "install":
        ok, out = ssh_run(ip, port, user, pw,
            "apt-get install -y stress-ng fio lm-sensors 2>&1 | tail -5", timeout=90)
    elif action == "clear_log":
        ok, out = ssh_run(ip, port, user, pw, f"truncate -s 0 {log} 2>/dev/null; echo cleared")
    elif action == "detect_fans":
        ok, out = ssh_run_script(ip, port, user, pw, FAN_DETECT_SCRIPT, timeout=12)
        if ok:
            try: return jsonify({"ok": True, "fans": json.loads(out)})
            except: return jsonify({"ok": False, "fans": [], "output": out[:200]})
        return jsonify({"ok": False, "fans": [], "output": out[:200]})
    elif action == "setup_all":
        # Alle Dependencies installieren: stress-ng, fio, lm-sensors, fancontrol, i2c-tools
        cmd = (
            "DEBIAN_FRONTEND=noninteractive apt-get update -qq 2>&1 | tail -2; "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "stress-ng fio lm-sensors fancontrol i2c-tools "
            "python3-pip sysstat hdparm nvme-cli 2>&1 | tail -10; "
            "sensors-detect --auto 2>/dev/null | tail -3; "
            "echo SETUP_DONE"
        )
        ok, out = ssh_run(ip, port, user, pw, cmd, timeout=180)
    elif action == "check_deps":
        # Prüfe welche Tools installiert sind
        check = (
            "echo stress-ng:$(which stress-ng 2>/dev/null && echo OK || echo MISSING); "
            "echo fio:$(which fio 2>/dev/null && echo OK || echo MISSING); "
            "echo sensors:$(which sensors 2>/dev/null && echo OK || echo MISSING); "
            "echo fancontrol:$(which fancontrol 2>/dev/null && echo OK || echo MISSING); "
            "echo i2cdetect:$(which i2cdetect 2>/dev/null && echo OK || echo MISSING); "
            "echo pwm_channels:$(ls /sys/class/hwmon/hwmon*/pwm[0-9] 2>/dev/null | wc -l); "
            "echo nvidia_smi:$(which nvidia-smi 2>/dev/null && echo OK || echo MISSING)"
        )
        ok, out = ssh_run(ip, port, user, pw, check)
    else:
        return jsonify({"ok": False, "output": "Unbekannte Aktion"})
    return jsonify({"ok": ok, "output": out[:500]})

@app.route("/api/server/<int:sid>/fan", methods=["POST"])
def api_set_fan(sid):
    data = request.json
    conn = get_db()
    s = dict(conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone())
    conn.close()
    pwm_path = data.get("pwm_path")
    value_pct = int(data.get("value_pct", 50))
    ok, out = set_fan_pwm(s["ip"], s["ssh_port"], s["ssh_user"], s["ssh_pass"],
                          pwm_path, value_pct)
    return jsonify({"ok": ok, "output": out})

@app.route("/api/servers", methods=["GET", "POST"])
def api_servers():
    if request.method == "POST":
        d = request.json
        conn = get_db()
        conn.execute("INSERT INTO servers (name,ip,ssh_port,ssh_user,ssh_pass) VALUES (?,?,?,?,?)",
                     (d["name"], d["ip"], d.get("port", 22), d.get("user", "root"), d.get("password", "")))
        conn.commit(); conn.close()
        return jsonify({"ok": True})
    conn = get_db()
    rows = [dict(r) for r in conn.execute(
        "SELECT id,name,ip,ssh_port,ssh_user,enabled FROM servers").fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/server/<int:sid>/acknowledge", methods=["POST"])
def api_acknowledge(sid):
    data = request.json or {}
    note = data.get("note", "")
    now = datetime.datetime.now().isoformat()
    conn = get_db()
    # Fehler quittieren
    conn.execute("UPDATE live_metrics SET stress_failure=NULL WHERE server_id=?", (sid,))
    # Alert-Log Eintrag
    conn.execute("INSERT INTO alerts (server_id,ts,type,message,acknowledged,ack_ts,ack_note) "
                 "SELECT ?,?,?,stress_failure,1,?,? FROM live_metrics WHERE server_id=?",
                 (sid, now, 'stress_failure', now, note, sid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/server/<int:sid>/alerts")
def api_alerts(sid):
    conn = get_db()
    rows = conn.execute("SELECT * FROM alerts WHERE server_id=? ORDER BY id DESC LIMIT 50", (sid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/alerts")
def api_all_alerts():
    conn = get_db()
    rows = conn.execute(
        "SELECT a.*,s.name as server_name FROM alerts a JOIN servers s ON a.server_id=s.id "
        "ORDER BY a.id DESC LIMIT 100").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/servers/<int:sid>", methods=["DELETE"])
def api_del_server(sid):
    conn = get_db()
    conn.execute("UPDATE servers SET enabled=0 WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/")
def index(): return render_template("index.html")

@app.route("/server/<int:sid>")
def server_detail(sid):
    conn = get_db()
    s = conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
    conn.close()
    return render_template("detail.html", server=dict(s)) if s else redirect("/")

@app.route("/fans")
def fans_page(): return render_template("fans.html")

@app.route("/setup")
def setup_page(): return render_template("setup.html")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=polling_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
