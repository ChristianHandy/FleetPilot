# FleetPilot — User Guides

The guides are written in Markdown; the PDFs here are built from them with `build_pdfs.py`.

| Guide | English | Deutsch | 简体中文 | Version |
|---|---|---|---|---|
| Installation | [Markdown](../installation.md) · [PDF](FleetPilot_Installation_EN.pdf) | [Markdown](../de/installation.md) · [PDF](FleetPilot_Installation_DE.pdf) | [Markdown](../zh-CN/installation.md) | 1.7 |
| User guide, all features | [Markdown](../user-guide.md) · [PDF](FleetPilot_User_Guide_EN.pdf) | [Markdown](../de/benutzerhandbuch.md) · [PDF](FleetPilot_Handbuch_DE.pdf) | [Markdown](../zh-CN/user-guide.md) | 1.7 |

The Simplified Chinese guides are translated from the English sources above. `build_pdfs.py` builds them with a CJK font (Noto Sans CJK); the PDFs are not committed yet.

## Older guides (version 1.0)

These describe FleetPilot 1.0 and do not cover routers, the security center, notifications, backups, accessibility or the new installers.

| Language | File |
|---|---|
| Français | [FleetPilot_Guide_Utilisateur_FR.pdf](FleetPilot_Guide_Utilisateur_FR.pdf) |
| Español | [FleetPilot_Manual_Usuario_ES.pdf](FleetPilot_Manual_Usuario_ES.pdf) |
| Italiano | [FleetPilot_Manuale_Utente_IT.pdf](FleetPilot_Manuale_Utente_IT.pdf) |
| English, Deutsch (1.0 and draft 2) | [archive/](archive/) |

## Rebuilding the PDFs

```bash
pip install markdown
```

```bash
python3 docs/user-guides/build_pdfs.py
```

LibreOffice (`soffice`) must be installed.
