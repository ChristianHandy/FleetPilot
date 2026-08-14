# Changelog

Alle bemerkenswerten Änderungen an FleetPilot werden in diesem Dokument festgehalten. Die Versionsnummern folgen dem Prinzip der semantischen Versionierung.

## [1.1.1] — 2026-08-14

### Behoben

- Der root-eigene Proxy-Apply-Helper verwendet beim ersten Einsatz `systemctl reload-or-restart`, sodass HAProxy nach der Migration auch dann zuverlässig startet, wenn zuvor noch kein Dienst aktiv war.

## [1.1.0] — 2026-08-14

Dieses Feature-Release verlagert den zentralen HTTP-Ingress auf den Raspberry Pi und ergänzt eine kontrollierte Verwaltung interner Dienste und Pfadrouten direkt in FleetPilot.

### Hinzugefügt

- Eine admin-geschützte Seite **Proxy Services** zum Hinzufügen, Testen und Entfernen interner HTTP-Dienstrouten.
- Eine persistent gespeicherte, validierte Routenregistrierung für Dienstname, öffentlichem Pfad, Backend-Ziel, Port und Health-Check.
- Einen root-eigenen HAProxy-Renderer, der die Registry erneut prüft, eine feste Konfiguration erzeugt, diese validiert und nur dann atomar neu lädt.
- Automatisches Rollback der FleetPilot-Routenregistrierung, wenn ein HAProxy-Reload nicht erfolgreich ist.
- Eine private Nginx-Upstream-Konfiguration auf `127.0.0.1:8080`; HAProxy besitzt den LAN-Ingress auf Port 80.

### Sicherheit

- Die Proxy-Kette entfernt klientengelieferte Weiterleitungsheader und setzt vertrauenswürdige Header neu, bevor die Anfrage an FleetPilot weitergegeben wird.
- Der FleetPilot-Webdienst erhält nur die eng begrenzten Sudo-Rechte `proxy-apply apply` und `proxy-apply status`; er kann keine beliebigen HAProxy-Befehle, Pfade oder Backends als Root ausführen.

## [1.0.1] — 2026-08-14

Dieses Patch-Release behebt die fehlgeschlagene Aktualisierung aus der FleetPilot-Weboberfläche, ohne dem Webdienst Schreibzugriff auf den Anwendungscode zu geben.

### Behoben

- Der Selbstupdate-Workflow verwendet nun einen root-eigenen, auf das freigegebene GitHub-Repository und den Branch `main` beschränkten Helper. Dadurch kann der eingeschränkte `fleetpilot`-Dienst keine `.git`-Dateien mehr direkt verändern müssen.
- Die Update-Prüfung ist schreibgeschützt. Eine tatsächliche Aktualisierung führt ausschließlich einen kontrollierten Fast-Forward-Updatepfad aus und installiert Anforderungen nur aus dem geprüften Repository.
- Der Dienstneustart wird als separater systemd-Auftrag geplant, damit Browserantwort und Update-Status vor dem Neustart zuverlässig verarbeitet werden.
- Der Raspberry-Pi-Installer installiert den Helper und eine Sudo-Regel, die nur die Aktionen `check`, `apply` und `restart` erlaubt.

## [1.0.0] — 2026-08-14

Dies ist das erste formale, produktionsorientierte FleetPilot-Release für kleine interne IT-Umgebungen.

### Hinzugefügt

- Eine einheitliche **Storage & Disks**-Arbeitsfläche für Datenträgerinventar, SMART-Zustand, dauerhafte Aufgaben und verwaltete Speichersysteme.
- Ein append-only **Audit Trail** für zustandsändernde Anfragen, ohne Passwörter, Tokens, SSH-Schlüssel, Request-Bodies oder Kommandoausgaben zu speichern.
- Eine administrative **Production Status**-Ansicht mit Laufzeit-, Cookie-, Proxy-, CSRF-, Secret- und Audit-Status.
- Ein `/healthz`-Endpunkt mit maschinenlesbaren Release-Metadaten.
- Eine gehärtete Gunicorn-/systemd-Laufzeit für den Raspberry-Pi-Betrieb hinter Nginx.
- Zentrale Versionsmetadaten in `fleetpilot_version.py`, die Weboberfläche, Health-Endpunkt, Selbstupdate-Ansicht und künftige Clients verwenden können.

### Verbessert

- Die zentrale Navigation enthält die administrative Production-Status-Seite.
- Der Versions-Toast verwendet den korrekten Selbstupdate-Endpunkt.
- Android-Client und C#-Backend tragen ebenfalls die Release-Version `1.0.0`.

### Sicherheits- und Betriebsstatus

- Der Live-Service läuft als dedizierter `fleetpilot`-Benutzer über Gunicorn hinter Nginx.
- Das Umgebungsdatei-Recht auf dem Raspberry Pi ist auf `root:fleetpilot` mit Modus `0640` eingeschränkt.
- HTTPS, sichere Cookies und die globale CSRF-Erzwingung bleiben bewusst als nächste, separat testbare Produktionsschritte ausstehend.

[1.1.1]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.1.1
[1.1.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.1.0
[1.0.1]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.0.1
[1.0.0]: https://github.com/ChristianHandy/FleetPilot/releases/tag/v1.0.0
