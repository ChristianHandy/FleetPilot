# FleetPilot Benutzerhandbuch

**Version 1.7** · für Administratoren, Operatoren und Betrachter

FleetPilot ist eine Weboberfläche für Server, PCs, Router, Festplatten, virtuelle Maschinen, Speichersysteme und Sicherungen im Homelab oder kleinen Unternehmen. Es erreicht Ihre Rechner über SSH und über die APIs von Proxmox, TrueNAS, Unraid und den Backup-Systemen. Auf den verwalteten Rechnern muss nichts installiert werden.

Die Installation beschreibt die **[Installationsanleitung](installation.md)**. *English: [../user-guide.md](../user-guide.md)*

**Inhalt**

- [1. Grundlagen](#1-grundlagen): Anmeldung, Bildschirm, Rollen, Sprachen, Barrierefreiheit
- [2. Startseite](#2-startseite)
- [3. Server](#3-server): [Hosts verwalten](#hosts-verwalten) · [Netzwerkscanner](#netzwerkscanner) · [Router](#router) · [Update-Übersicht](#update-übersicht) · [Server aktualisieren](#server-aktualisieren)
- [4. Hardware](#4-hardware): [Hardware-Übersicht](#hardware-übersicht) · [HW-Monitor](#hw-monitor) · [SMART-Zustand](#smart-zustand) · [Speicher & Festplatten](#speicher--festplatten) · [Lüfter & Kühlung](#lüfter--kühlung)
- [5. Virtualisierung und Speicher](#5-virtualisierung-und-speicher): [VM-Controller](#vm-controller) · [Speicher-Controller](#speicher-controller) · [Backup-Server](#backup-server)
- [6. Operationen](#6-operationen): [Geplantes Herunterfahren](#geplantes-herunterfahren) · [CheckMK](#checkmk) · [Systemmonitor](#systemmonitor) · [FleetPilot-Update](#fleetpilot-update)
- [7. System](#7-system): [Update-Einstellungen](#update-einstellungen) · [E-Mail-Konfiguration](#e-mail-konfiguration) · [Proxy-Dienste](#proxy-dienste) · [Produktionsstatus](#produktionsstatus) · [Sicherheitscenter](#sicherheitscenter) · [Benachrichtigungen](#benachrichtigungen) · [Audit-Protokoll](#audit-protokoll) · [Backups](#backups) · [Plugins](#plugins)
- [8. Konto](#8-konto): [Mein Profil](#mein-profil) · [Anmeldung & Sicherheit](#anmeldung--sicherheit) · [Zwei-Faktor-Anmeldung](#zwei-faktor-anmeldung) · [Barrierefreiheit](#barrierefreiheit) · [Benutzerverwaltung](#benutzerverwaltung)
- [9. Schnittstellen](#9-schnittstellen): API-Tokens und REST-API · Prometheus · Home Assistant · öffentliche Statusseite
- [10. Sicherheitshinweise](#10-sicherheitshinweise)
- [11. Häufige Fragen](#11-häufige-fragen)

Hinweis: Menünamen erscheinen hier so, wie die deutsche Oberfläche sie zeigt. Einige Schaltflächen sind noch nicht übersetzt; sie stehen hier in ihrer englischen Beschriftung.

---

## 1. Grundlagen

### Anmeldung

Öffnen Sie FleetPilot im Browser (zum Beispiel `https://192.168.1.62`) und melden Sie sich mit Benutzername und Passwort an. Ist für Ihr Konto die Zwei-Faktor-Anmeldung aktiv, fragt FleetPilot danach den Code der Authenticator-App, Ihren Sicherheitsschlüssel oder einen Wiederherstellungscode ab.

Nach der Anmeldung zeigt ein kurzer Hinweis, wann und von wo Sie sich zuletzt angemeldet haben und wie viele Fehlversuche es seitdem gab. Wenn Sie diese nicht erkennen, ändern Sie Ihr Passwort und prüfen Sie **Konto → Anmeldung & Sicherheit**.

Zu viele falsche Passwörter sperren das Konto für eine Weile (standardmäßig 10 Versuche und 10 Minuten). Sitzungen enden nach 2 Stunden ohne Aktivität oder nach insgesamt 12 Stunden; ein Administrator kann beides im Sicherheitscenter ändern.

### Der Bildschirm

- **Seitenleiste** (links): alle Bereiche, gruppiert in *Server*, *Hardware*, *Virtualisierung*, *Operationen*, *System* und *Konto*. Gruppen lassen sich einklappen. Auf dem Smartphone öffnet die Menü-Schaltfläche die Seitenleiste.
- **Seitenkopf**: Titel, eine Zeile Beschreibung und die wichtigsten Schaltflächen der Seite.
- **Oben rechts**: Sprache, helles/dunkles Design, Barrierefreiheit, Ihr Profil und *Abmelden*.

### Rollen

Jeder Benutzer hat eine oder mehrere Rollen:

| Rolle | Darf |
|---|---|
| **viewer** (Betrachter) | Alles sehen außer Sicherheitseinstellungen, Benutzern und Geheimnissen |
| **operator** | Zusätzlich Aktionen ausführen: Updates, SMART-Abfragen, Sicherungen, Hosts wecken/herunterfahren, VMs starten/stoppen, Router-Sicherungen |
| **admin** | Alles: Systeme hinzufügen und entfernen, Benutzer, Sicherheitseinstellungen, Sicherungen wiederherstellen, FleetPilot aktualisieren, Router neu starten |

Aktionen, die sicherheitsrelevante Daten ändern (Benutzer, Tokens, Sicherheitsregeln, Sicherungen), fragen erneut nach Ihrem Passwort, wenn Sie es nicht in den letzten 10 Minuten bestätigt haben.

### Sprachen

English, Deutsch, Français, Español und Nederlands. Die Sprache wählen Sie oben rechts; sie wird in Ihrem Profil gespeichert.

Wer Übersetzungen ergänzt, kann im Quellverzeichnis `python scripts/missing_translations.py` ausführen. Der Befehl listet fehlende Vorlagenübersetzungen und deren Anzahl pro Sprache auf. `--lang de` prüft nur Deutsch. Der Rückgabewert ist `0` bei vollständiger Übersetzung, `1` bei fehlenden Übersetzungen und `2` bei ungültigen Argumenten; FleetPilot wird dabei nicht gestartet.

### Barrierefreiheit

**Konto → Barrierefreiheit** macht FleetPilot leichter lesbar und bedienbar: größere Schrift, hoher Kontrast, gut lesbare Schriftart, mehr Abstand, unterstrichene Links, weniger Bewegung und *Leichte Sprache* mit einfachen Menünamen und einer kurzen Erklärung auf jeder Seite. Die Einstellungen gelten für Ihr Konto auf jedem Gerät. FleetPilot lässt sich vollständig mit der Tastatur und mit Screenreadern bedienen. Einzelheiten: [accessibility.md](../accessibility.md).

---

## 2. Startseite

Die Startseite zeigt den Zustand von allem auf einen Blick: Dienste und Serverübersicht, VM- und Speicher-Controller, SMART-Zustand der Festplatten, Umgebungen, Tags, letzte Updates und Verknüpfungen.

- **Customize** blendet Karten ein und aus und ändert ihre Reihenfolge (ziehen oder per Tastatur). **Save Layout** speichert die Anordnung für Ihr Konto; **Reset to Default** stellt sie zurück.
- Ist eine neue FleetPilot-Version verfügbar, erscheint ein Hinweis (Administratoren können sie dort installieren).

---

## 3. Server

### Hosts verwalten

Die Liste aller Server und PCs, die FleetPilot verwaltet.

**Host hinzufügen** (Operatoren und Administratoren):

| Feld | Bedeutung |
|---|---|
| Name | Ein kurzer, eindeutiger Name, zum Beispiel `nas` oder `web-01` |
| Adresse | IP-Adresse oder Hostname |
| Benutzer / Port | SSH-Benutzer und Port (22) |
| MAC-Adresse | Für Wake-on-LAN |
| Gruppe, Standort, Umgebung, Kritikalität, Tags | Zum Sortieren und Filtern (zum Beispiel *Production*, *Lab*, *High*) |
| OS-Profile | Was auf dem Rechner läuft: Linux-Distribution, Windows, Proxmox usw. Ein PC mit Dual-Boot kann mehrere Profile haben |

Klicken Sie danach am Host auf **Install Key**: FleetPilot fragt einmal nach dem Passwort dieses Rechners, installiert dort seinen eigenen SSH-Schlüssel und speichert das Passwort nicht. Ab dann meldet es sich mit dem Schlüssel an.

**Pro Host** können Sie:

- sehen, ob er erreichbar ist (Prüfung des SSH-Ports, ohne Anmeldung),
- ihn mit **Wake** aufwecken (Wake-on-LAN-Paket an die MAC-Adresse),
- ihn mit **Shutdown** herunterfahren (Linux und Windows),
- Updates ausführen (siehe Update-Übersicht),
- ein Bild für die Karte hochladen,
- ihn bearbeiten oder löschen.

Für lange Listen gibt es das Suchfeld und Filter nach Tag, Gruppe und Umgebung. Die beiden Schaltflächen oben wechseln zwischen Karten und einer kompakten Tabelle.

**IP-Änderungen erkennen**: Bekommen Rechner ihre Adresse per DHCP, vergleicht FleetPilot die MAC-Adressen mit der ARP-Tabelle und aktualisiert geänderte Adressen.

### Netzwerkscanner

Findet Geräte in einem Adressbereich (zum Beispiel `192.168.1.0/24`). Bereich eingeben und **Start Scan** klicken. FleetPilot pingt jede Adresse an, prüft, ob ein SSH-Port offen ist, und listet die gefundenen Geräte. **Host hinzufügen** übernimmt ein Ergebnis mit ausgefüllten Angaben. Scannen Sie nur Netze, für die Sie verantwortlich sind.

### Router

Router, Repeater und Access Points: FRITZ!Box und FRITZ!Repeater, OpenWrt (auch GL.iNet, Turris), OPNsense, pfSense, VyOS, DD-WRT/FreshTomato, MikroTik RouterOS, IPFire und andere Linux-Router, außerdem eine Erreichbarkeitsprüfung für jeden anderen Repeater oder Access Point.

- **Add device** (Administratoren): System und Rolle (Router, Repeater, Access Point) wählen, Adresse und Zugangsdaten eingeben. OPNsense nutzt einen API-Schlüssel mit Secret; FRITZ!-Geräte einen FRITZ!-Benutzer mit dem Recht *FRITZ!Box Einstellungen*; die übrigen SSH.
- Die Detailseite zeigt Modell, Firmware, Laufzeit, Last, Speicher, Schnittstellen, verbundene Geräte, WLAN-Netze und bei FRITZ! die Internetverbindung und das Mesh.
- **Update-Prüfung** zeigt, ob neue Firmware verfügbar ist. FleetPilot installiert Router-Firmware nie selbst, weil ein fehlgeschlagenes Update das ganze Netz lahmlegen kann.
- **Konfigurationssicherungen** (Operatoren) werden verschlüsselt gespeichert; Administratoren können sie herunterladen. Die letzten 10 pro Router bleiben erhalten.
- **Restart router** (Administratoren) muss durch Eintippen des Routernamens bestätigt werden.

Zugangsdaten werden verschlüsselt gespeichert. Einzelheiten und die nötigen Rechte je System: [routers.md](../routers.md).

### Update-Übersicht

Updates für alle verwalteten Hosts an einer Stelle:

| Paketverwaltung | Distributionen |
|---|---|
| `apt` | Debian, Ubuntu, Linux Mint, Pop!_OS, Raspberry Pi OS, Kali, Zorin, Devuan und andere Debian-/Ubuntu-Ableger, Proxmox VE |
| `dnf` (`yum` unter CentOS 7 und Amazon Linux 2) | Fedora, RHEL, Rocky Linux, AlmaLinux, Oracle Linux, CentOS Stream, Amazon Linux |
| `zypper` | openSUSE Leap, SLES; Tumbleweed und Slowroll bekommen `zypper dup` |
| `pacman` | Arch, Manjaro, EndeavourOS, Garuda, Artix, CachyOS (der Keyring wird zuerst aktualisiert) |
| `apk`, `xbps`, `eopkg`, `swupd` | Alpine, Void, Solus, Clear Linux |
| Windows Update | Windows, beim vollständigen Update zusätzlich `winget` für Anwendungen |

FleetPilot erkennt eine Distribution an `ID` und `ID_LIKE` in `/etc/os-release`, daher funktionieren auch nicht aufgeführte Ableger. Es meldet sich als root an oder nutzt `sudo` (oder `doas`, wie unter Alpine) ohne Passwortabfrage und wartet auf eine laufende Paketverwaltung (unattended-upgrades, cloud-init), statt abzubrechen. NixOS, Fedora Atomic/CoreOS, openSUSE MicroOS und andere imagebasierte Systeme aktualisieren sich selbst; FleetPilot weist darauf hin, statt eine Paketverwaltung aufzurufen.

- Einen oder mehrere Hosts auswählen und das Update starten. **Update Progress** zeigt die Ausgabe je Host live.
- **Update History** listet jeden Lauf mit Ergebnis und Dauer.
- **Automatic Updates** führt Updates nach Zeitplan aus (siehe [Update-Einstellungen](#update-einstellungen)).

### Schwachstellen

Bekannte Sicherheitslücken (CVEs) in der Software Ihrer Rechner, nach Schwere sortiert, jeweils mit der Version, die sie behebt.

- **Was geprüft wird:**
  - **Linux-Server:** FleetPilot liest die installierten Pakete per SSH (`dpkg`, `apk` oder `rpm`) und sucht sie in den Sicherheitsdaten der Distribution auf [OSV.dev](https://osv.dev). Das deckt Debian, Ubuntu, Raspberry Pi OS, Proxmox VE und Backup Server, TrueNAS SCALE, Alpine, Rocky Linux und AlmaLinux ab.
  - **Docker-Container** auf diesen Servern: FleetPilot prüft ihre Images mit [Trivy](https://trivy.dev), wenn Trivy auf dem Server installiert ist.
  - **pfSense und OPNsense:** über ihr eigenes `pkg audit`.
  - **FleetPilot selbst:** seine Python-Pakete und der Rechner, auf dem es läuft.
  - **Nicht abgedeckt:** Windows, FRITZ!OS und OpenWrt veröffentlichen keine Daten je Paket. Sie stehen als „Not covered" in der Liste, mit einem Hinweis, was stattdessen zu tun ist.
- **Ergebnisse lesen:**
  - **Scan now** (Operatoren und Administratoren) prüft alles im Hintergrund; **Rescan** prüft ein einzelnes Ziel.
  - Die Liste zeigt standardmäßig hohe und kritische Funde, für die es eine Korrektur gibt. Mit den Filtern sehen Sie alle, auch Lücken, die die Distribution noch nicht behoben hat.
  - Die meisten Funde verschwinden nach einem Update. Starten Sie es unter Hosts oder in der [Update-Übersicht](#update-übersicht) und prüfen Sie danach erneut.
- **Tägliche Prüfung und Meldungen:** Administratoren können eine tägliche Prüfung einschalten. Findet eine Prüfung neue hohe oder kritische Lücken mit Korrektur, benachrichtigt FleetPilot jeden Kanal, der „New vulnerabilities" abonniert hat ([Benachrichtigungen](#benachrichtigungen)). Die erste Prüfung eines Ziels gilt als Ausgangsstand und löst keine Meldung aus.
- **Datenschutz:** An OSV.dev gehen nur Paketnamen und Versionen, nie Adressen, Hostnamen oder andere Daten. Im Offline-Modus (`FLEETPILOT_OFFLINE=true`) wird nichts gesendet. Mit `FLEETPILOT_OSV_URL` nutzt FleetPilot stattdessen einen eigenen Spiegel der OSV-API.
- **An anderer Stelle:** Die Ergebnisse gibt es auch als `GET /api/vulnerabilities` und als Metriken `fleetpilot_vulnerabilities*` unter `/metrics`. Das [Sicherheitscenter](#sicherheitscenter) meldet kritische Lücken, deren Korrektur noch nicht installiert ist.

### Server aktualisieren

(Administratoren) Aktualisiert die Betriebssystempakete des Rechners, auf dem FleetPilot läuft. **Nur nach Updates suchen** listet ausstehende Pakete; **Update starten** installiert sie mit Live-Ausgabe; **Reboot Server** startet den Rechner neu.

---

## 4. Hardware

### Hardware-Übersicht

Hardwaredetails jedes Hosts: CPU, Arbeitsspeicher, Mainboard, Festplatten, Netzwerkkarten, Grafikkarte und Sensoren. **Collect hardware info** liest die Daten über SSH; **Refresh all** aktualisiert alle Hosts. Ein Klick auf einen Host zeigt den vollständigen Bericht.

### HW-Monitor

Live-Ansicht von Temperaturen, Last, Arbeitsspeicher, Netzwerk- und Festplatten-I/O und Lüfterdrehzahlen je Server, mit Verlaufsdiagrammen.

- **Add server** mit Name, Adresse und SSH-Benutzer.
- **Setup** prüft die Werkzeuge, die jeder Server braucht (`lm-sensors`, `smartmontools`, `stress-ng`, `fio`), und installiert fehlende.
- **Belastungstests** (CPU, Arbeitsspeicher, Festplatte) prüfen Kühlung und Stabilität neuer Hardware: **Start**, **Stop** oder **Start all tests**. Fehler während eines Tests müssen **bestätigt** werden (*Acknowledge*).
- **Tasks** listet laufende und beendete Aufträge mit ihren Protokollen.

Die Seite aktualisiert sich schneller, solange jemand sie ansieht, und sonst langsamer.

### SMART-Zustand

Der Zustand aller Festplatten, die FleetPilot kennt: Gesamtzustand, Temperatur, Betriebsstunden, umgelagerte und ausstehende Sektoren.

- **Active Disk Alerts** listet Festplatten, die Aufmerksamkeit brauchen. **Ack** bestätigt eine Warnung, damit sie nicht mehr als neu erscheint.
- **Jetzt abfragen** / **Poll Local Disks** lesen frische SMART-Daten; **Import Disks from Sources** sammelt Festplatten aller SSH-Hosts, Proxmox-Knoten und NAS-Systeme ein.
- **Polling Configuration** legt fest, wie oft SMART-Daten automatisch gelesen werden.
- Ein Klick auf eine Festplatte zeigt ihren Verlauf und die Entwicklung der Attribute.

Neue Probleme können eine E-Mail und eine Push-Benachrichtigung auslösen (siehe [E-Mail-Konfiguration](#e-mail-konfiguration) und [Benachrichtigungen](#benachrichtigungen)).

### Speicher & Festplatten

Der Arbeitsbereich für Festplatten: jede Festplatte mit SMART-Zustand, laufende Speicheraufträge und entfernte Systeme.

- **Disk Overview** listet lokale Festplatten und ihre Partitionen.
- **Validate** liest Stichproben über die ganze Festplatte, ohne etwas zu schreiben, und zeigt eine Karte der Ergebnisse. So fallen defekte Festplatten oder solche mit gefälschter Kapazität schnell auf.
- **Format** (Administratoren) löscht eine Festplatte und legt ein ext4-, xfs- oder FAT32-Dateisystem an. Wählen Sie *Quick wipe* (entfernt Partitionen und Signaturen) oder *Full zero wipe* (überschreibt jeden Block, kann Stunden dauern) und tippen Sie `ERASE /dev/<festplatte>`, um die Schaltfläche freizugeben. **Dabei gehen alle Daten auf der Festplatte verloren.** Systemfestplatten und eingehängte Festplatten sind gesperrt.
- **Remote Management** macht dasselbe für Festplatten in anderen Rechnern über SSH.
- **History** zeigt vergangene Vorgänge und SMART-Importe; **SMART Import** nimmt einen `smartctl -a`-Bericht als Datei entgegen.

Festplattenaktionen auf dem FleetPilot-Rechner laufen über einen kleinen root-Helfer, der nur genau diese Aktionen annimmt.

### Lüfter & Kühlung

Steuert Lüfter in Servern und PCs.

| Controller | Für |
|---|---|
| lm-sensors (Linux PWM) | Lüfteranschlüsse des Mainboards |
| IPMI / ipmitool | Server-BMCs (Supermicro, Dell iDRAC, HPE iLO, …) |
| nbfc-linux | Laptops |
| liquidctl | NZXT, Aquacomputer, Corsair und ähnliche USB-Controller |
| Arctic Fan Controller | Arctic-USB-Lüfterhub |
| PWM sysfs | Direkte Steuerung über den Kernel |
| Raspberry Pi PWM fan | 3-Pin-Lüfter an einem GPIO-Pin |

**Add Fan Controller**: **Auto-Detect Controllers** sucht unterstützte Hardware auf einem Host; **Use This** übernimmt ein Ergebnis. Auf der Geräteseite stellen Sie eine **feste Drehzahl** ein, nutzen den **Automatikmodus** oder wenden ein **Temperaturprofil** an (Drehzahl abhängig von der Temperatur). **Install Packages** installiert die nötigen Werkzeuge.

**Commander Pro** (unter Lüfter & Kühlung) steuert einen per USB an einem entfernten PC angeschlossenen Corsair Commander Pro über SSH und liquidctl.

---

## 5. Virtualisierung und Speicher

### VM-Controller

Zeigt und steuert die virtuellen Maschinen und Container von **Proxmox VE** und die Aufträge von **Veeam Backup & Replication 12**.

- **Endpunkt hinzufügen** (Administratoren): Proxmox auf Port 8006 mit `root@pam` oder einem API-Benutzer mit der Rolle *PVEAdmin* (Datacenter → Permissions → Users); Veeam auf Port 9419 mit eingeschalteter REST-API.
- Die Detailseite listet alle VMs und Container mit Zustand, CPU, Arbeitsspeicher und Speicher. Operatoren können **Start**, **Stop**, **Reboot**, **Suspend**, **Resume** und **Kill** ausführen.
- **Disks** zeigt die physischen Festplatten jedes Proxmox-Knotens mit ihrem SMART-Zustand.
- Bei Veeam werden die Backup-Aufträge und ihre letzten Ergebnisse angezeigt.

### Speicher-Controller

Zeigt Pools, Volumes, Freigaben und Festplatten von **TrueNAS SCALE/CORE** und **Unraid 6.12+**.

- **Endpunkt hinzufügen** mit API-Schlüssel: TrueNAS unter *System → API Keys*, Unraid unter *Settings → Management Access → API Keys*.
- Die Detailseite zeigt Festplatten, ZFS-Pools, SMB-/NFS-/Unraid-Freigaben und Warnungen. **Poll Disks** liest frische Festplattendaten.

### Backup-Server

Überwacht Sicherungen auf **Proxmox Backup Server**, **Duplicati**, **Restic REST-Server**, **BorgWarehouse**, **UrBackup**, **Bacula** (über `bconsole` per SSH) und jeder **generischen SSH-Sicherung** (ein Befehl, dessen Ergebnis FleetPilot auswertet).

- **Add Server** mit Typ, Adresse und Zugangsdaten; **Test** prüft die Verbindung.
- Die Detailseite zeigt Datastores, Aufträge, Snapshots und Verlauf. **Poll Now** aktualisiert; Operatoren können Aufträge starten, wo das System es unterstützt.
- Fehlgeschlagene oder fehlende Sicherungen erscheinen auf der Startseite und können als Benachrichtigung verschickt werden.

---

## 6. Operationen

### Geplantes Herunterfahren

Fährt Hosts nach Zeitplan herunter, zum Beispiel Laborserver nachts.

**Add Schedule**: Host, Aktion (*Shutdown*, *Reboot* oder *Suspend*), Tage und Uhrzeit wählen. **Now** führt einen Plan sofort aus. **Recent Activity** zeigt, was lief und ob es geklappt hat. Zum Einschalten nutzen Sie **Wake** am Host (Wake-on-LAN muss im BIOS/UEFI aktiv sein).

### CheckMK

Liefert FleetPilots Daten an CheckMK (und andere Überwachungssysteme).

- **API Token**: das Token, mit dem Überwachungssysteme zugreifen. **Regenerate** ersetzt es; alte Kopien funktionieren dann nicht mehr.
- **Setup Instructions** bietet vier Wege: lokales Check-Skript, Piggyback-Skript, Datasource-Programm oder REST-API. Zu jedem gibt es ein Skript zum Kopieren.
- **Live Agent Output Preview** zeigt genau, was CheckMK erhält; **Failed / Critical Disks** und **Host Status Overview** zeigen den aktuellen Zustand.

Dasselbe Token authentifiziert [Prometheus](#9-schnittstellen).

### Systemmonitor

(Administratoren) CPU, Arbeitsspeicher, Speicher, Netzwerk und Temperatur des FleetPilot-Rechners selbst, alle 60 Sekunden aktualisiert, mit Verlauf bis zu 24 Stunden.

### FleetPilot-Update

(Administratoren) **Nur nach Updates suchen** zeigt, ob es eine neue FleetPilot-Version gibt und was sich ändert; **Pull & Update FleetPilot** installiert sie mit Live-Ausgabe und startet FleetPilot neu. Daten und Einstellungen bleiben erhalten. Laden Sie vorher eine Sicherung herunter (siehe [Backups](#backups)).

---

## 7. System

### Update-Einstellungen

Regeln für automatische Host-Updates: an/aus, wie oft (täglich, wöchentlich, monatlich) und ob Benachrichtigungen verschickt und Update-Hinweise auf der Übersicht angezeigt werden.

### E-Mail-Konfiguration

SMTP-Server, Port, Verschlüsselung, Absender und Empfänger. **Send Test Email** prüft die Einstellungen. **Report Configuration** legt fest, welche Berichte verschickt werden (Update-Ergebnisse, SMART-Warnungen, tägliche Zusammenfassung). Das SMTP-Passwort wird verschlüsselt gespeichert.

### Proxy-Dienste

(Administratoren; Raspberry Pi mit HAProxy) Veröffentlicht interne Webdienste unter einer Adresse, zum Beispiel `/proxmox/` oder `/unraid/`. Eine Route entsteht in vier Schritten: eindeutiger öffentlicher Pfad, internes Ziel, Health-Pfad, und FleetPilot übernimmt sie. Jede Änderung wird geprüft, bevor HAProxy neu lädt; ungültige Konfigurationen werden automatisch zurückgerollt. **Add Proxmox route(s)** legt die Routen für Proxmox-Konsolen in einem Schritt an.

### Produktionsstatus

Eine Bereitschaftsübersicht der Installation: Betriebsmodus, Sitzungsschutz, Vertrauen in den Reverse Proxy, CSRF-Schutz, geheimer Schlüssel, Audit-Einträge und Identitäts-Bereitschaft. Es ist eine Betriebs-Checkliste, keine Zertifizierung.

### Sicherheitscenter

(Administratoren)

- **Checks**: HTTPS, Administratoren ohne Zwei-Faktor-Anmeldung, eine übrig gebliebene Erststart-Passwortdatei, Rechte des geheimen Schlüssels, CSRF, Debug-Modus, fehlgeschlagene Anmeldungen, Alter der Sicherungen, Tokens ohne Ablaufdatum und ungenutzte Konten. Jede Prüfung sagt, was zu tun ist.
- **Sign-in rules** (Anmelderegeln): 2FA für Administratoren vorschreiben, Leerlauf-Zeitlimit, maximale Sitzungsdauer, Gültigkeit einer Passwortbestätigung, längste Lebensdauer von API-Tokens, Kontosperre, Aufbewahrung des Audit-Protokolls, erlaubte Netze (nur diese Adressen dürfen sich anmelden) und ein Hinweistext, den Benutzer vor der Anmeldung bestätigen müssen.
- **Active sessions** und **API tokens** aller Benutzer, jeweils mit *Abmelden* / *Widerrufen*.
- **Recent failed sign-ins** (letzte Fehlanmeldungen).

### Benachrichtigungen

Schickt Festplattenwarnungen, Sicherheitsereignisse (Sperren, neue Administratoren, geänderte Einstellungen, neue Schreib-Tokens), Router- und Backup-Ereignisse an Ihr Smartphone oder Ihren Team-Chat: **ntfy**, **Gotify**, **Discord**, **Slack/Mattermost** und allgemeine **JSON-Webhooks**.

**Add channel**: Typ, URL (wird verschlüsselt gespeichert), welche Ereignisarten der Kanal erhält und die niedrigste Stufe (info, warning, critical). **Test** schickt eine Testnachricht. E-Mail wird getrennt unter *E-Mail-Konfiguration* eingerichtet.

### Audit-Protokoll

Ein nur erweiterbares Protokoll aller Anmeldungen und Änderungen: wer was wann von welcher Adresse mit welchem Ergebnis getan hat. Passwörter, Tokens, Schlüssel, Anfrageinhalte und Befehlsausgaben werden nie gespeichert.

Filtern nach Ereignis, Benutzer, Ergebnis, Zeitraum oder Text und Export als CSV. Die Einträge sind per HMAC verkettet, sodass geänderte oder gelöschte Einträge auffallen; das Sicherheitscenter zeigt das Ergebnis der Integritätsprüfung. Ereignisse werden zusätzlich als JSON ins Systemprotokoll geschrieben, zur Weiterleitung an ein SIEM.

### Backups

(Administratoren) Sicherungen der eigenen Daten von FleetPilot: Benutzer, Hosts, Controller-Einstellungen, SMART-Verlauf und geheimer Schlüssel.

- **Create backup now** erstellt sofort eine Sicherung; täglich läuft automatisch eine, die letzten 7 bleiben erhalten.
- **Herunterladen**, um sie an anderer Stelle aufzubewahren. Sie enthält Passwort-Hashes und verschlüsselte Zugangsdaten: sicher aufbewahren.
- **Stage restore** lädt eine Sicherung hoch. FleetPilot prüft ihre Prüfsummen und spielt sie beim nächsten Neustart ein; die bisherigen Dateien bleiben erhalten.

### Plugins

Erweitert FleetPilot. **Installed plugins** listet aktive Plugins und die Einhängepunkte, die sie nutzen; **Plugin Repository** listet verfügbare Plugins; **Write Your Own Plugin** öffnet die Entwicklerdokumentation.

Aus Sicherheitsgründen ist der Programmordner in einer normalen Installation für FleetPilot schreibgeschützt. Ein Administrator kopiert die Plugin-Datei auf dem Server nach `/opt/fleetpilot/addons` und startet FleetPilot neu. Installieren Sie nur Plugins, denen Sie vertrauen: Ein Plugin läuft mit den Rechten von FleetPilot.

---

## 8. Konto

### Mein Profil

Ihr Name, Ihre E-Mail-Adresse und Ihr Passwort. Ein neues Passwort braucht mindestens 12 Zeichen.

### Anmeldung & Sicherheit

- **Active sessions**: jeder Browser und jedes Gerät, auf dem Sie angemeldet sind. **Sign out** beendet eine Sitzung; **Sign out all other sessions** beendet alle außer der aktuellen.
- **Recent sign-ins** mit Zeit, Adresse und Ergebnis.
- **API tokens** für Skripte und Schnittstellen (siehe [Schnittstellen](#9-schnittstellen)).
- Ein Link zur Einrichtung der Zwei-Faktor-Anmeldung, falls noch nicht geschehen.

### Zwei-Faktor-Anmeldung

Schützt Ihr Konto auch dann, wenn Ihr Passwort gestohlen wurde. Wählen Sie eine oder mehrere Methoden:

- **Authenticator-App** (TOTP): QR-Code mit einer App wie Aegis, Google Authenticator oder 1Password scannen, Code eingeben, **Verify & Enable**.
- **Sicherheitsschlüssel oder Passkey** (WebAuthn): YubiKey, Windows Hello, Touch ID oder ein Smartphone. **Register security key**, dann den Schlüssel berühren.
- **Wiederherstellungscodes**: Einmalcodes für den Fall, dass Sie kein Gerät haben. **Print** oder sicher aufbewahren; **Regenerate Codes** macht die alten ungültig.

Administratoren können im Sicherheitscenter die Zwei-Faktor-Anmeldung für alle Administratoren vorschreiben.

### Barrierefreiheit

Siehe [Barrierefreiheit](#barrierefreiheit) unter Grundlagen.

### Benutzerverwaltung

(Administratoren) **Add User** mit Name, E-Mail, Passwort und Rollen; einen Benutzer bearbeiten, um Rollen zu ändern oder das Konto zu deaktivieren; **Delete** entfernt ihn. Geben Sie jeder Person ein eigenes Konto: Das Audit-Protokoll zeigt dann, wer was getan hat. Halten Sie mindestens zwei Administratorkonten bereit oder wissen Sie, wie man ein [Passwort auf dem Server zurücksetzt](installation.md#4-erste-anmeldung).

---

## 9. Schnittstellen

### API-Tokens und REST-API

Ein Token erstellen Sie unter **Konto → Anmeldung & Sicherheit → API tokens**: Namen vergeben, *read-only* oder *read/write* und ein Ablaufdatum wählen. Das Token wird einmal angezeigt; FleetPilot speichert nur einen Hash. Verwendung als Bearer-Token:

```bash
curl -H "Authorization: Bearer fp_..." https://fleetpilot.example/api/me
```

Nützliche Endpunkte (alle JSON): `/api/me`, `/api/hosts`, `/api/vms`, `/api/smart/summary`, `/api/smart/disks`, `/api/routers`, `/api/backup/servers`, `/api/hw/live`, `/api/fans/devices`, `/api/vulnerabilities`, `/api/monitor/latest`, `/api/registry/servers`. Mit einem Lese-/Schreib-Token: `POST /api/hosts/<name>/wol` und `/shutdown` (Operatoren), `/api/vms/<id>/action` (Admins), `/api/fans/<id>/set_fan` (Operatoren). Tokens gelten nur für `/api/`-Adressen, nie für die Webseiten; Nur-Lese-Tokens werden für alles außer Lesen abgewiesen.

### Android-App (Beta)

Die FleetPilot-App für Android 8.0 und neuer zeigt Dashboard, Server, virtuelle Maschinen, den HW-Monitor und Lüfter und kann Server wecken und herunterfahren, VMs starten und stoppen und Lüfter einstellen. Laden Sie die APK unter [Releases](https://github.com/ChristianHandy/FleetPilot/releases) herunter (*Android app*) und installieren Sie sie; Android fragt, ob der Browser oder Dateimanager Apps installieren darf.

1. Erstellen Sie wie oben ein API-Token. Ein *read-only*-Token zeigt nur an; ein *read/write*-Token erlaubt zusätzlich, was Ihre Rolle darf (Operatoren: wecken, herunterfahren, Lüfter; Admins: auch VMs).
2. Öffnen Sie die App, geben Sie die FleetPilot-Adresse (zum Beispiel `https://192.168.1.62`) und das Token ein.
3. FleetPilot nutzt ein eigenes Zertifikat, das Android nicht kennt. Die App zeigt den SHA-256-Fingerabdruck: Vergleichen Sie ihn mit dem, den Ihr Browser für FleetPilot anzeigt, oder mit `sudo openssl x509 -in /etc/fleetpilot/tls/fullchain.pem -noout -fingerprint -sha256` auf dem Server, und tippen Sie dann **Trust and sign in**. Danach akzeptiert die App nur dieses Zertifikat.

Die App braucht FleetPilot 1.7.1 oder neuer. Abmelden über den Pfeil oben rechts; geht das Telefon verloren, widerrufen Sie das Token in FleetPilot.

### Prometheus

`/metrics` liefert Hosts, SMART-Zustand, Temperaturen und Betriebsstunden, offene Warnungen, Festplattenaufträge, Router-Zustand sowie CPU und Arbeitsspeicher des FleetPilot-Rechners. Authentifizierung mit dem Token von der CheckMK-Seite:

```yaml
scrape_configs:
  - job_name: fleetpilot
    scheme: https
    authorization:
      credentials: "<Token von der CheckMK-Seite>"
    static_configs:
      - targets: ["fleetpilot.example"]
```

### Home Assistant

FleetPilots Daten liest Home Assistant mit dem eingebauten RESTful-Sensor und einem Nur-Lese-API-Token:

```yaml
rest:
  - resource: https://fleetpilot.example/api/smart/summary
    headers:
      Authorization: !secret fleetpilot_token   # "Bearer fp_..."
    sensor:
      - name: FleetPilot offene Festplattenwarnungen
        value_template: "{{ value_json.active_alerts }}"
```

Das Repository enthält außerdem eine eigene Integration, `integrations/home-assistant/custom_components/smart_monitor`, die SMART-Daten direkt per SSH von Ihren Rechnern liest.

### Öffentliche Statusseite

`/status` zeigt veröffentlichte Dienste und die verwalteten Hosts mit Namen und Zustand ohne Anmeldung, etwa für einen Wandbildschirm oder für Benutzer. Adressen oder weitere Details zeigt sie nicht; sind Hostnamen vertraulich, machen Sie diese Seite nicht erreichbar.

---

## 10. Sicherheitshinweise

- Nutzen Sie HTTPS mit vertrauenswürdigem Zertifikat, wenn außer Ihnen weitere Personen FleetPilot erreichen; siehe [Installationsanleitung](installation.md#6-https-und-eigenes-zertifikat).
- Schalten Sie die Zwei-Faktor-Anmeldung ein, mindestens für Administratoren.
- Geben Sie jeder Person ein eigenes Konto mit der kleinsten nötigen Rolle.
- Machen Sie FleetPilot nicht direkt aus dem Internet erreichbar. Nutzen Sie ein VPN (WireGuard, Tailscale) oder schränken Sie die *erlaubten Netze* im Sicherheitscenter ein.
- FleetPilot speichert Passwörter für Geräte und APIs verschlüsselt mit dem geheimen Schlüssel aus `.env`. Schützen Sie Sicherungen und die Datei `.env` wie Passwörter.
- Regulierte oder vom Internet getrennte Umgebungen: siehe [Hochsicherheitsumgebungen](installation.md#10-hochsicherheitsumgebungen) und [SECURITY.md](../../SECURITY.md).
- Sicherheitsprobleme melden Sie vertraulich wie in [SECURITY.md](../../SECURITY.md) beschrieben.

---

## 11. Häufige Fragen

**Braucht FleetPilot einen Agenten auf meinen Servern?** Nein. Es nutzt SSH und die eigenen APIs der Systeme.

**Welchen Benutzer soll FleetPilot auf meinen Servern verwenden?** Am sichersten ist ein eigener Benutzer mit Ihrem SSH-Schlüssel und sudo-Rechten für den Paketmanager und `smartctl`. `root` funktioniert ebenfalls.

**Ein Host wird als offline angezeigt, funktioniert aber.** FleetPilot prüft den SSH-Port. Prüfen Sie den Port in den Host-Einstellungen und eine Firewall zwischen FleetPilot und dem Host.

**Kann ich Windows-PCs und -Server verwalten?** Ja, alle Versionen, die Microsoft noch unterstützt:
- Windows 10 und 11, auch LTSC 2019, 2021 und 2024 und die IoT-Editionen
- Windows Server 2016 bis 2025, auch Server Core

Den OpenSSH-Server einschalten, den Host mit einem Administratorkonto anlegen und **Detect OS** klicken. FleetPilot zeigt dann die Version und ihr Support-Ende. Es installiert Windows-Updates (ohne Neustart) und, wo vorhanden, Anwendungsupdates über winget. Herunterfahren, Wake-on-LAN, die Hardwareübersicht und SMART (mit smartmontools) funktionieren ebenfalls. Einrichtung je Version: [WINDOWS_SUPPORT.md](../../WINDOWS_SUPPORT.md).

**Können sich zwei FleetPilot-Instanzen gegenseitig absichern?** Ja: Die Datensynchronisation spiegelt alle Daten von einer primären auf eine sekundäre Instanz. Setzen Sie auf beiden dasselbe `SYNC_TOKEN`.

**Wo liegen meine Daten?** In `/opt/fleetpilot/data` auf dem FleetPilot-Rechner. Nichts wird an Dritte geschickt; die Update-Prüfung fragt bei GitHub an, was `FLEETPILOT_OFFLINE=true` abschaltet.

**Ich habe das Administratorpasswort vergessen.** Führen Sie `sudo bash /opt/fleetpilot/reset-password.sh` auf dem FleetPilot-Rechner aus.
