# FleetPilot User Guide - Outline & Feature Notes

## 1. Introduction & Getting Started
- Was ist FleetPilot? (Zentrales Dashboard für Server, VMs, Storage, Backups, Lüfter).
- Systemanforderungen und Login (Brute-Force-Schutz nach 10 Versuchen).
- UI-Aufbau (Sidebar, Header, Dark Mode).

## 2. Dashboard & Customization
- **Widget-System**: 10 verfügbare Widgets (Stat Grid, Fleet Overview, VM Summary, Storage Summary, SMART Summary, Env Breakdown, Tag Cloud, Recent Updates, Nav Cards, Plugin Widgets).
- **Drag & Drop**: Layout per Drag & Drop anpassen.
- **Widgets ausblenden**: Rotes "X" zum Verstecken, "Hidden Widgets" Panel zum Wiederherstellen.
- **Persistenz**: Speichern des Layouts pro Nutzer (`Save Layout`). Reset auf Standard möglich.

## 3. Host Management
- **Hosts hinzufügen**: IP/Hostname (mit Validierung), Environment, Criticality, SSH-User, Group, Tags.
- **OS Auto-Erkennung**: Neuer "Detect OS" Button liest `/etc/os-release` über SSH und zeigt das Linux-Logo (z.B. Ubuntu, Debian, Proxmox) oder Windows an.
- **Custom Images**: Eigene Server-Bilder hochladen (via "Upload Image" Button in den Host Actions).
- **Filter & Suche**: Suchen nach Name, IP, Tags, Groups.
- **Aktionen**: Edit, Delete, Update, SSH-Test, MAC-Erkennung.

## 4. Update Manager
- **Server Updates**: Updates via SSH (apt update+upgrade). Unterstützt Passwort-Auth und automatische Root-Erkennung (lässt sudo weg, wenn user=root).
- **FleetPilot Self-Update**: Update der FleetPilot-Instanz aus dem GitHub-Repo (inkl. Auto-Stash für untracked Files).
- **Live-Logs**: Echtzeit-Ausgabe der Update-Prozesse via SSE (Server-Sent Events).

## 5. VM Controller (Virtualization)
- **Proxmox VE**: Anbindung via API Token oder Passwort.
- **Retry-Mechanismus**: Automatischer exponentieller Backoff (3 Versuche) bei transienten Netzwerkfehlern.
- **VM Actions**: Start, Stop, Shutdown (jetzt mit CSRF-Token gesichert).
- **Disk Inventory**: Anzeige physischer Disks des Proxmox-Hosts.
- **Veeam Integration**: Job-Starts.

## 6. Storage Controller (NAS & SAN)
- **Unraid Integration**: Nutzt jetzt die **GraphQL API** (ab Unraid 6.12+) via `x-api-key` Header (HTTPS Port 443).
- **TrueNAS / Generic NAS**: Unterstützung für Pools, Volumes, Disks.
- **Disk-Ansicht**: Zeigt alle Array-Disks, Parities und Cache-Laufwerke mit Temperaturen, SMART-Health, Seriennummern und Modellen.

## 7. Disk Management & SMART
- **SMART Dashboard**: Übersicht aller Disks nach Health-Status (Healthy, Warning, Critical).
- **Disk Tools**: SMART-Tests starten, Attribute einsehen, Historie.
- **Auto-Polling**: Hintergrund-Aktualisierung der SMART-Werte.

## 8. Backup Controller (NEU)
- **Unterstützte Systeme**: Proxmox Backup Server (PBS), Duplicati, Restic, BorgWarehouse, UrBackup, Bacula, SSH Generic.
- **Features**: Datastores, Jobs, Snapshots, 24h-History, Quota.
- **Aktionen**: Backup-Jobs direkt aus FleetPilot triggern.
- **Hinzufügen**: Über `/backup/add` mit protokollspezifischen Feldern (API Token, Bearer, Basic Auth, SSH).

## 9. Fan Controller & Cooling (NEU)
- **Universal Fan Controller**: Unterstützt `lm-sensors`, `ipmi`, `nbfc`, `liquidctl`, `pwm_sysfs`.
- **Auto-Detect**: SSH-basierte Erkennung von Controllern (prüft Hardware-Typ und installierte Tools). Priorisierte Vorschlagsliste.
- **Corsair Commander Pro**: Separates Modul für Corsair-Hardware via SSH+liquidctl. Fan-Kurven und Fixed Duty (%).
- **Features**: Temperatur- und RPM-Charts (Chart.js), manuelle Lüftersteuerung, 30s Polling.

## 10. CheckMK Integration
- **Verbindung**: CheckMK URL, Site Name, API Token (Bearer Token Authentifizierung).
- **Features**: Host Status, Service States, Alerts in Echtzeit.

## 11. User Management & Plugins
- **Benutzerverwaltung**: Rollen (Admin, Operator, Viewer), Passwörter, Profile.
- **Plugins**: Plugin-Manager für Erweiterungen.
