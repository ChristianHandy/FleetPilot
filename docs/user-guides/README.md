# FleetPilot — User Guides

The guides are written in Markdown; the PDFs here are built from them with `build_pdfs.py`.

The current release is **1.8.1**. The guides below describe **1.7**; most of it still applies, and updating them to the current release is tracked in [#175](https://github.com/ChristianHandy/FleetPilot/issues/175).

| Guide | English | Deutsch | 简体中文 | Version |
|---|---|---|---|---|
| Installation | [Markdown](../installation.md) · [PDF](FleetPilot_Installation_EN.pdf) | [Markdown](../de/installation.md) · [PDF](FleetPilot_Installation_DE.pdf) | [Markdown](../zh-CN/installation.md) · [PDF](FleetPilot_Installation_ZH.pdf) | 1.7 |
| User guide, all features | [Markdown](../user-guide.md) · [PDF](FleetPilot_User_Guide_EN.pdf) | [Markdown](../de/benutzerhandbuch.md) · [PDF](FleetPilot_Handbuch_DE.pdf) | [Markdown](../zh-CN/user-guide.md) · [PDF](FleetPilot_User_Guide_ZH.pdf) | 1.7 |

The Simplified Chinese guides are translated from the English sources above by [@zoizero86-beep](https://github.com/zoizero86-beep). The interface itself is not available in Chinese yet ([#135](https://github.com/ChristianHandy/FleetPilot/issues/135)), so the menu names in the guides will be checked again once it is. `build_pdfs.py` builds the PDFs with a CJK font (Noto Sans CJK) because DejaVu Sans has no CJK glyphs; the two Chinese PDFs are committed here.

## Older guides (version 1.0)

These describe FleetPilot 1.0 and do not cover routers, the security center, notifications, backups, accessibility, Windows hosts or the new installers.

| Language | File |
|---|---|
| Français | [FleetPilot_Guide_Utilisateur_FR.pdf](FleetPilot_Guide_Utilisateur_FR.pdf) |
| Español | [FleetPilot_Manual_Usuario_ES.pdf](FleetPilot_Manual_Usuario_ES.pdf) |
| Italiano | [FleetPilot_Manuale_Utente_IT.pdf](FleetPilot_Manuale_Utente_IT.pdf) |
| English, Deutsch (1.0 and draft 2) | [archive/](archive/) |

## Help wanted: a guide in your language

Guides are written by people who speak the language; machine translation is fine as a first draft. Pick a language, comment on its issue, and follow the rules in [#175](https://github.com/ChristianHandy/FleetPilot/issues/175).

| Language | Issue | Ready to start? |
|---|---|---|
| English (update to the current release, the source for all others) | [#176](https://github.com/ChristianHandy/FleetPilot/issues/176) | yes |
| Deutsch (update) | [#177](https://github.com/ChristianHandy/FleetPilot/issues/177) | yes |
| Français | [#178](https://github.com/ChristianHandy/FleetPilot/issues/178) | yes |
| Español | [#179](https://github.com/ChristianHandy/FleetPilot/issues/179) | yes |
| Nederlands | [#180](https://github.com/ChristianHandy/FleetPilot/issues/180) | yes |
| Italiano | [#181](https://github.com/ChristianHandy/FleetPilot/issues/181) | after the interface ([#127](https://github.com/ChristianHandy/FleetPilot/issues/127)) |
| Polski, Português (Brasil), Čeština, Svenska, Türkçe, Українська, 日本語 | [#182](https://github.com/ChristianHandy/FleetPilot/issues/182)–[#188](https://github.com/ChristianHandy/FleetPilot/issues/188) | after the interface translation ([#128](https://github.com/ChristianHandy/FleetPilot/issues/128)–[#134](https://github.com/ChristianHandy/FleetPilot/issues/134)) |

A new guide goes to `docs/<lang>/` in Markdown, with the same chapters as the English guide, and is added to `GUIDES` in `build_pdfs.py` and to the table above.

## Rebuilding the PDFs

```bash
pip install markdown
```

```bash
python3 docs/user-guides/build_pdfs.py
```

LibreOffice (`soffice`) must be installed.
