# HW Monitor — Hardware Stress Test & Live Dashboard

Ein eigenständiges Monitoring- und Stress-Test-Dashboard für Proxmox-Server und andere Linux-Hosts. Läuft als Flask-App in einem LXC-Container und überwacht alle Server per SSH.

## Features

- **Live-Monitoring** — CPU-Temperatur & Auslastung, RAM, Swap, Netzwerk I/O, Disk I/O, GPU-Temperatur, Lüfter-RPM (alle 8 Sekunden)
- **Stress-Tests** — CPU, RAM, Disk und GPU via `stress-ng` und `fio`, läuft bis zum Versagen mit vollständigem Log
- **Fan Control** — PWM-Lüftersteuerung via sysfs, Erkennung aller Kanäle, Schieberegler-UI
- **Setup-Seite** — Prüft und installiert alle Abhängigkeiten per Klick (`stress-ng`, `fio`, `lm-sensors`, `fancontrol`, `i2c-tools`)
- **Fehler-Acknowledge** — Hardware-Fehler quittieren und mit Notiz archivieren
- **Offline-Anzeige** — Bei Serverausfall werden letzte bekannte Temperaturen und Log-Einträge angezeigt
- **Cluster-Redundanz** — Läuft auf zwei LXC-Containern mit HAProxy + Keepalived Virtual IP Failover

## Architektur

```
Benutzer → http://192.168.1.100/ (Virtual IP)
               │
          HAProxy (pve03 + pve02)
               │
    ┌──────────┴──────────┐
    │                     │
  LXC 200 (pve03)      LXC 201 (pve02)
  Flask :5000           Flask :5000
    │                     │
    └──── SSH → pve01/02/03/04 (Metriken sammeln)
```

## Installation

### 1. LXC-Container erstellen (Proxmox)

```bash
# Auf dem Proxmox-Host als root
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname hw-monitor --memory 512 --swap 256 \
  --rootfs local-lvm:4 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1
pct start 200
```

### 2. Abhängigkeiten im LXC installieren

```bash
pct exec 200 -- bash -c "apt-get update && apt-get install -y python3 python3-pip && pip3 install flask paramiko"
```

### 3. App deployen

```bash
pct exec 200 -- mkdir -p /opt/hw-dashboard/templates
pct push 200 app.py /opt/hw-dashboard/app.py
pct push 200 templates/index.html /opt/hw-dashboard/templates/index.html
pct push 200 templates/detail.html /opt/hw-dashboard/templates/detail.html
pct push 200 templates/fans.html /opt/hw-dashboard/templates/fans.html
pct push 200 templates/setup.html /opt/hw-dashboard/templates/setup.html
```

### 4. App starten

```bash
pct exec 200 -- bash -c "cd /opt/hw-dashboard && nohup python3 app.py > /var/log/hw-dashboard.log 2>&1 &"
```

### 5. Stress-Test-Skript auf überwachte Server deployen

```bash
# Auf jedem Server (als root)
mkdir -p /root/hw_stress_test
scp hw_stress_test.py root@192.168.1.52:/root/hw_stress_test.py
```

## Stress-Test starten

```bash
# Über das Dashboard (empfohlen): ▶ Start Button
# Oder manuell auf dem Server:
nohup python3 /root/hw_stress_test.py > /root/hw_stress_test/stress_test.log 2>&1 &

# Bericht nach dem Test:
python3 /root/hw_stress_test.py --report
```

## Konfiguration

Server werden über die Web-UI hinzugefügt (`+ Server` Button) oder direkt in der SQLite-Datenbank (`/data/dashboard.db`).

Standard-Datenbankpfad: `/data/dashboard.db`

## Abhängigkeiten auf überwachten Servern

| Paket | Zweck | Pflicht |
|---|---|---|
| `stress-ng` | CPU/RAM/I/O Stress-Tests | Ja (für Tests) |
| `fio` | Disk I/O Benchmarks | Ja (für Tests) |
| `lm-sensors` | Temperatur-Sensoren | Empfohlen |
| `fancontrol` | PWM-Lüftersteuerung | Optional |
| `i2c-tools` | I2C Hardware-Sensoren | Optional |
| `nvidia-smi` | NVIDIA GPU Monitoring | Optional |

Alle Pakete können über die **Setup-Seite** (`/setup`) per Klick installiert werden.

## Cluster-Failover (optional)

Für Hochverfügbarkeit: HAProxy + Keepalived auf zwei Hosts installieren.

```bash
# Auf beiden Hosts (pve03 + pve02)
apt-get install -y haproxy keepalived
```

HAProxy leitet auf beide LXC-Container weiter. Keepalived verwaltet eine Virtual IP — fällt ein Host aus, übernimmt der andere die IP innerhalb von ~3 Sekunden.
