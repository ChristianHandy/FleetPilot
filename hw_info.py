"""
hw_info.py — Hardware Overview Module for FleetPilot

Collects detailed hardware information from remote servers via SSH,
inspired by fastfetch. Detects NVIDIA and AMD GPUs automatically,
along with CPU, RAM, Mainboard, Network, Disks, OS, and more.

Usage:
    from hw_info import HwInfoCollector
    collector = HwInfoCollector(data_dir)
    info = collector.collect(host, port, user, password, ssh_key)
"""

import sqlite3
import json
import os
import threading
import logging
import re
from datetime import datetime
from typing import Optional, Dict, List, Any
import paramiko

logger = logging.getLogger(__name__)

# ── Collection Script (runs on remote host) ──────────────────────────────────

_COLLECT_SCRIPT = r"""
import subprocess, json, os, re, platform

def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ''

def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ''

info = {}

# ── OS ────────────────────────────────────────────────────────────────────────
os_name = run('cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d \'"\'')
if not os_name:
    os_name = platform.system() + ' ' + platform.release()
info['os'] = os_name
info['kernel'] = run('uname -r')
info['hostname'] = run('hostname -f') or run('hostname')
info['uptime'] = run("awk '{d=int($1/86400);h=int(($1%86400)/3600);m=int(($1%3600)/60); printf \"%dd %dh %dm\",d,h,m}' /proc/uptime")
info['arch'] = run('uname -m')

# ── CPU ───────────────────────────────────────────────────────────────────────
cpu_model = run("grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2").strip()
cpu_cores = run("nproc --all")
cpu_threads = run("grep -c processor /proc/cpuinfo")
cpu_freq = run("grep 'cpu MHz' /proc/cpuinfo | head -1 | awk '{printf \"%.0f\", $4}'")
cpu_max_freq = run("cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq 2>/dev/null")
if cpu_max_freq:
    cpu_max_freq = str(int(cpu_max_freq) // 1000)
cpu_temp = ''
# Try multiple temperature sources
for src in [
    "sensors 2>/dev/null | grep -E 'Tdie|Tctl|Package|Core 0' | head -1 | awk '{print $2}' | tr -d '+°C'",
    "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null",
]:
    t = run(src)
    if t:
        try:
            val = float(t)
            if val > 1000:
                val /= 1000
            if 0 < val < 120:
                cpu_temp = f'{val:.1f}'
                break
        except Exception:
            pass
info['cpu'] = {
    'model': cpu_model,
    'cores': cpu_cores,
    'threads': cpu_threads,
    'freq_mhz': cpu_freq,
    'max_freq_mhz': cpu_max_freq,
    'temp_c': cpu_temp,
    'usage_pct': run("top -bn1 | grep 'Cpu(s)' | awk '{print 100-$8}'"),
}

# ── RAM ───────────────────────────────────────────────────────────────────────
mem_total = run("grep MemTotal /proc/meminfo | awk '{print $2}'")
mem_free = run("grep MemAvailable /proc/meminfo | awk '{print $2}'")
swap_total = run("grep SwapTotal /proc/meminfo | awk '{print $2}'")
swap_free = run("grep SwapFree /proc/meminfo | awk '{print $2}'")
try:
    mt = int(mem_total); mf = int(mem_free)
    mem_used = mt - mf
    mem_pct = round(mem_used * 100 / mt, 1) if mt else 0
except Exception:
    mem_used = mem_pct = 0; mt = 0
info['memory'] = {
    'total_kb': mem_total,
    'used_kb': str(mem_used),
    'free_kb': mem_free,
    'used_pct': str(mem_pct),
    'swap_total_kb': swap_total,
    'swap_free_kb': swap_free,
}
# Physical RAM slots (dmidecode)
ram_slots = run("dmidecode -t memory 2>/dev/null | grep -A5 'Memory Device' | grep -E 'Size:|Type:|Speed:|Manufacturer:|Part Number:' | head -40")
info['memory']['slots_raw'] = ram_slots

# ── Mainboard ─────────────────────────────────────────────────────────────────
info['motherboard'] = {
    'manufacturer': run("dmidecode -s baseboard-manufacturer 2>/dev/null"),
    'product': run("dmidecode -s baseboard-product-name 2>/dev/null"),
    'version': run("dmidecode -s baseboard-version 2>/dev/null"),
    'bios_vendor': run("dmidecode -s bios-vendor 2>/dev/null"),
    'bios_version': run("dmidecode -s bios-version 2>/dev/null"),
    'bios_date': run("dmidecode -s bios-release-date 2>/dev/null"),
}

# ── GPU — NVIDIA ──────────────────────────────────────────────────────────────
nvidia_gpus = []
nvidia_out = run("nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,temperature.gpu,utilization.gpu,power.draw,power.limit,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader,nounits 2>/dev/null")
if nvidia_out:
    for line in nvidia_out.strip().split('\n'):
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2:
            nvidia_gpus.append({
                'vendor': 'NVIDIA',
                'name': parts[0] if len(parts) > 0 else '',
                'driver': parts[1] if len(parts) > 1 else '',
                'vram_total_mb': parts[2] if len(parts) > 2 else '',
                'vram_used_mb': parts[3] if len(parts) > 3 else '',
                'temp_c': parts[4] if len(parts) > 4 else '',
                'util_pct': parts[5] if len(parts) > 5 else '',
                'power_w': parts[6] if len(parts) > 6 else '',
                'power_limit_w': parts[7] if len(parts) > 7 else '',
                'pcie_gen': parts[8] if len(parts) > 8 else '',
                'pcie_width': parts[9] if len(parts) > 9 else '',
            })

# ── GPU — AMD ─────────────────────────────────────────────────────────────────
amd_gpus = []
# Try rocm-smi first
rocm_out = run("rocm-smi --showproductname --showtemp --showuse --showmeminfo vram --showpower --json 2>/dev/null")
if rocm_out and '{' in rocm_out:
    try:
        rocm_data = json.loads(rocm_out)
        for card_id, card_data in rocm_data.items():
            if card_id.startswith('card'):
                amd_gpus.append({
                    'vendor': 'AMD',
                    'name': card_data.get('Card Series', card_data.get('Card SKU', 'AMD GPU')),
                    'driver': run("cat /sys/module/amdgpu/version 2>/dev/null"),
                    'vram_total_mb': str(int(card_data.get('VRAM Total Memory (B)', 0)) // 1048576),
                    'vram_used_mb': str(int(card_data.get('VRAM Total Used Memory (B)', 0)) // 1048576),
                    'temp_c': card_data.get('Temperature (Sensor junction) (C)', card_data.get('Temperature (Sensor edge) (C)', '')),
                    'util_pct': card_data.get('GPU use (%)', ''),
                    'power_w': card_data.get('Average Graphics Package Power (W)', ''),
                    'power_limit_w': card_data.get('Max Graphics Package Power (W)', ''),
                    'pcie_gen': '',
                    'pcie_width': '',
                })
    except Exception:
        pass

# Fallback: amdgpu sysfs
if not amd_gpus:
    amd_cards = run("ls /sys/class/drm/ 2>/dev/null | grep '^card[0-9]$'")
    for card in amd_cards.split('\n'):
        card = card.strip()
        if not card:
            continue
        vendor = read(f'/sys/class/drm/{card}/device/vendor')
        if vendor == '0x1002':  # AMD
            name = read(f'/sys/class/drm/{card}/device/product_name') or \
                   run(f"cat /sys/class/drm/{card}/device/uevent 2>/dev/null | grep PCI_ID | cut -d= -f2")
            temp_raw = run(f"cat /sys/class/drm/{card}/device/hwmon/hwmon*/temp1_input 2>/dev/null | head -1")
            temp = ''
            if temp_raw:
                try:
                    temp = str(int(temp_raw) // 1000)
                except Exception:
                    pass
            vram_total = run(f"cat /sys/class/drm/{card}/device/mem_info_vram_total 2>/dev/null")
            vram_used = run(f"cat /sys/class/drm/{card}/device/mem_info_vram_used 2>/dev/null")
            amd_gpus.append({
                'vendor': 'AMD',
                'name': name or f'AMD GPU ({card})',
                'driver': run("cat /sys/module/amdgpu/version 2>/dev/null"),
                'vram_total_mb': str(int(vram_total) // 1048576) if vram_total.isdigit() else '',
                'vram_used_mb': str(int(vram_used) // 1048576) if vram_used.isdigit() else '',
                'temp_c': temp,
                'util_pct': '',
                'power_w': '',
                'power_limit_w': '',
                'pcie_gen': '',
                'pcie_width': '',
            })

# Also check lspci for any GPU
lspci_gpus = run("lspci 2>/dev/null | grep -iE 'VGA|3D|Display|GPU'")
info['gpus'] = nvidia_gpus + amd_gpus
info['gpus_lspci'] = lspci_gpus

# ── Network ───────────────────────────────────────────────────────────────────
nics = []
nic_names = run("ip -o link show | awk -F': ' '{print $2}' | grep -v lo").split('\n')
for nic in nic_names:
    nic = nic.strip().split('@')[0]
    if not nic:
        continue
    mac = read(f'/sys/class/net/{nic}/address')
    speed = read(f'/sys/class/net/{nic}/speed')
    state = read(f'/sys/class/net/{nic}/operstate')
    driver = run(f"ethtool -i {nic} 2>/dev/null | grep driver | awk '{{print $2}}'")
    ips = run(f"ip -4 addr show {nic} 2>/dev/null | grep inet | awk '{{print $2}}'")
    ip6 = run(f"ip -6 addr show {nic} 2>/dev/null | grep 'inet6 ' | grep -v 'fe80' | awk '{{print $2}}' | head -1")
    nics.append({
        'name': nic,
        'mac': mac,
        'speed_mbps': speed,
        'state': state,
        'driver': driver,
        'ipv4': ips,
        'ipv6': ip6,
    })
info['network'] = nics

# ── Storage ───────────────────────────────────────────────────────────────────
disks = []
lsblk_out = run("lsblk -J -o NAME,SIZE,TYPE,MODEL,ROTA,TRAN,VENDOR,REV,SERIAL,MOUNTPOINT 2>/dev/null")
if lsblk_out:
    try:
        lsblk_data = json.loads(lsblk_out)
        for dev in lsblk_data.get('blockdevices', []):
            if dev.get('type') in ('disk', 'nvme'):
                disks.append({
                    'name': dev.get('name', ''),
                    'size': dev.get('size', ''),
                    'model': (dev.get('model') or dev.get('vendor') or '').strip(),
                    'rotational': dev.get('rota') == '1',
                    'transport': dev.get('tran', ''),
                    'serial': dev.get('serial', ''),
                    'type': 'HDD' if dev.get('rota') == '1' else ('NVMe' if 'nvme' in dev.get('name','') else 'SSD'),
                })
    except Exception:
        pass
# Fallback
if not disks:
    df_out = run("df -h --output=source,size,used,avail,pcent,target 2>/dev/null | grep '^/dev'")
    for line in df_out.split('\n'):
        parts = line.split()
        if len(parts) >= 6:
            disks.append({'name': parts[0], 'size': parts[1], 'used': parts[2], 'avail': parts[3], 'pct': parts[4], 'mount': parts[5]})
info['disks'] = disks

# ── PCIe Devices ─────────────────────────────────────────────────────────────
info['pcie_devices'] = run("lspci 2>/dev/null | grep -vE 'USB|PCI bridge|ISA bridge|SMBus|Host bridge|System peripheral' | head -30")

# ── Virtualization ────────────────────────────────────────────────────────────
virt = run("systemd-detect-virt 2>/dev/null") or run("virt-what 2>/dev/null | head -1")
info['virtualization'] = virt or 'bare-metal'

# ── Packages ─────────────────────────────────────────────────────────────────
pkg_count = run("dpkg -l 2>/dev/null | grep -c '^ii'") or run("rpm -qa 2>/dev/null | wc -l")
info['packages'] = pkg_count

# ── Shell / Terminal ─────────────────────────────────────────────────────────
info['shell'] = os.environ.get('SHELL', run('echo $SHELL'))

print(json.dumps(info))
"""


class HwInfoCollector:
    """Collects and caches hardware information from remote servers."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS hw_info (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        server_name TEXT NOT NULL UNIQUE,
        host        TEXT NOT NULL,
        data        TEXT NOT NULL,
        collected_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_hw_info_host ON hw_info(host);
    """

    def __init__(self, data_dir: str):
        self._db_path = os.path.join(data_dir, "hw_info.db")
        self._init_db()
        self._lock = threading.Lock()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()

    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def collect(self, host: str, port: int, user: str,
                password: str = '', ssh_key: str = '',
                server_name: str = '') -> Dict:
        """Collect hardware info from a remote server via SSH."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            connect_kwargs = dict(
                hostname=host, port=port, username=user,
                timeout=15, allow_agent=False, look_for_keys=False
            )
            if ssh_key and os.path.exists(ssh_key):
                connect_kwargs['key_filename'] = ssh_key
            elif password:
                connect_kwargs['password'] = password
            client.connect(**connect_kwargs)

            # Upload and run the collection script
            sftp = client.open_sftp()
            with sftp.open('/tmp/_hw_collect.py', 'w') as f:
                f.write(_COLLECT_SCRIPT)
            sftp.close()

            stdin, stdout, stderr = client.exec_command(
                'python3 /tmp/_hw_collect.py 2>/dev/null', timeout=30
            )
            output = stdout.read().decode(errors='replace').strip()
            client.close()

            if not output:
                return {'error': 'No output from collection script'}

            # Find JSON in output
            json_start = output.find('{')
            if json_start >= 0:
                data = json.loads(output[json_start:])
            else:
                return {'error': 'Invalid output format'}

            data['_collected_at'] = datetime.utcnow().isoformat()
            data['_host'] = host

            # Cache in DB
            name = server_name or host
            with self._lock:
                with self._conn() as conn:
                    conn.execute("""
                        INSERT INTO hw_info (server_name, host, data, collected_at)
                        VALUES (?,?,?,?)
                        ON CONFLICT(server_name) DO UPDATE SET
                            host=excluded.host,
                            data=excluded.data,
                            collected_at=excluded.collected_at
                    """, (name, host, json.dumps(data), data['_collected_at']))
                    conn.commit()

            return data

        except Exception as e:
            logger.error(f"[HwInfo] Collection failed for {host}: {e}")
            return {'error': str(e), '_host': host}
        finally:
            try:
                client.close()
            except Exception:
                pass

    def get_cached(self, server_name: str) -> Optional[Dict]:
        """Get cached hardware info for a server."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM hw_info WHERE server_name=?", (server_name,)
            ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row['data'])
            data['_cached'] = True
            data['_collected_at'] = row['collected_at']
            return data
        except Exception:
            return None

    def list_cached(self) -> List[Dict]:
        """List all cached hardware info entries."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT server_name, host, collected_at FROM hw_info ORDER BY server_name"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_cached(self, server_name: str):
        """Delete cached hardware info for a server."""
        with self._conn() as conn:
            conn.execute("DELETE FROM hw_info WHERE server_name=?", (server_name,))
            conn.commit()


# ── Flask route registration ──────────────────────────────────────────────────

_collector: Optional[HwInfoCollector] = None


def init(data_dir: str):
    global _collector
    _collector = HwInfoCollector(data_dir)
    logger.info("[HwInfo] Initialized")


def register_routes(app, login_required, csrf=None):
    """Register /hw_overview routes on the Flask app."""
    from flask import render_template, request, jsonify, redirect, url_for

    @app.route('/hw_overview')
    @login_required
    def hw_overview():
        if not _collector:
            return "HwInfo not initialized", 503
        cached = _collector.list_cached()
        return render_template('hw_overview/index.html', servers=cached)

    @app.route('/hw_overview/<server_name>')
    @login_required
    def hw_overview_detail(server_name):
        if not _collector:
            return "HwInfo not initialized", 503
        data = _collector.get_cached(server_name)
        return render_template('hw_overview/detail.html',
                                server_name=server_name, hw=data)

    @app.route('/hw_overview/<server_name>/refresh')
    @login_required
    def hw_overview_refresh(server_name):
        if not _collector:
            return jsonify({'error': 'Not initialized'}), 503
        # Get server credentials from registry or hosts.json
        from flask import current_app
        import server_registry as _reg_mod
        reg = _reg_mod.get_registry(current_app.config.get('DATA_DIR', '.'))
        srv = reg.get_server(name=server_name)
        if not srv:
            # Try hosts.json
            import json as _json, os as _os
            data_dir = current_app.config.get('DATA_DIR', '.')
            try:
                with open(_os.path.join(data_dir, 'hosts.json')) as f:
                    hosts = _json.load(f)
                h = hosts.get(server_name, {})
                srv = {'host': h.get('host',''), 'port': h.get('port',22),
                       'user': h.get('user','root'), 'password': '',
                       'ssh_key': h.get('ssh_key','')}
            except Exception:
                return jsonify({'error': 'Server not found'}), 404
        data = _collector.collect(
            host=srv['host'], port=srv.get('port', 22),
            user=srv.get('user', 'root'),
            password=srv.get('password', ''),
            ssh_key=srv.get('ssh_key', ''),
            server_name=server_name
        )
        return jsonify(data)

    @app.route('/api/hw_overview/servers')
    @login_required
    def api_hw_overview_servers():
        if not _collector:
            return jsonify([])
        return jsonify(_collector.list_cached())

    @app.route('/api/hw_overview/<server_name>')
    @login_required
    def api_hw_overview_detail(server_name):
        if not _collector:
            return jsonify({'error': 'Not initialized'}), 503
        data = _collector.get_cached(server_name)
        if not data:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(data)

    logger.info("[HwInfo] Routes registered")
