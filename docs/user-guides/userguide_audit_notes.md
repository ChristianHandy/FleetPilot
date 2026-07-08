# Audit-Notizen zum vorhandenen FleetPilot User Guide

Quelle: `/home/ubuntu/FleetPilot_repo/docs/user-guides/FleetPilot_User_Guide_EN.pdf`

## Sichtbarer Inhalt des bestehenden PDFs

Das bestehende Handbuch ist **Version 1.0 – June 2026** und umfasst 12 Seiten.

### Inhaltsverzeichnis des vorhandenen PDFs
1. Getting Started
2. Dashboard
3. Host Management
4. Update Manager
5. VM Controller
6. Storage Controller
7. Disk Management & SMART
8. CheckMK Integration
9. User Management
10. Plugins & Extensions

### Bereits dokumentierte Inhalte im Alt-PDF

| Abschnitt | Sichtbar dokumentiert |
|---|---|
| Getting Started | Login, Systemanforderungen, UI-Grundaufbau |
| Dashboard | Quick Stats, Layout-Anpassung, verfügbare Widgets |
| Host Management | Host anlegen, Filtern, Basis-Aktionen |
| Update Manager | Updates starten, Historie, automatische Updates |
| VM Controller | Proxmox-Verbindung, VM-Übersicht, Disk-Inventar |
| Storage Controller | Storage-System anlegen, Pool/Volume-Übersicht, Disk-Inventar |
| SMART | SMART-Dashboard, Disk Tools, automatisches Polling |
| CheckMK | Verbindung, API-Authentifizierung, Monitoringdaten |

## Auffällige Lücken im Alt-PDF

Das bestehende PDF ist **nicht mehr aktuell**. Es fehlen mindestens diese in der Codebasis bzw. Änderungsdokumentation vorhandenen Bereiche:

| Fehlende oder veraltete Inhalte | Status |
|---|---|
| Fan Controller | fehlt |
| Corsair Commander Pro | fehlt |
| Backup Controller | fehlt |
| Dashboard-Widget-System im aktuellen Umfang | vermutlich unvollständig |
| VM-Actions / CSRF-Fix / Proxmox-Update per SSH | fehlt |
| OS-Erkennung für Hosts | fehlt |
| Custom Host Images | fehlt |
| Storage-Controller GraphQL-basierte Unraid-Unterstützung | fehlt |
| Hinweise zum Hinzufügen von Servern mit allen Feldern und Workflows | ausbaufähig |

## Schlussfolgerung

Ein neues Handbuch sollte vollständig neu erstellt werden und nicht nur das alte PDF leicht aktualisieren. Es soll insbesondere folgende Ziele erfüllen:

1. **Alle aktuellen Module** dokumentieren.
2. **Server/Hosts hinzufügen** Schritt für Schritt erklären.
3. **Controller hinzufügen** (VM, Storage, Backup, Fan, Commander) systematisch erklären.
4. **Neue Features und Fixes** aus AGENTS.md und aktueller Codebasis aufnehmen.
5. Ein **ausführliches Benutzerhandbuch** mit praxisnahen Bedienhinweisen liefern.

## Nächster Arbeitsschritt

Codebasis und Routen systematisch analysieren, danach ein neues vollständiges Handbuch in Markdown verfassen und als PDF exportieren.

