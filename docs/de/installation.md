# FleetPilot installieren

Diese Anleitung beschreibt alle Wege, FleetPilot zu installieren, was der Installer einrichtet, die erste Anmeldung, HTTPS, Updates, Sicherungen, die Deinstallation und die Fehlersuche.

*English: [../installation.md](../installation.md)*

**Inhalt**

1. [Installationsweg wählen](#1-installationsweg-wählen)
2. [Proxmox VE: ein Befehl (empfohlen)](#2-proxmox-ve-ein-befehl-empfohlen)
3. [Debian, Ubuntu oder Raspberry Pi OS](#3-debian-ubuntu-oder-raspberry-pi-os)
4. [Erste Anmeldung](#4-erste-anmeldung)
5. [FleetPilot Zugriff auf Ihre Server geben](#5-fleetpilot-zugriff-auf-ihre-server-geben)
6. [HTTPS und eigenes Zertifikat](#6-https-und-eigenes-zertifikat)
7. [Aktualisieren](#7-aktualisieren)
8. [Sichern und Wiederherstellen](#8-sichern-und-wiederherstellen)
9. [Einstellungen (`.env`)](#9-einstellungen-env)
10. [Hochsicherheitsumgebungen](#10-hochsicherheitsumgebungen)
11. [Deinstallieren](#11-deinstallieren)
12. [Fehlersuche](#12-fehlersuche)

---

## 1. Installationsweg wählen

| Sie haben | Verwenden Sie | Dauer |
|---|---|---|
| Einen Proxmox-VE-Server | Das [Proxmox-Hilfsskript](#2-proxmox-ve-ein-befehl-empfohlen): Es legt einen Container an und installiert FleetPilot darin | etwa 4 Minuten |
| Einen Debian-/Ubuntu-Server, eine VM oder einen Container | [`install.sh`](#3-debian-ubuntu-oder-raspberry-pi-os) | etwa 3 Minuten |
| Einen Raspberry Pi (3, 4 oder 5) | [`install.sh`](#3-debian-ubuntu-oder-raspberry-pi-os); installiert zusätzlich die Lüfter- und USB-Werkzeuge | etwa 5 Minuten |

**Voraussetzungen**

- Debian 12 oder 13, Ubuntu 22.04 oder 24.04 oder Raspberry Pi OS (Bookworm oder Trixie), möglichst 64 Bit.
- Mindestens 1 CPU-Kern, 1 GB RAM und 4 GB Speicher; empfohlen sind 2 Kerne, 2 GB RAM und 8 GB (diese Werte nutzt das Proxmox-Skript).
- Internetzugang während der Installation (GitHub und der Python-Paketindex).
- Root-Zugang.

FleetPilot verwaltet andere Rechner über SSH und muss deshalb nicht auf den verwalteten Rechnern laufen.

---

## 2. Proxmox VE: ein Befehl (empfohlen)

Öffnen Sie die **Shell** Ihres Proxmox-Knotens (Weboberfläche → Knoten → *Shell*) und führen Sie aus:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)"
```

Das Skript stellt eine Frage:

- **Default settings** (Standard): nächste freie Container-ID, 2 Kerne, 2 GB RAM, 8 GB Speicher, DHCP an `vmbr0`, HTTPS an. Der Speicher wird automatisch gewählt.
- **Advanced** (Erweitert): Container-ID, Hostname, Kerne, RAM, Speichergröße, Speicherort, Bridge, VLAN, feste IP-Adresse mit Gateway, SSH-Schlüssel für root im Container sowie HTTPS oder einfaches HTTP selbst festlegen.

Danach:

1. Lädt es die neueste Debian-13-Containervorlage (Debian 12, falls 13 nicht verfügbar ist).
2. Legt einen **unprivilegierten** Container mit *Nesting* an, der beim Booten startet und das Tag `fleetpilot` trägt.
3. Installiert FleetPilot darin mit `install.sh` (was dabei passiert, steht im nächsten Abschnitt).
4. Trägt die Adresse und den Ort der Zugangsdaten in die **Notizen** des Containers in Proxmox ein und zeigt eine Zusammenfassung:

```text
 ✔ FleetPilot is ready in container 114.
  Open:       https://192.168.1.62
  User:       admin
  Password:   (einmal angezeigt; auch in /root/fleetpilot-credentials.txt im Container)
```

Das Passwort wird bei der ersten Installation erzeugt, einmal angezeigt und im Container in `/root/fleetpilot-credentials.txt` gespeichert (nur für root lesbar). Später lesen Sie es so:

```bash
pct exec 114 -- cat /root/fleetpilot-credentials.txt
```

### Unbeaufsichtigte Installation

Alle Fragen lassen sich vorab mit Umgebungsvariablen beantworten, zum Beispiel:

```bash
CT_ID=150 CT_HOSTNAME=fleetpilot CT_RAM=4096 CT_IP=192.168.1.50/24 CT_GW=192.168.1.1 FP_DEFAULTS=1 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)"
```

| Variable | Standard | Bedeutung |
|---|---|---|
| `CT_ID` | nächste freie ID | Container-ID |
| `CT_HOSTNAME` | `fleetpilot` | Hostname |
| `CT_CORES` / `CT_RAM` / `CT_DISK` | `2` / `2048` (MB) / `8` (GB) | Ressourcen |
| `CT_STORAGE` | erster Speicher für Container | Speicher für die Root-Disk, z. B. `local-lvm` |
| `CT_TEMPLATE_STORAGE` | erster Speicher für Vorlagen | Ablage der Debian-Vorlage, z. B. `local` |
| `CT_BRIDGE` / `CT_VLAN` | `vmbr0` / keins | Netzwerk-Bridge und optionales VLAN-Tag |
| `CT_IP` / `CT_GW` | `dhcp` / keins | `dhcp` oder eine Adresse wie `192.168.1.50/24` mit Gateway |
| `CT_SSH_KEY` | keiner | Datei mit öffentlichem Schlüssel für root im Container |
| `FP_HTTPS` | `yes` | `no` liefert einfaches HTTP auf Port 5000 |
| `FP_BRANCH` | `main` | Git-Branch oder -Tag |
| `FP_DEFAULTS` | nicht gesetzt | `1` überspringt alle Fragen |

### Den Proxmox-Host selbst verwalten

Ein Container sieht die Festplatten des Hosts nicht. Für SMART-Daten, Updates und Hardware-Informationen des Proxmox-Knotens fügen Sie ihn unter **Hosts verwalten** wie jeden anderen Server hinzu. Das Skript zeigt FleetPilots öffentlichen SSH-Schlüssel und den genauen Befehl, mit dem Sie ihn auf dem Host freigeben.

Für die virtuellen Maschinen und Container des Knotens fügen Sie ihn unter **VM-Controller** hinzu (siehe [Benutzerhandbuch](benutzerhandbuch.md#vm-controller)).

### Container aktualisieren

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/proxmox/fleetpilot-lxc.sh)" -- update 114
```

Ersetzen Sie `114` durch Ihre Container-ID. Daten und Einstellungen bleiben erhalten.

---

## 3. Debian, Ubuntu oder Raspberry Pi OS

Als root auf dem Rechner, auf dem FleetPilot laufen soll:

```bash
curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh | bash
```

Oder aus einer Kopie des Repositorys:

```bash
git clone https://github.com/ChristianHandy/FleetPilot.git
```

```bash
sudo bash FleetPilot/install.sh
```

Die älteren Skripte `install-debian.sh` und `install_raspberry_pi.sh` funktionieren weiterhin; sie starten `install.sh`.

### Was der Installer einrichtet

| Schritt | Einzelheiten |
|---|---|
| Pakete | Python 3, venv, git, OpenSSH-Client, `smartmontools`, `sudo`; für HTTPS nginx und OpenSSL. Auf einem Raspberry Pi zusätzlich `lm-sensors`, `ipmitool` und die USB-HID-Bibliotheken |
| Dienstbenutzer | Ein Systembenutzer `fleetpilot` ohne Passwort und ohne Login-Shell |
| Programm | `/opt/fleetpilot`, gehört root und ist **für den Dienst schreibgeschützt** |
| Daten | `/opt/fleetpilot/data` (Datenbanken, Einstellungen, Sicherungen) und `/opt/fleetpilot/logs`, gehören `fleetpilot`, Rechte 0700/0750 |
| SSH-Schlüssel | Ein neuer Ed25519-Schlüssel in `/opt/fleetpilot/.ssh/id_ed25519`, mit dem FleetPilot Ihre Server erreicht |
| Root-Helfer | Drei kleine root-eigene Helfer in `/usr/local/lib/fleetpilot` (Festplattenaktionen, FleetPilot-Update, Proxy übernehmen). Eine einzige sudo-Regel erlaubt genau diese mit festen Argumenten, sonst nichts |
| Einstellungen | `/opt/fleetpilot/.env` (root:fleetpilot, 0640) mit zufälligem `SECRET_KEY`. Vorhandene Werte werden nie überschrieben |
| Dienst | `fleetpilot.service` (gunicorn), startet beim Booten, mit systemd-Sandbox |
| HTTPS | nginx auf Port 443 mit selbstsigniertem Zertifikat in `/etc/fleetpilot/tls`; FleetPilot selbst hört nur auf `127.0.0.1:5000` |
| Prüfung | Wartet, bis `/healthz` antwortet, zeigt dann Adresse und Zugangsdaten und speichert sie in `/root/fleetpilot-credentials.txt` |

Ein erneuter Aufruf des Installers **aktualisiert** die Installation und behält Daten und Einstellungen.

### Optionen

| Variable | Standard | Bedeutung |
|---|---|---|
| `FP_NONINTERACTIVE` | `0` | `1` stellt keine Fragen |
| `FP_HTTPS` | `yes` | `no` liefert `http://<ip>:5000` direkt ohne nginx (nur für vertrauenswürdige Netze) |
| `FP_ADMIN_PASSWORD` | erzeugt | Passwort des ersten Administratorkontos (mindestens 12 Zeichen) |
| `FP_EXTRAS` | `yes` auf einem Pi, sonst `no` | Lüfter-, IPMI- und USB-HID-Werkzeuge |
| `FP_BRANCH` | `main` | Branch oder Tag |
| `FP_REPO` | GitHub-URL | Quell-Repository (für Forks oder Spiegel) |

Beispiel:

```bash
curl -fsSL https://raw.githubusercontent.com/ChristianHandy/FleetPilot/main/install.sh | FP_NONINTERACTIVE=1 FP_EXTRAS=yes bash
```

### Raspberry-Pi-Extras

Auf einem Raspberry Pi kann der Installer den Pi zusätzlich als **Proxmox-QDevice** einrichten (eine Entscheidungsstimme für einen Cluster mit zwei Knoten). Antworten Sie bei der Frage mit *yes* und führen Sie danach auf einem Proxmox-Knoten `pvecm qdevice setup <pi-ip>` aus.

### Ports

| Port | Lauscht auf | Zweck |
|---|---|---|
| 443 | allen Adressen | FleetPilot über HTTPS (nginx) |
| 5000 | 127.0.0.1 | FleetPilot selbst (gunicorn); mit HTTPS nicht aus dem Netz erreichbar |
| 8080 | 127.0.0.1 | Einfaches HTTP für ein lokales HAProxy (Proxy-Dienste); nicht aus dem Netz erreichbar |

Port 80 bleibt frei, damit der optionale HAProxy ihn nutzen kann. Öffnen Sie direkt `https://<ip>`.

---

## 4. Erste Anmeldung

1. Öffnen Sie die Adresse, die der Installer angezeigt hat, zum Beispiel `https://192.168.1.62`.
2. Der Browser warnt einmal vor dem selbstsignierten Zertifikat. Akzeptieren Sie es oder [installieren Sie ein eigenes Zertifikat](#6-https-und-eigenes-zertifikat).
3. Melden Sie sich als `admin` mit dem erzeugten Passwort an.
4. Empfohlen direkt danach:
   - **Konto → Mein Profil**: Passwort ändern.
   - **Konto → Anmeldung & Sicherheit**: über den Link die Zwei-Faktor-Anmeldung mit einer Authenticator-App oder einem Sicherheitsschlüssel (YubiKey, Passkey) einrichten. Unter **System → Sicherheitscenter** lässt sich 2FA für alle Administratoren vorschreiben.
   - **System → Sicherheitscenter**: die Prüfungen lesen; bei einer frischen Installation sollten alle grün sein, außer denen, die von Ihren Entscheidungen abhängen (etwa ein vertrauenswürdiges Zertifikat).
   - **Konto → Benutzerverwaltung**: eigene Konten für andere Personen anlegen, statt `admin` zu teilen. Rollen: *admin* (alles), *operator* (Aktionen ausführen), *viewer* (nur lesen).

Administratorpasswort vergessen? Auf dem FleetPilot-Server oder im Container:

```bash
sudo bash /opt/fleetpilot/reset-password.sh
```

Mit `--generate` wird ein zufälliges Passwort erzeugt und angezeigt, `--list` listet die Benutzer, oder geben Sie einen anderen Benutzernamen an. Offene Sitzungen dieses Benutzers werden beendet.

---

## 5. FleetPilot Zugriff auf Ihre Server geben

FleetPilot erreicht Ihre Server über SSH mit einem eigenen Schlüssel. Den öffentlichen Schlüssel zeigen Sie so an:

```bash
cat /opt/fleetpilot/.ssh/id_ed25519.pub
```

Für jeden Server dann entweder:

- **In der Weboberfläche**: *Hosts verwalten → Host hinzufügen*, danach am Host *Install Key* (fragt einmal nach dem Passwort dieses Servers und speichert es nicht), oder
- **Von Hand**: den Schlüssel an `~/.ssh/authorized_keys` des Benutzers anhängen, den FleetPilot auf diesem Server verwenden soll.

Für Updates, Festplattenwerkzeuge und SMART braucht dieser Benutzer root-Rechte oder eine sudo-Regel für den Paketmanager und `smartctl`. Windows-Rechner brauchen die Funktion *OpenSSH-Server*.

Beim ersten Kontakt speichert FleetPilot den Host-Schlüssel des Servers (*Trust on first use*) und verweigert die Verbindung, wenn er sich später ändert. Umgebungen, die dem ersten Kontakt nicht vertrauen dürfen, schalten [strikte Host-Schlüssel](#10-hochsicherheitsumgebungen) ein.

---

## 6. HTTPS und eigenes Zertifikat

Der Installer erzeugt ein selbstsigniertes Zertifikat (ECDSA P-256, 825 Tage gültig) für Hostname und IP-Adresse des Rechners. HSTS bleibt aus, weil Browser einem selbstsignierten Zertifikat nicht vertrauen können.

Für ein Zertifikat Ihrer eigenen CA oder von Let's Encrypt ersetzen Sie die beiden Dateien (Zertifikatskette und privater Schlüssel im PEM-Format) und laden nginx neu:

```bash
sudo cp fullchain.pem /etc/fleetpilot/tls/fullchain.pem
```

```bash
sudo install -m 0600 privkey.pem /etc/fleetpilot/tls/privkey.pem
```

```bash
sudo nginx -t
```

```bash
sudo systemctl reload nginx
```

Mit einem vertrauenswürdigen Zertifikat können Sie HSTS einschalten: `FLEETPILOT_HSTS=true` in `/opt/fleetpilot/.env` setzen und FleetPilot neu starten (`sudo systemctl restart fleetpilot`). Die vollständige gehärtete TLS-Konfiguration steht in `deploy/nginx-fleetpilot-tls.conf`.

Hinter einem eigenen Reverse Proxy (Traefik, Caddy, nginx Proxy Manager) behalten Sie `GUNICORN_BIND=127.0.0.1:5000` bei, wenn der Proxy auf demselben Rechner läuft, setzen `FLEETPILOT_TRUST_PROXY=true` und sorgen dafür, dass der Proxy `X-Forwarded-For` und `X-Forwarded-Proto` setzt. Schalten Sie `FLEETPILOT_TRUST_PROXY` nur ein, wenn wirklich ein Proxy davor steht; sonst könnten Clients ihre Adresse fälschen.

---

## 7. Aktualisieren

Jeder dieser Wege funktioniert; Daten und Einstellungen bleiben immer erhalten:

- **Weboberfläche**: *System → FleetPilot-Update* (Administratoren) sucht nach neuen Versionen und installiert sie.
- **Installer**: denselben `install.sh`-Befehl erneut ausführen.
- **Proxmox**: das Hilfsskript mit `-- update <Container-ID>` aufrufen.

Laden Sie vor einem größeren Update unter *System → Backups* eine Sicherung herunter. Laden Sie nach einem Update die Seite im Browser einmal neu.

---

## 8. Sichern und Wiederherstellen

*System → Backups* erstellt eine konsistente Sicherung von Benutzern, Hosts, Controller-Einstellungen, SMART-Verlauf und geheimem Schlüssel. Automatische tägliche Sicherungen laufen um 03:00 Uhr, die letzten 7 bleiben erhalten (`FLEETPILOT_AUTO_BACKUP`, `FLEETPILOT_BACKUP_HOUR`, `FLEETPILOT_BACKUP_KEEP`). Sicherungen liegen in `/opt/fleetpilot/data/backups`.

- **Herunterladen**, um eine Kopie an anderer Stelle aufzubewahren. Sie enthält Passwort-Hashes und verschlüsselte Zugangsdaten; bewahren Sie sie sicher auf.
- **Wiederherstellen**: Sicherung hochladen und *Stage restore* wählen. FleetPilot prüft sie und spielt sie beim nächsten Neustart ein; die bisherigen Dateien bleiben erhalten.

Für eine Sicherung des ganzen Rechners sichern Sie `/opt/fleetpilot/data` und `/opt/fleetpilot/.env` oder den ganzen Container mit Proxmox Backup Server.

---

## 9. Einstellungen (`.env`)

Die Einstellungen stehen in `/opt/fleetpilot/.env`. Nach einer Änderung neu starten: `sudo systemctl restart fleetpilot`.

| Einstellung | Standard | Bedeutung |
|---|---|---|
| `SECRET_KEY` | erzeugt | Signiert Sitzungen und verschlüsselt gespeicherte Zugangsdaten. Auf einer laufenden Installation nie ändern: gespeicherte Passwörter ließen sich sonst nicht mehr entschlüsseln |
| `DASHBOARD_USERNAME` | `admin` | Name des ersten Administratorkontos |
| `DASHBOARD_PASSWORD` | erzeugt | Erstes Administratorpasswort; nur beim ersten Start gelesen und danach vom Installer entfernt |
| `FLEETPILOT_DATA_DIR` | `/opt/fleetpilot/data` | Ablage aller Daten |
| `GUNICORN_BIND` | `127.0.0.1:5000` | Adresse und Port des Anwendungsservers |
| `GUNICORN_THREADS` | `4` | Anfrage-Threads |
| `FLEETPILOT_PRODUCTION` | `true` mit HTTPS | Produktionsvorgaben (sichere Cookies, strenge Prüfungen) |
| `FLEETPILOT_COOKIE_SECURE` | `true` mit HTTPS | Cookies nur über HTTPS senden |
| `FLEETPILOT_TRUST_PROXY` | `true` mit HTTPS | `X-Forwarded-*`-Kopfzeilen des lokalen Proxys vertrauen |
| `FLEETPILOT_HSTS` | `false` | HSTS senden; nur mit vertrauenswürdigem Zertifikat |
| `FLEETPILOT_SESSION_MINUTES` | `480` | Sitzungsdauer (15–1440) |
| `FLEETPILOT_AUTO_BACKUP` / `_BACKUP_HOUR` / `_BACKUP_KEEP` | `true` / `3` / `7` | Tägliche Datensicherung |
| `FLEETPILOT_ROUTER_POLL_MINUTES` | `5` | Wie oft Router geprüft werden; `0` schaltet es ab |
| `FLEETPILOT_VERIFY_SSL` | `false` | TLS-Zertifikate der VM-, Speicher- und Backup-APIs prüfen. Einschalten, sobald diese vertrauenswürdige Zertifikate haben |
| `FLEETPILOT_WEBAUTHN_RP_ID` / `_ORIGIN` | aus der Adresse | Domain und Origin für Sicherheitsschlüssel, wenn FleetPilot unter einem anderen Namen erreichbar ist |
| `FLEETPILOT_FIPS` | aus | Siehe [Hochsicherheitsumgebungen](#10-hochsicherheitsumgebungen) |
| `FLEETPILOT_SSH_STRICT_HOST_KEYS` | aus | Siehe [Hochsicherheitsumgebungen](#10-hochsicherheitsumgebungen) |
| `FLEETPILOT_OFFLINE` | aus | Siehe [Hochsicherheitsumgebungen](#10-hochsicherheitsumgebungen) |
| `SYNC_TOKEN` | keins | Gemeinsames Geheimnis, wenn zwei FleetPilot-Instanzen Daten abgleichen |
| `YUBICO_CLIENT_ID` / `YUBICO_SECRET_KEY` | keins | Nur für das alte YubiKey-OTP-Verfahren |

---

## 10. Hochsicherheitsumgebungen

Für regulierte oder vom Internet getrennte Umgebungen in `.env` ergänzen:

```ini
FLEETPILOT_FIPS=true
FLEETPILOT_SSH_STRICT_HOST_KEYS=true
FLEETPILOT_OFFLINE=true
```

- **FIPS**: Passwörter werden nur mit PBKDF2-HMAC-SHA256 gespeichert; vorhandene Hashes werden bei der nächsten Anmeldung umgestellt.
- **Strikte Host-Schlüssel**: FleetPilot verbindet sich nur mit Servern, deren Host-Schlüssel bereits in `/opt/fleetpilot/data/known_hosts` steht.
- **Offline**: keine Update-Prüfung und kein Online-Pluginkatalog.

Für eine noch engere systemd-Sandbox das strikte Profil installieren:

```bash
sudo install -D -m 0644 /opt/fleetpilot/deploy/fleetpilot-strict.conf /etc/systemd/system/fleetpilot.service.d/strict.conf
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl restart fleetpilot
```

Das strikte Profil sperrt lokale Festplattenwerkzeuge und Lüftersteuerung auf dem FleetPilot-Rechner selbst; die Verwaltung anderer Rechner über SSH ist nicht betroffen. Einzelheiten in [SECURITY.md](../../SECURITY.md) und [production_profile.md](../production_profile.md).

---

## 11. Deinstallieren

**Proxmox-Container**: den Container in Proxmox stoppen und entfernen, oder:

```bash
pct stop 114
```

```bash
pct destroy 114
```

**Debian/Ubuntu/Raspberry Pi**: Wenn Sie Ihre Daten behalten möchten, vorher eine Sicherung herunterladen, dann:

```bash
sudo systemctl disable --now fleetpilot
```

```bash
sudo rm -rf /opt/fleetpilot /etc/fleetpilot /usr/local/lib/fleetpilot /etc/sudoers.d/fleetpilot /etc/systemd/system/fleetpilot.service /etc/systemd/system/fleetpilot.service.d /etc/nginx/sites-enabled/fleetpilot* /etc/nginx/sites-available/fleetpilot* /root/fleetpilot-credentials.txt
```

```bash
sudo userdel fleetpilot
```

```bash
sudo systemctl reload nginx
```

Entfernen Sie FleetPilots öffentlichen Schlüssel aus den `authorized_keys`-Dateien Ihrer Server.

---

## 12. Fehlersuche

| Problem | Lösung |
|---|---|
| Die Seite lädt nicht | `systemctl status fleetpilot nginx`, dann `journalctl -u fleetpilot -n 50` |
| `http://<ip>` antwortet nicht | `https://<ip>` verwenden. Port 80 bleibt für HAProxy frei |
| „Security token expired or missing" | Die Seite war zu lange offen oder Cookies sind blockiert. Seite neu laden und erneut versuchen. Hinter einem eigenen Proxy prüfen, ob er `X-Forwarded-Proto: https` weitergibt |
| Nach Fehlversuchen gesperrt | Ablauf der Sperre abwarten (standardmäßig 10 Minuten, einstellbar unter *Sicherheitscenter → Sign-in rules*) oder Passwort mit `reset-password.sh` zurücksetzen |
| Ein Server wird als offline angezeigt | FleetPilot prüft den SSH-Port. Adresse, Port und Firewall prüfen; testen mit `sudo -u fleetpilot ssh -i /opt/fleetpilot/.ssh/id_ed25519 benutzer@server` |
| „Host key changed" | Der Server wurde neu installiert oder seine Adresse gehört jetzt einem anderen Rechner. Wenn das erwartet ist, seine Zeile aus `/opt/fleetpilot/data/known_hosts` löschen |
| Installer bricht in einem Proxmox-Container ab | Den Proxmox-Update-Befehl erneut ausführen; der Installer setzt fort. Das Protokoll steht im Container: `journalctl -u fleetpilot` |
| Dienst startet in einem älteren LXC nicht | Der Installer legt automatisch eine passende Sandbox-Ergänzung an (`/etc/systemd/system/fleetpilot.service.d/lxc.conf`) |
| Plugin-Installation meldet einen schreibgeschützten Ordner | Das ist so gewollt. Die Plugin-Datei als root nach `/opt/fleetpilot/addons` kopieren und FleetPilot neu starten |

Weiterhin Probleme? Erstellen Sie ein Issue mit der Ausgabe von `journalctl -u fleetpilot -n 100` (Adressen und Namen, die Sie als privat ansehen, vorher entfernen): <https://github.com/ChristianHandy/FleetPilot/issues>
