"""
home_widgets.py — Data helpers for the FleetPilot home dashboard.

Keeps the "Fan & Cooling" widget's local sensor reading and the quick-stat
trend/sparkline bookkeeping in one small, self-contained module instead of
growing app.py further. Everything here degrades gracefully to an honest
"no data yet" state rather than ever inventing numbers.
"""
import json
import os
import subprocess
from datetime import datetime, timedelta

# ── Local temperature / fan sensors ─────────────────────────────────────────

def _classify_temp(celsius):
    """Map a temperature reading to a (css_class, label) pair.

    css_class matches the existing .temp-chip-v4 tiers (cool/warm/hot/crit).
    """
    if celsius is None:
        return None, None
    if celsius < 60:
        return 'cool', 'Normal'
    if celsius < 75:
        return 'warm', 'Elevated'
    if celsius < 85:
        return 'hot', 'High'
    return 'crit', 'Critical'


def _read_gpu_temp():
    """Best-effort NVIDIA GPU temperature via nvidia-smi. None if unavailable."""
    try:
        out = subprocess.run(
            ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=2
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def get_local_sensors():
    """
    Read local CPU / GPU / NVMe temperatures and fan RPMs from the machine
    FleetPilot itself runs on (via psutil, plus a best-effort nvidia-smi
    probe for GPU temp since psutil has no GPU support).

    Returns:
        {
          'available': bool,
          'temps': [{'label','value','unit','css_class','status'}, ...],
          'fans':  [{'label','rpm','status'}, ...],
        }

    Never fabricates a reading — a chip/row only appears when a real
    sensor value was found. Fine (and expected) to come back empty on
    VMs/containers/cloud hosts with no exposed hwmon sensors.
    """
    temps = []
    fans = []

    try:
        import psutil
    except ImportError:
        return {'available': False, 'temps': [], 'fans': []}

    # ── Temperatures ──
    cpu_val = None
    nvme_val = None
    try:
        raw = psutil.sensors_temperatures() if hasattr(psutil, 'sensors_temperatures') else {}
    except Exception:
        raw = {}
    for chip, entries in (raw or {}).items():
        chip_l = (chip or '').lower()
        for e in entries:
            val = getattr(e, 'current', None)
            if val is None:
                continue
            if cpu_val is None and any(k in chip_l for k in ('coretemp', 'k10temp', 'cpu', 'zenpower')):
                cpu_val = val
            elif nvme_val is None and 'nvme' in chip_l:
                nvme_val = val

    gpu_val = _read_gpu_temp()

    for label, val in (('CPU', cpu_val), ('GPU', gpu_val), ('NVMe', nvme_val)):
        if val is None:
            continue
        css_class, status = _classify_temp(val)
        temps.append({
            'label': label, 'value': round(val), 'unit': '\u00b0C',
            'css_class': css_class, 'status': status,
        })

    # ── Fans ──
    try:
        raw_fans = psutil.sensors_fans() if hasattr(psutil, 'sensors_fans') else {}
    except Exception:
        raw_fans = {}
    for chip, entries in (raw_fans or {}).items():
        for i, e in enumerate(entries):
            rpm = getattr(e, 'current', None)
            if not rpm:
                continue
            label = (getattr(e, 'label', '') or '').strip() or f'{chip} Fan {i + 1}'
            fans.append({'label': label, 'rpm': int(rpm), 'status': 'Normal'})

    return {'available': bool(temps or fans), 'temps': temps, 'fans': fans}


# ── Quick-stat history & sparklines ─────────────────────────────────────────

_HISTORY_FILE = 'dashboard_stats_history.json'
_MAX_SNAPSHOTS = 30


def _history_path(data_dir):
    return os.path.join(data_dir, _HISTORY_FILE)


def _load_history(data_dir):
    try:
        with open(_history_path(data_dir)) as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        pass
    return []


def _save_history(data_dir, snapshots):
    path = _history_path(data_dir)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(snapshots[-_MAX_SNAPSHOTS:], f)
        os.replace(tmp, path)
    except OSError:
        pass


def _record_snapshot(data_dir, values):
    """Append/update today's metric snapshot (idempotent per calendar day)."""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    snapshots = _load_history(data_dir)
    if snapshots and snapshots[-1].get('date') == today:
        snapshots[-1]['values'] = values
    else:
        snapshots.append({'date': today, 'values': values})
    _save_history(data_dir, snapshots)
    return snapshots


def _sparkline_points(series, width=100, height=32, pad=3):
    """Turn a list of numbers into normalized SVG polyline points."""
    if not series:
        return ''
    if len(series) == 1 or max(series) == min(series):
        y = height / 2
        return f'0,{y:.1f} {width},{y:.1f}'
    lo, hi = min(series), max(series)
    span = hi - lo
    n = len(series)
    pts = []
    for i, v in enumerate(series):
        x = (i / (n - 1)) * width
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        pts.append(f'{x:.1f},{y:.1f}')
    return ' '.join(pts)


def get_trends(data_dir, current_values, lookback_days=7):
    """
    Record today's snapshot and compute a trend (direction + % change text
    + sparkline points) for each metric in `current_values`, comparing
    against the oldest snapshot within `lookback_days`.

    Falls back to a flat trend when there isn't enough history yet (e.g.
    right after install) instead of fabricating a percentage — the trend
    line becomes meaningful as the app accumulates real daily snapshots.
    """
    snapshots = _record_snapshot(data_dir, current_values)
    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    window = [s for s in snapshots if s.get('date', '') >= cutoff] or snapshots[-1:]

    trends = {}
    for key, current in current_values.items():
        series = [s.get('values', {}).get(key, current) for s in window]
        baseline = series[0]
        if len(series) < 2 or baseline == current:
            direction, pct_text = 'flat', '0%'
        elif baseline == 0:
            direction, pct_text = 'up', 'new'
        else:
            pct = round(abs(current - baseline) / baseline * 100)
            direction = 'up' if current > baseline else 'down'
            pct_text = f'{pct}%'
        trends[key] = {
            'value': current,
            'direction': direction,
            'pct_text': pct_text,
            'sparkline': _sparkline_points(series),
        }
    return trends
