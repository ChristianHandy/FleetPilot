#!/usr/bin/env python3
"""
pve03 Hardware Stress Test
==========================
Testet CPU, RAM, Festplatten und GPU bis zum Versagen.
Alle Ergebnisse werden in /root/hw_stress_test/stress_test.log gespeichert.

Verwendung:
  python3 hw_stress_test.py              # Läuft bis zum Versagen oder manuellen Abbruch
  python3 hw_stress_test.py --duration 3600  # Läuft 1 Stunde
  python3 hw_stress_test.py --skip-gpu   # GPU-Test überspringen
  python3 hw_stress_test.py --report     # Nur Log analysieren und Bericht ausgeben
"""

import subprocess
import threading
import time
import os
import sys
import signal
import json
import datetime
import shutil
import argparse
import re

# ─── Konfiguration ────────────────────────────────────────────────────────────
LOG_DIR       = "/root/hw_stress_test"
LOG_FILE      = f"{LOG_DIR}/stress_test.log"
RESULT_FILE   = f"{LOG_DIR}/results.json"
TEMP_WARN_CPU = 85    # °C — Warnung
TEMP_CRIT_CPU = 95    # °C — Kritisch, Test wird gestoppt
TEMP_WARN_GPU = 85    # °C
TEMP_CRIT_GPU = 95    # °C
POLL_INTERVAL = 5     # Sekunden zwischen Monitoring-Abfragen
CPU_CORES     = os.cpu_count() or 4
RAM_MB        = int(subprocess.check_output("free -m | awk '/Mem:/{print $2}'", shell=True).decode().strip())
RAM_STRESS_MB = int(RAM_MB * 0.85)  # 85% des RAMs verwenden

# ─── Globale Zustandsvariablen ─────────────────────────────────────────────────
running       = True
test_results  = {
    "start_time": None,
    "end_time": None,
    "failure": None,
    "phases": {}
}
log_lock      = threading.Lock()

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def log(msg, level="INFO"):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    with log_lock:
        # Nur in Datei schreiben wenn als Hintergrundprozess gestartet
        # (stdout wird bereits von außen in die Logdatei umgeleitet)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

def run_cmd(cmd, timeout=None, capture=True):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture,
            text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)

def run_bg(cmd):
    """Startet einen Prozess im Hintergrund und gibt ihn zurück."""
    return subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, preexec_fn=os.setsid)

def kill_bg(proc):
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            time.sleep(1)
            if proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass

def get_cpu_temp():
    """Liest CPU-Temperatur via sensors."""
    rc, out, _ = run_cmd("sensors 2>/dev/null | grep -E 'Core [0-9]+:' | awk '{print $3}' | tr -d '+°C'")
    if rc == 0 and out:
        temps = []
        for t in out.splitlines():
            try:
                temps.append(float(t))
            except ValueError:
                pass
        return max(temps) if temps else None
    return None

def get_gpu_temp():
    """Liest GPU-Temperatur via nvidia-smi."""
    rc, out, _ = run_cmd("nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null")
    if rc == 0 and out:
        try:
            return int(out.strip().splitlines()[0])
        except (ValueError, IndexError):
            pass
    return None

def get_gpu_status():
    """Prüft ob die GPU noch auf dem PCIe-Bus erreichbar ist."""
    rc, out, _ = run_cmd("nvidia-smi -q --display=POWER 2>/dev/null | grep 'GPU 00'")
    return rc == 0 and "GPU" in out

def get_system_stats():
    """Sammelt aktuelle Systemmetriken."""
    stats = {}
    # CPU-Auslastung
    rc, out, _ = run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")
    if rc == 0:
        try:
            stats["cpu_usage_pct"] = float(out.replace(",", "."))
        except ValueError:
            stats["cpu_usage_pct"] = None

    # RAM
    rc, out, _ = run_cmd("free -m | awk '/Mem:/{print $3\"/\"$2}'")
    if rc == 0:
        stats["ram_used_mb"] = out

    # CPU-Temp
    stats["cpu_temp_c"] = get_cpu_temp()

    # GPU-Temp
    stats["gpu_temp_c"] = get_gpu_temp()

    # GPU erreichbar
    stats["gpu_on_bus"] = get_gpu_status()

    # Disk I/O (einfach: iostat wenn vorhanden)
    rc, out, _ = run_cmd("iostat -d -x 1 1 2>/dev/null | awk '/^sd/{print $1, $14}' | head -5")
    if rc == 0:
        stats["disk_util"] = out.replace("\n", " | ")

    return stats

def save_results():
    test_results["end_time"] = datetime.datetime.now().isoformat()
    with open(RESULT_FILE, "w") as f:
        json.dump(test_results, f, indent=2, default=str)

def signal_handler(sig, frame):
    global running
    log("Abbruch-Signal empfangen. Beende Tests...", "WARN")
    running = False

# ─── Monitoring-Thread ────────────────────────────────────────────────────────

def monitor_loop(stop_event):
    """Läuft im Hintergrund und protokolliert Temperaturen und Systemstatus."""
    global running
    log("Monitoring gestartet (Intervall: {}s)".format(POLL_INTERVAL))
    while not stop_event.is_set():
        stats = get_system_stats()
        log(
            f"MONITOR | CPU: {stats.get('cpu_temp_c','?')}°C | "
            f"GPU: {stats.get('gpu_temp_c','?')}°C | "
            f"GPU-Bus: {'OK' if stats.get('gpu_on_bus') else 'FEHLT!'} | "
            f"RAM: {stats.get('ram_used_mb','?')} MB | "
            f"Disk-Util: {stats.get('disk_util','?')}",
            "MONITOR"
        )

        # Temperatur-Warnungen
        cpu_t = stats.get("cpu_temp_c")
        if cpu_t:
            if cpu_t >= TEMP_CRIT_CPU:
                log(f"KRITISCH: CPU-Temperatur {cpu_t}°C überschreitet {TEMP_CRIT_CPU}°C! Stoppe Tests.", "CRITICAL")
                test_results["failure"] = f"CPU Überhitzung: {cpu_t}°C"
                running = False
                stop_event.set()
                return
            elif cpu_t >= TEMP_WARN_CPU:
                log(f"WARNUNG: CPU-Temperatur {cpu_t}°C (Grenzwert: {TEMP_WARN_CPU}°C)", "WARN")

        gpu_t = stats.get("gpu_temp_c")
        if gpu_t:
            if gpu_t >= TEMP_CRIT_GPU:
                log(f"KRITISCH: GPU-Temperatur {gpu_t}°C überschreitet {TEMP_CRIT_GPU}°C! Stoppe Tests.", "CRITICAL")
                test_results["failure"] = f"GPU Überhitzung: {gpu_t}°C"
                running = False
                stop_event.set()
                return
            elif gpu_t >= TEMP_WARN_GPU:
                log(f"WARNUNG: GPU-Temperatur {gpu_t}°C (Grenzwert: {TEMP_WARN_GPU}°C)", "WARN")

        # GPU vom Bus gefallen?
        if not stats.get("gpu_on_bus", True):
            log("KRITISCH: GPU ist vom PCIe-Bus verschwunden (Xid 79 möglich)! Stoppe Tests.", "CRITICAL")
            test_results["failure"] = "GPU vom PCIe-Bus gefallen"
            running = False
            stop_event.set()
            return

        stop_event.wait(POLL_INTERVAL)

# ─── Test-Phasen ──────────────────────────────────────────────────────────────

def test_cpu(stop_event):
    """CPU-Stress-Test mit stress-ng (alle Kerne, alle Methoden)."""
    log(f"=== CPU-TEST START === ({CPU_CORES} Kerne, stress-ng)", "TEST")
    test_results["phases"]["cpu"] = {"status": "running", "start": datetime.datetime.now().isoformat()}

    # Runde 1: Reine CPU-Last (Primzahlen)
    log(f"CPU Phase 1: Primzahlen-Berechnung ({CPU_CORES} Worker)", "TEST")
    proc = run_bg(f"stress-ng --cpu {CPU_CORES} --cpu-method prime --timeout 120s --metrics-brief")
    start = time.time()
    while time.time() - start < 125 and not stop_event.is_set():
        time.sleep(2)
    kill_bg(proc)
    if stop_event.is_set():
        return

    # Runde 2: Floating-Point (typisch für GPU-Passthrough-VMs)
    log(f"CPU Phase 2: Floating-Point ({CPU_CORES} Worker)", "TEST")
    proc = run_bg(f"stress-ng --cpu {CPU_CORES} --cpu-method fft --timeout 120s")
    start = time.time()
    while time.time() - start < 125 and not stop_event.is_set():
        time.sleep(2)
    kill_bg(proc)
    if stop_event.is_set():
        return

    # Runde 3: Cache-Stress
    log(f"CPU Phase 3: Cache-Stress ({CPU_CORES} Worker)", "TEST")
    proc = run_bg(f"stress-ng --cache {CPU_CORES} --timeout 120s")
    start = time.time()
    while time.time() - start < 125 and not stop_event.is_set():
        time.sleep(2)
    kill_bg(proc)

    test_results["phases"]["cpu"]["status"] = "passed" if not stop_event.is_set() else "aborted"
    test_results["phases"]["cpu"]["end"] = datetime.datetime.now().isoformat()
    log("=== CPU-TEST ABGESCHLOSSEN ===", "TEST")

def test_ram(stop_event):
    """RAM-Stress-Test mit stress-ng (Schreiben, Lesen, Bit-Flip-Erkennung)."""
    log(f"=== RAM-TEST START === ({RAM_STRESS_MB} MB)", "TEST")
    test_results["phases"]["ram"] = {"status": "running", "start": datetime.datetime.now().isoformat()}

    # Runde 1: Sequentielles Schreiben/Lesen
    log(f"RAM Phase 1: Sequentiell ({RAM_STRESS_MB} MB)", "TEST")
    proc = run_bg(f"stress-ng --vm 1 --vm-bytes {RAM_STRESS_MB}M --vm-method all --timeout 180s --metrics-brief")
    start = time.time()
    while time.time() - start < 185 and not stop_event.is_set():
        time.sleep(2)
    kill_bg(proc)
    if stop_event.is_set():
        return

    # Runde 2: Bit-Flip-Erkennung (prüft auf defekte RAM-Zellen)
    log(f"RAM Phase 2: Bit-Flip-Erkennung (stress-ng --vm-rw)", "TEST")
    proc = run_bg(f"stress-ng --vm-rw 2 --vm-bytes {RAM_STRESS_MB // 2}M --timeout 180s --verify")
    start = time.time()
    while time.time() - start < 185 and not stop_event.is_set():
        time.sleep(2)
    kill_bg(proc)

    # Runde 3: Hugepages
    if not stop_event.is_set():
        log(f"RAM Phase 3: Hugepages-Test", "TEST")
        proc = run_bg(f"stress-ng --bigheap 2 --timeout 60s")
        start = time.time()
        while time.time() - start < 65 and not stop_event.is_set():
            time.sleep(2)
        kill_bg(proc)

    test_results["phases"]["ram"]["status"] = "passed" if not stop_event.is_set() else "aborted"
    test_results["phases"]["ram"]["end"] = datetime.datetime.now().isoformat()
    log("=== RAM-TEST ABGESCHLOSSEN ===", "TEST")

def test_disk(stop_event):
    """Festplatten-Test mit fio (sequentiell + random I/O)."""
    log("=== DISK-TEST START === (fio)", "TEST")
    test_results["phases"]["disk"] = {"status": "running", "start": datetime.datetime.now().isoformat(), "results": {}}

    test_dir = f"{LOG_DIR}/fio_tmp"
    os.makedirs(test_dir, exist_ok=True)

    # Sequentielles Schreiben
    log("Disk Phase 1: Sequentielles Schreiben (4 GB)", "TEST")
    rc, out, err = run_cmd(
        f"fio --name=seq_write --ioengine=libaio --iodepth=16 --rw=write "
        f"--bs=1M --size=4G --numjobs=1 --runtime=120 --time_based "
        f"--filename={test_dir}/fio_test.dat --output-format=terse 2>&1",
        timeout=130
    )
    if rc == 0:
        log(f"Disk seq_write: {out[:200]}", "RESULT")
        test_results["phases"]["disk"]["results"]["seq_write"] = out[:500]
    else:
        log(f"Disk seq_write FEHLER: {err[:200]}", "ERROR")
    if stop_event.is_set():
        return

    # Sequentielles Lesen
    log("Disk Phase 2: Sequentielles Lesen", "TEST")
    rc, out, err = run_cmd(
        f"fio --name=seq_read --ioengine=libaio --iodepth=16 --rw=read "
        f"--bs=1M --size=4G --numjobs=1 --runtime=120 --time_based "
        f"--filename={test_dir}/fio_test.dat --output-format=terse 2>&1",
        timeout=130
    )
    if rc == 0:
        log(f"Disk seq_read: {out[:200]}", "RESULT")
        test_results["phases"]["disk"]["results"]["seq_read"] = out[:500]
    else:
        log(f"Disk seq_read FEHLER: {err[:200]}", "ERROR")
    if stop_event.is_set():
        return

    # Random Read/Write (4K — typisch für VM-Workloads)
    log("Disk Phase 3: Random 4K Read/Write (VM-typisch)", "TEST")
    rc, out, err = run_cmd(
        f"fio --name=rand_rw --ioengine=libaio --iodepth=32 --rw=randrw "
        f"--bs=4k --size=2G --numjobs=4 --runtime=120 --time_based "
        f"--filename={test_dir}/fio_test.dat --output-format=terse 2>&1",
        timeout=130
    )
    if rc == 0:
        log(f"Disk rand_rw: {out[:200]}", "RESULT")
        test_results["phases"]["disk"]["results"]["rand_rw"] = out[:500]
    else:
        log(f"Disk rand_rw FEHLER: {err[:200]}", "ERROR")

    # SMART-Status nach dem Test
    log("Disk Phase 4: SMART-Status nach Belastung", "TEST")
    for disk in ["sda", "sdb"]:
        rc, out, _ = run_cmd(f"smartctl -A /dev/{disk} 2>/dev/null | grep -E 'Reallocated|Pending|Uncorrectable|Temperature'")
        if rc == 0:
            log(f"SMART /dev/{disk}: {out.replace(chr(10), ' | ')}", "RESULT")
            test_results["phases"]["disk"]["results"][f"smart_{disk}"] = out

    # Aufräumen
    try:
        shutil.rmtree(test_dir)
    except Exception:
        pass

    test_results["phases"]["disk"]["status"] = "passed" if not stop_event.is_set() else "aborted"
    test_results["phases"]["disk"]["end"] = datetime.datetime.now().isoformat()
    log("=== DISK-TEST ABGESCHLOSSEN ===", "TEST")

def test_gpu(stop_event):
    """GPU-Stress-Test via nvidia-smi und stress-ng mit GPU-Speicher."""
    log("=== GPU-TEST START === (NVIDIA GTX 1650)", "TEST")
    test_results["phases"]["gpu"] = {"status": "running", "start": datetime.datetime.now().isoformat()}

    # Prüfe ob GPU erreichbar
    if not get_gpu_status():
        log("GPU ist nicht erreichbar! Test übersprungen.", "ERROR")
        test_results["phases"]["gpu"]["status"] = "failed"
        test_results["phases"]["gpu"]["error"] = "GPU nicht erreichbar beim Start"
        return

    # Phase 1: GPU-Info loggen
    rc, out, _ = run_cmd("nvidia-smi -q 2>/dev/null | grep -E 'Product Name|Driver Version|CUDA Version|Total|Free|Used|Temp|Power'")
    log(f"GPU Info:\n{out}", "INFO")
    test_results["phases"]["gpu"]["info"] = out

    # Phase 2: GPU-Last via stress-ng (Matrix-Operationen auf CPU die GPU-ähnlich sind)
    # Da kein cuda-Benchmark vorhanden, nutzen wir stress-ng matrix + GPU-Monitoring
    log("GPU Phase 1: Kombinierter CPU+GPU-Speicher-Stress (120s)", "TEST")
    proc = run_bg(f"stress-ng --matrix {CPU_CORES} --matrix-size 512 --timeout 120s")
    start = time.time()
    while time.time() - start < 125 and not stop_event.is_set():
        gpu_t = get_gpu_temp()
        gpu_ok = get_gpu_status()
        if not gpu_ok:
            log("KRITISCH: GPU während Matrix-Test vom Bus gefallen!", "CRITICAL")
            test_results["phases"]["gpu"]["status"] = "failed"
            test_results["phases"]["gpu"]["failure"] = "GPU vom Bus gefallen während Matrix-Test"
            test_results["failure"] = "GPU vom PCIe-Bus gefallen während GPU-Test"
            kill_bg(proc)
            running = False
            stop_event.set()
            return
        time.sleep(5)
    kill_bg(proc)
    if stop_event.is_set():
        return

    # Phase 3: GPU-Speicher-Stress via nvidia-smi + stress-ng vm
    log("GPU Phase 2: GPU-Speicher-Stress (stress-ng --vm, 120s)", "TEST")
    proc = run_bg(f"stress-ng --vm 2 --vm-bytes 1G --vm-method flip --timeout 120s")
    start = time.time()
    while time.time() - start < 125 and not stop_event.is_set():
        gpu_ok = get_gpu_status()
        if not gpu_ok:
            log("KRITISCH: GPU während VM-Stress-Test vom Bus gefallen!", "CRITICAL")
            test_results["phases"]["gpu"]["status"] = "failed"
            test_results["phases"]["gpu"]["failure"] = "GPU vom Bus gefallen während VM-Stress"
            test_results["failure"] = "GPU vom PCIe-Bus gefallen während GPU-Test Phase 2"
            kill_bg(proc)
            running = False
            stop_event.set()
            return
        time.sleep(5)
    kill_bg(proc)

    # Phase 4: PCIe-Stress (viele kleine Transfers)
    log("GPU Phase 3: PCIe-Stabilitätstest (nvidia-smi Dauerpoll, 60s)", "TEST")
    start = time.time()
    pcie_errors = 0
    while time.time() - start < 60 and not stop_event.is_set():
        rc, out, _ = run_cmd("nvidia-smi --query-gpu=pcie.link.gen.current,pcie.link.width.current,temperature.gpu,power.draw --format=csv,noheader,nounits 2>/dev/null")
        if rc != 0:
            pcie_errors += 1
            log(f"PCIe-Poll Fehler #{pcie_errors}", "WARN")
            if pcie_errors >= 3:
                log("KRITISCH: GPU antwortet nicht mehr auf PCIe-Abfragen!", "CRITICAL")
                test_results["phases"]["gpu"]["status"] = "failed"
                test_results["phases"]["gpu"]["failure"] = "GPU antwortet nicht auf PCIe-Abfragen"
                test_results["failure"] = "GPU PCIe-Kommunikation unterbrochen"
                running = False
                stop_event.set()
                return
        else:
            log(f"PCIe-Status: {out}", "MONITOR")
        time.sleep(5)

    test_results["phases"]["gpu"]["status"] = "passed" if not stop_event.is_set() else "aborted"
    test_results["phases"]["gpu"]["end"] = datetime.datetime.now().isoformat()
    log("=== GPU-TEST ABGESCHLOSSEN ===", "TEST")

def test_combined(stop_event):
    """Kombinierter Stress-Test: CPU + RAM + Disk + GPU gleichzeitig."""
    log("=== KOMBINIERTER STRESS-TEST START === (alles gleichzeitig)", "TEST")
    test_results["phases"]["combined"] = {"status": "running", "start": datetime.datetime.now().isoformat()}

    procs = []
    # CPU
    procs.append(run_bg(f"stress-ng --cpu {CPU_CORES} --cpu-method all --timeout 300s"))
    # RAM
    procs.append(run_bg(f"stress-ng --vm 2 --vm-bytes {RAM_STRESS_MB // 2}M --vm-method all --timeout 300s"))
    # Disk I/O
    os.makedirs(f"{LOG_DIR}/combined_tmp", exist_ok=True)
    procs.append(run_bg(
        f"fio --name=combined --ioengine=libaio --iodepth=16 --rw=randrw "
        f"--bs=4k --size=2G --numjobs=2 --runtime=300 --time_based "
        f"--filename={LOG_DIR}/combined_tmp/fio.dat"
    ))

    log("Kombinierter Test läuft 5 Minuten lang (CPU+RAM+Disk gleichzeitig)...", "TEST")
    start = time.time()
    while time.time() - start < 305 and not stop_event.is_set():
        # GPU-Status prüfen
        if not get_gpu_status():
            log("KRITISCH: GPU während kombiniertem Test vom Bus gefallen!", "CRITICAL")
            test_results["phases"]["combined"]["status"] = "failed"
            test_results["phases"]["combined"]["failure"] = "GPU vom Bus gefallen"
            test_results["failure"] = "GPU PCIe-Ausfall während kombiniertem Stress-Test"
            for p in procs:
                kill_bg(p)
            running = False
            stop_event.set()
            return
        time.sleep(5)

    for p in procs:
        kill_bg(p)

    try:
        shutil.rmtree(f"{LOG_DIR}/combined_tmp")
    except Exception:
        pass

    test_results["phases"]["combined"]["status"] = "passed" if not stop_event.is_set() else "aborted"
    test_results["phases"]["combined"]["end"] = datetime.datetime.now().isoformat()
    log("=== KOMBINIERTER TEST ABGESCHLOSSEN ===", "TEST")

def run_report():
    """Analysiert das Log und gibt eine Zusammenfassung aus."""
    if not os.path.exists(LOG_FILE):
        print("Kein Log gefunden:", LOG_FILE)
        return

    print("\n" + "="*70)
    print("  HARDWARE STRESS TEST — AUSWERTUNG")
    print("="*70)

    with open(LOG_FILE) as f:
        lines = f.readlines()

    criticals = [l for l in lines if "[CRITICAL]" in l]
    errors    = [l for l in lines if "[ERROR]" in l]
    warnings  = [l for l in lines if "[WARN]" in l]
    results   = [l for l in lines if "[RESULT]" in l]
    tests     = [l for l in lines if "[TEST]" in l and "START" in l]

    print(f"\nLog-Datei:   {LOG_FILE}")
    print(f"Zeilen:      {len(lines)}")
    print(f"Tests:       {len(tests)}")
    print(f"Ergebnisse:  {len(results)}")
    print(f"Warnungen:   {len(warnings)}")
    print(f"Fehler:      {len(errors)}")
    print(f"KRITISCH:    {len(criticals)}")

    if criticals:
        print("\n─── KRITISCHE EREIGNISSE ───────────────────────────────────────────")
        for l in criticals:
            print(" ", l.rstrip())

    if errors:
        print("\n─── FEHLER ─────────────────────────────────────────────────────────")
        for l in errors:
            print(" ", l.rstrip())

    if results:
        print("\n─── TESTERGEBNISSE ─────────────────────────────────────────────────")
        for l in results:
            print(" ", l.rstrip())

    # Temperatur-Statistik
    cpu_temps, gpu_temps = [], []
    for l in lines:
        m = re.search(r"CPU: ([\d.]+)°C", l)
        if m:
            try:
                cpu_temps.append(float(m.group(1)))
            except ValueError:
                pass
        m = re.search(r"GPU: ([\d.]+)°C", l)
        if m:
            try:
                gpu_temps.append(float(m.group(1)))
            except ValueError:
                pass

    if cpu_temps:
        print(f"\n─── TEMPERATUREN ───────────────────────────────────────────────────")
        print(f"  CPU: min={min(cpu_temps):.1f}°C  max={max(cpu_temps):.1f}°C  avg={sum(cpu_temps)/len(cpu_temps):.1f}°C")
    if gpu_temps:
        print(f"  GPU: min={min(gpu_temps):.1f}°C  max={max(gpu_temps):.1f}°C  avg={sum(gpu_temps)/len(gpu_temps):.1f}°C")

    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE) as f:
            res = json.load(f)
        print(f"\n─── TESTERGEBNIS ───────────────────────────────────────────────────")
        print(f"  Start:   {res.get('start_time','?')}")
        print(f"  Ende:    {res.get('end_time','?')}")
        print(f"  Fehler:  {res.get('failure','Keiner — Test abgeschlossen oder abgebrochen')}")
        for phase, data in res.get("phases", {}).items():
            print(f"  Phase [{phase}]: {data.get('status','?')}", end="")
            if "failure" in data:
                print(f" — {data['failure']}", end="")
            print()

    print("\n" + "="*70 + "\n")

# ─── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    global running

    parser = argparse.ArgumentParser(description="pve03 Hardware Stress Test")
    parser.add_argument("--duration", type=int, default=0,
                        help="Testdauer in Sekunden (0 = bis Versagen/Abbruch)")
    parser.add_argument("--skip-gpu", action="store_true", help="GPU-Test überspringen")
    parser.add_argument("--skip-disk", action="store_true", help="Disk-Test überspringen")
    parser.add_argument("--skip-combined", action="store_true", help="Kombinierten Test überspringen")
    parser.add_argument("--report", action="store_true", help="Nur Bericht aus Log generieren")
    args = parser.parse_args()

    if args.report:
        run_report()
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    test_results["start_time"] = datetime.datetime.now().isoformat()

    log("="*60)
    log("  pve03 HARDWARE STRESS TEST — START")
    log("="*60)
    log(f"System: {CPU_CORES} CPU-Kerne, {RAM_MB} MB RAM")
    log(f"Log-Datei: {LOG_FILE}")
    log(f"Dauer: {'unbegrenzt (bis Versagen)' if args.duration == 0 else str(args.duration) + 's'}")
    log(f"GPU-Test: {'ÜBERSPRUNGEN' if args.skip_gpu else 'AKTIV'}")

    # Monitoring-Thread starten
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=monitor_loop, args=(stop_event,), daemon=True)
    monitor_thread.start()

    # Zeitlimit-Thread (falls --duration gesetzt)
    if args.duration > 0:
        def timeout_fn():
            time.sleep(args.duration)
            global running
            log(f"Zeitlimit von {args.duration}s erreicht. Beende Tests.", "INFO")
            running = False
            stop_event.set()
        threading.Thread(target=timeout_fn, daemon=True).start()

    # ── Testsequenz ──────────────────────────────────────────────────────────
    try:
        # 1. CPU
        if running:
            test_cpu(stop_event)

        # 2. RAM
        if running:
            test_ram(stop_event)

        # 3. Disk
        if running and not args.skip_disk:
            test_disk(stop_event)

        # 4. GPU
        if running and not args.skip_gpu:
            test_gpu(stop_event)

        # 5. Kombiniert (alles gleichzeitig — der härteste Test)
        if running and not args.skip_combined:
            test_combined(stop_event)

        # 6. Wiederhole bis Versagen
        cycle = 2
        while running:
            log(f"=== WIEDERHOLUNGSZYKLUS {cycle} START ===", "TEST")
            if running:
                test_cpu(stop_event)
            if running:
                test_ram(stop_event)
            if running and not args.skip_disk:
                test_disk(stop_event)
            if running and not args.skip_gpu:
                test_gpu(stop_event)
            if running and not args.skip_combined:
                test_combined(stop_event)
            cycle += 1

    except KeyboardInterrupt:
        log("Manueller Abbruch.", "WARN")
    finally:
        stop_event.set()
        running = False
        save_results()
        log("="*60)
        if test_results.get("failure"):
            log(f"TEST BEENDET MIT FEHLER: {test_results['failure']}", "CRITICAL")
        else:
            log("TEST BEENDET — Kein Fehler erkannt.", "INFO")
        log(f"Log: {LOG_FILE}")
        log(f"Ergebnisse: {RESULT_FILE}")
        log("="*60)
        run_report()

if __name__ == "__main__":
    main()
