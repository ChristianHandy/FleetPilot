# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""
FleetPilot — Universal Plugin/Addon Loader
==========================================
Supports plugins for ALL areas of the dashboard:
  - Disk Tools (legacy, fully supported)
  - Dashboard widgets
  - Host card actions & detail tabs
  - Scanner result actions
  - Update pre/post hooks
  - Sidebar navigation links
  - Notification hooks
  - Settings panels
"""

import os
import importlib.util
import logging
import traceback
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional
import textwrap

logger = logging.getLogger(__name__)

HOOK_NAMES = [
    "device_buttons",
    "dashboard_widgets",
    "navbar_badges",
    "sidebar_links",
    "settings_panels",
    "host_card_actions",
    "host_detail_tabs",
    "scanner_result_actions",
    "update_pre_hook",
    "update_post_hook",
    "notification_hook",
]


class PluginInfo:
    def __init__(self, name: str, file: str):
        self.name = name
        self.file = file
        self.status: str = "loading"
        self.error: str = ""
        self.version: str = "1.0.0"
        self.author: str = "Unknown"
        self.description: str = ""
        self.hooks_registered: List[str] = []
        self.scope: str = "global"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file": self.file,
            "status": self.status,
            "error": self.error,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "hooks": self.hooks_registered,
            "scope": self.scope,
        }


class AddonManager:
    """Universal plugin manager for FleetPilot."""

    def __init__(self, app, core, hookpoints: Optional[Dict] = None):
        self.app = app
        self.core = core
        self.hooks: Dict[str, List[Callable]] = {h: [] for h in HOOK_NAMES}
        if hookpoints:
            for k, v in hookpoints.items():
                self.hooks.setdefault(k, []).extend(v if isinstance(v, list) else [v])
        self.css_files: List[str] = []
        self.plugins: List[PluginInfo] = []
        self._lock = threading.Lock()

    def load_addons(self, addon_dir: str = "addons",
                    template_target: str = "templates/addons") -> None:
        os.makedirs(template_target, exist_ok=True)
        os.makedirs(addon_dir, exist_ok=True)
        for fname in sorted(os.listdir(addon_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            self._load_one(fname, addon_dir, template_target)

    def _load_one(self, fname: str, addon_dir: str,
                  template_target: str) -> PluginInfo:
        fpath = os.path.join(addon_dir, fname)
        modname = fname[:-3]
        info = PluginInfo(name=modname, file=fname)
        try:
            spec = importlib.util.spec_from_file_location(modname, fpath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            meta: dict = getattr(mod, "addon_meta", {})
            info.name = meta.get("name", modname)
            info.version = meta.get("version", "1.0.0")
            info.author = meta.get("author", "Unknown")
            info.description = meta.get("description", "")
            info.scope = meta.get("scope", "global")

            # Embedded HTML template (legacy disk-tool style)
            if "html" in meta:
                html_path = Path(template_target) / f"{modname}.html"
                html = textwrap.dedent(meta["html"]).strip()
                # Only write when it changed: the code directory is read-only
                # for the service in a normal install.
                if not html_path.exists() or html_path.read_text(encoding="utf-8") != html:
                    html_path.write_text(html, encoding="utf-8")
                def _make_btn(pname):
                    return lambda dev: (
                        f'<a class="btn btn-sm btn-outline-secondary" '
                        f'href="/disks/addons/{pname}/{dev}">{pname}</a>'
                    )
                self._register_hook("device_buttons", _make_btn(modname), info)

            # Explicit html_hooks dict
            for hookname, func in meta.get("html_hooks", {}).items():
                self._register_hook(hookname, func, info)

            # CSS
            if "css" in meta:
                self.css_files.append(meta["css"])

            # Shorthand hooks
            _shorthands = {
                "dashboard_widget":  "dashboard_widgets",
                "host_card_action":  "host_card_actions",
                "host_detail_tab":   "host_detail_tabs",
                "scanner_action":    "scanner_result_actions",
                "update_post":       "update_post_hook",
                "update_pre":        "update_pre_hook",
                "notification":      "notification_hook",
                "sidebar_link":      "sidebar_links",
                "navbar_badge":      "navbar_badges",
                "settings_panel":    "settings_panels",
            }
            for short, full in _shorthands.items():
                if short in meta:
                    self._register_hook(full, meta[short], info)

            if hasattr(mod, "register"):
                mod.register(self.app, self.core)

            info.status = "ok"
        except Exception:
            info.status = "error"
            info.error = traceback.format_exc(limit=5)

        with self._lock:
            self.plugins.append(info)
        return info

    def _register_hook(self, name: str, func: Callable, info: PluginInfo) -> None:
        self.hooks.setdefault(name, []).append(func)
        if name not in info.hooks_registered:
            info.hooks_registered.append(name)

    def render_hooks(self, hookname: str, *args, **kwargs) -> str:
        parts = []
        for func in self.hooks.get(hookname, []):
            try:
                result = func(*args, **kwargs)
                if result:
                    parts.append(str(result))
            except Exception as exc:
                parts.append(f"<!-- Hook {hookname} error: {exc} -->")
        return "\n".join(parts)

    def fire_hooks(self, hookname: str, *args, **kwargs) -> None:
        for func in self.hooks.get(hookname, []):
            try:
                func(*args, **kwargs)
            except Exception as exc:
                print(f"[plugin] Hook {hookname} error: {exc}")

    def get_sidebar_links(self) -> List[Dict]:
        links = []
        for func in self.hooks.get("sidebar_links", []):
            try:
                result = func()
                if isinstance(result, dict):
                    links.append(result)
                elif isinstance(result, list):
                    links.extend(result)
            except Exception as exc:
                print(f"[plugin] sidebar_links error: {exc}")
        return links

    def get_host_detail_tabs(self, host: dict) -> List[Dict]:
        tabs = []
        for func in self.hooks.get("host_detail_tabs", []):
            try:
                result = func(host)
                if isinstance(result, dict):
                    tabs.append(result)
                elif isinstance(result, list):
                    tabs.extend(result)
            except Exception as exc:
                print(f"[plugin] host_detail_tabs error: {exc}")
        return tabs

    @property
    def status(self) -> List[dict]:
        return [p.to_dict() for p in self.plugins]

    def get_plugin_count(self) -> Dict[str, int]:
        counts = {"total": 0, "ok": 0, "error": 0, "disabled": 0}
        for p in self.plugins:
            counts["total"] += 1
            counts[p.status if p.status in counts else "error"] += 1
        return counts


def fire_app_hook(hook_name: str, *args, **kwargs) -> None:
    """
    Fire a hook on the addon manager of the running app, if there is one.

    Core code calls this to announce that something happened: an update
    finished, a new FleetPilot version is available. It says nothing at all
    when there is no app context, which is the normal case for the scheduler,
    the CLI helpers and most unit tests -- those import ``updater`` and
    ``version_manager`` without ever starting Flask.

    A hook is a notification, so it must never be able to break the thing it
    reports on: ``AddonManager.fire_hooks`` already swallows what each hook
    raises, and this wrapper logs anything the plumbing itself throws.
    """
    try:
        from flask import current_app, has_app_context

        if not has_app_context():
            return
        addon_mgr = getattr(current_app, "addon_mgr", None)
        if addon_mgr is None:
            return
        addon_mgr.fire_hooks(hook_name, *args, **kwargs)
    except Exception as exc:  # a notification must never break the caller
        logger.warning("Plugin hook %s failed: %s", hook_name, exc)
