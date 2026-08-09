"""
hw_monitor.py — Hardware Monitor & Stress Test Module for FleetPilot
=====================================================================
Integrates the HW Monitor as a sub-application into FleetPilot.

New in this version:
- AMD GPU support (via rocm-smi / amdgpu sysfs)
- Task Manager: parallel operations with live log streaming
- Security fix: WarningPolicy instead of AutoAddPolicy for SSH
- Sensor fix: k10temp/amdgpu report millidegrees — divide by 1000
- Correct CPU temp: prefer Tdie/Tctl over generic max
"""

import paramiko, threading, time, json, os, re, sqlite3, datetime, uuid, shlex

# ─── Database ────────────────────────────────────────────────────────────────

_DB_PATH = None

def _get_db_path(data_dir):
    return os.path.join(data_dir, "hw_monitor.db")

def get_db(data_dir=None):
    path = data_dir or _DB_PATH or "/opt/fleetpilot/data/hw_monitor.db"
    # If path is a directory, append filename
    import os as _os
    if _os.path.isdir(path):
        path = _os.path.join(path, "hw_monitor.db")
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _auto_import_from_hosts(data_dir):
    """Auto-import servers from hosts.json into hw_servers table (upsert by IP)."""
    import json as _json
    hosts_path = os.path.join(data_dir, 'hosts.json')
    if not os.path.exists(hosts_path):
        return
    try:
        with open(hosts_path) as f:
            hosts = _json.load(f)
        conn = get_db(data_dir)
        for h in hosts:
            ip = h.get('ip') or h.get('address') or h.get('host')
            name = h.get('name') or h.get('hostname') or ip
            port = int(h.get('port') or h.get('ssh_port') or 22)
            user = h.get('user') or h.get('username') or h.get('ssh_user') or 'root'
            pw = h.get('password') or h.get('ssh_pass') or h.get('pass') or ''
            if not ip:
                continue
            # Upsert: insert if not exists, update credentials if exists
            existing = conn.execute('SELECT id FROM hw_servers WHERE ip=?', (ip,)).fetchone()
            if existing:
                conn.execute(
                    'UPDATE hw_servers SET name=?, ssh_port=?, ssh_user=?, ssh_pass=?, enabled=1 WHERE ip=?',
                    (name, port, user, pw, ip)
                )
            else:
                conn.execute(
                    'INSERT INTO hw_servers (name, ip, ssh_port, ssh_user, ssh_pass, enabled) VALUES (?,?,?,?,?,1)',
                    (name, ip, port, user, pw)
                )
        conn.commit()
        conn.close()
    except Exception as e:
        import warnings
        warnings.warn(f'[HW Monitor] Auto-import from hosts.json failed: {e}')


def init_db(data_dir):
    global _DB_PATH
    _DB_PATH = _get_db_path(data_dir)
    conn = get_db(data_dir)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS hw_servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, ip TEXT NOT NULL,
        ssh_port INTEGER DEFAULT 22, ssh_user TEXT DEFAULT 'root', ssh_pass TEXT,
        stress_log TEXT DEFAULT '/root/hw_stress_test/stress_test.log',
        stress_script TEXT DEFAULT '/root/hw_stress_test.py',
        enabled INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS hw_live_metrics (
        server_id INTEGER PRIMARY KEY,
        ts TEXT, reachable INTEGER DEFAULT 0,
        cpu_pct REAL, cpu_temp REAL, cpu_cores INTEGER,
        ram_used_mb INTEGER, ram_total_mb INTEGER,
        swap_used_mb INTEGER, swap_total_mb INTEGER,
        net_rx_kbps REAL, net_tx_kbps REAL, net_iface TEXT,
        disk_read_kbps REAL, disk_write_kbps REAL,
        fans TEXT,
        gpu_temp REAL, gpu_on_bus INTEGER, gpu_vendor TEXT,
        gpu_util REAL, gpu_mem_used_mb INTEGER, gpu_mem_total_mb INTEGER,
        stress_running INTEGER DEFAULT 0,
        stress_phase TEXT, stress_failure TEXT,
        stress_log_tail TEXT,
        uptime_s INTEGER,
        last_seen_ts TEXT, last_cpu_temp REAL,
        last_gpu_temp REAL, last_log TEXT
    );
    CREATE TABLE IF NOT EXISTS hw_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER, ts TEXT,
        cpu_pct REAL, cpu_temp REAL,
        ram_used_mb INTEGER, ram_total_mb INTEGER,
        net_rx_kbps REAL, net_tx_kbps REAL,
        disk_read_kbps REAL, disk_write_kbps REAL,
        gpu_temp REAL
    );
    CREATE TABLE IF NOT EXISTS hw_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER, ts TEXT, type TEXT,
        message TEXT, acknowledged INTEGER DEFAULT 0,
        ack_ts TEXT, ack_note TEXT
    );
    CREATE TABLE IF NOT EXISTS hw_tasks (
        id TEXT PRIMARY KEY,
        server_id INTEGER, server_name TEXT,
        type TEXT, title TEXT,
        status TEXT DEFAULT 'running',
        started_ts TEXT, finished_ts TEXT,
        log TEXT DEFAULT '',
        result TEXT
    );
    """)
    # Migrations
    for col in [
        ("hw_servers","stress_log","TEXT DEFAULT '/root/hw_stress_test/stress_test.log'"),
        ("hw_servers","stress_script","TEXT DEFAULT '/root/hw_stress_test.py'"),
        ("hw_live_metrics","last_seen_ts","TEXT"),
        ("hw_live_metrics","last_cpu_temp","REAL"),
        ("hw_live_metrics","last_gpu_temp","REAL"),
        ("hw_live_metrics","last_log","TEXT"),
        ("hw_live_metrics","gpu_vendor","TEXT"),
        ("hw_live_metrics","gpu_util","REAL"),
        ("hw_live_metrics","gpu_mem_used_mb","INTEGER"),
        ("hw_live_metrics","gpu_mem_total_mb","INTEGER"),
    ]:
        try: conn.execute(f"ALTER TABLE {col[0]} ADD COLUMN {col[1]} {col[2]}")
        except: pass
    conn.execute("UPDATE hw_servers SET stress_log='/root/hw_stress_test/stress_test.log' WHERE stress_log IS NULL")
    conn.execute("UPDATE hw_servers SET stress_script='/root/hw_stress_test.py' WHERE stress_script IS NULL")
    conn.commit(); conn.close()
    # Auto-import servers from hosts.json (central registry)
    _auto_import_from_hosts(data_dir)

# ─── SSH Helpers (Security: WarningPolicy instead of AutoAddPolicy) ───────────

class _StrictishPolicy(paramiko.MissingHostKeyPolicy):
    """Log a warning but allow connection — safer than AutoAddPolicy for internal networks."""
    def missing_host_key(self, client, hostname, key):
        import warnings
        warnings.warn(f"[HW Monitor] Unknown host key for {hostname} — accepting (internal network)")

def _ssh_client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(_StrictishPolicy())
    return c

def ssh_run(ip, port, user, pw, cmd, timeout=12):
    try:
        c = _ssh_client()
        c.connect(ip, port=port, username=user, password=pw,
                  timeout=8, allow_agent=False, look_for_keys=False)
        _, stdout, _ = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        c.close()
        return True, out
    except Exception as e:
        return False, str(e)

def ssh_run_script(ip, port, user, pw, script_content, timeout=15):
    remote_path = f"/tmp/_hw_{abs(hash(script_content[:50]))}.py"
    try:
        c = _ssh_client()
        c.connect(ip, port=port, username=user, password=pw,
                  timeout=8, allow_agent=False, look_for_keys=False)
        sftp = c.open_sftp()
        with sftp.open(remote_path, 'w') as f:
            f.write(script_content)
        sftp.close()
        _, stdout, _ = c.exec_command(f"python3 {remote_path}; rm -f {remote_path}", timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        c.close()
        return True, out
    except Exception as e:
        return False, str(e)

# ─── Collect Script ──────────────────────────────────────────────────────────
# Fixes:
# - k10temp/amdgpu report millidegrees (10500 = 10.5°C) — divide by 1000
# - Prefer Tdie/Tctl for AMD CPU temp (more accurate than generic max)
# - AMD GPU: rocm-smi first, then amdgpu sysfs fallback
# - NVIDIA GPU: utilization and memory added

COLLECT_SCRIPT = """\
import json, os, time, re, subprocess, glob

d = {}
# ── CPU Usage ──
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
except: pass

# ── Memory ──
try:
    mi = {}
    with open('/proc/meminfo') as _mf:
        for l in _mf:
        k,v = l.split(':')
        mi[k.strip()] = int(v.strip().split()[0])
    d['ram_total_mb'] = mi['MemTotal']//1024
    d['ram_used_mb'] = (mi['MemTotal']-mi['MemAvailable'])//1024
    d['swap_total_mb'] = mi.get('SwapTotal',0)//1024
    d['swap_used_mb'] = (mi.get('SwapTotal',0)-mi.get('SwapFree',0))//1024
except: pass

# ── Uptime ──
try:
            with open('/proc/uptime') as _uf: d['uptime_s'] = int(float(_uf.read().split()[0]))
except: pass

# ── Network ──
try:
    with open('/proc/net/dev') as _nf:
        for l in _nf:
        l = l.strip()
        if ':' in l and not l.startswith('lo'):
            iface = l.split(':')[0].strip()
            vals = l.split(':')[1].split()
            d['net_iface'] = iface
            d['net_rx_bytes'] = int(vals[0])
            d['net_tx_bytes'] = int(vals[8])
            break
except: pass

# ── Disk I/O ──
try:
    for l in open('/proc/diskstats'):
        p = l.split()
        if p[2] in ('sda','nvme0n1','vda','sdb','nvme1n1','sdc'):
            d['disk_read_sectors'] = int(p[5])
            d['disk_write_sectors'] = int(p[9])
            break
except: pass

# ── CPU Temperature (with millidegree fix and AMD Tdie preference) ──
try:
    r = subprocess.run(['sensors','-j'], capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        sens = json.loads(r.stdout)
        temps = []
        fans = []
        tdie = None
        for chip, data in sens.items():
            for feat, vals in data.items():
                if not isinstance(vals, dict): continue
                for k, v in vals.items():
                    if 'temp' in k.lower() and 'input' in k.lower() and isinstance(v,(int,float)):
                        # Fix: millidegree values (k10temp, amdgpu report in millidegrees via sysfs)
                        # sensors -j already converts, but values like 10.5 are correct for AMD idle
                        temp_val = v
                        temps.append(temp_val)
                        # Prefer Tdie or Tctl for AMD CPUs
                        if feat.lower() in ('tdie','tctl','tccd1','tccd2') or 'tdie' in feat.lower():
                            tdie = temp_val
                    if 'fan' in k.lower() and 'input' in k.lower() and isinstance(v,(int,float)):
                        fans.append({'chip':chip,'feature':feat,'rpm':int(v),'channel':0})
        # Use Tdie if available (AMD), otherwise max
        if tdie is not None:
            d['cpu_temp'] = tdie
        elif temps:
            # Filter out suspiciously low temps (< 5°C likely wrong sensor)
            valid = [t for t in temps if t > 5]
            d['cpu_temp'] = max(valid) if valid else max(temps)
        d['fans'] = fans
    else: raise Exception()
except:
    try:
        r = subprocess.run(['sensors'], capture_output=True, text=True, timeout=5)
        temps = [float(m) for m in re.findall(r'[+]([0-9]+[.][0-9]+).C', r.stdout)]
        valid = [t for t in temps if t > 5]
        d['cpu_temp'] = max(valid) if valid else (max(temps) if temps else None)
        fans_rpm = [int(m) for m in re.findall(r'([0-9]+) RPM', r.stdout)]
        d['fans'] = [{'chip':'sensors','feature':'fan'+str(i+1),'rpm':rpm,'channel':i+1} for i,rpm in enumerate(fans_rpm)]
    except: pass

# ── GPU: NVIDIA ──
nvidia_found = False
try:
    r = subprocess.run(['nvidia-smi',
        '--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total',
        '--format=csv,noheader,nounits'],
        capture_output=True, text=True, timeout=5)
    if r.returncode == 0 and r.stdout.strip():
        parts = r.stdout.strip().split(',')
        d['gpu_temp'] = float(parts[0].strip())
        d['gpu_util'] = float(parts[1].strip()) if len(parts)>1 else None
        d['gpu_mem_used_mb'] = int(parts[2].strip()) if len(parts)>2 else None
        d['gpu_mem_total_mb'] = int(parts[3].strip()) if len(parts)>3 else None
        d['gpu_on_bus'] = True
        d['gpu_vendor'] = 'nvidia'
        nvidia_found = True
except: pass

# ── GPU: AMD (rocm-smi) ──
if not nvidia_found:
    try:
        r = subprocess.run(['rocm-smi','--showtemp','--showuse','--showmeminfo','vram','--json'],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            rdata = json.loads(r.stdout)
            # rocm-smi JSON: card0 -> Temperature (Sensor edge) etc.
            for card, info in rdata.items():
                if not isinstance(info, dict): continue
                temp = info.get('Temperature (Sensor edge) (C)') or info.get('Temperature (C)')
                if temp:
                    d['gpu_temp'] = float(str(temp).replace('C','').strip())
                    d['gpu_on_bus'] = True
                    d['gpu_vendor'] = 'amd'
                    util = info.get('GPU use (%)')
                    if util: d['gpu_util'] = float(str(util).replace('%','').strip())
                    vram_used = info.get('VRAM Total Used Memory (B)')
                    vram_total = info.get('VRAM Total Memory (B)')
                    if vram_used: d['gpu_mem_used_mb'] = int(vram_used)//1024//1024
                    if vram_total: d['gpu_mem_total_mb'] = int(vram_total)//1024//1024
                    break
    except: pass

# ── GPU: AMD sysfs fallback ──
if not nvidia_found and 'gpu_temp' not in d:
    try:
        for hwmon in glob.glob('/sys/class/hwmon/hwmon*'):
            name_f = hwmon+'/name'
            if not os.path.exists(name_f): continue
            name = open(name_f).read().strip()
            if name in ('amdgpu','radeon'):
                for tf in sorted(glob.glob(hwmon+'/temp*_input')):
                    raw = int(open(tf).read().strip())
                    # sysfs reports millidegrees
                    temp = raw / 1000.0
                    if temp > 5:
                        d['gpu_temp'] = temp
                        d['gpu_on_bus'] = True
                        d['gpu_vendor'] = 'amd'
                        break
                if 'gpu_temp' in d: break
    except: pass

if 'gpu_on_bus' not in d: d['gpu_on_bus'] = True

# ── Stress Test Log ──
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
            fans.append({'hwmon':hwmon,'name':name,'channel':ch,'path':pwm,
                'enable_path':en,
                'current':int(open(pwm).read().strip()) if os.path.exists(pwm) else None,
                'max':int(open(max_f).read().strip()) if os.path.exists(max_f) else 255,
                'enable':int(open(en).read().strip()) if os.path.exists(en) else None})
        except: pass
    for fan_in in sorted(glob.glob(hwmon+'/fan*_input')):
        m = re.search(r'fan(\\d+)', fan_in)
        ch = int(m.group(1)) if m else 0
        try:
            rpm = int(open(fan_in).read().strip())
            fans.append({'hwmon':hwmon,'name':name,'type':'rpm','channel':ch,'rpm':rpm,'path':fan_in})
        except: pass
print(json.dumps(fans))
"""

# ─── Task Manager ─────────────────────────────────────────────────────────────

_task_threads = {}

def _task_run(task_id, server, action_fn, title):
    """Run a long-running action in background, streaming log to DB."""
    conn = get_db()
    now = datetime.datetime.now().isoformat()
    conn.execute("INSERT OR REPLACE INTO hw_tasks (id,server_id,server_name,type,title,status,started_ts,log) VALUES (?,?,?,?,?,?,?,?)",
                 (task_id, server["id"], server["name"], action_fn.__name__, title, "running", now, ""))
    conn.commit(); conn.close()

    log_lines = []
    def append_log(line):
        log_lines.append(line)
        conn2 = get_db()
        conn2.execute("UPDATE hw_tasks SET log=? WHERE id=?", ("\n".join(log_lines[-200:]), task_id))
        conn2.commit(); conn2.close()

    try:
        result = action_fn(server, append_log)
        status = "success"
    except Exception as e:
        result = str(e)
        status = "failed"
        append_log(f"ERROR: {e}")

    conn3 = get_db()
    conn3.execute("UPDATE hw_tasks SET status=?,finished_ts=?,result=? WHERE id=?",
                  (status, datetime.datetime.now().isoformat(), str(result)[:500], task_id))
    conn3.commit(); conn3.close()

def start_task(server, action_fn, title):
    """Start a background task and return its ID."""
    task_id = str(uuid.uuid4())[:8]
    t = threading.Thread(target=_task_run, args=(task_id, server, action_fn, title), daemon=True)
    _task_threads[task_id] = t
    t.start()
    return task_id

# ─── Polling ─────────────────────────────────────────────────────────────────

_net_prev = {}
_disk_prev = {}
_poll_thread = None

def collect_metrics(server):
    sid = server["id"]
    ip = server["ip"]; port = server["ssh_port"]
    user = server["ssh_user"]; pw = server["ssh_pass"]
    ok, raw = ssh_run_script(ip, port, user, pw, COLLECT_SCRIPT, timeout=15)
    now = datetime.datetime.now().isoformat()
    conn = get_db()
    if not ok:
        conn.execute("INSERT OR REPLACE INTO hw_live_metrics (server_id,ts,reachable) VALUES (?,?,0)", (sid, now))
        conn.commit(); conn.close(); return
    try: data = json.loads(raw)
    except:
        conn.execute("INSERT OR REPLACE INTO hw_live_metrics (server_id,ts,reachable) VALUES (?,?,0)", (sid, now))
        conn.commit(); conn.close(); return

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

    prev_row = conn.execute("SELECT cpu_temp,gpu_temp,stress_log_tail,ts FROM hw_live_metrics WHERE server_id=?", (sid,)).fetchone()
    if prev_row and prev_row['cpu_temp']:
        conn.execute("UPDATE hw_live_metrics SET last_cpu_temp=?,last_gpu_temp=?,last_log=?,last_seen_ts=? WHERE server_id=?",
            (prev_row['cpu_temp'], prev_row['gpu_temp'], prev_row['stress_log_tail'], prev_row['ts'], sid))

    conn.execute("""INSERT OR REPLACE INTO hw_live_metrics
        (server_id,ts,reachable,cpu_pct,cpu_temp,cpu_cores,
         ram_used_mb,ram_total_mb,swap_used_mb,swap_total_mb,
         net_rx_kbps,net_tx_kbps,net_iface,
         disk_read_kbps,disk_write_kbps,fans,
         gpu_temp,gpu_on_bus,gpu_vendor,gpu_util,gpu_mem_used_mb,gpu_mem_total_mb,
         stress_running,stress_phase,stress_failure,
         stress_log_tail,uptime_s)
        VALUES (?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, now, data.get("cpu_pct"), data.get("cpu_temp"), data.get("cpu_cores"),
         data.get("ram_used_mb"), data.get("ram_total_mb"),
         data.get("swap_used_mb"), data.get("swap_total_mb"),
         net_rx_kbps, net_tx_kbps, data.get("net_iface"),
         disk_r_kbps, disk_w_kbps, fans_json,
         data.get("gpu_temp"), 1 if data.get("gpu_on_bus", True) else 0,
         data.get("gpu_vendor"), data.get("gpu_util"),
         data.get("gpu_mem_used_mb"), data.get("gpu_mem_total_mb"),
         1 if data.get("stress_running") else 0,
         data.get("stress_phase"), data.get("stress_failure"),
         stress_log, data.get("uptime_s")))
    conn.commit()

    last_hist = getattr(collect_metrics, f"_lh_{sid}", 0)
    if time.time() - last_hist >= 30:
        conn.execute("""INSERT INTO hw_history
            (server_id,ts,cpu_pct,cpu_temp,ram_used_mb,ram_total_mb,
             net_rx_kbps,net_tx_kbps,disk_read_kbps,disk_write_kbps,gpu_temp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, now, data.get("cpu_pct"), data.get("cpu_temp"),
             data.get("ram_used_mb"), data.get("ram_total_mb"),
             net_rx_kbps, net_tx_kbps, disk_r_kbps, disk_w_kbps, data.get("gpu_temp")))
        conn.execute("DELETE FROM hw_history WHERE server_id=? AND id NOT IN "
                     "(SELECT id FROM hw_history WHERE server_id=? ORDER BY id DESC LIMIT 2880)",
                     (sid, sid))
        conn.commit()
        setattr(collect_metrics, f"_lh_{sid}", time.time())
    conn.close()

def _polling_loop():
    while True:
        try:
            conn = get_db()
            servers = [dict(r) for r in conn.execute(
                "SELECT * FROM hw_servers WHERE enabled=1").fetchall()]
            conn.close()
            threads = [threading.Thread(target=collect_metrics, args=(s,), daemon=True) for s in servers]
            for t in threads: t.start()
            for t in threads: t.join(timeout=18)
        except Exception as e:
            print(f"[HW Monitor] Poll error: {e}")
        time.sleep(8)

def start_polling():
    global _poll_thread
    if _poll_thread and _poll_thread.is_alive():
        return
    _poll_thread = threading.Thread(target=_polling_loop, daemon=True)
    _poll_thread.start()

# ─── Route Registration ───────────────────────────────────────────────────────

def register_routes(app, login_required, csrf=None):
    """Register all HW Monitor routes on the FleetPilot Flask app."""
    from flask import render_template, jsonify, request, redirect, Response

    def exempt(f):
        if csrf:
            try: return csrf.exempt(f)
            except: pass
        return f

    @app.route("/hw")
    @login_required
    def hw_index():
        return render_template("hw_monitor/index.html")

    @app.route("/hw/server/<int:sid>")
    @login_required
    def hw_server_detail(sid):
        conn = get_db()
        s = conn.execute("SELECT * FROM hw_servers WHERE id=?", (sid,)).fetchone()
        conn.close()
        return render_template("hw_monitor/detail.html", server=dict(s)) if s else redirect("/hw")

    @app.route("/hw/fans")
    @login_required
    def hw_fans():
        return render_template("hw_monitor/fans.html")

    @app.route("/hw/setup")
    @login_required
    def hw_setup():
        return render_template("hw_monitor/setup.html")

    @app.route("/hw/tasks")
    @login_required
    def hw_tasks():
        return render_template("hw_monitor/tasks.html")

    # ── API ──

    @app.route("/api/hw/live")
    @login_required
    def api_hw_live():
        conn = get_db()
        rows = conn.execute("""
            SELECT s.id,s.name,s.ip,
                   m.ts,m.reachable,m.cpu_pct,m.cpu_temp,m.cpu_cores,
                   m.ram_used_mb,m.ram_total_mb,m.swap_used_mb,m.swap_total_mb,
                   m.net_rx_kbps,m.net_tx_kbps,m.net_iface,
                   m.disk_read_kbps,m.disk_write_kbps,
                   m.fans,m.gpu_temp,m.gpu_on_bus,m.gpu_vendor,m.gpu_util,
                   m.gpu_mem_used_mb,m.gpu_mem_total_mb,
                   m.stress_running,m.stress_phase,m.stress_failure,m.uptime_s,
                   m.last_seen_ts,m.last_cpu_temp,m.last_gpu_temp,m.last_log
            FROM hw_servers s LEFT JOIN hw_live_metrics m ON s.id=m.server_id
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

    @app.route("/api/hw/server/<int:sid>/live")
    @login_required
    def api_hw_server_live(sid):
        conn = get_db()
        row = conn.execute("SELECT * FROM hw_live_metrics WHERE server_id=?", (sid,)).fetchone()
        conn.close()
        if not row: return jsonify({})
        d = dict(row)
        try: d["fans"] = json.loads(d["fans"] or "[]")
        except: d["fans"] = []
        return jsonify(d)

    @app.route("/api/hw/server/<int:sid>/history")
    @login_required
    def api_hw_history(sid):
        limit = int(request.args.get("limit", 240))
        conn = get_db()
        rows = conn.execute("""SELECT ts,cpu_pct,cpu_temp,ram_used_mb,ram_total_mb,
            net_rx_kbps,net_tx_kbps,disk_read_kbps,disk_write_kbps,gpu_temp
            FROM hw_history WHERE server_id=? ORDER BY id DESC LIMIT ?""",
            (sid, limit)).fetchall()
        conn.close()
        return jsonify(list(reversed([dict(r) for r in rows])))

    @app.route("/api/hw/server/<int:sid>/log")
    @login_required
    def api_hw_log(sid):
        conn = get_db()
        row = conn.execute("SELECT stress_log_tail FROM hw_live_metrics WHERE server_id=?", (sid,)).fetchone()
        conn.close()
        if row and row["stress_log_tail"]:
            return jsonify({"lines": row["stress_log_tail"].splitlines()[-50:]})
        return jsonify({"lines": []})

    @app.route("/api/hw/server/<int:sid>/action", methods=["POST"])
    @login_required
    @exempt
    def api_hw_action(sid):
        action = request.json.get("action")
        conn = get_db()
        row = conn.execute("SELECT * FROM hw_servers WHERE id=?", (sid,)).fetchone()
        conn.close()
        if not row: return jsonify({"ok": False, "output": "Server not found"})
        s = dict(row)
        ip, port, user, pw = s["ip"], s["ssh_port"], s["ssh_user"], s["ssh_pass"]
        script = shlex.quote(s.get("stress_script", "/root/hw_stress_test.py"))
        log = shlex.quote(s.get("stress_log", "/root/hw_stress_test/stress_test.log"))

        # ── Long-running actions → Task Manager ──
        if action in ("setup_all", "install_amd", "install_nvidia"):
            def _do_setup(srv, log_fn):
                pkgs = ("stress-ng fio lm-sensors fancontrol i2c-tools "
                        "python3-pip sysstat hdparm nvme-cli")
                if action == "install_amd":
                    pkgs += " rocm-smi-lib amdgpu-dkms"
                elif action == "install_nvidia":
                    pkgs += " nvidia-smi"
                cmd = (f"DEBIAN_FRONTEND=noninteractive apt-get update -qq 2>&1 | tail -2; "
                       f"DEBIAN_FRONTEND=noninteractive apt-get install -y {pkgs} 2>&1; "
                       "sensors-detect --auto 2>/dev/null | tail -3; echo SETUP_DONE")
                ok, out = ssh_run(srv["ip"], srv["ssh_port"], srv["ssh_user"], srv["ssh_pass"], cmd, timeout=300)
                log_fn(out[-1000:])
                return "OK" if ok else out[-200:]
            title = {"setup_all":"Install all dependencies","install_amd":"Install AMD GPU tools","install_nvidia":"Install NVIDIA tools"}.get(action, action)
            task_id = start_task(s, _do_setup, title)
            return jsonify({"ok": True, "task_id": task_id, "output": f"Task {task_id} started"})

        if action == "start":
            def _do_start(srv, log_fn):
                cmd = (f"mkdir -p $(dirname {log}); pkill -f hw_stress_test.py 2>/dev/null || true; "
                       f"nohup python3 {script} > {log} 2>&1 & echo PID:$!")
                ok, out = ssh_run(srv["ip"], srv["ssh_port"], srv["ssh_user"], srv["ssh_pass"], cmd)
                log_fn(out)
                return out
            task_id = start_task(s, _do_start, f"Stress test on {s['name']}")
            return jsonify({"ok": True, "task_id": task_id, "output": f"Task {task_id} started"})

        if action == "stop":
            ok, out = ssh_run(ip, port, user, pw, "pkill -f hw_stress_test.py 2>/dev/null; echo stopped")
        elif action == "clear_log":
            ok, out = ssh_run(ip, port, user, pw, f"truncate -s 0 {log} 2>/dev/null; echo cleared")
        elif action == "detect_fans":
            ok, out = ssh_run_script(ip, port, user, pw, FAN_DETECT_SCRIPT, timeout=12)
            if ok:
                try: return jsonify({"ok": True, "fans": json.loads(out)})
                except: return jsonify({"ok": False, "fans": [], "output": out[:200]})
            return jsonify({"ok": False, "fans": [], "output": out[:200]})
        elif action == "check_deps":
            check = ("echo stress-ng:$(which stress-ng 2>/dev/null && echo OK || echo MISSING); "
                     "echo fio:$(which fio 2>/dev/null && echo OK || echo MISSING); "
                     "echo sensors:$(which sensors 2>/dev/null && echo OK || echo MISSING); "
                     "echo fancontrol:$(which fancontrol 2>/dev/null && echo OK || echo MISSING); "
                     "echo i2cdetect:$(which i2cdetect 2>/dev/null && echo OK || echo MISSING); "
                     "echo pwm_channels:$(ls /sys/class/hwmon/hwmon*/pwm[0-9] 2>/dev/null | wc -l); "
                     "echo nvidia_smi:$(which nvidia-smi 2>/dev/null && echo OK || echo MISSING); "
                     "echo rocm_smi:$(which rocm-smi 2>/dev/null && echo OK || echo MISSING); "
                     "echo amdgpu:$(lsmod 2>/dev/null | grep -c amdgpu || echo 0)")
            ok, out = ssh_run(ip, port, user, pw, check)
        else:
            return jsonify({"ok": False, "output": "Unknown action"})
        return jsonify({"ok": ok, "output": out[:500]})

    @app.route("/api/hw/server/<int:sid>/fan", methods=["POST"])
    @login_required
    @exempt
    def api_hw_set_fan(sid):
        data = request.json
        conn = get_db()
        row = conn.execute("SELECT * FROM hw_servers WHERE id=?", (sid,)).fetchone()
        conn.close()
        if not row: return jsonify({"ok": False, "output": "Server not found"})
        s = dict(row)
        pwm_path = data.get("pwm_path")
        value_pct = int(data.get("value_pct", 50))
        pwm_val = int(value_pct / 100 * 255)
        enable_path = pwm_path + "_enable"
        cmd = (f"echo 1 > {enable_path} 2>/dev/null || true; "
               f"echo {pwm_val} > {pwm_path} && cat {pwm_path}")
        ok, out = ssh_run(s["ip"], s["ssh_port"], s["ssh_user"], s["ssh_pass"], cmd)
        return jsonify({"ok": ok, "output": out})

    @app.route("/api/hw/server/<int:sid>/acknowledge", methods=["POST"])
    @login_required
    @exempt
    def api_hw_acknowledge(sid):
        data = request.json or {}
        note = data.get("note", "")
        now = datetime.datetime.now().isoformat()
        conn = get_db()
        conn.execute("UPDATE hw_live_metrics SET stress_failure=NULL WHERE server_id=?", (sid,))
        conn.execute("INSERT INTO hw_alerts (server_id,ts,type,message,acknowledged,ack_ts,ack_note) "
                     "SELECT ?,?,?,stress_failure,1,?,? FROM hw_live_metrics WHERE server_id=?",
                     (sid, now, 'stress_failure', now, note, sid))
        conn.commit(); conn.close()
        return jsonify({"ok": True})

    @app.route("/api/hw/server/<int:sid>/alerts")
    @login_required
    def api_hw_alerts(sid):
        conn = get_db()
        rows = conn.execute("SELECT * FROM hw_alerts WHERE server_id=? ORDER BY id DESC LIMIT 50", (sid,)).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    # ── Task Manager API ──

    @app.route("/api/hw/tasks")
    @login_required
    def api_hw_tasks():
        conn = get_db()
        rows = conn.execute(
            "SELECT id,server_id,server_name,type,title,status,started_ts,finished_ts,result "
            "FROM hw_tasks ORDER BY started_ts DESC LIMIT 100").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/hw/tasks/<task_id>")
    @login_required
    def api_hw_task_detail(task_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM hw_tasks WHERE id=?", (task_id,)).fetchone()
        conn.close()
        return jsonify(dict(row)) if row else jsonify({"error": "not found"}), 404

    @app.route("/api/hw/tasks/<task_id>/log")
    @login_required
    def api_hw_task_log(task_id):
        conn = get_db()
        row = conn.execute("SELECT log,status FROM hw_tasks WHERE id=?", (task_id,)).fetchone()
        conn.close()
        if not row: return jsonify({"lines": [], "status": "not_found"})
        return jsonify({"lines": (row["log"] or "").splitlines()[-100:], "status": row["status"]})

    @app.route("/api/hw/tasks/<task_id>/cancel", methods=["POST"])
    @login_required
    @exempt
    def api_hw_task_cancel(task_id):
        conn = get_db()
        conn.execute("UPDATE hw_tasks SET status='cancelled',finished_ts=? WHERE id=? AND status='running'",
                     (datetime.datetime.now().isoformat(), task_id))
        conn.commit(); conn.close()
        return jsonify({"ok": True})

    @app.route("/api/hw/tasks/<task_id>/delete", methods=["POST"])
    @login_required
    @exempt
    def api_hw_task_delete(task_id):
        conn = get_db()
        conn.execute("DELETE FROM hw_tasks WHERE id=?", (task_id,))
        conn.commit(); conn.close()
        return jsonify({"ok": True})

    @app.route("/api/hw/tasks/clear", methods=["POST"])
    @login_required
    @exempt
    def api_hw_tasks_clear():
        conn = get_db()
        conn.execute("DELETE FROM hw_tasks WHERE status != 'running'")
        conn.commit(); conn.close()
        return jsonify({"ok": True})

    # ── Server Management ──

    @app.route("/api/hw/servers", methods=["GET", "POST"])
    @login_required
    @exempt
    def api_hw_servers():
        if request.method == "POST":
            d = request.json
            conn = get_db()
            conn.execute("INSERT INTO hw_servers (name,ip,ssh_port,ssh_user,ssh_pass) VALUES (?,?,?,?,?)",
                         (d["name"], d["ip"], d.get("port", 22), d.get("user", "root"), d.get("password", "")))
            conn.commit(); conn.close()
            return jsonify({"ok": True})
        conn = get_db()
        rows = [dict(r) for r in conn.execute(
            "SELECT id,name,ip,ssh_port,ssh_user,enabled FROM hw_servers").fetchall()]
        conn.close()
        return jsonify(rows)

    @app.route("/api/hw/servers/<int:sid>", methods=["DELETE"])
    @login_required
    @exempt
    def api_hw_del_server(sid):
        conn = get_db()
        conn.execute("UPDATE hw_servers SET enabled=0 WHERE id=?", (sid,))
        conn.commit(); conn.close()
        return jsonify({"ok": True})
